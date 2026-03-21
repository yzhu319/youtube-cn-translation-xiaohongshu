"""FFmpeg subtitle burning for video output."""
import subprocess
import threading
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Callable
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    FFMPEG_PATH, DEFAULT_FONT, DEFAULT_FONT_SIZE,
    DEFAULT_MARGIN_V, DEFAULT_OUTLINE
)

# Global status tracking
_burn_status = {}


@dataclass
class BurnConfig:
    font: str = DEFAULT_FONT
    font_size: int = DEFAULT_FONT_SIZE
    margin_v: int = DEFAULT_MARGIN_V
    outline: int = DEFAULT_OUTLINE
    primary_color: str = "&H00FFFFFF"  # White in ASS format
    outline_color: str = "&H00000000"  # Black


@dataclass
class BurnResult:
    success: bool
    output_path: Path | None = None
    error: str | None = None


def get_burn_status(job_id: str) -> dict:
    """Get status of a burn job."""
    return _burn_status.get(job_id, {"status": "unknown"})


def _create_ass_style(config: BurnConfig) -> str:
    """Create ASS style string for subtitles."""
    return (
        f"FontName={config.font},"
        f"FontSize={config.font_size},"
        f"PrimaryColour={config.primary_color},"
        f"OutlineColour={config.outline_color},"
        f"Outline={config.outline},"
        f"MarginV={config.margin_v},"
        "Alignment=2"  # Bottom center
    )


def burn_subtitles(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    config: BurnConfig | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> BurnResult:
    """
    Burn subtitles into video using FFmpeg.
    Returns path to output video.
    """
    if config is None:
        config = BurnConfig()

    if not video_path.exists():
        return BurnResult(False, error=f"Video not found: {video_path}")
    if not srt_path.exists():
        return BurnResult(False, error=f"Subtitle not found: {srt_path}")

    # Get video duration for progress
    duration = _get_video_duration(video_path)

    style = _create_ass_style(config)
    srt_escaped = str(srt_path).replace(":", r"\:").replace("'", r"\'")

    filter_str = f"subtitles='{srt_escaped}':force_style='{style}'"

    cmd = [
        FFMPEG_PATH,
        "-i", str(video_path),
        "-vf", filter_str,
        "-c:a", "copy",
        "-y",
        "-progress", "pipe:1",
        str(output_path),
    ]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

        # Parse progress from FFmpeg output
        while True:
            line = process.stdout.readline()
            if not line:
                break
            if line.startswith("out_time_ms="):
                try:
                    time_ms = int(line.split("=")[1])
                    if duration > 0 and progress_callback:
                        progress = min((time_ms / 1000000) / duration, 1.0)
                        progress_callback(progress)
                except ValueError:
                    pass

        process.wait()

        if process.returncode != 0:
            stderr = process.stderr.read()
            return BurnResult(False, error=f"FFmpeg failed: {stderr}")

        if not output_path.exists():
            return BurnResult(False, error="Output file not created")

        return BurnResult(success=True, output_path=output_path)

    except Exception as e:
        return BurnResult(False, error=str(e))


def burn_subtitles_async(
    job_id: str,
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    config: BurnConfig | None = None,
) -> None:
    """
    Start async burn job. Check status with get_burn_status(job_id).
    """
    _burn_status[job_id] = {"status": "starting", "progress": 0}

    def run_burn():
        def update_progress(progress: float):
            _burn_status[job_id] = {
                "status": "burning",
                "progress": progress
            }

        try:
            result = burn_subtitles(
                video_path, srt_path, output_path, config, update_progress
            )

            if result.success:
                _burn_status[job_id] = {
                    "status": "complete",
                    "progress": 1.0,
                    "output_path": str(result.output_path),
                }
            else:
                _burn_status[job_id] = {
                    "status": "failed",
                    "error": result.error,
                }
        except Exception as e:
            _burn_status[job_id] = {
                "status": "failed",
                "error": str(e),
            }

    thread = threading.Thread(target=run_burn, daemon=True)
    thread.start()


def _get_video_duration(video_path: Path) -> float:
    """Get video duration in seconds using ffprobe."""
    try:
        ffprobe_path = FFMPEG_PATH.replace("ffmpeg", "ffprobe")
        cmd = [
            ffprobe_path,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except Exception:
        return 0
