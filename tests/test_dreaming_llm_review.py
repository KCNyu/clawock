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
    assert receipt["reviewer"] == "llm:minimax/MiniMax-M3.1-Flash"
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


def test_prose_wrapped_batch_records_both_candidates(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    text = (candidate("Verify the source before trusting a summary.")
            + candidate("Separate observations from conclusions.", line=20,
                        source="memory/2026-11-13.md"))
    ws = workspace(tmp_path, text)
    entries = load_gate().extract(text)[1]
    reply = [{"key": entry["key"], "decision": "approve",
              "conclusion": conclusion, "scope": "engineering",
              "salience": "normal", "reason": "可复用"}
             for entry, conclusion in zip(entries, [
                 "先核对来源，再把摘要当作独立证据", "把观测事实和推导结论分别记录"])]
    response = ws / "reply.txt"
    response.write_text("审阅结果如下：\n```json\n"
                        + json.dumps(reply, ensure_ascii=False) + "\n```\n审阅完成。",
                        encoding="utf-8")
    result = subprocess.run([sys.executable, str(REVIEW), "--workspace", str(ws),
                             "--store", str(store), "--llm-response", str(response)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["approved"] == 2
    approvals = json.loads((ws / "memory/.dreams/promotion-approvals.json").read_text())
    assert set(approvals) == {entry["key"] for entry in entries}


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


def test_rejected_candidate_releases_the_next_candidate_from_its_source(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    text = (candidate("A vague slogan about careful work.")
            + candidate("Verify original evidence before drawing conclusions.", line=20))
    ws = workspace(tmp_path, text)
    entries = load_gate().extract(text)[1]
    first = run_review(ws, store, [{"key": entries[0]["key"], "decision": "reject",
                                  "reason": "口号，没有可执行结论"}], "--limit", "1")
    assert first.returncode == 0, first.stderr
    second = run_review(ws, store, [{"key": entries[1]["key"], "decision": "approve",
                                    "conclusion": "得出结论前先核验原始证据",
                                    "scope": "engineering", "salience": "high",
                                    "reason": "可复用方法"}], "--limit", "1")
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["approved"] == 1
    rejected = json.loads((ws / "memory/.dreams/promotion-rejections.json").read_text())
    assert rejected[entries[0]["key"]]["sha256"] == entries[0]["sha256"]


def test_rejected_batch_does_not_starve_later_sources(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    text = (candidate("A vague slogan about careful work.")
            + candidate("Separate evidence and inference.", source="memory/other.md"))
    ws = workspace(tmp_path, text)
    entries = load_gate().extract(text)[1]
    for entry in entries:
        result = run_review(ws, store, [{"key": entry["key"], "decision": "reject",
                                        "reason": "已有结论覆盖"}], "--limit", "1")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["sent"] == 1
    exhausted = run_review(ws, store, [], "--limit", "1")
    assert exhausted.returncode == 0, exhausted.stderr
    assert json.loads(exhausted.stdout)["sent"] == 0


def test_changed_rejected_candidate_is_reviewed_again(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    text = candidate("A vague slogan about careful work.")
    ws = workspace(tmp_path, text)
    entry = load_gate().extract(text)[1][0]
    result = run_review(ws, store, [{"key": entry["key"], "decision": "reject",
                                    "reason": "口号"}])
    assert result.returncode == 0, result.stderr
    (ws / "memory/.dreams/promotion-candidates.md").write_text(
        candidate("Verify original evidence before drawing conclusions."))
    retry = run_review(ws, store, [], "--check")
    assert retry.returncode == 0, retry.stderr
    assert json.loads(retry.stdout)["sent"] == 1


def test_missing_model_answer_and_invalid_approval_remain_retryable(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    ws = workspace(tmp_path, candidate("Verify original evidence before drawing conclusions."))
    for reply in ([], [{"key": load_gate().extract(
            (ws / "memory/.dreams/promotion-candidates.md").read_text())[1][0]["key"],
            "decision": "approve", "conclusion": "今天 12.34 美元", "reason": "x"}]):
        result = run_review(ws, store, reply)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["sent"] == 1
        assert not (ws / "memory/.dreams/promotion-rejections.json").exists()


def test_check_does_not_record_a_rejection(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    text = candidate("A vague slogan about careful work.")
    ws = workspace(tmp_path, text)
    entry = load_gate().extract(text)[1][0]
    result = run_review(ws, store, [{"key": entry["key"], "decision": "reject",
                                    "reason": "口号"}], "--check")
    assert result.returncode == 0, result.stderr
    assert not (ws / "memory/.dreams/promotion-rejections.json").exists()


def test_already_promoted_source_does_not_consume_review_slots(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    text = (candidate("Another conclusion from an already accepted source.")
            + candidate("Verify original evidence before drawing conclusions.", source="memory/new.md"))
    ws = workspace(tmp_path, text)
    (ws / "MEMORY.md").write_text("# Memory\n\n- Source: memory/2026-11-12.md:1-1 (reviewed)\n")
    new = load_gate().extract(text)[1][1]
    result = run_review(ws, store, [{"key": new["key"], "decision": "approve",
                                    "conclusion": "得出结论前先核验原始证据",
                                    "scope": "engineering", "salience": "high",
                                    "reason": "可复用方法"}], "--limit", "1")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["approved"] == 1
