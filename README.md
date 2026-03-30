# 屋内 K 歌

在家唱 K 的工具。搜索 YouTube 歌曲，自动去除人声生成伴奏，同步显示歌词，跟着视频字幕唱。

## 每次使用

```bash
cd /Users/getupyang/Documents/ai/coding/屋内k歌
./start.sh
```

浏览器会自动打开 http://127.0.0.1:5000，用完关掉终端即可。

## 使用方式

1. 在搜索框输入歌名，选择搜索结果（URL 自动填入）
2. 点击「生成伴奏」，等待约 1-2 分钟
3. 先点视频播放（静音，看字幕），再点伴奏播放，跟着唱

也可以直接粘贴 YouTube 链接，或上传本地音频文件（mp3/wav/m4a 等）。

## 歌词来源（自动按顺序尝试）

1. YouTube 视频字幕（有时间轴，自动高亮当前行）
2. syncedlyrics 在线歌词库（有时间轴）
3. Kimi 联网搜索（无时间轴，静态显示）

歌词面板右上角会显示来源标签。

## 环境配置（仅首次或重装后需要）

**依赖：**
- macOS + Apple M1（MPS 加速）
- [uv](https://github.com/astral-sh/uv)：`brew install uv`
- ffmpeg：`brew install ffmpeg`

**安装：**
```bash
cd /Users/getupyang/Documents/ai/coding/屋内k歌
uv venv
uv pip install --python venv/bin/python -r requirements.txt
```

**API Key 配置：**

```bash
cp .env.example .env
# 用编辑器打开 .env，填入 key
```

`.env` 内容：
```
DEEPSEEK_API_KEY=你的key
MOONSHOT_API_KEY=你的key
```

Kimi key 在 https://platform.moonshot.cn 获取，用于歌词兜底搜索。

## 生成的文件

每次生成的伴奏保存在 `outputs/` 目录，可在页面直接下载。
