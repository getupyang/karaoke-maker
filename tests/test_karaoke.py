# tests/test_karaoke.py
import pytest
from pathlib import Path
from karaoke import parse_vtt, LyricLine

def test_parse_vtt_basic():
    vtt = """WEBVTT

00:00:01.000 --> 00:00:04.000
Hello world

00:00:05.000 --> 00:00:08.000
Second line
"""
    lines = parse_vtt(vtt)
    assert len(lines) == 2
    assert lines[0].start == 1.0
    assert lines[0].end == 4.0
    assert lines[0].text == "Hello world"
    assert lines[1].start == 5.0

def test_parse_vtt_empty():
    lines = parse_vtt("WEBVTT\n\n")
    assert lines == []
