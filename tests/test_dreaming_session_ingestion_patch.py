"""The session-ingestion patch: direct chats are no longer pinned to their first messages."""
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "ops/host/openclaw-patches/patch-dreaming-session-ingestion.py"
MANIFEST = ROOT / "ops/host/openclaw-patches/manifest.json"

FIXTURE = """const SESSION_INGESTION_MAX_MESSAGES_PER_SWEEP = 240;
const SESSION_INGESTION_MAX_MESSAGES_PER_FILE = 80;
const SESSION_INGESTION_MIN_MESSAGES_PER_FILE = 12;
function collectSessionIngestionBatches(params) {
\tconst sessionFiles = [];
\tfor (const entry of params.entries) {
\t\tsessionFiles.push({
\t\t\tagentId,
\t\t\tabsolutePath,
\t\t\tgeneratedByDreamingNarrative: entry.generatedByDreamingNarrative === true,
\t\t\tgeneratedByCronRun: entry.generatedByCronRun === true,
\t\t\tsessionPath: sessionPathForFile(absolutePath)
\t\t});
\t}
\tconst sortedFiles = sessionFiles.toSorted((a, b) => {
\t\tif (a.agentId !== b.agentId) return a.agentId.localeCompare(b.agentId);
\t\treturn a.sessionPath.localeCompare(b.sessionPath);
\t});
\tconst totalCap = SESSION_INGESTION_MAX_MESSAGES_PER_SWEEP;
\tlet remaining = totalCap;
\tconst perFileCap = Math.min(SESSION_INGESTION_MAX_MESSAGES_PER_FILE, Math.max(SESSION_INGESTION_MIN_MESSAGES_PER_FILE, Math.ceil(totalCap / Math.max(1, sortedFiles.length))));
\tfor (const file of sortedFiles) {
\t\tlet cursor = previous && previous.mtimeMs === fingerprint.mtimeMs && previous.size === fingerprint.size && previous.contentHash === contentHash && previous.lineCount === lineCount ? Math.max(0, Math.min(previous.lastContentLine, lineCount)) : 0;
\t}
}
"""


def load_patch():
    spec = importlib.util.spec_from_file_location("session_ingestion_patch", PATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_patch_changes_selection_not_scoring_and_is_idempotent():
    patch = load_patch()
    new = patch.patch(FIXTURE)
    assert "clawock-dreaming-session-ingestion-v1" in new
    assert "SESSION_INGESTION_MAX_MESSAGES_PER_SWEEP = 4000" in new
    assert "SESSION_INGESTION_MAX_MESSAGES_PER_FILE = 400" in new
    assert "const perFileCap = SESSION_INGESTION_MAX_MESSAGES_PER_FILE;" in new
    assert "fingerprint.size > previous.size" in new
    assert "previous.contentHash === contentHash && previous.lineCount === lineCount" not in new
    assert "sessionKey: entry.sessionKey" in new
    assert "/:direct:|:main$/.test(a.sessionKey)" in new
    assert patch.patch(new) == new
    for old, _ in patch.EDITS:
        assert old not in new


def test_patched_fixture_is_valid_javascript():
    patch = load_patch()
    new = patch.patch(FIXTURE)
    result = subprocess.run(["node", "--input-type=module", "--check"], input=new, text=True,
                            capture_output=True)
    assert result.returncode == 0, result.stderr


def test_manifest_declares_the_patch_and_its_postconditions():
    manifest = json.loads(MANIFEST.read_text())
    found = [item for item in manifest["patches"] if item["id"] == "dreaming-session-ingestion"]
    assert len(found) == 1
    assert found[0]["script"].endswith("patch-dreaming-session-ingestion.py")
    required = found[0]["targets"][0]["required"]
    assert "clawock-dreaming-session-ingestion-v1" in required
    assert "sessionKey: entry.sessionKey" in required
    assert "fingerprint.size > previous.size" in required
