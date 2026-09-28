#!/usr/bin/env python3
"""Build a compact map of the clawock repo for patrol rounds.

Each round used to rediscover the layout with ls/grep/read before doing any review. The map is
generated from the code (never written by a model), so it cannot drift from the commit it names;
patrol.sh rebuilds it only when the tracked code changed.

    build_codemap.py <worktree> <out.md>
"""
import ast
import re
import subprocess
import sys
from pathlib import Path

WT = Path(sys.argv[1])
OUT = Path(sys.argv[2])


def git(*args):
    return subprocess.run(["git", "-C", str(WT), *args], capture_output=True, text=True).stdout


def lines(path):
    try:
        return sum(1 for _ in (WT / path).open("rb"))
    except OSError:
        return 0


def first_sentence(text, limit=110):
    text = " ".join((text or "").strip().split())
    m = re.match(r"(.+?[。.!?！？])(\s|$)", text)
    text = m.group(1) if m else text
    return text[:limit] + ("…" if len(text) > limit else "")


def comment_head(path, limit=110):
    """First meaningful comment line of a script / JS / CSS file."""
    try:
        for raw in (WT / path).read_text(errors="replace").splitlines()[:25]:
            s = raw.strip()
            if not s or s.startswith("#!") or "shellcheck" in s or s in ("/**", "/*", "*/", "#", "//"):
                continue
            if s.startswith(("#", "//", "/*", "*")):
                s = s.lstrip("#/* ").strip()
                if s and not s.startswith(("-*-", "eslint", "@ts-")):
                    return first_sentence(s, limit)
            elif s.startswith(("name:", '"""', "'''")):
                continue
            else:
                break
    except OSError:
        pass
    return ""


files = git("ls-files").splitlines()
head = git("log", "-1", "--format=%h %cs %s").strip()
out = [f"# clawock 代码地图（{head}）", "",
       "由 `/root/tools/clawock-patrol/build_codemap.py` 从代码生成，代码变了自动重建；只写结构，不写结论。",
       "用法：按本轮范围 `grep -n '<关键词>' codemap.md` 找入口，再去读真实文件。行数/函数名以这个 commit 为准。", ""]

# ---- python packages ---------------------------------------------------------
py = sorted((f for f in files if f.startswith("src/") and f.endswith(".py")), key=lambda f: (str(Path(f).parent), f))
out += ["## src/（Python 包）", "", "格式：`路径` 行数 — 模块说明 · 顶层公开函数/类（`_` 开头的私有函数不列）", ""]
current = None
for f in py:
    pkg = str(Path(f).parent)
    if pkg != current:
        current = pkg
        out.append(f"### {pkg}/")
    try:
        tree = ast.parse((WT / f).read_text(errors="replace"))
    except SyntaxError:
        out.append(f"- `{Path(f).name}` {lines(f)}L — (解析失败)")
        continue
    doc = first_sentence(ast.get_docstring(tree))
    names = [n.name for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not n.name.startswith("_")]
    shown = ", ".join(names[:14]) + (f", …(+{len(names) - 14})" if len(names) > 14 else "")
    out.append(f"- `{Path(f).name}` {lines(f)}L" + (f" — {doc}" if doc else "") + (f" · {shown}" if shown else ""))
out.append("")

# ---- CLI subcommands -----------------------------------------------------------
cli = WT / "src/clawock/cli.py"
if cli.is_file():
    subs = re.findall(r"add_parser\(\s*[\"']([\w-]+)[\"']", cli.read_text(errors="replace"))
    if subs:
        out += ["## CLI 子命令（`clawock <cmd>`，定义在 src/clawock/cli.py）", "", ", ".join(dict.fromkeys(subs)), ""]

# ---- workflows -------------------------------------------------------------------
wf = sorted(f for f in files if f.startswith(".github/workflows/"))
if wf:
    out += ["## .github/workflows/", "", "格式：文件 — name · 触发 · cron（UTC）", ""]
    for f in wf:
        text = (WT / f).read_text(errors="replace")
        name = re.search(r"^name:\s*(.+)$", text, re.M)
        crons = re.findall(r"cron:\s*['\"]([^'\"]+)['\"]", text)
        on = re.search(r"^on:\s*\n((?:[ \t]+.*\n)+)", text, re.M)
        trig = sorted(set(re.findall(r"^\s{2}(\w+):", on.group(1), re.M))) if on else []
        out.append(f"- `{Path(f).name}` — {name.group(1).strip() if name else '?'}"
                   + (f" · {'/'.join(trig)}" if trig else "") + (f" · cron {', '.join(crons)}" if crons else ""))
    out.append("")

# ---- scripts, site, dsh, skills, config, docs, tests -------------------------------


def listing(title, prefix, exts, note=""):
    sel = sorted(f for f in files if f.startswith(prefix) and f.endswith(exts))
    if not sel:
        return
    out.extend([f"## {title}", ""] + ([note, ""] if note else []))
    for f in sel:
        c = comment_head(f)
        out.append(f"- `{f[len(prefix):]}` {lines(f)}L" + (f" — {c}" if c else ""))
    out.append("")


listing("ops/（主机/CI/发布脚本）", "ops/", (".sh", ".py", ".mjs", ".js"))
listing("site/（面板源码）", "site/", (".html", ".js", ".css", ".md", ".txt", ".webmanifest"),
        "`assets/data/*.json` 是运行时生成的投影数据，不在此列。")
listing("examples/dsh/packages/clawock-dsh/（DSH 插件）", "examples/dsh/packages/clawock-dsh/",
        (".ts", ".js", ".json", ".md"))

skills = sorted({f.split("/")[1] for f in files if f.startswith("skills/") and f.count("/") >= 2})
if skills:
    out += ["## skills/（给 agent 读的 SKILL.md，常是数据的消费者）", "", ", ".join(skills), ""]
cfg = sorted(f for f in files if f.startswith("config/"))
if cfg:
    out += ["## config/", "", ", ".join(f[len("config/"):] for f in cfg), ""]
docs = sorted(f for f in files if f.startswith("docs/") and f.endswith(".md"))
if docs:
    out += ["## docs/", "", ", ".join(f[len("docs/"):] for f in docs), ""]
tests = sorted(f for f in files if f.startswith("tests/") and f.endswith((".py", ".js", ".ts")))
if tests:
    out += [f"## tests/（{len(tests)} 个文件；按被测符号 `git grep` 找对应测试）", "",
            ", ".join(Path(f).name for f in tests), ""]

out += ["## 运行时数据（开发 PR 不改，巡检只读）", "",
        "`memory/`（台账、简报、快照、bars）、`assets/data/`（面板投影）、`portfolio.json`：由 cron/runtime 写入。", ""]

OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"codemap: {OUT} {OUT.stat().st_size // 1024}KB, {len(py)} python modules")
