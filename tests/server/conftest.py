import pytest
from fastmcp import Client

from cloud_cost_janitor.config import Settings
from cloud_cost_janitor.server.app import create_app
from tests.server.fake_provider import FakeProvider

TOKEN = "test-token"


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def settings() -> Settings:
    return Settings(token=TOKEN)  # dry-run, demo tag guard on


@pytest.fixture
def live_settings() -> Settings:
    return Settings(token=TOKEN, allow_delete=True)


@pytest.fixture
def mcp(settings, fake):
    return create_app(settings, fake)


@pytest.fixture
def live_mcp(live_settings, fake):
    return create_app(live_settings, fake)


@pytest.fixture
async def client(mcp):
    async with Client(transport=mcp) as c:
        yield c


@pytest.fixture
async def live_client(live_mcp):
    async with Client(transport=live_mcp) as c:
        yield c
