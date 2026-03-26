# tests/test_karaoke.py
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from karaoke import parse_vtt, LyricLine, get_lyrics

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

def test_get_lyrics_uses_subtitles_when_available(tmp_path):
    mock_lines = [LyricLine(start=1.0, end=3.0, text="Hello")]
    with patch("karaoke.fetch_youtube_subtitles", return_value=mock_lines) as mock_sub, \
         patch("karaoke.transcribe_with_whisper") as mock_whisper:
        audio = tmp_path / "audio.mp3"
        audio.touch()
        result = get_lyrics("https://example.com", audio, tmp_path)
        assert result == mock_lines
        mock_whisper.assert_not_called()

def test_get_lyrics_falls_back_to_whisper(tmp_path):
    mock_lines = [LyricLine(start=0.0, end=2.0, text="Test")]
    with patch("karaoke.fetch_youtube_subtitles", return_value=None), \
         patch("karaoke.transcribe_with_whisper", return_value=mock_lines) as mock_w:
        audio = tmp_path / "audio.mp3"
        audio.touch()
        result = get_lyrics("https://example.com", audio, tmp_path)
        assert result == mock_lines
        mock_w.assert_called_once_with(audio)

def test_get_lyrics_no_url_skips_subtitles(tmp_path):
    mock_lines = [LyricLine(start=0.0, end=2.0, text="Test")]
    with patch("karaoke.fetch_youtube_subtitles") as mock_sub, \
         patch("karaoke.transcribe_with_whisper", return_value=mock_lines):
        audio = tmp_path / "audio.mp3"
        audio.touch()
        result = get_lyrics(None, audio, tmp_path)
        mock_sub.assert_not_called()

def test_get_lyrics_missing_audio_raises(tmp_path):
    with patch("karaoke.fetch_youtube_subtitles", return_value=None):
        audio = tmp_path / "nonexistent.mp3"
        with pytest.raises(FileNotFoundError):
            get_lyrics(None, audio, tmp_path)
