"""YouTube video and subtitle downloader."""
import subprocess
from pathlib import Path
from dataclasses import dataclass
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import YTDLP_PATH, DATA_DIR


@dataclass
class DownloadResult:
    success: bool
    video_path: Path | None = None
    srt_path: Path | None = None
    error: str | None = None
    title: str | None = None


def download_video(url: str, output_name: str | None = None) -> DownloadResult:
    """
    Download YouTube video and English subtitles.
    Returns paths to video and SRT file.
    """
    # Create output directory
    output_dir = DATA_DIR / (output_name or "video")
    output_dir.mkdir(parents=True, exist_ok=True)

    video_template = str(output_dir / "video.%(ext)s")

    cmd = [
        YTDLP_PATH,
        "--remote-components", "ejs:github",  # Required for YouTube JS challenges
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--merge-output-format", "mp4",
        "--write-auto-subs",
        "--write-subs",
        "--sub-langs", "en",
        "--sub-format", "srt",
        "--convert-subs", "srt",
        "-o", video_template,
        url,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        # Extract title from output (look for the line after "Downloading webpage")
        title = None
        if result.stderr:
            for line in result.stderr.split('\n'):
                if 'Destination:' in line and 'video.mp4' in line:
                    break
                if '[download]' not in line and '[info]' not in line and line.strip():
                    title = line.strip()

        # Find downloaded files
        video_path = next(output_dir.glob("video.mp4"), None)
        srt_path = next(output_dir.glob("video.en.srt"), None)

        if not srt_path:
            srt_path = next(output_dir.glob("video*.srt"), None)

        if not video_path:
            return DownloadResult(False, error="Video download failed")
        if not srt_path:
            return DownloadResult(False, error="No English subtitles found")

        return DownloadResult(
            success=True,
            video_path=video_path,
            srt_path=srt_path,
            title=title
        )

    except subprocess.CalledProcessError as e:
        return DownloadResult(False, error=f"Download failed: {e.stderr}")
    except Exception as e:
        return DownloadResult(False, error=str(e))
