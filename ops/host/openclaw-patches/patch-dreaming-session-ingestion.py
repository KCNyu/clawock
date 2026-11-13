#!/usr/bin/env python3
"""Make dreaming ingest the user's direct-chat session, not an alphabetical prefix.

OpenClaw 2026.7.1-2 splits the session-message budget across every transcript it can
see (1827 files on this host) and resets a changed transcript's cursor to line 0.
The result is that a long-lived direct chat never gets past the first handful of
messages: the file grows, the whole-file hash changes, the sweep starts at line 0
again, the per-file cap stops it at the same line, and the already-seen hashes add
nothing. Sessions whose name sorts late are never reached at all.

This patch keeps the same candidate/scoring pipeline and changes only selection:

  * a larger sweep/file budget, so a changed session is not reduced to 1-2 messages;
  * resume at the saved cursor when a transcript grew (append-only JSONL);
  * try `:direct:` / `:main` sessions first, so the owner's own instructions are not
    starved by cron briefs.

No model prompt, score, or review rule changes here.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

_CHECKOUT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / "src"))
sys.path.insert(0, str(_CHECKOUT / "ops/host"))

from patch_dreaming_fallbacks import replace_once  # noqa: E402

MARKER = "clawock-dreaming-session-ingestion-v1"
OLD_SWEEP = "const SESSION_INGESTION_MAX_MESSAGES_PER_SWEEP = 240;"
NEW_SWEEP = ("const SESSION_INGESTION_MAX_MESSAGES_PER_SWEEP = 4000; "
             f"// {MARKER}: every changed session, not an alphabetical prefix")
OLD_FILE = "const SESSION_INGESTION_MAX_MESSAGES_PER_FILE = 80;"
NEW_FILE = ("const SESSION_INGESTION_MAX_MESSAGES_PER_FILE = 400; "
            f"// {MARKER}: a long chat keeps its own messages")
OLD_PER_FILE = (
    "\tconst perFileCap = Math.min(SESSION_INGESTION_MAX_MESSAGES_PER_FILE, "
    "Math.max(SESSION_INGESTION_MIN_MESSAGES_PER_FILE, "
    "Math.ceil(totalCap / Math.max(1, sortedFiles.length))));")
NEW_PER_FILE = (
    "\t// " + MARKER + ": a 1-2 message share never advances a long session.\n"
    "\tconst perFileCap = SESSION_INGESTION_MAX_MESSAGES_PER_FILE;")
OLD_CURSOR = (
    "\t\tlet cursor = previous && previous.mtimeMs === fingerprint.mtimeMs && "
    "previous.size === fingerprint.size && previous.contentHash === contentHash && "
    "previous.lineCount === lineCount ? "
    "Math.max(0, Math.min(previous.lastContentLine, lineCount)) : 0;")
NEW_CURSOR = (
    "\t\t// " + MARKER + ": transcripts are append-only, so a grown file resumes at\n"
    "\t\t// the saved cursor. Requiring the whole-file hash to match restarted every\n"
    "\t\t// active session at line 0, and the per-file cap then pinned it to the same\n"
    "\t\t// first N messages forever.\n"
    "\t\tlet cursor = previous && fingerprint.size > previous.size && "
    "lineCount >= previous.lineCount ? "
    "Math.max(0, Math.min(previous.lastContentLine, lineCount)) : 0;")
OLD_PUSH = (
    "\t\tsessionFiles.push({\n"
    "\t\t\tagentId,\n"
    "\t\t\tabsolutePath,\n"
    "\t\t\tgeneratedByDreamingNarrative: entry.generatedByDreamingNarrative === true,\n"
    "\t\t\tgeneratedByCronRun: entry.generatedByCronRun === true,\n"
    "\t\t\tsessionPath: sessionPathForFile(absolutePath)\n"
    "\t\t});")
NEW_PUSH = (
    "\t\tsessionFiles.push({\n"
    "\t\t\tagentId,\n"
    "\t\t\tabsolutePath,\n"
    "\t\t\tgeneratedByDreamingNarrative: entry.generatedByDreamingNarrative === true,\n"
    "\t\t\tgeneratedByCronRun: entry.generatedByCronRun === true,\n"
    "\t\t\tsessionPath: sessionPathForFile(absolutePath),\n"
    "\t\t\tsessionKey: entry.sessionKey ?? \"\"\n"
    "\t\t});")
OLD_SORT = (
    "\tconst sortedFiles = sessionFiles.toSorted((a, b) => {\n"
    "\t\tif (a.agentId !== b.agentId) return a.agentId.localeCompare(b.agentId);\n"
    "\t\treturn a.sessionPath.localeCompare(b.sessionPath);\n"
    "\t});")
NEW_SORT = (
    "\tconst sortedFiles = sessionFiles.toSorted((a, b) => {\n"
    "\t\t// " + MARKER + ": the owner's direct instructions go before cron briefs.\n"
    "\t\tconst aDirect = /:direct:|:main$/.test(a.sessionKey) ? 0 : 1;\n"
    "\t\tconst bDirect = /:direct:|:main$/.test(b.sessionKey) ? 0 : 1;\n"
    "\t\tif (aDirect !== bDirect) return aDirect - bDirect;\n"
    "\t\tif (a.agentId !== b.agentId) return a.agentId.localeCompare(b.agentId);\n"
    "\t\treturn a.sessionPath.localeCompare(b.sessionPath);\n"
    "\t});")
EDITS = (
    (OLD_SWEEP, NEW_SWEEP),
    (OLD_FILE, NEW_FILE),
    (OLD_PER_FILE, NEW_PER_FILE),
    (OLD_CURSOR, NEW_CURSOR),
    (OLD_PUSH, NEW_PUSH),
    (OLD_SORT, NEW_SORT),
)
REQUIRED = (MARKER, "sessionKey: entry.sessionKey", "fingerprint.size > previous.size",
            "const perFileCap = SESSION_INGESTION_MAX_MESSAGES_PER_FILE;")


def patch(text: str) -> str:
    if MARKER in text:
        missing = [item for item in REQUIRED if item not in text]
        stale = [old for old, _ in EDITS if old in text]
        if missing or stale:
            raise ValueError(
                f"incomplete dreaming session-ingestion patch (missing={missing[:2]}, stale={stale[:2]})")
        return text
    for old, new in EDITS:
        text = replace_once(text, old, new)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.dist is None:
        from clawock.providers.openclaw import runtime_paths
        install = runtime_paths().install_dir
        if install is None:
            parser.error("OpenClaw installation missing")
        args.dist = install / "dist"
    paths = [p for p in args.dist.glob("dreaming-phases-*.js")
             if "SESSION_INGESTION_MAX_MESSAGES_PER_SWEEP" in p.read_text()]
    if len(paths) != 1:
        raise ValueError("expected one dreaming session-ingestion bundle")
    path = paths[0]
    new = patch(path.read_text())
    if args.check and new != path.read_text():
        raise ValueError(f"dreaming session-ingestion patch not installed: {path.name}")
    subprocess.run(["node", "--input-type=module", "--check"], input=new, text=True, check=True)
    if new != path.read_text():
        backup = path.with_name(path.name + ".before-dreaming-session-ingestion")
        if not backup.exists():
            backup.write_text(path.read_text())
        tmp = path.with_name(path.name + ".dreaming-session-ingestion-tmp")
        tmp.write_text(new)
        tmp.chmod(path.stat().st_mode & 0o777)
        tmp.replace(path)
    print(f"{MARKER}: direct-chat session ingestion verified; gateway not restarted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
