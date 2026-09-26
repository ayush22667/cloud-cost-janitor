"""Live unit prices from the AWS Price List API, with the static table as fallback.

The Price List API is served from us-east-1 (and ap-south-1) regardless of the region being priced.
Each (kind, region, type) lookup is cached for the life of the process. If the API is denied or
returns nothing for a type, the static book answers and the source note says so.
"""

from __future__ import annotations

import json
from functools import lru_cache

from botocore.exceptions import BotoCoreError, ClientError

from cloud_cost_janitor.pricing import STATIC, PriceBook

PRICING_ENDPOINT_REGION = "us-east-1"


def _on_demand_usd(product_json: str) -> float | None:
    """First on-demand price dimension of a Price List product, in USD."""
    try:
        terms = json.loads(product_json)["terms"]["OnDemand"]
        term = next(iter(terms.values()))
        dim = next(iter(term["priceDimensions"].values()))
        return float(dim["pricePerUnit"]["USD"])
    except (KeyError, StopIteration, ValueError, TypeError):
        return None


class AwsPriceListBook(PriceBook):
    def __init__(self, pricing_client, fallback: PriceBook = STATIC) -> None:
        self._c = pricing_client
        self._fallback = fallback
        self._live_regions: set[str] = set()
        self._denied = False

    # --- PriceBook ---
    def instance_hourly(self, region: str, instance_type: str) -> float | None:
        live = self._lookup(
            "AmazonEC2",
            region,
            ("instanceType", instance_type),
            ("operatingSystem", "Linux"),
            ("tenancy", "Shared"),
            ("preInstalledSw", "NA"),
            ("capacitystatus", "Used"),
        )
        return live if live is not None else self._fallback.instance_hourly(region, instance_type)

    def volume_gb_month(self, region: str, volume_type: str) -> float | None:
        live = self._lookup("AmazonEC2", region, ("productFamily", "Storage"), ("volumeApiName", volume_type))
        return live if live is not None else self._fallback.volume_gb_month(region, volume_type)

    def lb_hourly(self, region: str, lb_type: str) -> float | None:
        family = {"application": "Load Balancer-Application", "network": "Load Balancer-Network",
                  "gateway": "Load Balancer-Gateway", "classic": "Load Balancer"}.get(lb_type)
        live = None
        if family:
            live = self._lookup("AWSELB", region, ("productFamily", family), ("usagetypeSuffix", "LoadBalancerUsage"))
        return live if live is not None else self._fallback.lb_hourly(region, lb_type)

    def source(self, region: str) -> str:
        if self._denied:
            return f"{self._fallback.source(region)} (Price List API not permitted)"
        if region in self._live_regions:
            return f"AWS Price List API ({region})"
        return self._fallback.source(region)

    # --- internals ---
    def _lookup(self, service: str, region: str, *attrs: tuple[str, str]) -> float | None:
        if self._denied:
            return None
        price = self._cached(service, region, attrs)
        if price is not None:
            self._live_regions.add(region)
        return price

    @lru_cache(maxsize=512)  # noqa: B019 - price cache for the process lifetime
    def _cached(self, service: str, region: str, attrs: tuple[tuple[str, str], ...]) -> float | None:
        filters = [{"Type": "TERM_MATCH", "Field": "regionCode", "Value": region}]
        for field, value in attrs:
            if field == "usagetypeSuffix":
                continue  # matched on the response below; usagetype carries a region prefix
            filters.append({"Type": "TERM_MATCH", "Field": field, "Value": value})
        suffix = next((v for f, v in attrs if f == "usagetypeSuffix"), None)
        try:
            resp = self._c.get_products(ServiceCode=service, Filters=filters, MaxResults=20)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in {"AccessDeniedException", "AccessDenied", "UnauthorizedOperation"}:
                self._denied = True
                return None
            return None
        except BotoCoreError:
            return None
        for product_json in resp.get("PriceList", []):
            if suffix:
                usagetype = json.loads(product_json).get("product", {}).get("attributes", {}).get("usagetype", "")
                if not usagetype.endswith(suffix):
                    continue
            price = _on_demand_usd(product_json)
            if price is not None and price > 0:
                return price
        return None


def live_price_book(clients) -> AwsPriceListBook:
    """Build the live book on the shared client factory (Price List lives in us-east-1)."""
    return AwsPriceListBook(clients._client("pricing", PRICING_ENDPOINT_REGION))
