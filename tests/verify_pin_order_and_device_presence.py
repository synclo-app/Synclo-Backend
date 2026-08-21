import sys
from unittest.mock import MagicMock, AsyncMock
import os
import base64
import time
from datetime import datetime, timezone

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

# Mock fastapi_limiter before import
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

# Add parent directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app

def generate_random_base64(length=32):
    return base64.b64encode(os.urandom(length)).decode('utf-8')

def test_pin_order_and_device_presence():
    with TestClient(app) as client:
        # 1. Register User with Device 1
        email = f"test_presence_{int(time.time())}_{os.urandom(4).hex()}@example.com"
        device_id_1 = f"dev1_{os.urandom(4).hex()}"
        device_id_2 = f"dev2_{os.urandom(4).hex()}"
        auth_key = generate_random_base64(32)
        enc_mk = generate_random_base64(32)
        salt = generate_random_base64(32)
        
        reg_payload = {
            "email": email,
            "auth_key": auth_key,
            "encrypted_master_key": enc_mk,
            "salt": salt,
            "kdf_version": 1,
            "device_id": device_id_1,
            "device_name": "Desktop PC"
        }
        resp = client.post("/api/v1/register", json=reg_payload)
        assert resp.status_code == 200, f"Registration failed: {resp.text}"
        tokens = resp.json()
        token1 = tokens["access_token"]
        headers1 = {"Authorization": f"Bearer {token1}"}

        # 2. Register Device 2
        dev2_payload = {
            "device_id": device_id_2,
            "device_name": "Laptop",
            "os": "Windows"
        }
        resp = client.post("/api/v1/devices/register", json=dev2_payload, headers=headers1)
        assert resp.status_code == 200, f"Registering device 2 failed: {resp.text}"

        # 3. Verify GET /devices returns both devices with last_seen and is_online=False
        resp = client.get("/api/v1/devices", headers=headers1)
        assert resp.status_code == 200, f"Get devices failed: {resp.text}"
        devices = resp.json()
        assert len(devices) == 2
        for dev in devices:
            assert "last_seen" in dev and dev["last_seen"] is not None
            assert dev["is_online"] is False

        # 4. Add Pinned Item 1 (pinned earlier: T1)
        pinned_id_1 = "pin1_" + os.urandom(4).hex()
        pinned_at_1 = "2026-08-20T10:00:00Z"
        resp = client.post(
            "/api/v1/clipboard",
            headers=headers1,
            json={
                "id": pinned_id_1,
                "ciphertext": generate_random_base64(32),
                "nonce": generate_random_base64(12),
                "blob_version": 1,
                "timestamp": "2026-08-20T09:00:00Z",
                "is_pinned": True,
                "pinned_at": pinned_at_1
            }
        )
        assert resp.status_code == 200, f"Failed to add pinned item 1: {resp.text}"

        # 5. Add Pinned Item 2 (pinned later: T2)
        pinned_id_2 = "pin2_" + os.urandom(4).hex()
        pinned_at_2 = "2026-08-20T11:00:00Z"
        resp = client.post(
            "/api/v1/clipboard",
            headers=headers1,
            json={
                "id": pinned_id_2,
                "ciphertext": generate_random_base64(32),
                "nonce": generate_random_base64(12),
                "blob_version": 1,
                "timestamp": "2026-08-20T08:00:00Z", # Copied earlier, but pinned later!
                "is_pinned": True,
                "pinned_at": pinned_at_2
            }
        )
        assert resp.status_code == 200, f"Failed to add pinned item 2: {resp.text}"

        # 6. Verify sync returns pinned_at for both items
        resp = client.get("/api/v1/clipboard/sync", headers=headers1)
        assert resp.status_code == 200, f"Sync failed: {resp.text}"
        sync_items = resp.json()["entries"]
        
        item1 = next((i for i in sync_items if i["id"] == pinned_id_1), None)
        item2 = next((i for i in sync_items if i["id"] == pinned_id_2), None)
        
        assert item1 is not None and item1["is_pinned"] is True
        assert item1["pinned_at"] is not None and "2026-08-20T10:00:00" in item1["pinned_at"]
        
        assert item2 is not None and item2["is_pinned"] is True
        assert item2["pinned_at"] is not None and "2026-08-20T11:00:00" in item2["pinned_at"]

        # 7. Test WebSocket connection and presence
        # Login to get token for device 2
        login_resp = client.post("/api/v1/login", json={
            "email": email,
            "auth_key": auth_key,
            "device_id": device_id_2
        })
        assert login_resp.status_code == 200
        token2 = login_resp.json()["access_token"]

        with client.websocket_connect("/ws/v1/sync", headers={"Authorization": f"Bearer {token1}"}) as ws1:
            # Device 1 is now online
            resp = client.get("/api/v1/devices", headers=headers1)
            devices = resp.json()
            dev1 = next(d for d in devices if d["device_id"] == device_id_1)
            dev2 = next(d for d in devices if d["device_id"] == device_id_2)
            assert dev1["is_online"] is True
            assert dev2["is_online"] is False

            # Ping to verify last_seen updates
            ws1.send_json({"type": "ping"})
            pong = ws1.receive_json()
            assert pong.get("type") == "pong"

            # Connect Device 2 to listen for broadcasts
            with client.websocket_connect("/ws/v1/sync", headers={"Authorization": f"Bearer {token2}"}) as ws2:
                # Device 1 sends a pinned item over WebSocket
                ws_pin_id = "wspin_" + os.urandom(4).hex()
                ws_pinned_at = "2026-08-20T12:30:00Z"
                ws1.send_json({
                    "id": ws_pin_id,
                    "ciphertext": generate_random_base64(32),
                    "nonce": generate_random_base64(12),
                    "blob_version": 1,
                    "timestamp": "2026-08-20T12:00:00Z",
                    "is_pinned": True,
                    "pinned_at": ws_pinned_at
                })

                # Device 1 receives ACK
                ack = ws1.receive_json()
                assert ack.get("type") == "ack" and ack.get("id") == ws_pin_id

                # Device 2 receives broadcast with pinned_at
                broadcast = ws2.receive_json()
                assert broadcast["id"] == ws_pin_id
                assert broadcast["is_pinned"] is True
                assert broadcast["pinned_at"] is not None and "2026-08-20T12:30:00" in broadcast["pinned_at"]

        # Both disconnected
        time.sleep(0.1)
        resp = client.get("/api/v1/devices", headers=headers1)
        devices = resp.json()
        for dev in devices:
            assert dev["is_online"] is False

        print("All pin order and device presence tests passed successfully!")

if __name__ == "__main__":
    test_pin_order_and_device_presence()
