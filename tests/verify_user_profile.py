import sys
import os
import base64
import time
from unittest.mock import MagicMock, AsyncMock

# --- MOCK SETUP ---
mock_redis_module = MagicMock()
mock_redis_client = AsyncMock()

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

mock_limiter = MagicMock()
sys.modules["fastapi_limiter"] = mock_limiter

from fastapi import Request, Response

class MockRateLimiter:
    def __init__(self, times=1, seconds=1, **kwargs): pass
    async def __call__(self, request: Request, response: Response): pass

mock_limiter_depends = MagicMock()
mock_limiter_depends.RateLimiter = MockRateLimiter
sys.modules["fastapi_limiter.depends"] = mock_limiter_depends
mock_limiter.FastAPILimiter.init = AsyncMock()

# --- IMPORTS ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app

def generate_random_base64(length=32):
    return base64.b64encode(os.urandom(length)).decode('utf-8')

def test_user_profile():
    with TestClient(app) as client:
        email = f"profile_{int(time.time())}@example.com"
        auth_key = generate_random_base64(32)
        device_id = f"dev_{int(time.time())}"
        enc_mk = generate_random_base64(32)
        salt = generate_random_base64(32)

        # 1. Register User
        print(f"Registering user: {email}")
        reg_payload = {
            "email": email,
            "username": "profile_user",
            "auth_key": auth_key,
            "device_id": device_id,
            "device_name": "Test Device",
            "os": "Linux",
            "encrypted_master_key": enc_mk,
            "salt": salt,
            "kdf_version": 1
        }
        resp = client.post("/api/v1/register", json=reg_payload)
        assert resp.status_code == 200, f"Registration failed: {resp.text}"
        res = resp.json()
        token = res["access_token"]

        # 2. Get User Profile Details
        print("Fetching user profile details via GET /user...")
        resp = client.get("/api/v1/user", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, f"Get profile failed: {resp.text}"
        profile = resp.json()

        print(f"Profile fetched successfully: {profile}")
        
        # 3. Assert on fields
        assert "user_id" in profile, "user_id missing in profile response"
        assert len(profile["user_id"]) > 0, "user_id is empty"
        assert profile["email"] == email, f"Expected email {email}, got {profile['email']}"
        assert profile["username"] == "profile_user", f"Expected username 'profile_user', got {profile['username']}"
        assert profile["kdf_version"] == 1, f"Expected kdf_version 1, got {profile['kdf_version']}"
        
        print("USER PROFILE VERIFICATION PASSED")

if __name__ == "__main__":
    try:
        test_user_profile()
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
