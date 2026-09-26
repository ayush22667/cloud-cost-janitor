"""AwsProvider: the CloudProvider implementation for AWS."""

from __future__ import annotations

import re
from datetime import datetime

from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from cloud_cost_janitor.models import Instance, LoadBalancer, Volume
from cloud_cost_janitor.pricing import PriceBook
from cloud_cost_janitor.providers.aws import ec2, elb
from cloud_cost_janitor.providers.aws.client import AwsClients, AwsCredentials
from cloud_cost_janitor.providers.aws.prices import live_price_book
from cloud_cost_janitor.providers.aws.spend import actual_spend as ce_actual_spend
from cloud_cost_janitor.providers.base import CloudProvider, ProviderError, SpendRow


# IAM refusals name the principal ARN and the account; other AWS messages can embed ARNs too. None of
# that may reach the model, the chat or the audit log.
_DENIED_CODES = frozenset({"AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "Client.UnauthorizedOperation"})
_ARN_RE = re.compile(r"arn:aws[^\s'\"(),;]*")
_ACCOUNT_RE = re.compile(r"\b\d{12}\b")
_ENCODED_RE = re.compile(r"\s*Encoded authorization failure message:.*$", re.DOTALL)


def redact(message: str) -> str:
    """Strip ARNs, account ids and encoded authorization blobs from an AWS error message."""
    message = _ENCODED_RE.sub("", message)
    message = _ARN_RE.sub("<arn>", message)
    return _ACCOUNT_RE.sub("<account>", message)


def _wrap(fn):
    """Turn boto errors into ProviderError with a message the agent can act on, never one that leaks identity."""

    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except NoCredentialsError as e:
            raise ProviderError("No AWS credentials found on the host (configure ~/.aws or AWS_PROFILE)") from e
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "ClientError")
            if code in _DENIED_CODES:
                raise ProviderError(f"AWS {code}: IAM denied {e.operation_name}") from e
            msg = e.response.get("Error", {}).get("Message", str(e))
            raise ProviderError(f"AWS {code}: {redact(msg)}") from e
        except BotoCoreError as e:  # expired SSO token, endpoint timeouts, ...
            raise ProviderError(f"AWS {type(e).__name__}: {redact(str(e))}") from e

    inner.__name__ = fn.__name__
    inner.__doc__ = fn.__doc__
    return inner


class AwsProvider(CloudProvider):
    def __init__(self, clients: AwsClients | None = None, *, credentials: AwsCredentials | None = None) -> None:
        if clients is None:
            if credentials is None:
                raise ValueError("AwsProvider needs explicit credentials or a prepared AwsClients")
            clients = AwsClients(credentials)
        self._c = clients

    @property
    def name(self) -> str:
        return "aws"

    @_wrap
    def verify_credentials(self) -> None:
        self._c.verify()

    def price_book(self) -> PriceBook:
        if not hasattr(self, "_prices"):
            self._prices = live_price_book(self._c)
        return self._prices

    @_wrap
    def actual_spend(self, *, days: int, group_by: str) -> tuple[str, str, list[SpendRow]]:
        return ce_actual_spend(self._c, days=days, group_by=group_by)

    @_wrap
    def list_regions(self) -> list[str]:
        return self._c.list_regions()

    @_wrap
    def list_instances(self, region: str, *, lookback_days: int, now: datetime | None = None) -> list[Instance]:
        return ec2.list_instances(self._c, region, lookback_days=lookback_days, now=now)

    @_wrap
    def list_unattached_volumes(self, region: str) -> list[Volume]:
        return ec2.list_unattached_volumes(self._c, region)

    @_wrap
    def list_load_balancers(self, region: str, *, lookback_days: int, now: datetime | None = None) -> list[LoadBalancer]:
        return elb.list_load_balancers(self._c, region, lookback_days=lookback_days, now=now)

    @_wrap
    def get_instance(self, region: str, instance_id: str) -> Instance | None:
        return ec2.get_instance(self._c, region, instance_id)

    @_wrap
    def get_volume(self, region: str, volume_id: str) -> Volume | None:
        return ec2.get_volume(self._c, region, volume_id)

    @_wrap
    def get_load_balancer(self, region: str, lb_id: str) -> LoadBalancer | None:
        return elb.get_load_balancer(self._c, region, lb_id)

    @_wrap
    def snapshot_volume(self, region: str, volume_id: str, *, description: str, tags: dict[str, str]) -> str:
        return ec2.snapshot_volume(self._c, region, volume_id, description=description, tags=tags)

    @_wrap
    def find_snapshot(self, region: str, volume_id: str, plan_id: str) -> str | None:
        return ec2.find_snapshot(self._c, region, volume_id, plan_id)

    @_wrap
    def snapshot_state(self, region: str, snapshot_id: str) -> str | None:
        return ec2.snapshot_state(self._c, region, snapshot_id)

    @_wrap
    def tag_resources(self, region: str, resource_ids: list[str], tags: dict[str, str]) -> None:
        lbs = [r for r in resource_ids if elb.is_load_balancer_id(r)]
        ids = [r for r in resource_ids if not elb.is_load_balancer_id(r)]
        ec2.tag_resources(self._c, region, ids, tags)
        elb.tag_load_balancers(self._c, region, lbs, tags)

    @_wrap
    def untag_resources(self, region: str, resource_ids: list[str], keys: list[str]) -> None:
        lbs = [r for r in resource_ids if elb.is_load_balancer_id(r)]
        ids = [r for r in resource_ids if not elb.is_load_balancer_id(r)]
        ec2.untag_resources(self._c, region, ids, keys)
        elb.untag_load_balancers(self._c, region, lbs, keys)

    @_wrap
    def terminate_instance(self, region: str, instance_id: str) -> None:
        ec2.terminate_instance(self._c, region, instance_id)

    @_wrap
    def delete_volume(self, region: str, volume_id: str) -> None:
        ec2.delete_volume(self._c, region, volume_id)

    @_wrap
    def delete_load_balancer(self, region: str, lb_id: str) -> None:
        elb.delete_load_balancer(self._c, region, lb_id)
