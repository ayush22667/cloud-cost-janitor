import re
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, ProfileNotFound

from cloud_cost_janitor.config import load_settings
from cloud_cost_janitor.providers.aws.client import AwsClients, AwsCredentials
from cloud_cost_janitor.providers.aws.provider import AwsProvider
from cloud_cost_janitor.providers.base import ProviderError
from tests.providers.conftest import TEST_CREDENTIALS

ROLE_ARN = "arn:aws:iam::123456789012:role/CloudCostJanitorRole"


def test_credentials_require_profile_or_keys():
    with pytest.raises(ValueError):
        AwsCredentials().base_session()


def test_secrets_hidden_from_repr():
    c = AwsCredentials(access_key_id="AKIAEXAMPLE", secret_access_key="s3cret", session_token="tok", external_id="ext")
    assert "s3cret" not in repr(c) and "tok" not in repr(c) and "ext" not in repr(c) and "AKIAEXAMPLE" not in repr(c)


def test_verify_with_key_pair(mocked_aws):
    AwsClients(TEST_CREDENTIALS).verify()  # no exception, no return value


def test_provider_verify_credentials_wraps_errors(mocked_aws, monkeypatch):
    provider = AwsProvider(AwsClients(TEST_CREDENTIALS))
    provider.verify_credentials()

    class Boom(Exception):
        response = {"Error": {"Code": "InvalidClientTokenId", "Message": "The security token is invalid."}}

    from botocore.exceptions import ClientError

    def fail(*_a, **_k):
        raise ClientError(Boom.response, "GetCallerIdentity")

    monkeypatch.setattr(provider._c, "verify", fail)
    with pytest.raises(ProviderError, match="InvalidClientTokenId"):
        provider.verify_credentials()


def test_role_assumption_uses_temporary_credentials(mocked_aws):
    iam = boto3.client("iam", region_name="us-east-1")
    iam.create_role(RoleName="CloudCostJanitorRole", AssumeRolePolicyDocument="{}")
    clients = AwsClients(AwsCredentials(access_key_id="testing", secret_access_key="testing", role_arn=ROLE_ARN, external_id="shared-secret-1"))
    ident = clients._client("sts", "us-east-1").get_caller_identity()
    assert ":assumed-role/CloudCostJanitorRole/cloud-cost-janitor" in ident["Arn"]
    clients.verify()


def test_profile_session_is_explicit(monkeypatch, tmp_path):
    cred = tmp_path / "credentials"
    cred.write_text("[janitor]\naws_access_key_id = testing\naws_secret_access_key = testing\n")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(cred))
    session = AwsCredentials(profile="janitor").base_session()
    assert session.profile_name == "janitor"
    with pytest.raises(ProfileNotFound):  # an unknown profile must fail loudly, not fall back to default
        AwsCredentials(profile="does-not-exist").base_session()


def test_key_pair_ignores_a_blank_aws_profile_in_the_environment(monkeypatch):
    """Regression: .env.example once shipped ``AWS_PROFILE=``; boto3 read the blank and raised ProfileNotFound."""
    monkeypatch.setenv("AWS_PROFILE", "")
    load_settings_env = {"COST_JANITOR_TOKEN": "t", "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing"}
    for k, v in load_settings_env.items():
        monkeypatch.setenv(k, v)
    settings = load_settings(env_file=None)
    session = AwsCredentials.from_settings(settings).base_session()
    session.client("sts", region_name="us-east-1")  # no ProfileNotFound


def test_assumed_role_session_is_built_from_the_base_session(mocked_aws, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "")
    monkeypatch.setenv("COST_JANITOR_TOKEN", "t")
    settings = load_settings(env_file=None)  # drops the blank AWS_PROFILE
    iam = boto3.client("iam", region_name="us-east-1")
    iam.create_role(RoleName="CloudCostJanitorRole", AssumeRolePolicyDocument="{}")
    creds = AwsCredentials(access_key_id="testing", secret_access_key="testing", role_arn=ROLE_ARN)
    assert settings.aws_profile is None
    AwsClients(creds).verify()
    source = (Path(__file__).resolve().parents[2] / "src" / "cloud_cost_janitor" / "providers" / "aws" / "client.py").read_text()
    assert not re.search(r"^\s*\w+ = boto3\.Session\(\)", source, re.MULTILINE)  # the root rules forbid the host default chain


def _client_error(code: str, message: str, operation: str = "DeleteVolume") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, operation)


@pytest.mark.parametrize(
    "exc, expect, forbidden",
    [
        (
            _client_error(
                "UnauthorizedOperation",
                "You are not authorized to perform this operation. User: arn:aws:iam::123456789012:user/janitor is not "
                "authorized to perform: ec2:DeleteVolume on resource: arn:aws:ec2:us-east-1:123456789012:volume/vol-1. "
                "Encoded authorization failure message: AbCdEf123",
            ),
            "AWS UnauthorizedOperation: IAM denied DeleteVolume",
            ("arn:aws", "123456789012", "AbCdEf123", "janitor"),
        ),
        (
            _client_error("InvalidVolume.NotFound", "The volume 'vol-1' owned by 123456789012 (arn:aws:ec2:us-east-1:123456789012:volume/vol-1) does not exist."),
            "AWS InvalidVolume.NotFound: The volume 'vol-1' owned by <account> (<arn>) does not exist.",
            ("arn:aws", "123456789012"),
        ),
        (
            EndpointConnectionError(endpoint_url="https://ec2.us-east-1.amazonaws.com/"),
            "AWS EndpointConnectionError: Could not connect to the endpoint URL",
            (),
        ),
    ],
)
def test_provider_errors_never_leak_identity(mocked_aws, monkeypatch, exc, expect, forbidden):
    provider = AwsProvider(AwsClients(TEST_CREDENTIALS))

    def fail(*_a, **_k):
        raise exc

    monkeypatch.setattr(provider._c, "verify", fail)
    with pytest.raises(ProviderError) as info:
        provider.verify_credentials()
    text = str(info.value)
    assert text.startswith(expect), text
    for token in forbidden:
        assert token not in text, token
