import json

from cloud_cost_janitor.server.audit import AuditLog


def test_audit_log_appends_json_lines(tmp_path):
    log = AuditLog(tmp_path / "nested" / "audit.jsonl")
    log.record("plan.created", plan_id="abc", findings=["vol-1"])
    log.record("delete.done", resource_id="vol-1", snapshots=[{"snapshot_id": "snap-1", "state": "pending"}])
    lines = [json.loads(l) for l in (tmp_path / "nested" / "audit.jsonl").read_text().splitlines()]
    assert [l["event"] for l in lines] == ["plan.created", "delete.done"]
    assert lines[0]["plan_id"] == "abc" and lines[1]["snapshots"][0]["snapshot_id"] == "snap-1"
    assert all("ts" in l for l in lines)
