"""
Test Suite: Health Check & Server Verification

Scenarios Targeted:
1. Validates '/api/health' returns 200 OK, genuine server status, and 'Synclo-Server: genuine' header.
2. Validates legacy deprecated '/health' endpoint returns 404 Not Found.
"""


def test_health_check_endpoint(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert data.get("server") == "synclo"
    assert resp.headers.get("Synclo-Server") == "genuine"


def test_legacy_health_endpoint_is_not_found(client):
    resp = client.get("/health")
    assert resp.status_code == 404
