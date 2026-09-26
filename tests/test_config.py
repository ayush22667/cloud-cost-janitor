import pytest

from cloud_cost_janitor.config import IDENTITY_HELP, load_settings

ENV_KEYS = (
    "COST_JANITOR_TOKEN", "AWS_REGIONS", "ALLOW_DELETE", "DELETE_ONLY_TAGGED", "JANITOR_PORT",
    "AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_ROLE_ARN", "AWS_EXTERNAL_ID",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def base(monkeypatch):
    monkeypatch.setenv("COST_JANITOR_TOKEN", "abc")
    monkeypatch.setenv("AWS_PROFILE", "janitor")


def test_token_is_required(monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "janitor")
    with pytest.raises(ValueError, match="COST_JANITOR_TOKEN"):
        load_settings(env_file=None)


def test_identity_is_required_no_implicit_default(monkeypatch):
    monkeypatch.setenv("COST_JANITOR_TOKEN", "abc")
    with pytest.raises(ValueError, match="AWS identity must be set"):
        load_settings(env_file=None)


def test_profile_is_accepted(base):
    s = load_settings(env_file=None)
    assert s.aws_profile == "janitor" and s.aws_access_key_id is None


def test_key_pair_is_accepted(monkeypatch):
    monkeypatch.setenv("COST_JANITOR_TOKEN", "abc")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "tok")
    s = load_settings(env_file=None)
    assert s.aws_access_key_id == "AKIAEXAMPLE" and s.aws_profile is None


def test_half_key_pair_is_rejected(monkeypatch):
    monkeypatch.setenv("COST_JANITOR_TOKEN", "abc")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    with pytest.raises(ValueError, match="together"):
        load_settings(env_file=None)


def test_profile_and_keys_together_are_rejected(base, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    with pytest.raises(ValueError, match="not both"):
        load_settings(env_file=None)


def test_external_id_needs_role_and_length(base, monkeypatch):
    monkeypatch.setenv("AWS_EXTERNAL_ID", "shared-secret-1")
    with pytest.raises(ValueError, match="AWS_ROLE_ARN"):
        load_settings(env_file=None)
    monkeypatch.setenv("AWS_ROLE_ARN", "arn:aws:iam::123456789012:role/CloudCostJanitorRole")
    s = load_settings(env_file=None)
    assert s.aws_role_arn.endswith("CloudCostJanitorRole") and s.aws_external_id == "shared-secret-1"
    monkeypatch.setenv("AWS_EXTERNAL_ID", "short")
    with pytest.raises(ValueError, match="at least 8"):
        load_settings(env_file=None)


def test_secrets_never_appear_in_repr(monkeypatch):
    monkeypatch.setenv("COST_JANITOR_TOKEN", "tok-SECRET-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "key-SECRET-2")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "sess-SECRET-3")
    monkeypatch.setenv("AWS_ROLE_ARN", "arn:aws:iam::123456789012:role/r")
    monkeypatch.setenv("AWS_EXTERNAL_ID", "ext-SECRET-4-long-enough")
    text = repr(load_settings(env_file=None))
    for secret in ("tok-SECRET-1", "AKIAEXAMPLE", "key-SECRET-2", "sess-SECRET-3", "ext-SECRET-4-long-enough"):
        assert secret not in text


def test_safe_defaults(base):
    s = load_settings(env_file=None)
    assert s.allow_delete is False and s.dry_run is True
    assert s.delete_only_tag == ("janitor-demo", "true")
    assert s.regions == ("us-east-1",)
    assert s.port == 8000
    assert ("janitor:keep", "true") in s.protected_tags


def test_env_overrides(base, monkeypatch):
    monkeypatch.setenv("AWS_REGIONS", "us-east-1, ap-south-1")
    monkeypatch.setenv("ALLOW_DELETE", "true")
    monkeypatch.setenv("DELETE_ONLY_TAGGED", "team=platform")
    monkeypatch.setenv("JANITOR_PORT", "8010")
    s = load_settings(env_file=None)
    assert s.regions == ("us-east-1", "ap-south-1")
    assert s.allow_delete is True and s.dry_run is False
    assert s.delete_only_tag == ("team", "platform")
    assert s.port == 8010


def test_empty_delete_only_tag_disables_guard(base, monkeypatch):
    monkeypatch.setenv("DELETE_ONLY_TAGGED", "")
    assert load_settings(env_file=None).delete_only_tag is None


def test_env_file_is_loaded(tmp_path):
    env = tmp_path / ".env"
    env.write_text("COST_JANITOR_TOKEN=from-file\nAWS_PROFILE=janitor\nALLOW_DELETE=yes\n")
    s = load_settings(env_file=env)
    assert s.token == "from-file" and s.aws_profile == "janitor" and s.allow_delete is True


def test_help_text_names_both_options():
    assert "AWS_PROFILE" in IDENTITY_HELP and "AWS_ACCESS_KEY_ID" in IDENTITY_HELP
