# tests/test_app.py
import json
import pytest
from app import app as flask_app, parse_vtt, parse_lrc

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

def test_search_no_query(client):
    resp = client.get("/search")
    assert resp.status_code == 400

def test_output_not_found(client):
    resp = client.get("/output/nonexistent/accompaniment.mp3")
    assert resp.status_code == 404

def test_download_not_found(client):
    resp = client.get("/download/nonexistent/accompaniment.mp3")
    assert resp.status_code == 404


# ── parse_vtt unit tests ──────────────────────────────────────────

def test_parse_vtt_basic():
    vtt = """WEBVTT

00:00:12.340 --> 00:00:15.670
lyrics text here

00:00:15.670 --> 00:00:18.000
next line
"""
    result = parse_vtt(vtt)
    assert len(result) == 2
    assert result[0]["time"] == pytest.approx(12.34, abs=0.01)
    assert result[0]["text"] == "lyrics text here"
    assert result[1]["time"] == pytest.approx(15.67, abs=0.01)
    assert result[1]["text"] == "next line"


def test_parse_vtt_deduplicates_consecutive():
    vtt = """WEBVTT

00:00:01.000 --> 00:00:03.000
same line

00:00:03.000 --> 00:00:05.000
same line

00:00:05.000 --> 00:00:07.000
different line
"""
    result = parse_vtt(vtt)
    assert len(result) == 2
    assert result[0]["text"] == "same line"
    assert result[1]["text"] == "different line"


def test_parse_vtt_strips_tags():
    vtt = """WEBVTT

00:00:01.000 --> 00:00:03.000
<c>tagged</c> text
"""
    result = parse_vtt(vtt)
    assert len(result) == 1
    assert result[0]["text"] == "tagged text"


def test_parse_vtt_empty():
    result = parse_vtt("WEBVTT\n\n")
    assert result == []


def test_parse_vtt_skips_blank_text():
    vtt = """WEBVTT

00:00:01.000 --> 00:00:03.000


00:00:04.000 --> 00:00:06.000
real line
"""
    result = parse_vtt(vtt)
    assert len(result) == 1
    assert result[0]["text"] == "real line"


# ── parse_lrc unit tests ──────────────────────────────────────────

def test_parse_lrc_basic():
    lrc = "[00:12.34] lyrics text\n[00:15.67] next line\n"
    result = parse_lrc(lrc)
    assert len(result) == 2
    assert result[0]["time"] == pytest.approx(12.34, abs=0.01)
    assert result[0]["text"] == "lyrics text"
    assert result[1]["time"] == pytest.approx(15.67, abs=0.01)
    assert result[1]["text"] == "next line"


def test_parse_lrc_skips_metadata():
    lrc = "[ti:My Song]\n[ar:Artist]\n[al:Album]\n[00:01.00] actual lyric\n"
    result = parse_lrc(lrc)
    assert len(result) == 1
    assert result[0]["text"] == "actual lyric"


def test_parse_lrc_skips_empty_lines():
    lrc = "[00:01.00] \n[00:02.00] real text\n"
    result = parse_lrc(lrc)
    assert len(result) == 1
    assert result[0]["text"] == "real text"


def test_parse_lrc_empty():
    result = parse_lrc("")
    assert result == []


def test_parse_lrc_minutes_conversion():
    lrc = "[01:30.00] one and a half minutes\n"
    result = parse_lrc(lrc)
    assert len(result) == 1
    assert result[0]["time"] == pytest.approx(90.0, abs=0.01)
