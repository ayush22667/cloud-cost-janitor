import boto3
import pytest

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
    with pytest.raises(Exception):  # an unknown profile must fail loudly, not fall back to default
        AwsCredentials(profile="does-not-exist").base_session()
