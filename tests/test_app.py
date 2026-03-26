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

def test_lyrics_not_found(client):
    resp = client.get("/lyrics/nonexistent")
    assert resp.status_code == 404

def test_mix_missing_job(client):
    resp = client.post("/mix/nonexistent",
                       data={"audio": (b"fake audio data", "vocal.webm")},
                       content_type="multipart/form-data")
    assert resp.status_code == 404

def test_mix_no_audio_field(client):
    # POST without audio file should return 400
    resp = client.post("/mix/nonexistent",
                       content_type="multipart/form-data")
    # 404 because job doesn't exist, but if it did it would be 400
    # Test the 400 path by creating a fake job dir
    import os
    from pathlib import Path
    outputs = Path("outputs")
    fake_job = outputs / "testjob99"
    fake_job.mkdir(parents=True, exist_ok=True)
    (fake_job / "accompaniment.mp3").write_bytes(b"fake")
    try:
        resp = client.post("/mix/testjob99", content_type="multipart/form-data")
        assert resp.status_code == 400
    finally:
        import shutil
        shutil.rmtree(fake_job, ignore_errors=True)

def test_serve_mixed_not_found(client):
    resp = client.get("/output/nonexistent/mixed.mp3")
    assert resp.status_code == 404

def test_download_mixed_not_found(client):
    resp = client.get("/download/nonexistent/mixed.mp3")
    assert resp.status_code == 404
