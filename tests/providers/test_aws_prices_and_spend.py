"""Price List and Cost Explorer adapters, driven by stub clients (moto does not model these APIs)."""

import json

import pytest
from botocore.exceptions import ClientError

from cloud_cost_janitor import pricing
from cloud_cost_janitor.providers.aws.prices import AwsPriceListBook
from cloud_cost_janitor.providers.aws.spend import actual_spend
from cloud_cost_janitor.providers.base import ProviderError

R = "us-east-1"


def product(price: str, usagetype: str = "BoxUsage:t3.micro") -> str:
    return json.dumps({
        "product": {"attributes": {"usagetype": usagetype}},
        "terms": {"OnDemand": {"t1": {"priceDimensions": {"d1": {"pricePerUnit": {"USD": price}, "unit": "Hrs"}}}}},
    })


class StubPricing:
    def __init__(self, answers: dict[str, list[str]] | None = None, error: ClientError | None = None):
        self.answers = answers or {}
        self.error = error
        self.calls = 0

    def get_products(self, ServiceCode, Filters, MaxResults):
        self.calls += 1
        if self.error:
            raise self.error
        key = next((f["Value"] for f in Filters if f["Field"] in ("instanceType", "volumeApiName", "productFamily")), "")
        return {"PriceList": self.answers.get(key, [])}


def denied(code="AccessDeniedException"):
    return ClientError({"Error": {"Code": code, "Message": "no"}}, "GetProducts")


def test_live_price_wins_and_is_cached():
    stub = StubPricing({"t3.micro": [product("0.0104000000")], "gp3": [product("0.08", "EBS:VolumeUsage.gp3")]})
    book = AwsPriceListBook(stub)
    assert book.instance_hourly(R, "t3.micro") == 0.0104
    assert book.instance_hourly(R, "t3.micro") == 0.0104
    assert stub.calls == 1  # cached
    assert book.volume_gb_month(R, "gp3") == 0.08
    assert book.source(R) == f"AWS Price List API ({R})"
    assert pricing.instance_monthly_cost(book, R, "t3.micro") == 7.59


def test_unknown_type_falls_back_to_static_table():
    book = AwsPriceListBook(StubPricing({}))
    assert book.instance_hourly(R, "m5.large") == 0.096  # from the table
    assert book.instance_hourly(R, "z9.mega") is None


def test_access_denied_falls_back_and_says_so():
    stub = StubPricing(error=denied())
    book = AwsPriceListBook(stub)
    assert book.instance_hourly(R, "t3.micro") == 0.0104
    assert "not permitted" in book.source(R)
    book.volume_gb_month(R, "gp3")
    assert stub.calls == 1  # after a denial it stops calling the API


def test_load_balancer_matches_usagetype_suffix():
    stub = StubPricing({"Load Balancer-Application": [
        product("0.008", "USE1-LCUUsage"),
        product("0.0225", "LoadBalancerUsage"),
    ]})
    book = AwsPriceListBook(stub)
    assert book.lb_hourly(R, "application") == 0.0225


class StubClients:
    def __init__(self, ce):
        self.ce = ce

    def _client(self, service, region):
        assert service == "ce"
        return self.ce


class StubCE:
    def __init__(self, groups=None, error=None):
        self.groups, self.error = groups or [], error

    def get_cost_and_usage(self, **kw):
        if self.error:
            raise self.error
        return {"ResultsByTime": [{"Groups": [{"Keys": [k], "Metrics": {"UnblendedCost": {"Amount": str(v)}}} for k, v in self.groups]}]}


def test_actual_spend_sorted_and_summed():
    ce = StubCE([("Amazon Elastic Compute Cloud - Compute", 12.5), ("EC2 - Other", 3.25), ("AmazonCloudWatch", 0.1)])
    start, end, rows = actual_spend(StubClients(ce), days=30, group_by="service")
    assert [r.key for r in rows][0] == "Amazon Elastic Compute Cloud - Compute"
    assert rows[0].to_dict() == {"key": "Amazon Elastic Compute Cloud - Compute", "amount_usd": 12.5}
    assert start < end


def test_actual_spend_not_enabled_is_explained():
    err = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "User not enabled for cost explorer access"}}, "GetCostAndUsage")
    with pytest.raises(ProviderError, match="Cost Explorer is not enabled"):
        actual_spend(StubClients(StubCE(error=err)), days=30, group_by="service")


def test_actual_spend_rejects_bad_group():
    with pytest.raises(ProviderError, match="group_by"):
        actual_spend(StubClients(StubCE()), days=30, group_by="colour")
