"""
Test Suite: Clipboard Synchronization, Pin System & Soft Deletions

Scenarios Targeted:
1. Active encrypted clipboard creation and retrieval via latest and ID-specific endpoints.
2. Bulk history deletion preserving pinned items intact.
3. Targeted single item deletion converting entries into tombstones and unsetting pinned status.
4. Custom client-provided 'pinned_at' timestamp preservation and delta delivery.
"""

from tests.conftest import make_clipboard_payload


def test_create_and_fetch_clipboard_item(client, auth_headers):
    # 1. Create clipboard entry
    clip_id = "clip_test_1"
    payload = make_clipboard_payload(clip_id)
    res = client.post("/api/v1/clipboard", json=payload, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "clipboard synced"

    # 2. Get latest clipboard
    res_latest = client.get("/api/v1/clipboard", headers=auth_headers)
    assert res_latest.status_code == 200
    assert res_latest.json()["id"] == clip_id
    assert res_latest.json()["is_pinned"] is False
    assert res_latest.json()["is_deleted"] is False

    # 3. Get by ID
    res_by_id = client.get(f"/api/v1/clipboard/{clip_id}", headers=auth_headers)
    assert res_by_id.status_code == 200
    assert res_by_id.json()["id"] == clip_id


def test_pinned_clipboard_preserved_on_bulk_delete(client, auth_headers):
    # 1. Create regular unpinned item
    client.post("/api/v1/clipboard",
                json=make_clipboard_payload("item_unpinned"), headers=auth_headers)

    # 2. Create pinned item
    client.post("/api/v1/clipboard",
                json=make_clipboard_payload("item_pinned", is_pinned=True), headers=auth_headers)

    # 3. Bulk delete all
    res_del = client.delete("/api/v1/clipboard", headers=auth_headers)
    assert res_del.status_code == 200

    # 4. Check all items - only pinned item should remain active
    res_all = client.get("/api/v1/clipboard/all", headers=auth_headers)
    assert res_all.status_code == 200
    items = res_all.json()
    assert len(items) == 1
    assert items[0]["id"] == "item_pinned"
    assert items[0]["is_pinned"] is True


def test_single_delete_soft_deletes_and_unpins(client, auth_headers):
    client.post("/api/v1/clipboard",
                json=make_clipboard_payload("pinned_to_delete", is_pinned=True), headers=auth_headers)

    # Delete single item directly
    res_del = client.delete("/api/v1/clipboard/pinned_to_delete", headers=auth_headers)
    assert res_del.status_code == 200

    # Item should no longer appear in active list
    res_all = client.get("/api/v1/clipboard/all", headers=auth_headers)
    assert len(res_all.json()) == 0

    # Check with include_deleted=True (tombstone)
    res_tombstone = client.get("/api/v1/clipboard/all?include_deleted=true", headers=auth_headers)
    tombstones = res_tombstone.json()
    assert len(tombstones) == 1
    assert tombstones[0]["id"] == "pinned_to_delete"
    assert tombstones[0]["is_deleted"] is True
    assert tombstones[0]["is_pinned"] is False
    assert tombstones[0]["ciphertext"] is None


def test_pinned_at_timestamp_preservation_and_sync(client, auth_headers):
    # Add pinned item with explicit pinned_at
    custom_pinned_at = "2026-08-20T10:00:00Z"
    clip_id = "pin_ts_custom"
    res = client.post("/api/v1/clipboard", json=make_clipboard_payload(
        clip_id, is_pinned=True, pinned_at=custom_pinned_at, timestamp="2026-08-20T08:00:00Z",
    ), headers=auth_headers)
    assert res.status_code == 200

    # Sync endpoint should return the item with is_pinned=True and matching pinned_at
    res_sync = client.get("/api/v1/clipboard/sync", headers=auth_headers)
    assert res_sync.status_code == 200
    entries = res_sync.json()["entries"]
    match = next(e for e in entries if e["id"] == clip_id)
    assert match["is_pinned"] is True
    assert "2026-08-20T10:00:00" in match["pinned_at"]
