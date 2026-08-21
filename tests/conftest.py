import os
import sys

# Route all Python bytecode (.pyc) files into a single root __pycache__ folder
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.pycache_prefix = os.path.join(ROOT_DIR, "__pycache__")

import base64
import time
from unittest.mock import MagicMock, AsyncMock
import pytest
from fastapi import Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 1. Early Mocking of Redis and FastAPILimiter
mock_redis_module = MagicMock()
mock_redis_client = AsyncMock()

mock_pubsub = MagicMock()
mock_pubsub.psubscribe = AsyncMock()
mock_pubsub.subscribe = AsyncMock()
mock_pubsub.close = AsyncMock()

async def _empty_async_iter():
    if False:
        yield None

mock_pubsub.listen.return_value = _empty_async_iter()
mock_redis_client.pubsub = MagicMock(return_value=mock_pubsub)
mock_redis_module.Redis.from_url.return_value = mock_redis_client
sys.modules["redis.asyncio"] = mock_redis_module

mock_limiter = MagicMock()
mock_limiter.FastAPILimiter.init = AsyncMock()
sys.modules["fastapi_limiter"] = mock_limiter

class MockRateLimiter:
    def __init__(self, times=1, seconds=1, **kwargs):
        pass

    async def __call__(self, request: Request, response: Response):
        pass

mock_limiter_depends = MagicMock()
mock_limiter_depends.RateLimiter = MockRateLimiter
sys.modules["fastapi_limiter.depends"] = mock_limiter_depends

from app.main import app
from app.models.models import Base
from app.services.auth import get_db
from app.core.database import SessionLocal

def generate_random_base64(length=32):
    return base64.b64encode(os.urandom(length)).decode("utf-8")


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal.configure(bind=engine)
    return engine


@pytest.fixture(autouse=True)
def setup_test_db(engine):
    """Recreate tables before each test to ensure complete test isolation."""
    SessionLocal.configure(bind=engine)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def user_factory(client):
    """Helper factory to register unique test users."""
    def _create_user(
        email=None,
        username="testuser",
        device_id=None,
        device_name="Test Device",
        os_name="Linux",
        kdf_version=1,
    ):
        ts = int(time.time() * 1000)
        email = email or f"user_{ts}_{os.urandom(3).hex()}@example.com"
        device_id = device_id or f"dev_{ts}_{os.urandom(3).hex()}"
        auth_key = generate_random_base64(32)
        enc_mk = generate_random_base64(32)
        salt = generate_random_base64(32)

        reg_payload = {
            "email": email,
            "username": username,
            "auth_key": auth_key,
            "device_id": device_id,
            "device_name": device_name,
            "os": os_name,
            "encrypted_master_key": enc_mk,
            "salt": salt,
            "kdf_version": kdf_version,
        }

        resp = client.post("/api/v1/register", json=reg_payload)
        assert resp.status_code == 200, f"Registration failed: {resp.text}"
        data = resp.json()
        token = data["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        return {
            "email": email,
            "username": username,
            "auth_key": auth_key,
            "device_id": device_id,
            "device_name": device_name,
            "os": os_name,
            "encrypted_master_key": enc_mk,
            "salt": salt,
            "kdf_version": kdf_version,
            "access_token": token,
            "refresh_token": data.get("refresh_token"),
            "headers": headers,
            "raw_response": data,
        }

    return _create_user


@pytest.fixture
def auth_user(user_factory):
    """Provides a default registered and authenticated user."""
    return user_factory()


@pytest.fixture
def auth_headers(auth_user):
    """Provides authorization headers for the default user."""
    return auth_user["headers"]
