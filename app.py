#!/usr/bin/env python3
"""
K歌伴奏生成器 - 本地 Web 服务
支持 YouTube 链接或本地音频文件，使用 Demucs htdemucs 去除人声
"""

import json as _json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file

load_dotenv(Path(__file__).parent / ".env")

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
OUTPUTS_DIR = BASE_DIR / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".webm", ".opus"}


def get_device():
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def download_audio(url: str, job_dir: Path):
    """用 yt-dlp 下载音频，返回 (文件路径, 标题, video_id)"""
    meta_cmd = [
        sys.executable, "-m", "yt_dlp",
        "--skip-download", "--print-json", "--quiet", "--no-playlist", url,
    ]
    meta_result = subprocess.run(meta_cmd, capture_output=True, text=True)
    title = url
    video_id = None
    if meta_result.returncode == 0 and meta_result.stdout.strip():
        try:
            info = _json.loads(meta_result.stdout)
            title = info.get("title", url)
            video_id = info.get("id")
        except Exception:
            pass

    outtmpl = str(job_dir / "source.%(ext)s")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--format", "bestaudio/best",
        "--output", outtmpl,
        "--no-playlist", "--quiet", url,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    for f in job_dir.iterdir():
        if f.stem == "source":
            return f, title, video_id
    raise FileNotFoundError("yt-dlp 下载后找不到音频文件")


def separate_vocals(audio_path: Path, job_dir: Path) -> Path:
    """运行 Demucs 去人声，返回伴奏 mp3 路径"""
    device = get_device()
    demucs_out = job_dir / "demucs_out"
    cmd = [
        sys.executable, "-m", "demucs",
        "--two-stems=vocals",
        "-n", "htdemucs",
        "--device", device,
        "-o", str(demucs_out),
        str(audio_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)

    no_vocals_wav = demucs_out / "htdemucs" / audio_path.stem / "no_vocals.wav"
    if not no_vocals_wav.exists():
        raise FileNotFoundError(f"Demucs 输出文件不存在: {no_vocals_wav}")

    accompaniment_mp3 = job_dir / "accompaniment.mp3"
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", str(no_vocals_wav),
        "-vn", "-codec:a", "libmp3lame", "-b:a", "192k",
        str(accompaniment_mp3),
    ]
    subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True)
    return accompaniment_mp3


def parse_vtt(vtt_text: str):
    """Parse a WebVTT string and return a list of {time, text} dicts (deduplicated)."""
    lines = []
    time_pattern = re.compile(
        r"(\d+):(\d{2}):(\d{2})[\.,](\d+)\s+-->\s+(\d+):(\d{2}):(\d{2})[\.,](\d+)"
    )
    blocks = re.split(r"\n{2,}", vtt_text.strip())
    last_text = None
    for block in blocks:
        block = block.strip()
        if not block or block.startswith("WEBVTT") or block.startswith("NOTE"):
            continue
        block_lines = block.splitlines()
        # Find the timing line
        timing_line = None
        text_start = 0
        for i, bl in enumerate(block_lines):
            if time_pattern.search(bl):
                timing_line = bl
                text_start = i + 1
                break
        if timing_line is None:
            continue
        m = time_pattern.search(timing_line)
        if not m:
            continue
        h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        start_time = h * 3600 + mi * 60 + s + int(m.group(4)) / (10 ** len(m.group(4)))
        raw_text = " ".join(block_lines[text_start:]).strip()
        # Strip VTT tags like <00:00:00.000><c> etc.
        raw_text = re.sub(r"<[^>]+>", "", raw_text).strip()
        if not raw_text:
            continue
        # Deduplicate consecutive identical lines
        if raw_text == last_text:
            continue
        last_text = raw_text
        lines.append({"time": round(start_time, 3), "text": raw_text})
    return lines


def parse_lrc(lrc_text: str):
    """Parse an LRC string and return a list of {time, text} dicts."""
    lines = []
    pattern = re.compile(r"^\[(\d+):(\d{2}(?:\.\d+)?)\](.*)")
    metadata_keys = re.compile(r"^\[(ti|ar|al|by|offset|length|re|ve):", re.IGNORECASE)
    for raw_line in lrc_text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        if metadata_keys.match(raw_line):
            continue
        m = pattern.match(raw_line)
        if not m:
            continue
        minutes = int(m.group(1))
        seconds = float(m.group(2))
        text = m.group(3).strip()
        if not text:
            continue
        time_sec = minutes * 60 + seconds
        lines.append({"time": round(time_sec, 3), "text": text})
    return lines


def fetch_lyrics(title: str, url: str, job_dir: Path) -> dict:
    """3-tier lyrics fallback: YouTube VTT → syncedlyrics synced → syncedlyrics plain."""
    try:
        # --- Tier 1: YouTube VTT subtitles ---
        if url:
            try:
                sub_cmd = [
                    sys.executable, "-m", "yt_dlp",
                    "--skip-download",
                    "--write-subs", "--write-auto-subs",
                    "--sub-lang", "zh-Hans,zh-Hant,zh,en",
                    "--sub-format", "vtt",
                    "--output", str(job_dir / "subtitle.%(ext)s"),
                    "--quiet", "--no-playlist", url,
                ]
                subprocess.run(sub_cmd, capture_output=True, text=True, timeout=60)
                vtt_files = list(job_dir.glob("*.vtt"))
                if vtt_files:
                    vtt_text = vtt_files[0].read_text(encoding="utf-8", errors="replace")
                    parsed = parse_vtt(vtt_text)
                    if parsed:
                        return {"type": "synced", "lines": parsed, "source": "YouTube字幕"}
            except Exception:
                pass

        # --- Tier 2: syncedlyrics synced (LRC with timestamps) ---
        try:
            import syncedlyrics
            lrc = syncedlyrics.search(title, allow_plain_format=False)
            if lrc:
                parsed = parse_lrc(lrc)
                if parsed:
                    return {"type": "synced", "lines": parsed, "source": "syncedlyrics"}
        except Exception:
            pass

        # --- Tier 3: syncedlyrics plain text ---
        try:
            import syncedlyrics
            lrc = syncedlyrics.search(title, allow_plain_format=True, enhanced=False)
            if lrc:
                # Check if it actually has timestamps; if so parse as synced
                parsed = parse_lrc(lrc)
                if parsed:
                    return {"type": "synced", "lines": parsed, "source": "syncedlyrics"}
                # Otherwise treat as plain text
                stripped = lrc.strip()
                if stripped:
                    return {"type": "plain", "text": stripped, "source": "syncedlyrics"}
        except Exception:
            pass

    except Exception:
        pass

    # --- Tier 4: DeepSeek LLM fallback ---
    try:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if api_key and title:
            import urllib.request
            prompt = (
                f"以下是一首歌的 YouTube 视频标题：{title}\n\n"
                f"请从标题中识别歌手和歌名，然后输出该歌曲的完整原版歌词。\n"
                f"输出格式严格如下（不要任何多余内容）：\n"
                f"歌名：xxx\n"
                f"歌手：xxx\n"
                f"\n"
                f"（歌词正文，每行一句，段落间空一行，不要重复同一句话除非原曲本身重复）"
            )
            payload = _json.dumps({
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 2000,
            }).encode()
            req = urllib.request.Request(
                "https://api.deepseek.com/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = _json.loads(resp.read())
            text = result["choices"][0]["message"]["content"].strip()
            if text:
                return {"type": "plain", "text": text, "source": "DeepSeek"}
    except Exception:
        pass

    return {"type": None}


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "请输入搜索词"}), 400
    cmd = [
        sys.executable, "-m", "yt_dlp",
        f"ytsearch5:{query}",
        "--skip-download", "--print-json", "--quiet", "--no-playlist",
        "--flat-playlist",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    videos = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        try:
            info = _json.loads(line)
            vid_id = info.get("id") or info.get("url", "").split("v=")[-1]
            title = info.get("title", "")
            duration = info.get("duration")
            thumbnail = info.get("thumbnail") or f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"
            if vid_id and title:
                videos.append({
                    "id": vid_id,
                    "title": title,
                    "duration": duration,
                    "thumbnail": thumbnail,
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                })
        except Exception:
            continue
    return jsonify(videos)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/process", methods=["POST"])
def process():
    job_id = str(uuid.uuid4())[:8]
    job_dir = OUTPUTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        url = request.form.get("url", "").strip()
        uploaded_file = request.files.get("file")

        if url:
            audio_path, title, video_id = download_audio(url, job_dir)
        elif uploaded_file and uploaded_file.filename:
            suffix = Path(uploaded_file.filename).suffix.lower()
            if suffix not in ALLOWED_EXTENSIONS:
                shutil.rmtree(job_dir, ignore_errors=True)
                return jsonify({"error": f"不支持的文件格式: {suffix}"}), 400
            audio_path = job_dir / f"source{suffix}"
            uploaded_file.save(str(audio_path))
            title = uploaded_file.filename
            video_id = None
        else:
            shutil.rmtree(job_dir, ignore_errors=True)
            return jsonify({"error": "请输入 YouTube 链接或上传音频文件"}), 400

        separate_vocals(audio_path, job_dir)

        if url:
            lyrics_data = fetch_lyrics(title, url, job_dir)
        else:
            lyrics_data = {"type": None}

        return jsonify({
            "job_id": job_id,
            "title": title,
            "video_id": video_id,
            "accompaniment_url": f"/output/{job_id}/accompaniment.mp3",
            "lyrics": lyrics_data,
        })

    except subprocess.CalledProcessError as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        stderr = e.stderr or ""
        return jsonify({"error": f"处理失败: {stderr[-500:] if stderr else str(e)}"}), 500
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"error": str(e)}), 500


@app.route("/output/<job_id>/accompaniment.mp3")
def serve_output(job_id):
    safe_id = Path(job_id).name
    mp3_path = OUTPUTS_DIR / safe_id / "accompaniment.mp3"
    if not mp3_path.exists():
        return jsonify({"error": "文件不存在"}), 404
    return send_file(str(mp3_path), mimetype="audio/mpeg", as_attachment=False)


@app.route("/download/<job_id>/accompaniment.mp3")
def download_output(job_id):
    safe_id = Path(job_id).name
    mp3_path = OUTPUTS_DIR / safe_id / "accompaniment.mp3"
    if not mp3_path.exists():
        return jsonify({"error": "文件不存在"}), 404
    return send_file(str(mp3_path), mimetype="audio/mpeg", as_attachment=True,
                     download_name="accompaniment.mp3")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "device": get_device()})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
