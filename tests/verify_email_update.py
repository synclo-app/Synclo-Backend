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

def test_email_update():
    with TestClient(app) as client:
        ts = int(time.time() * 1000)
        old_email = f"user_{ts}@example.com"
        new_email = f"user_new_{ts}@example.com"
        other_user_email = f"other_{ts}@example.com"
        auth_key = generate_random_base64(32)
        device_id_1 = f"dev1_{ts}"
        enc_mk = generate_random_base64(32)
        salt = generate_random_base64(32)

        # 1. Register User A on Device 1
        print(f"1. Registering user A: {old_email} on Device 1...")
        reg_payload = {
            "email": old_email,
            "username": "user_a",
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

        # 2. Register User B (to test duplicate email conflict)
        print(f"2. Registering user B: {other_user_email}...")
        resp_b = client.post("/api/v1/register", json={
            "email": other_user_email,
            "username": "user_b",
            "auth_key": generate_random_base64(32),
            "device_id": f"dev_b_{ts}",
            "device_name": "Device B",
            "os": "Linux",
            "encrypted_master_key": generate_random_base64(32),
            "salt": generate_random_base64(32),
            "kdf_version": 1
        })
        assert resp_b.status_code == 200, f"User B registration failed: {resp_b.text}"

        # 3. Login on Device 2 for User A
        device_id_2 = f"dev2_{ts}"
        print(f"3. Logging in on Device 2 for User A: {device_id_2}...")
        login_payload = {
            "email": old_email,
            "auth_key": auth_key,
            "device_id": device_id_2,
            "device_name": "Device 2",
            "os": "Android"
        }
        resp = client.post("/api/v1/login", json=login_payload)
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        res_login_2 = resp.json()
        token_2 = res_login_2["access_token"]
        refresh_token_2 = res_login_2["refresh_token"]

        # 4. Connect Device 2 to WebSocket sync
        print("4. Connecting Device 2 to WebSocket sync...")
        with client.websocket_connect("/ws/v1/sync", headers={"Authorization": f"Bearer {token_2}"}) as ws:
            # 5a. Attempt to update email to same current email -> expect 400 Bad Request
            print("5a. Testing same email rejection...")
            resp_same = client.put(
                "/api/v1/user/email",
                json={"email": old_email},
                headers={"Authorization": f"Bearer {token_1}"}
            )
            assert resp_same.status_code == 400, f"Expected 400 Bad Request, got {resp_same.status_code}: {resp_same.text}"
            print("Same email rejection correctly rejected with 400.")

            # 5b. Attempt to update email to already existing User B email -> expect 409 Conflict
            print("5b. Testing duplicate email conflict...")
            resp_conflict = client.put(
                "/api/v1/user/email",
                json={"email": other_user_email},
                headers={"Authorization": f"Bearer {token_1}"}
            )
            assert resp_conflict.status_code == 409, f"Expected 409 Conflict, got {resp_conflict.status_code}: {resp_conflict.text}"
            print("Duplicate email conflict correctly rejected with 409.")

            # 6. Update email from Device 1 to new_email
            print(f"6. Updating email to {new_email} from Device 1...")
            resp_update = client.put(
                "/api/v1/user/email",
                json={"email": new_email},
                headers={"Authorization": f"Bearer {token_1}"}
            )
            assert resp_update.status_code == 200, f"Email update failed: {resp_update.text}"
            update_data = resp_update.json()
            assert update_data["email"] == new_email
            assert "access_token" in update_data
            assert "refresh_token" in update_data
            new_token_1 = update_data["access_token"]

            # 7. Verify WebSocket broadcast on Device 2
            print("7. Verifying WebSocket broadcast message on Device 2...")
            broadcast = ws.receive_json()
            print(f"Broadcast message received: {json.dumps(broadcast)}")
            assert broadcast.get("type") == "email_updated", f"Expected type 'email_updated', got {broadcast.get('type')}"
            assert broadcast.get("email") == new_email, f"Expected email '{new_email}', got {broadcast.get('email')}"

            # 8. Verify GET /user with new_token_1
            print("8. Verifying GET /user with new access token...")
            resp_profile = client.get("/api/v1/user", headers={"Authorization": f"Bearer {new_token_1}"})
            assert resp_profile.status_code == 200, f"Profile fetch failed: {resp_profile.text}"
            profile_data = resp_profile.json()
            assert profile_data["email"] == new_email, f"Expected profile email '{new_email}', got {profile_data['email']}"

            # 9. Verify Device 2 can refresh token and get a new valid token with new email
            print("9. Verifying Device 2 token refresh...")
            resp_refresh = client.post("/api/v1/refresh", json={"refresh_token": refresh_token_2})
            assert resp_refresh.status_code == 200, f"Token refresh failed: {resp_refresh.text}"
            refreshed_token_2 = resp_refresh.json()["access_token"]

            resp_profile_2 = client.get("/api/v1/user", headers={"Authorization": f"Bearer {refreshed_token_2}"})
            assert resp_profile_2.status_code == 200, f"Profile fetch with refreshed token failed: {resp_profile_2.text}"
            assert resp_profile_2.json()["email"] == new_email

            # 10. Verify login with new email vs old email
            print("10. Verifying login with new email vs old email...")
            # Old email login should fail
            resp_old_login = client.post("/api/v1/login", json={
                "email": old_email,
                "auth_key": auth_key,
                "device_id": f"dev3_{ts}",
                "device_name": "Device 3",
                "os": "iOS"
            })
            assert resp_old_login.status_code == 401, f"Expected 401 with old email, got {resp_old_login.status_code}"

            # New email login should succeed
            resp_new_login = client.post("/api/v1/login", json={
                "email": new_email,
                "auth_key": auth_key,
                "device_id": f"dev3_{ts}",
                "device_name": "Device 3",
                "os": "iOS"
            })
            assert resp_new_login.status_code == 200, f"Expected 200 with new email login, got {resp_new_login.status_code}: {resp_new_login.text}"

        print("\nEMAIL UPDATE VERIFICATION PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    try:
        test_email_update()
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
