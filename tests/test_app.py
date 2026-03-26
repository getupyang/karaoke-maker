# tests/test_app.py
import json
import pytest
from app import app as flask_app

@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["status"] == "ok"

def test_process_no_input(client):
    resp = client.post("/process")
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert "error" in data

def test_output_not_found(client):
    resp = client.get("/output/nonexistent/accompaniment.mp3")
    assert resp.status_code == 404

def test_download_not_found(client):
    resp = client.get("/download/nonexistent/accompaniment.mp3")
    assert resp.status_code == 404
