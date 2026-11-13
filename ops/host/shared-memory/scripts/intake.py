#!/usr/bin/env python3
"""Turn a dispatch brief or a finished task into reviewed, distilled shared memory.

The owner's own words used to live only in the dispatch task directory.
A dispatch now queues the user's section (and, at the end, the task report plus any
appended instructions) under the private state directory. A model then answers one
question per item: does this contain a durable preference, rule, definition or
lesson, and is it already covered? Only its one-line conclusion is written to the
store; the raw words never are.

This is deliberately not a per-turn extractor:

  * queueing is cheap and always happens, so a model outage loses nothing;
  * a model (not the worker, not the dispatcher) makes the durable/transient call;
  * a deterministic screen rejects dates, prices/positions, HTML, paths, task/session
    metadata and command-like text before a topic is written;
  * an existing topic wins over a new one; a new public topic is regenerated through
    `publish.py` immediately, and is downgraded to private if that projection fails;
  * public writes are capped per day.

Nothing here reads a private store topic into a public body; the model sees only
public topic descriptions and the captured item.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import llm_json  # noqa: E402

DEFAULT_STORE = Path(os.environ.get("SHARED_MEMORY_DIR", "~/.shared-memory")).expanduser()
DEFAULT_STATE = Path(os.environ.get("SHARED_MEMORY_STATE", "~/.local/state/shared-memory")).expanduser()
DEFAULT_REPO = Path(os.environ.get("OPENCLAW_WORKSPACE") or (Path.home() / ".openclaw" / "workspace")).expanduser()
MEMORY_PY = SCRIPTS / "memory.py"
PUBLISH_PY = SCRIPTS / "publish.py"
MANIFEST_REL = Path("ops/host/shared-memory/publish-manifest.json")
MAX_ATTEMPTS = 3
MAX_PUBLIC_PER_DAY = 3
MAX_ITEM_CHARS = 12000
_HOST_ROOT = "/" + "root/"

# The same classes review_dreaming.py rejects. The LLM is a semantic filter, not the
# authority: a conclusion with a price, a dated fact, HTML or an internal path never
# reaches the store even when the model calls it durable.
RULES = {
    "front_matter": r"\b(?:layout|title|description)\s*:",
    "html": r"</?[A-Za-z][^>]*>",
    "dated_fact": r"\d{4}-\d{2}-\d{2}|\b\d{1,2}:\d{2}\b|今天|昨天|昨夜|当天|今晚|当日|目标价|收在|收盘价",
    "price_or_position": r"\d+\.\d+|\d+\s*(?:股|港元|美元)|买入|卖出|加仓|减仓|仓位动作",
    "internal_metadata": (_HOST_ROOT + r"|/tmp/|/home/|[A-Z]:\\|"
                          r"\b(?:DONE|BLOCKED|session[_ -]?id|task[_ -]?id|run\s*`?\d+)\b|"
                          r"任务\s*id|模型自报|release-\d|"
                          r"[0-9a-f]{8}-[0-9a-f-]{27,}"),
    "command_like": r"`clawock[ -]",
}
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
PREFIXES = ("feedback-", "lessons-", "decision-", "project-", "incident-", "reference-")
KIND_PREFIX = {"preference": "feedback-", "rule": "feedback-", "lessons": "lessons-",
               "lesson": "lessons-", "definition": "reference-", "project": "project-"}
SECTION_RE = re.compile(r"^【([^】]+)】[^\n]*$", re.M)
QUOTE_RE = re.compile(r"「([^」]{4,600})」")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{24,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\b(?:api[_-]?key|secret|token|passw(?:or)?d)\b[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-/+=]{24,}", re.I),
)


class IntakeError(RuntimeError):
    pass


def state_dir() -> Path:
    return DEFAULT_STATE / "intake"


def store_dir() -> Path:
    return DEFAULT_STORE


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scrub(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def reasons(text: str) -> list[str]:
    return [name for name, pattern in RULES.items() if re.search(pattern, text, re.I)]


def one_line(text: str) -> bool:
    return bool(text) and "\n" not in text and "\r" not in text


def atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def lock():
    path = state_dir() / "intake.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


# --- capture ---------------------------------------------------------------

def user_sections(text: str) -> list[str]:
    """The owner's own words, not the dispatcher's context or the appended contract."""
    sections = []
    matches = list(SECTION_RE.finditer(text))
    for index, match in enumerate(matches):
        if not any(word in match.group(1) for word in ("原话", "追加指令", "要求")):
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end():end]
        block = block.split("\n---\n", 1)[0].strip()
        if block:
            sections.append(block[:6000])
    if sections:
        return sections
    quotes = [quote.strip() for quote in QUOTE_RE.findall(text) if len(quote.strip()) >= 8]
    if quotes:
        return quotes[:6]
    head = text.split("\n---\n", 1)[0].strip()
    return [head[:3000]] if head else []


def task_texts(task_dir: Path) -> tuple[str, str]:
    prompt = (task_dir / "prompt.md").read_text(encoding="utf-8", errors="replace") \
        if (task_dir / "prompt.md").is_file() else ""
    # Appended instructions reach the model through attempt<N>.prompt; the original
    # prompt.md is not rewritten. Include both, then de-duplicate by text.
    appended = []
    for path in sorted(task_dir.glob("attempt*.prompt")):
        try:
            appended.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    for path in sorted((task_dir / "inbox").glob("*.md")):
        try:
            appended.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    sections = []
    for text in [prompt, *appended]:
        for section in user_sections(text):
            if section not in sections:
                sections.append(section)
    return "\n\n".join(sections), prompt


def task_result(task_dir: Path) -> dict:
    result = {}
    result_env = task_dir / "result.env"
    if result_env.is_file():
        for line in result_env.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key in ("STATE", "OUTCOME", "NEEDS", "NEED_SUMMARY", "RESTART", "STOP_REASON"):
                result[key] = value.strip().strip("'\"")
    summary = task_dir / "runner-summary.txt"
    if summary.is_file():
        result["report"] = summary.read_text(encoding="utf-8", errors="replace")[-6000:]
    return result


def capture(task_dir: Path, stage: str) -> Path:
    if stage not in ("dispatch", "outcome"):
        raise IntakeError("stage must be dispatch or outcome")
    task_dir = task_dir.resolve()
    if stage == "outcome":
        user_words, prompt = task_texts(task_dir)
    else:
        prompt = ((task_dir / "prompt.md").read_text(encoding="utf-8", errors="replace")
                  if (task_dir / "prompt.md").is_file() else "")
        user_words = "\n\n".join(user_sections(prompt))
    if not user_words.strip():
        raise IntakeError("no user words found in this task")
    result = task_result(task_dir) if stage == "outcome" else {}
    item = {
        "schema": 1,
        "task_id": task_dir.name,
        "stage": stage,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "prompt_sha256": digest(prompt),
        "user_words": scrub(user_words)[:MAX_ITEM_CHARS],
        "result": {key: scrub(value)[:3000] for key, value in result.items()},
        "attempts": 0,
    }
    identity = digest(json.dumps([item["task_id"], stage, item["prompt_sha256"],
                                  result.get("report", "")[:2000]], ensure_ascii=False))
    item["id"] = identity[:16]
    path = state_dir() / "queue" / f"{task_dir.name}-{stage}.json"
    # No global lock here: a capture must never wait for the model run that holds it.
    # The queue is append-only and the filename is unique per task/stage, so an
    # atomic rename is enough. A repeated capture of the same stage is idempotent.
    if path.exists():
        return path
    atomic_write(path, json.dumps(item, ensure_ascii=False, indent=2) + "\n")
    return path


CHAT_LINE = re.compile(r"^\[(?P<path>[^\]]+\.jsonl)#L(?P<line>\d+)\] User: (?P<text>.*)$")
CHAT_SKIP = ("[agent-dispatch 事件]", "Call memory_search", "Reply with ONLY",
             "HEARTBEAT_OK", "System: [")


def capture_chat(day: str, workspace: Path) -> list[Path]:
    """Queue one item per direct/cron transcript that has user text that day.

    The dreaming ingest writes the day's excerpts to `session-corpus`; this reads
    that private file rather than the transcript again. It is the direct-chat
    counterpart to a dispatch brief: the model still decides durable vs chatter.
    """
    corpus = workspace / "memory/.dreams/session-corpus" / f"{day}.txt"
    if not corpus.is_file():
        return []
    groups: dict[str, list[str]] = {}
    for line in corpus.read_text(encoding="utf-8", errors="replace").splitlines():
        match = CHAT_LINE.match(line)
        if not match:
            continue
        text = match.group("text").strip()
        if not text or any(skip in text for skip in CHAT_SKIP):
            continue
        groups.setdefault(match.group("path"), []).append(text)
    paths = []
    for session, lines in groups.items():
        words = "\n".join(lines)[:MAX_ITEM_CHARS]
        identity = digest(f"{day}\n{session}\n{words}")[:16]
        item = {
            "schema": 1,
            "task_id": f"chat-{day}-{identity[:8]}",
            "stage": "chat",
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "prompt_sha256": digest(words),
            "user_words": scrub(words),
            "result": {"date": day, "session": session},
            "attempts": 0,
            "id": identity,
        }
        path = state_dir() / "queue" / f"chat-{day}-{identity[:8]}.json"
        if path.exists():
            paths.append(path)
            continue
        atomic_write(path, json.dumps(item, ensure_ascii=False, indent=2) + "\n")
        paths.append(path)
    return paths


# --- existing topics / dedupe ---------------------------------------------

def store_topics(store: Path) -> list[dict]:
    topics = []
    if not store.is_dir():
        return topics
    for path in sorted(store.glob("*.md")):
        if path.name == "MEMORY.md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.match(r"^---\n([\s\S]*?)\n---\n?", text)
        head = match.group(1) if match else ""
        description = ""
        tags = ""
        salience = "normal"
        publish = "private"
        for line in head.splitlines():
            key, _, value = line.partition(":")
            value = value.strip().strip("'\"")
            if key.strip() == "description":
                description = value
            elif key.strip() == "tags":
                tags = value
            elif key.strip() == "salience":
                salience = value
            elif key.strip() == "publish":
                publish = value
        topics.append({"slug": path.stem, "description": description, "tags": tags,
                       "salience": salience, "publish": publish,
                       "body": text[match.end():] if match else text})
    order = {"high": 0, "normal": 1, "low": 2}
    topics.sort(key=lambda topic: (order.get(topic["salience"], 1), topic["slug"]))
    return topics


def tokens(text: str) -> set[str]:
    latin = set(re.findall(r"[a-z0-9]{3,}", text.lower()))
    han = re.findall(r"[\u4e00-\u9fff]+", text)
    grams = set()
    for run in han:
        for size in (2, 3):
            grams.update(run[index:index + size] for index in range(max(0, len(run) - size + 1)))
    return latin | grams


def covered_by(conclusion: str, topics: list[dict], suggested: str | None) -> str | None:
    if suggested and any(topic["slug"] == suggested for topic in topics):
        return suggested
    wanted = tokens(conclusion)
    if not wanted:
        return None
    best = (0.0, None)
    for topic in topics:
        have = tokens(topic["description"] + " " + topic["tags"])
        if not have:
            continue
        score = len(wanted & have) / len(wanted)
        if score > best[0]:
            best = (score, topic["slug"])
    return best[1] if best[0] >= 0.65 else None


def existing_marker(slug: str, marker: str, topics: list[dict]) -> bool:
    return any(topic["slug"] == slug and marker in topic["body"] for topic in topics)


# --- model decision -------------------------------------------------------

def curator_prompt(item: dict, topics: list[dict]) -> str:
    # Only public descriptions leave the host. De-dupe below still runs against
    # every topic locally, so a private note can suppress a duplicate without its
    # text reaching the model.
    catalogue = "\n".join(
        f"- {topic['slug']}: {topic['description'][:180]}"
        for topic in topics[:80] if topic["description"] and topic["publish"] == "public")
    payload = {
        "stage": item["stage"],
        "task": item["task_id"].rsplit("-", 2)[0],
        "user_words": item["user_words"],
        "result": item["result"],
    }
    return f"""你是 Rick 的记忆管理员。判断下面这次派发里 owner 的原话（或这次任务的结果）是否包含一条**跨日期仍然成立、会改变未来行为**的规则、偏好、定义或教训。

只在同时满足以下条件时 store=true：
- 是 owner 对未来同类任务的稳定要求，或任务得出的可复用工程结论；
- 不含某一天的价格、仓位、涨跌、日期、HTML 壳、文件路径、task/session id、凭证；
- 不是一次性的任务描述（例如「修 #1234」「跑一下测试」）；
- 不是现有 topic 已经覆盖的内容。

如果现有 topic 已覆盖，store=false 并填 existing_topic。宁可漏记，不要写噪音。不要复述原话；用一句自足的中文结论。

现有 topic：
{catalogue or '(none)'}

待判断内容（JSON）：
{json.dumps(payload, ensure_ascii=False)}

只输出一个 JSON 对象，不要 Markdown：
{{"store": true|false, "kind": "preference|rule|definition|lessons|none", "summary": "一行摘要，<=80字", "conclusion": "一行自足结论，<=200字", "slug": "feedback-...", "scope": "engineering|investment|persona|memory", "salience": "high|normal|low", "publish": "public|private", "tags": ["facet"], "confidence": 0.0, "reason": "一句话", "existing_topic": null}}"""


def validate_decision(decision, topics: list[dict]) -> dict:
    if not isinstance(decision, dict):
        raise IntakeError("decision is not an object")
    store = decision.get("store")
    if store is False:
        return {"store": False, "reason": str(decision.get("reason") or "not durable")[:300],
                "existing_topic": decision.get("existing_topic")}
    if store is not True:
        raise IntakeError("decision.store must be true or false")
    kind = str(decision.get("kind") or "").lower()
    if kind not in KIND_PREFIX:
        raise IntakeError("decision.kind is not storable")
    summary = str(decision.get("summary") or "").strip()
    conclusion = str(decision.get("conclusion") or "").strip()
    if not one_line(summary) or not one_line(conclusion) or len(conclusion) > 240:
        raise IntakeError("summary/conclusion must be one short line")
    for text in (summary, conclusion):
        if reasons(text):
            raise IntakeError(f"contamination: {','.join(reasons(text))}")
        if "<!--" in text or text.startswith("#") or "`clawock" in text:
            raise IntakeError("conclusion contains markup/command text")
    scope = str(decision.get("scope") or "").lower()
    if scope not in ("engineering", "investment", "persona", "memory"):
        raise IntakeError("decision.scope is not a known scope")
    salience = str(decision.get("salience") or "normal").lower()
    if salience not in ("high", "normal", "low"):
        raise IntakeError("decision.salience is invalid")
    publish = str(decision.get("publish") or "private").lower()
    if publish not in ("public", "private"):
        raise IntakeError("decision.publish is invalid")
    try:
        confidence = float(decision.get("confidence"))
    except (TypeError, ValueError):
        raise IntakeError("decision.confidence is not a number")
    slug = str(decision.get("slug") or "").strip().lower()
    if not SLUG_RE.fullmatch(slug) or not slug.startswith(PREFIXES):
        slug = KIND_PREFIX[kind] + (SLUG_RE.sub("-", slug).strip("-") or digest(conclusion)[:8])
    if not slug.startswith(PREFIXES):
        slug = KIND_PREFIX[kind] + slug
    suggested = decision.get("existing_topic")
    suggested = str(suggested).strip() if isinstance(suggested, str) and suggested.strip() else None
    covered = covered_by(conclusion, topics, suggested)
    if covered:
        return {"store": False, "reason": "already covered", "existing_topic": covered}
    # A single capture can propose public only for an explicit user rule, with high
    # confidence; the caller still caps and projects it.
    if publish == "public" and (kind not in ("preference", "rule") or confidence < 0.8):
        publish = "private"
    return {"store": True, "kind": kind, "summary": summary, "conclusion": conclusion,
            "slug": slug, "scope": scope, "salience": salience, "publish": publish,
            "tags": [str(tag)[:32] for tag in (decision.get("tags") or []) if re.fullmatch(r"[a-z0-9-]{1,32}", str(tag))][:6],
            "confidence": confidence, "reason": str(decision.get("reason") or "")[:300],
            "existing_topic": None}


# --- write ----------------------------------------------------------------

def run(command: list[str], *, env: dict, what: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(command, text=True, capture_output=True, env=env)
    if proc.returncode:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise IntakeError(f"{what} failed: {detail[-1][:300] if detail else 'no output'}")
    return proc


def memory_env(store: Path) -> dict:
    env = {**os.environ, "SHARED_MEMORY_DIR": str(store), "SHARED_MEMORY_STATE": str(DEFAULT_STATE),
           "MEMCTL_AGENT": "rick"}
    return env


def next_order(store: Path) -> int | None:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    try:
        import publish as projection
        topics = projection.load_public_topics(store)
    except Exception:
        return None
    return max(topic["order"] for topic in topics) + 1


def write_topic(store: Path, repo: Path, decision: dict) -> dict:
    # Serialize with promote_dreaming.py: order allocation, the store write and the
    # projection must be one transaction, or two public writers can claim one order.
    lock_path = store / ".dreaming-promotion.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = lock_path.open("a")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_handle.close()
        raise IntakeError("promotion lock is held; the item stays queued for the next run") from exc
    try:
        return _write_topic_locked(store, repo, decision)
    finally:
        lock_handle.close()


def _write_topic_locked(store: Path, repo: Path, decision: dict) -> dict:
    marker = f"<!-- memory-intake:{digest(decision['conclusion'])[:16]} -->"
    order = None
    publish = decision["publish"]
    if publish == "public":
        order = next_order(store)
        if order is None:
            publish = "private"
    body = f"# {decision['summary']}\n\n{decision['conclusion']}\n\n{marker}\n"
    if publish == "public":
        body = ("---\nmetadata:\n"
                f"  order: {order}\n  separator: true\n"
                "---\n\n" + body)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as stream:
        stream.write(body)
        body_file = stream.name
    try:
        status = "verified" if decision["kind"] in ("preference", "rule") else "hypothesis"
        command = [sys.executable, str(MEMORY_PY), "add", decision["slug"],
                   "--summary", decision["summary"], "--body-file", body_file,
                   "--type", "feedback" if decision["kind"] in ("preference", "rule") else "project",
                   "--scope", decision["scope"], "--salience", decision["salience"],
                   "--status", status, "--publish", publish]
        for tag in decision["tags"]:
            command += ["--tag", tag]
        run(command, env=memory_env(store), what="memory write")
    finally:
        Path(body_file).unlink(missing_ok=True)
    result = {"store": True, "slug": decision["slug"], "publish": publish,
              "marker": marker, "status": status}
    if publish == "public":
        manifest = repo / MANIFEST_REL
        try:
            run([sys.executable, str(PUBLISH_PY), "--write", "--repo", str(repo),
                 "--store", str(store), "--manifest", str(manifest)],
                env=memory_env(store), what="publish projection")
        except IntakeError as exc:
            run([sys.executable, str(MEMORY_PY), "update", decision["slug"], "--publish", "private"],
                env=memory_env(store), what="downgrade to private")
            result.update(publish="private", projection_error=str(exc)[:300])
    return result


def record(entry: dict) -> None:
    path = state_dir() / "ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


def public_writes_today() -> int:
    path = state_dir() / "ledger.jsonl"
    if not path.is_file():
        return 0
    today = date.today().isoformat()
    count = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("action") == "written" and entry.get("publish") == "public" \
                and str(entry.get("at", "")).startswith(today):
            count += 1
    return count


# --- process --------------------------------------------------------------

def process(item: dict, *, dry_run: bool, llm_response: str | None,
            repo: Path, store: Path) -> dict:
    topics = store_topics(store)
    prompt = curator_prompt(item, topics)
    if llm_response is not None:
        text = Path(llm_response).read_text(encoding="utf-8")
    else:
        text = llm_json.run_model(prompt)
    decision = validate_decision(llm_json.extract_json(text), topics)
    base = {"id": item["id"], "task_id": item["task_id"], "stage": item["stage"],
            "at": datetime.now().astimezone().isoformat(timespec="seconds")}
    if not decision["store"]:
        return {**base, "action": "skipped", "reason": decision["reason"],
                "existing_topic": decision.get("existing_topic")}
    if decision["slug"] and any(topic["slug"] == decision["slug"] for topic in topics):
        return {**base, "action": "skipped", "reason": "slug exists",
                "existing_topic": decision["slug"]}
    if decision["publish"] == "public" and public_writes_today() >= MAX_PUBLIC_PER_DAY:
        decision["publish"] = "private"
        decision["reason"] += " (daily public cap)"
    if dry_run:
        return {**base, "action": "would_write", **{key: decision[key] for key in
                ("slug", "summary", "conclusion", "scope", "salience", "publish")}}
    written = write_topic(store, repo, decision)
    entry = {**base, "action": "written", **written, "summary": decision["summary"],
             "conclusion": decision["conclusion"], "scope": decision["scope"],
             "salience": decision["salience"], "confidence": decision["confidence"],
             "reason": decision["reason"], "user_words_sha256": item["prompt_sha256"]}
    record(entry)
    return entry


def queue_items(task: str | None) -> list[Path]:
    queue = state_dir() / "queue"
    if not queue.is_dir():
        return []
    paths = sorted(queue.glob("*.json"), key=lambda path: path.stat().st_mtime)
    return [path for path in paths if task is None or path.name.startswith(task + "-")]


def run_queue(args) -> dict:
    item_paths = queue_items(args.task)
    summary = {"seen": len(item_paths), "written": 0, "skipped": 0, "failed": 0, "results": []}
    for path in item_paths[:args.limit]:
        handle = lock()
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            try:
                result = process(item, dry_run=args.dry_run, llm_response=args.llm_response,
                                 repo=args.repo.resolve(), store=args.store.resolve())
            except (IntakeError, llm_json.LLMError, OSError, ValueError) as exc:
                item["attempts"] = int(item.get("attempts", 0)) + 1
                item["last_error"] = str(exc)[:400]
                if item["attempts"] >= MAX_ATTEMPTS:
                    atomic_write(state_dir() / "failed" / path.name, json.dumps(item, ensure_ascii=False, indent=2) + "\n")
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, json.dumps(item, ensure_ascii=False, indent=2) + "\n")
                summary["failed"] += 1
                summary["results"].append({"task_id": item.get("task_id"), "action": "failed",
                                           "error": str(exc)[:300]})
                continue
            summary["results"].append(result)
            if result.get("action") == "written":
                summary["written"] += 1
            else:
                summary["skipped"] += 1
            if not args.dry_run:
                atomic_write(state_dir() / "processed" / path.name,
                             json.dumps({"item": item, "result": result}, ensure_ascii=False, indent=2) + "\n")
                path.unlink(missing_ok=True)
        finally:
            handle.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture", help="queue one task's user words (no model call)")
    cap.add_argument("--task-dir", type=Path, required=True)
    cap.add_argument("--stage", choices=("dispatch", "outcome"), default="dispatch")
    cap.add_argument("--check", action="store_true", help="report what would be queued")
    run = sub.add_parser("run", help="distil queued items through the model")
    run.add_argument("--limit", type=int, default=5)
    run.add_argument("--task")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--llm-response", type=Path, help="read one fake model reply (tests)")
    chat = sub.add_parser("capture-chat", help="queue the day's user lines from the private corpus")
    chat.add_argument("--date", default=date.today().isoformat())
    chat.add_argument("--workspace", type=Path, default=DEFAULT_REPO)
    sub.add_parser("status", help="queue/processed/failed counts")
    args = parser.parse_args()
    try:
        if args.command == "capture":
            path = capture(args.task_dir, args.stage)
            print(json.dumps({"queued": str(path), "dry_run": args.check}, ensure_ascii=False))
            return 0
        if args.command == "run":
            if args.limit < 1:
                raise IntakeError("--limit must be positive")
            print(json.dumps(run_queue(args), ensure_ascii=False, indent=2))
            return 0
        if args.command == "capture-chat":
            paths = capture_chat(args.date, args.workspace.expanduser().resolve())
            print(json.dumps({"queued": len(paths), "date": args.date}, ensure_ascii=False))
            return 0
        counts = {name: len(list((state_dir() / name).glob("*.json")))
                  for name in ("queue", "processed", "failed")}
        print(json.dumps(counts, ensure_ascii=False))
        return 0
    except (IntakeError, llm_json.LLMError, OSError, ValueError) as exc:
        print(f"intake: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
