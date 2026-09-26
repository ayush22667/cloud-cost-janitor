"""Startup behaviour: fail fast on bad configuration or credentials, and never print identity details."""

import pytest

from cloud_cost_janitor.config import Settings
from cloud_cost_janitor.providers.base import ProviderError
from cloud_cost_janitor.server import __main__ as entry
from tests.server.fake_provider import FakeProvider


def test_exits_without_identity(monkeypatch, capsys):
    monkeypatch.setattr(entry, "load_settings", lambda: (_ for _ in ()).throw(ValueError("AWS identity must be set in .env")))
    with pytest.raises(SystemExit) as e:
        entry.main()
    assert e.value.code == 2 and "AWS identity must be set" in capsys.readouterr().err


def test_exits_when_credentials_rejected(monkeypatch, capsys):
    settings = Settings(token="t", aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="key-SECRET")
    fake = FakeProvider()
    fake.fail_with = "AWS InvalidClientTokenId: The security token included in the request is invalid."
    monkeypatch.setattr(entry, "load_settings", lambda: settings)
    monkeypatch.setattr(entry, "get_provider", lambda s: fake)
    with pytest.raises(SystemExit) as e:
        entry.main()
    err = capsys.readouterr().err
    assert e.value.code == 2 and "credentials rejected" in err
    assert "AKIAEXAMPLE" not in err and "key-SECRET" not in err


def test_startup_line_has_no_identity(monkeypatch, capsys):
    settings = Settings(token="t", aws_profile="ops-profile", aws_role_arn="arn:aws:iam::123456789012:role/CloudCostJanitorRole")
    fake = FakeProvider()
    monkeypatch.setattr(entry, "load_settings", lambda: settings)
    monkeypatch.setattr(entry, "get_provider", lambda s: fake)

    class StopServe(Exception):
        pass

    class App:
        def run(self, **_):
            raise StopServe

    monkeypatch.setattr(entry, "create_app", lambda s, p: App())
    with pytest.raises(StopServe):
        entry.main()
    err = capsys.readouterr().err
    assert "mode=dry-run" in err and "regions=us-east-1" in err
    for forbidden in ("ops-profile", "123456789012", "arn:", "account", "AKIA"):
        assert forbidden not in err, forbidden
