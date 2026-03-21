# YouTube → 小红书 Converter

A Streamlit web app that downloads YouTube videos, translates subtitles to Chinese using AI, and burns bilingual captions into the video for sharing on 小红书 (Xiaohongshu / RedNote).

## Features

- Download YouTube videos and auto-generated subtitles via yt-dlp
- AI-powered English → Chinese translation with context-aware batching
- Real-time subtitle preview with adjustable styling (font, size, position, color)
- Burn Chinese subtitles permanently into the video via ffmpeg
- Download the finished MP4 directly from the browser

## Demo

```
YouTube URL → Download → Translate → Preview & Style → Burn → Download
```

## Setup

**Prerequisites:** Python 3.11+, [ffmpeg](https://ffmpeg.org/download.html)

```bash
pip install -r requirements.txt
```

Create a `.env` file:
```
OPENAI_API_KEY=sk-...
```

Run:
```bash
streamlit run app.py
```

## Usage

1. Paste a YouTube URL and click **Download Video**
2. Click **Start Translation** to translate subtitles to Chinese
3. Adjust subtitle styling in the sidebar with live preview
4. Click **Burn Subtitles** to encode them into the video
5. Download the final MP4

## Project Structure

```
app.py              # Streamlit UI
config.py           # Config and constants
core/
  downloader.py     # yt-dlp wrapper
  translator.py     # OpenAI translation
  subtitles.py      # SRT parsing and writing
  burner.py         # ffmpeg subtitle burning
scripts/
  yt_to_xiaohongshu.py   # Original CLI pipeline script
```

## Stack

- [Streamlit](https://streamlit.io) — UI
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — YouTube downloader
- [OpenAI API](https://platform.openai.com) — Translation (gpt-4o-mini)
- [ffmpeg](https://ffmpeg.org) — Video encoding
