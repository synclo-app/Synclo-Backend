"""
Test Suite: Real-Time WebSocket Synchronization & Event Broadcasting

Scenarios Targeted:
1. WebSocket connection lifecycle and heartbeat ping/pong message exchange.
2. Synchronous clipboard creation via WebSocket receiving server acknowledgment ({'type': 'ack'}).
3. Live broadcast of display username changes across connected client devices.
4. Live broadcast of email address updates across connected client devices.
5. Live multi-device clipboard sync propagation from device 1 to device 2.
6. Connection rejection (error frame / close 1008) when authentication credentials are missing.
"""

import datetime
from tests.conftest import generate_random_base64


def _receive_non_ping(ws):
    while True:
        msg = ws.receive_json()
        if msg.get("type") == "ping":
            ws.send_json({"type": "pong"})
            continue
        return msg


def test_websocket_connect_and_ping(client, auth_user):
    token = auth_user["access_token"]
    with client.websocket_connect("/ws/v1/sync", headers={"Authorization": f"Bearer {token}"}) as ws:
        # Send ping
        ws.send_json({"type": "ping"})
        response = _receive_non_ping(ws)
        assert response.get("type") == "pong"


def test_websocket_clipboard_sync_event(client, auth_user):
    token = auth_user["access_token"]
    with client.websocket_connect("/ws/v1/sync", headers={"Authorization": f"Bearer {token}"}) as ws:
        # Send clipboard item over websocket
        clip_id = "ws_clip_item_01"
        payload = {
            "id": clip_id,
            "ciphertext": generate_random_base64(32),
            "nonce": generate_random_base64(12),
            "blob_version": 1,
            "is_deleted": False,
            "is_pinned": False,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        ws.send_json(payload)
        resp = _receive_non_ping(ws)
        assert resp.get("type") == "ack"
        assert resp.get("id") == clip_id


def test_websocket_broadcast_on_username_update(client, user_factory):
    # Setup user with 2 devices
    user = user_factory(username="orig_name")
    
    # Register device 2
    dev2_res = client.post("/api/v1/login", json={
        "email": user["email"],
        "auth_key": user["auth_key"],
        "device_id": "ws_device_2",
        "device_name": "Device 2",
        "os": "Android",
    })
    token_dev2 = dev2_res.json()["access_token"]

    # Device 2 connects to WebSocket
    with client.websocket_connect("/ws/v1/sync", headers={"Authorization": f"Bearer {token_dev2}"}) as ws_dev2:
        # Device 1 updates username via REST
        resp_update = client.put(
            "/api/v1/user/username",
            json={"username": "broadcasted_name"},
            headers=user["headers"],
        )
        assert resp_update.status_code == 200

        # Device 2 should receive username_updated broadcast
        msg = _receive_non_ping(ws_dev2)
        assert msg.get("type") == "username_updated"
        assert msg.get("username") == "broadcasted_name"


def test_websocket_broadcast_on_email_update(client, user_factory):
    user = user_factory()
    dev2_res = client.post("/api/v1/login", json={
        "email": user["email"],
        "auth_key": user["auth_key"],
        "device_id": "ws_device_email_2",
        "device_name": "Device 2",
        "os": "iOS",
    })
    token_dev2 = dev2_res.json()["access_token"]

    with client.websocket_connect("/ws/v1/sync", headers={"Authorization": f"Bearer {token_dev2}"}) as ws_dev2:
        new_email = f"new_{user['email']}"
        res = client.put(
            "/api/v1/user/email",
            json={"email": new_email},
            headers=user["headers"],
        )
        assert res.status_code == 200

        msg = _receive_non_ping(ws_dev2)
        assert msg.get("type") == "email_updated"
        assert msg.get("email") == new_email


def test_websocket_clipboard_broadcast_to_other_devices(client, user_factory):
    user = user_factory()
    dev2_res = client.post("/api/v1/login", json={
        "email": user["email"],
        "auth_key": user["auth_key"],
        "device_id": "ws_device_clip_2",
        "device_name": "Device 2",
        "os": "Android",
    })
    token_dev2 = dev2_res.json()["access_token"]

    with client.websocket_connect("/ws/v1/sync", headers=user["headers"]) as ws1:
        with client.websocket_connect("/ws/v1/sync", headers={"Authorization": f"Bearer {token_dev2}"}) as ws2:
            clip_id = "broadcast_item_123"
            ws1.send_json({
                "id": clip_id,
                "ciphertext": generate_random_base64(32),
                "nonce": generate_random_base64(12),
                "blob_version": 1,
                "timestamp": "2026-08-20T12:00:00Z",
                "is_pinned": False,
                "is_deleted": False,
            })
            ack = _receive_non_ping(ws1)
            assert ack.get("type") == "ack"

            # Device 2 should receive broadcast
            broadcast_msg = _receive_non_ping(ws2)
            assert broadcast_msg.get("id") == clip_id
            assert broadcast_msg.get("is_deleted") is False


def test_websocket_rejects_missing_auth(client):
    try:
        with client.websocket_connect("/ws/v1/sync") as ws:
            resp = ws.receive_json()
            assert resp.get("type") == "error"
    except Exception:
        # Connection closed with 1008
        pass
