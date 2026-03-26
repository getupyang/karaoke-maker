# karaoke.py
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import subprocess
import sys


@dataclass
class LyricLine:
    start: float   # seconds
    end: float
    text: str


def _timestamp_to_seconds(ts: str) -> float:
    """'00:01:23.456' or '01:23.456' -> float seconds"""
    parts = ts.strip().replace(",", ".").split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(parts[0])


def parse_vtt(content: str) -> List[LyricLine]:
    """解析 WebVTT 字幕内容，返回 LyricLine 列表"""
    lines = []
    blocks = re.split(r"\n\n+", content.strip())
    pattern = re.compile(
        r"(\d[\d:,.]+)\s+-->\s+(\d[\d:,.]+)\s*\n([\s\S]+)"
    )
    seen_texts = set()
    for block in blocks:
        m = pattern.search(block)
        if not m:
            continue
        start = _timestamp_to_seconds(m.group(1))
        end = _timestamp_to_seconds(m.group(2))
        text = re.sub(r"<[^>]+>", "", m.group(3)).strip()
        text = re.sub(r"\s+", " ", text)
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        lines.append(LyricLine(start=start, end=end, text=text))
    return lines


def fetch_youtube_subtitles(url: str, job_dir: Path) -> Optional[List[LyricLine]]:
    """用 yt-dlp 下载字幕（优先手动字幕，fallback 自动字幕）"""
    for auto in [False, True]:
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--skip-download",
            "--write-subs" if not auto else "--write-auto-subs",
            "--sub-format", "vtt",
            "--sub-langs", "zh-Hans,zh-Hant,zh,en",
            "--output", str(job_dir / "subtitle.%(ext)s"),
            "--quiet",
            url,
        ]
        subprocess.run(cmd, capture_output=True)
        for f in job_dir.glob("subtitle*.vtt"):
            content = f.read_text(encoding="utf-8", errors="ignore")
            lines = parse_vtt(content)
            if lines:
                return lines
    return None


def transcribe_with_whisper(audio_path: Path) -> List[LyricLine]:
    """用本地 Whisper medium 模型转写，返回带时间轴歌词"""
    import whisper
    model = whisper.load_model("medium")
    result = model.transcribe(str(audio_path), word_timestamps=False)
    lines = []
    for seg in result.get("segments", []):
        text = seg["text"].strip()
        if text:
            lines.append(LyricLine(
                start=seg["start"],
                end=seg["end"],
                text=text,
            ))
    return lines


def get_lyrics(url: Optional[str], audio_path: Path, job_dir: Path) -> List[LyricLine]:
    """主入口：YouTube字幕（url不为空时）→ Whisper fallback"""
    if url:
        lines = fetch_youtube_subtitles(url, job_dir)
        if lines:
            return lines
    return transcribe_with_whisper(audio_path)
