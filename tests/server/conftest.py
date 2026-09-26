import pytest
from fastmcp import Client

from cloud_cost_janitor.config import Settings
from cloud_cost_janitor.server.app import create_app
from cloud_cost_janitor.server.audit import NullAuditLog
from tests.server.fake_provider import FakeProvider

TOKEN = "test-token"


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def settings() -> Settings:
    return Settings(token=TOKEN, aws_profile="test")


@pytest.fixture
def audit() -> NullAuditLog:
    return NullAuditLog()


@pytest.fixture
def mcp(settings, fake, audit):
    return create_app(settings, fake, audit=audit)


@pytest.fixture
async def client(mcp):
    async with Client(transport=mcp) as c:
        yield c
