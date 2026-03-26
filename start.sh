#!/bin/bash
# 屋内K歌 - 启动脚本
cd "$(dirname "$0")"

# 检查 venv
if [ ! -f "venv/bin/python" ]; then
  echo "首次运行，正在初始化环境..."
  uv venv --python 3.11 venv
  uv pip install --python venv/bin/python \
    flask yt-dlp demucs soundfile \
    "torch==2.2.2" "torchaudio==2.2.2" "numpy<2" \
    --index-url https://download.pytorch.org/whl/cpu
  echo "环境初始化完成"
fi

echo "启动 K歌伴奏生成器..."
echo "浏览器打开: http://127.0.0.1:5000"
venv/bin/python app.py
