# YouTube → 小红书 Converter

A Streamlit web app that downloads YouTube videos, translates subtitles to Chinese using AI, and burns bilingual captions into the video for sharing on 小红书 (Xiaohongshu / RedNote).

## Features

- Download YouTube videos and auto-generated subtitles via yt-dlp
- AI-powered English → Chinese translation with adaptive, context-aware batching
- Real-time subtitle preview with adjustable styling (font, size, position, color, background)
- Preview-accurate subtitle burning via proper ASS file generation
- Hardware-accelerated encoding (VideoToolbox on macOS, NVENC on Linux)
- Multi-level translation fallback — batch → sub-batch → individual line

## Demo

```
YouTube URL → Download → Translate → Preview & Style → Burn → Download
```

## Setup

### Prerequisites

- **Python 3.11+**
- **ffmpeg** with libass + VideoToolbox support
- **yt-dlp** (YouTube downloader)

#### macOS (Homebrew)

```bash
# ffmpeg with libass (required for subtitle rendering)
# The default brew formula may lack libass — use the tap:
brew tap homebrew-ffmpeg/ffmpeg
brew install homebrew-ffmpeg/ffmpeg/ffmpeg

# yt-dlp
brew install yt-dlp
```

#### Verify prerequisites

```bash
ffmpeg -filters 2>&1 | grep ass     # should show "ass" and "subtitles" filters
ffmpeg -encoders 2>&1 | grep videotoolbox  # should show h264_videotoolbox on macOS
yt-dlp --version
python3 --version                    # 3.11+
```

### Install Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure API key

The app searches up the directory tree for a `.env` file, so you can share one
across all projects under `~/src/github.com/yzhu319/`:

```bash
# Shared key for all personal projects (recommended)
echo "OPENAI_API_KEY=sk-..." > ~/src/github.com/yzhu319/.env

# Or project-local (takes precedence over shared)
echo "OPENAI_API_KEY=sk-..." > .env
```

### (Optional) Override defaults via `.env`

```bash
# Translation model (default: gpt-5.4-mini)
OPENAI_MODEL=gpt-5.4-mini

# Binary paths (auto-detected from PATH if not set)
FFMPEG_PATH=/path/to/ffmpeg
YTDLP_PATH=/path/to/yt-dlp
```

## Run

```bash
./run.sh
```

That's it — it auto-creates the venv if needed and launches the app at http://localhost:8501.

Or manually:
```bash
source .venv/bin/activate
streamlit run app.py
```

## Usage

1. Paste a YouTube URL and click **Download Video**
2. Review the auto-computed translation strategy (batch size adapts to content length/density)
3. Click **Start Translation** — subtitles are translated in semantically-split chunks with full-transcript context
4. Adjust subtitle styling in the sidebar with **live preview** (font, color, size, position, background opacity)
5. Click **Burn Subtitles** — generates an ASS file scaled to actual video dimensions, so the burned result matches the preview
6. Download the final MP4

### Default subtitle settings

| Setting | Default |
|---|---|
| Font | Heiti SC |
| Font size | 21px |
| Position | 12% from bottom |
| Background opacity | 20% |
| Outline | 2px |

## Testing

### Quick smoke test (no API key needed)

```bash
source .venv/bin/activate
python3 -c "
from core.subtitles import SubtitleEntry
from core.translator import compute_optimal_batch_size, split_into_semantic_chunks
from core.burner import BurnConfig, hex_to_ass_color, srt_time_to_ass

entries = [SubtitleEntry(str(i), '00:00:01,000', '00:00:02,000', 'Hello world') for i in range(150)]
size, desc = compute_optimal_batch_size(entries)
print(f'150 entries → batch={size}, strategy: {desc}')

chunks = split_into_semantic_chunks(entries, size)
print(f'Split into {len(chunks)} chunks')

assert hex_to_ass_color('#FFFFFF') == '&H00FFFFFF'
assert srt_time_to_ass('00:01:23,456') == '0:01:23.45'
print('All smoke tests passed.')
"
```

### Test burn only (no API key needed)

If you have a translated `.cn.srt` file:

```python
from pathlib import Path
from core.burner import BurnConfig, burn_subtitles

result = burn_subtitles(
    video_path=Path("data/test/video.mp4"),
    srt_path=Path("data/test/video.cn.srt"),
    output_path=Path("data/test/output_test.mp4"),
    config=BurnConfig(font_size=21, position_bottom_pct=12.0, bg_opacity=20),
    progress_callback=lambda p: print(f"{p*100:.0f}%"),
)
print(f"Success: {result.success}, output: {result.output_path}")
```

## Project Organization

Each video gets its own project folder under `data/`, auto-named from YouTube metadata:

```
data/
  Bernie vs Claude - 20260319 - h3AtWdeu_G0/
    Bernie vs Claude - 20260319 - h3AtWdeu_G0.mp4         # downloaded video
    Bernie vs Claude - 20260319 - h3AtWdeu_G0.en.srt      # original English subtitles
    Bernie vs Claude - 20260319 - h3AtWdeu_G0.cn.srt      # translated Chinese subtitles
    Bernie vs Claude - 20260319 - h3AtWdeu_G0.bilingual.srt
    Bernie vs Claude - 20260319 - h3AtWdeu_G0.cn.ass      # styled ASS (generated at burn)
    Bernie vs Claude - 20260319 - h3AtWdeu_G0 - CN.mp4    # final output
  AI and the Future - 20260315 - xK9f2Lp_Q3w/
    AI and the Future - 20260315 - xK9f2Lp_Q3w.mp4
    ...
```

Folder naming convention: `{title} - {YYYYMMDD} - {video_id}`

- **Title** — sanitized YouTube video title
- **Date** — upload date from YouTube (YYYYMMDD)
- **Video ID** — YouTube video ID for deduplication

When you paste a URL, the app auto-detects if a project already exists for that video ID and offers to reuse it.

## Code Structure

```
app.py              # Streamlit UI (4-step wizard)
config.py           # Config, env vars, binary path resolution
core/
  downloader.py     # yt-dlp wrapper with auto project naming
  translator.py     # OpenAI translation with adaptive chunking
  subtitles.py      # SRT parsing, writing, overlap fixing
  burner.py         # ffmpeg subtitle burning via ASS generation
scripts/
  yt_to_xiaohongshu.py   # Original CLI pipeline script
```

## Architecture

### Translation pipeline

1. **Summary pass** — one API call summarizes the full transcript (topic, speakers, key terms, tone)
2. **Adaptive chunking** — `compute_optimal_batch_size()` picks chunk size based on entry count and average word density; `split_into_semantic_chunks()` adjusts boundaries to avoid mid-sentence splits
3. **Context-aware translation** — each chunk is translated with the global summary + a sliding window of surrounding lines as local context
4. **Multi-level fallback** — robust marker parsing (0-indexed, 1-indexed, plain lines); on partial failure, missing lines are re-batched then individually translated as last resort

### Burn pipeline (preview-accurate)

The burn step generates a proper `.ass` (Advanced SubStation Alpha) subtitle file rather than using ffmpeg's `force_style` on raw SRT. This ensures the burned video matches the browser preview:

- `PlayResX/PlayResY` set to actual video dimensions (via ffprobe)
- Font size scaled correctly: `css_px * video_width / 900` (the preview container max-width)
- Position scaled correctly: `(bottom_pct / 100) * video_height`
- Background box via ASS `BorderStyle=3` with alpha-blended `BackColour`
- Hardware encoding auto-detected: VideoToolbox (macOS), NVENC (Linux), VAAPI (Linux)
- Progress written to temp file instead of pipe to avoid stdout/stderr deadlock
- Default font `Heiti SC` — available via fontconfig on macOS (unlike `PingFang SC` which is a private framework font)

### Key design decisions

| Decision | Why |
|---|---|
| Synchronous burn (not async) | Simpler, no polling loop, direct `st.progress` updates, no pipe deadlock |
| ASS file instead of `force_style` | Allows `PlayResX/PlayResY` for accurate scaling, proper background box |
| Hardware encoder | 8-10x faster than software libx264 on Apple Silicon |
| Progress via temp file | Avoids classic stdout/stderr pipe deadlock with `subprocess.Popen` |
| Adaptive batch size | Balances translation quality (context) vs reliability (smaller batches fail less) |
| Semantic chunk splitting | Avoids cutting mid-sentence, which degrades translation quality |
| `gpt-5.4-mini` default | Latest cost-effective OpenAI model; configurable via `OPENAI_MODEL` env var |
| `Heiti SC` font | Available via fontconfig on macOS; `PingFang SC` causes libass glyph errors |

## Stack

- [Streamlit](https://streamlit.io) — UI
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — YouTube downloader
- [OpenAI API](https://platform.openai.com) — Translation (gpt-5.4-mini default, configurable via `OPENAI_MODEL`)
- [ffmpeg](https://ffmpeg.org) — Video encoding with libass subtitle rendering + VideoToolbox hardware acceleration
