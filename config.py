"""Configuration and environment setup."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Paths
APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# FFmpeg path (use ffmpeg-full for subtitle support)
FFMPEG_PATH = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
YTDLP_PATH = "/Users/yuanzheng/Library/Python/3.11/bin/yt-dlp"

# Translation defaults
DEFAULT_BATCH_SIZE = 12
DEFAULT_CONTEXT_SIZE = 5
OPENAI_MODEL = "gpt-4o-mini"

# Subtitle style defaults
DEFAULT_FONT = "PingFang SC"
DEFAULT_FONT_SIZE = 18
DEFAULT_MARGIN_V = 55
DEFAULT_OUTLINE = 2
