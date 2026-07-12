import sys
import os
import base64
import time
import json
from unittest.mock import MagicMock, AsyncMock

# --- MOCK SETUP ---
# Mock Redis BEFORE importing main to avoid connection attempts
mock_redis_module = MagicMock()
mock_redis_client = AsyncMock()

# handle pubsub
mock_pubsub = MagicMock()
mock_pubsub.psubscribe = AsyncMock()
mock_pubsub.subscribe = AsyncMock()
mock_pubsub.close = AsyncMock()

async def async_iter():
    if False: yield None

mock_pubsub.listen.return_value = async_iter()
mock_redis_client.pubsub = MagicMock(return_value=mock_pubsub)
mock_redis_module.Redis.from_url.return_value = mock_redis_client
sys.modules["redis.asyncio"] = mock_redis_module

# Also mock fastapi_limiter before import
mock_limiter = MagicMock()
sys.modules["fastapi_limiter"] = mock_limiter

# Create a dummy RateLimiter class
from fastapi import Request, Response

class MockRateLimiter:
    def __init__(self, times=1, seconds=1, **kwargs): pass
    async def __call__(self, request: Request, response: Response): pass

mock_limiter_depends = MagicMock()
mock_limiter_depends.RateLimiter = MockRateLimiter
sys.modules["fastapi_limiter.depends"] = mock_limiter_depends

# Mock FastAPILimiter init just in case
mock_limiter.FastAPILimiter.init = AsyncMock()

# --- IMPORTS ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app

def generate_random_base64(length=32):
    return base64.b64encode(os.urandom(length)).decode('utf-8')

def test_username_broadcast():
    with TestClient(app) as client:
        email = f"user_{int(time.time())}@example.com"
        auth_key = generate_random_base64(32)
        device_id_1 = f"dev1_{int(time.time())}"
        enc_mk = generate_random_base64(32)
        salt = generate_random_base64(32)

        # 1. Register User on Device 1
        print("Registering user on Device 1...")
        reg_payload = {
            "email": email,
            "username": "initial_name",
            "auth_key": auth_key,
            "device_id": device_id_1,
            "device_name": "Device 1",
            "os": "Windows",
            "encrypted_master_key": enc_mk,
            "salt": salt,
            "kdf_version": 1
        }
        resp = client.post("/api/v1/register", json=reg_payload)
        assert resp.status_code == 200, f"Registration failed: {resp.text}"
        res = resp.json()
        token_1 = res["access_token"]
        assert res.get("username") == "initial_name"

        # 2. Login on Device 2 to associate the second device
        device_id_2 = f"dev2_{int(time.time())}"
        print(f"Logging in on Device 2: {device_id_2}...")
        login_payload = {
            "email": email,
            "auth_key": auth_key,
            "device_id": device_id_2,
            "device_name": "Device 2",
            "os": "Android"
        }
        resp = client.post("/api/v1/login", json=login_payload)
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        res = resp.json()
        token_2 = res["access_token"]
        assert res.get("username") == "initial_name"

        # 3. Connect Device 2 to the WebSocket sync endpoint
        print("Connecting Device 2 to WebSocket sync...")
        with client.websocket_connect("/ws/v1/sync", headers={"Authorization": f"Bearer {token_2}"}) as ws:
            # 4. Update username from Device 1 via PUT endpoint
            print("Updating username from Device 1...")
            update_payload = {"username": "updated_name"}
            resp = client.put("/api/v1/user/username", json=update_payload, headers={"Authorization": f"Bearer {token_1}"})
            assert resp.status_code == 200, f"Username update failed: {resp.text}"
            res = resp.json()
            assert res.get("username") == "updated_name"

            # 5. Assert that Device 2 receives the username_updated WebSocket message
            print("Waiting for broadcast message on Device 2's WebSocket...")
            broadcast = ws.receive_json()
            print(f"Broadcast message received: {json.dumps(broadcast)}")
            assert broadcast.get("type") == "username_updated"
            assert broadcast.get("username") == "updated_name"

        print("USERNAME BROADCAST VERIFICATION PASSED")

if __name__ == "__main__":
    try:
        test_username_broadcast()
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
