import pytest

from cloud_cost_janitor.config import load_settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("COST_JANITOR_TOKEN", "AWS_REGIONS", "ALLOW_DELETE", "DELETE_ONLY_TAGGED", "JANITOR_PORT", "AWS_PROFILE"):
        monkeypatch.delenv(key, raising=False)


def test_token_is_required():
    with pytest.raises(ValueError, match="COST_JANITOR_TOKEN"):
        load_settings(env_file=None)


def test_safe_defaults(monkeypatch):
    monkeypatch.setenv("COST_JANITOR_TOKEN", "abc")
    s = load_settings(env_file=None)
    assert s.allow_delete is False and s.dry_run is True
    assert s.delete_only_tag == ("janitor-demo", "true")
    assert s.regions == ("us-east-1",)
    assert s.port == 8000
    assert ("janitor:keep", "true") in s.protected_tags


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("COST_JANITOR_TOKEN", "abc")
    monkeypatch.setenv("AWS_REGIONS", "us-east-1, ap-south-1")
    monkeypatch.setenv("ALLOW_DELETE", "true")
    monkeypatch.setenv("DELETE_ONLY_TAGGED", "team=platform")
    monkeypatch.setenv("JANITOR_PORT", "8010")
    s = load_settings(env_file=None)
    assert s.regions == ("us-east-1", "ap-south-1")
    assert s.allow_delete is True and s.dry_run is False
    assert s.delete_only_tag == ("team", "platform")
    assert s.port == 8010


def test_empty_delete_only_tag_disables_guard(monkeypatch):
    monkeypatch.setenv("COST_JANITOR_TOKEN", "abc")
    monkeypatch.setenv("DELETE_ONLY_TAGGED", "")
    assert load_settings(env_file=None).delete_only_tag is None


def test_env_file_is_loaded(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("COST_JANITOR_TOKEN=from-file\nALLOW_DELETE=yes\n")
    s = load_settings(env_file=env)
    assert s.token == "from-file" and s.allow_delete is True
