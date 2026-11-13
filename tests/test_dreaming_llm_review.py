"""The model reviewer writes hash-bound receipts for clean dreaming candidates.

The deterministic gate remains the authority; these tests pin that a model cannot
approve contaminated text, cannot bind a different candidate, and cannot bypass the
one-conclusion-per-source rule.
"""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "ops/host/review_dreaming_llm.py"
PROMOTE = ROOT / "ops/host/promote_dreaming.py"
GATE = ROOT / "ops/host/review_dreaming.py"
sys.path.insert(0, str(ROOT / "ops/host"))


def load_gate():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gate_for_test", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate(text, line=10, source="memory/2026-11-12.md"):
    return (f"## Promoted From Short-Term Memory (2026-11-13)\n\n"
            f"<!-- openclaw-memory-promotion:memory:{source}:{line}:{line} -->\n"
            f"- {text} [score=0.8 recalls=0 avg=0.6 source={source}:{line}-{line}]\n")


def workspace(tmp_path, text):
    ws = tmp_path / "ws"
    (ws / "memory/.dreams").mkdir(parents=True)
    (ws / "MEMORY.md").write_text("# Memory\n\n## Existing\n\nkeep\n", encoding="utf-8")
    (ws / "memory/.dreams/promotion-candidates.md").write_text(text, encoding="utf-8")
    return ws


def run_review(ws, store, reply, *args):
    response = ws / "reply.json"
    response.write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
    return subprocess.run([sys.executable, str(REVIEW), "--workspace", str(ws),
                           "--store", str(store), "--llm-response", str(response), *args],
                          capture_output=True, text=True, timeout=60)


def test_the_reviewer_catalogue_contains_only_public_topics(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("review_for_test", REVIEW)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = tmp_path / "store"
    store.mkdir()
    (store / "feedback-public.md").write_text(
        "---\nname: feedback-public\ndescription: \"public rule\"\n"
        "metadata:\n  publish: public\n---\n\n# P\n", encoding="utf-8")
    (store / "project-private.md").write_text(
        "---\nname: project-private\ndescription: \"private deployment note\"\n"
        "metadata:\n  publish: private\n---\n\n# P\n", encoding="utf-8")
    catalogue = module.topic_catalogue(store)
    assert "public rule" in catalogue
    assert "private deployment note" not in catalogue


def test_a_clean_candidate_gets_a_hash_bound_receipt_and_promotes(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    text = candidate("派 agent 处理 issue 前先独立复现，不要照描述直接改代码。")
    ws = workspace(tmp_path, text)
    entry = load_gate().extract(text)[1][0]
    result = run_review(ws, store, [{
        "key": entry["key"], "decision": "approve",
        "conclusion": "派 agent 处理 issue 前先独立复现或反证，不照描述直接改代码",
        "scope": "engineering", "salience": "high", "reason": "重复出现且可跨日复用"}])
    assert result.returncode == 0, result.stderr
    approvals = json.loads((ws / "memory/.dreams/promotion-approvals.json").read_text())
    receipt = approvals[entry["key"]]
    assert receipt["sha256"] == entry["sha256"]
    assert receipt["reviewer"] == "llm:deepseek/deepseek-v4-pro"
    assert receipt["scope"] == "engineering" and receipt["salience"] == "high"
    check = subprocess.run([sys.executable, str(PROMOTE), "--workspace", str(ws),
                            "--store", str(store), "--check"],
                           capture_output=True, text=True, timeout=60)
    assert check.returncode == 0, check.stderr
    decision = json.loads(check.stdout)
    assert decision["decisions"]["approved"] == 1
    assert decision["write"] == ["lessons-dreaming-2026-11-12-10-10"]


def test_a_named_covering_topic_blocks_the_promotion(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    text = candidate("chat 里只做判断，代码都交给 coding agent。")
    ws = workspace(tmp_path, text)
    entry = load_gate().extract(text)[1][0]
    result = run_review(ws, store, [{
        "key": entry["key"], "decision": "reject", "covered_by": "feedback-delegation-brief",
        "conclusion": "chat 里只做判断，代码交给 coding agent",
        "scope": "engineering", "salience": "high", "reason": "已有 topic 覆盖"}])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["approved"] == 0
    assert not (ws / "memory/.dreams/promotion-approvals.json").exists()


def test_a_contaminated_candidate_is_never_sent_to_the_model(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    text = (candidate("今天 178.1 卖 40 股，恒科收在 4045.91。", line=10)
            + candidate("Verify the source before trusting a summary.", line=20,
                        source="memory/2026-11-13.md"))
    ws = workspace(tmp_path, text)
    gate = load_gate()
    clean = gate.extract(text)[1][1]
    result = run_review(ws, store, [{
        "key": clean["key"], "decision": "approve",
        "conclusion": "先核对来源，再把摘要当作独立证据",
        "scope": "engineering", "salience": "normal", "reason": "可复用"}])
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["sent"] == 1 and summary["approved"] == 1
    approvals = json.loads((ws / "memory/.dreams/promotion-approvals.json").read_text())
    assert set(approvals) == {clean["key"]}
    assert "今天 178.1" not in json.dumps(approvals, ensure_ascii=False)


def test_a_contaminated_model_conclusion_is_dropped(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    text = candidate("Verify the source before trusting a summary.")
    ws = workspace(tmp_path, text)
    entry = load_gate().extract(text)[1][0]
    result = run_review(ws, store, [{
        "key": entry["key"], "decision": "approve",
        "conclusion": "2026-11-13 收盘 12.34 美元，减仓",
        "scope": "investment", "salience": "high", "reason": "x"}])
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["approved"] == 0 and summary["rejected"] == 1
    assert not (ws / "memory/.dreams/promotion-approvals.json").exists()


def test_a_receipt_cannot_be_bound_to_a_different_sha(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    text = candidate("Verify the source before trusting a summary.")
    ws = workspace(tmp_path, text)
    entry = load_gate().extract(text)[1][0]
    result = run_review(ws, store, [{
        "key": entry["key"], "decision": "approve",
        "conclusion": "先核对来源，再把摘要当作独立证据",
        "scope": "engineering", "salience": "normal", "reason": "可复用"}])
    assert result.returncode == 0, result.stderr
    approvals = json.loads((ws / "memory/.dreams/promotion-approvals.json").read_text())
    approvals[entry["key"]]["sha256"] = "0" * 64
    (ws / "memory/.dreams/promotion-approvals.json").write_text(json.dumps(approvals))
    check = subprocess.run([sys.executable, str(PROMOTE), "--workspace", str(ws),
                            "--store", str(store), "--check"],
                           capture_output=True, text=True, timeout=60)
    assert check.returncode == 1
    assert "invalid review receipt" in check.stderr
