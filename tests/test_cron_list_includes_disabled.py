"""The CLI omits disabled jobs unless asked, and a host-triggered job is disabled
in OpenClaw on purpose. Reading without `--all` made the contract check call it a
missing live job — a CRITICAL that blocks every live push (2026-09-12 03:24)."""
from clawock.providers import openclaw


def test_both_job_reads_ask_for_disabled_jobs_too(monkeypatch):
    seen = []

    def fake(args, **kwargs):
        seen.append(list(args))
        return {"jobs": [{"name": "港股午后快报", "enabled": False}]}

    monkeypatch.setattr(openclaw, "cron_cli_json", fake)
    assert openclaw.read_jobs("cli").entries[0]["enabled"] is False
    assert openclaw.read_jobs_strict()[0]["name"] == "港股午后快报"
    assert seen and all("--all" in args for args in seen)
