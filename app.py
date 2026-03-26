#!/usr/bin/env python3
"""
K歌伴奏生成器 - 本地 Web 服务
支持 YouTube 链接或本地音频文件，使用 Demucs htdemucs 去除人声
"""

import json as _json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
OUTPUTS_DIR = BASE_DIR / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".webm", ".opus"}


def get_device():
    """检测最佳可用设备"""
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
    """用 yt-dlp 下载音频，返回 (文件路径, 标题)"""
    # 先获取 metadata（不下载）
    meta_cmd = [
        sys.executable, "-m", "yt_dlp",
        "--skip-download", "--print-json", "--quiet", "--no-playlist", url,
    ]
    meta_result = subprocess.run(meta_cmd, capture_output=True, text=True)
    title = url  # fallback
    if meta_result.returncode == 0 and meta_result.stdout.strip():
        try:
            title = _json.loads(meta_result.stdout)["title"]
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
            return f, title
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

    # Demucs 输出结构: demucs_out/htdemucs/<stem>/no_vocals.wav
    no_vocals_wav = demucs_out / "htdemucs" / audio_path.stem / "no_vocals.wav"
    if not no_vocals_wav.exists():
        raise FileNotFoundError(f"Demucs 输出文件不存在: {no_vocals_wav}")

    # 转换为 mp3
    accompaniment_mp3 = job_dir / "accompaniment.mp3"
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", str(no_vocals_wav),
        "-vn", "-codec:a", "libmp3lame", "-b:a", "192k",
        str(accompaniment_mp3),
    ]
    subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True)

    return accompaniment_mp3


def _fetch_and_save_lyrics(url: str, audio_path: Path, job_dir: Path):
    """后台线程：获取歌词并写入 lyrics.json"""
    try:
        from karaoke import get_lyrics
        lyrics = get_lyrics(url if url else None, audio_path, job_dir)
        data = {"status": "done", "lines": [{"start": l.start, "end": l.end, "text": l.text} for l in lyrics]}
    except Exception as e:
        import logging
        logging.warning(f"lyrics fetch failed: {e}")
        data = {"status": "error", "lines": []}
    # atomic write: tmp file + rename
    tmp = job_dir / "lyrics.json.tmp"
    tmp.write_text(_json.dumps(data, ensure_ascii=False))
    tmp.rename(job_dir / "lyrics.json")


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
            audio_path, title = download_audio(url, job_dir)
        elif uploaded_file and uploaded_file.filename:
            suffix = Path(uploaded_file.filename).suffix.lower()
            if suffix not in ALLOWED_EXTENSIONS:
                shutil.rmtree(job_dir, ignore_errors=True)
                return jsonify({"error": f"不支持的文件格式: {suffix}"}), 400
            audio_path = job_dir / f"source{suffix}"
            uploaded_file.save(str(audio_path))
            title = uploaded_file.filename
        else:
            shutil.rmtree(job_dir, ignore_errors=True)
            return jsonify({"error": "请输入 YouTube 链接或上传音频文件"}), 400

        accompaniment_path = separate_vocals(audio_path, job_dir)

        threading.Thread(
            target=_fetch_and_save_lyrics,
            args=(url, audio_path, job_dir),
            daemon=True
        ).start()

        return jsonify({
            "job_id": job_id,
            "title": title,
            "accompaniment_url": f"/output/{job_id}/accompaniment.mp3",
            "lyrics_url": f"/lyrics/{job_id}",
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
    # 防止路径穿越
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


@app.route("/lyrics/<job_id>")
def serve_lyrics(job_id):
    safe_id = Path(job_id).name
    job_dir = OUTPUTS_DIR / safe_id
    if not job_dir.exists():
        return jsonify({"error": "任务不存在"}), 404
    lyrics_path = job_dir / "lyrics.json"
    if not lyrics_path.exists():
        return jsonify({"status": "processing"}), 202
    return jsonify(_json.loads(lyrics_path.read_text()))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
