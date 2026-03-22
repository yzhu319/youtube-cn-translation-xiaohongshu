"""Configuration and environment setup."""
import os
import shutil
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


def _find_binary(name: str, env_var: str, hardcoded_fallbacks: list[str]) -> str:
    """Resolve a binary path: env var > PATH lookup > hardcoded fallbacks."""
    env = os.getenv(env_var)
    if env and os.path.isfile(env):
        return env
    found = shutil.which(name)
    if found:
        return found
    for path in hardcoded_fallbacks:
        if os.path.isfile(path):
            return path
    return name  # bare name; will fail loudly at runtime if missing


FFMPEG_PATH = _find_binary("ffmpeg", "FFMPEG_PATH", [
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
])

YTDLP_PATH = _find_binary("yt-dlp", "YTDLP_PATH", [
    "/opt/homebrew/bin/yt-dlp",
    "/usr/local/bin/yt-dlp",
])

# Translation defaults
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")

# Subtitle style defaults
DEFAULT_FONT = "Heiti SC"
DEFAULT_FONT_SIZE = 18
DEFAULT_MARGIN_V = 55
DEFAULT_OUTLINE = 2
