"""YouTube video and subtitle downloader with auto project naming."""
import re
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
    video_id: str | None = None
    upload_date: str | None = None
    project_name: str | None = None


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    match = re.search(r'(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else None


def _sanitize_for_filename(name: str, max_len: int = 80) -> str:
    """Sanitize a string for use in file/folder names."""
    name = re.sub(r'[/\\:*?"<>|]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name


def _fetch_video_metadata(url: str) -> dict | None:
    """Fetch video metadata (title, id, upload_date) without downloading."""
    try:
        cmd = [
            YTDLP_PATH,
            "--print", "title",
            "--print", "id",
            "--print", "upload_date",
            "--skip-download",
            "--no-warnings",
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        lines = result.stdout.strip().split('\n')
        if len(lines) >= 3:
            return {
                "title": lines[0].strip(),
                "video_id": lines[1].strip(),
                "upload_date": lines[2].strip(),  # YYYYMMDD
            }
    except Exception:
        pass
    return None


def build_project_name(title: str, upload_date: str, video_id: str) -> str:
    """
    Build project folder name: '{title} - {YYYYMMDD} - {video_id}'

    Example: 'Bernie vs Claude - 20260319 - h3AtWdeu_G0'
    """
    safe_title = _sanitize_for_filename(title)
    return f"{safe_title} - {upload_date} - {video_id}"


def find_existing_project(video_id: str) -> Path | None:
    """Find an existing project folder that contains the given video ID."""
    if not video_id or not DATA_DIR.exists():
        return None
    for d in sorted(DATA_DIR.iterdir(), reverse=True):
        if d.is_dir() and video_id in d.name:
            # Check for any .mp4 video file (new or old naming)
            if any(d.glob("*.mp4")):
                return d
    return None


def download_video(url: str, output_name: str | None = None) -> DownloadResult:
    """
    Download YouTube video and English subtitles.

    Auto-generates a project folder name from video metadata:
        data/{title} - {YYYYMMDD} - {video_id}/
    """
    # Fetch metadata first (fast, no download)
    meta = _fetch_video_metadata(url)

    if meta and not output_name:
        project_name = build_project_name(
            meta["title"], meta["upload_date"], meta["video_id"]
        )
    elif output_name:
        project_name = output_name
    else:
        # Fallback: use video ID from URL or generic name
        vid = extract_video_id(url) or "video"
        project_name = vid

    output_dir = DATA_DIR / project_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Name files after the project: "{project_name}.mp4", "{project_name}.en.srt"
    base_name = project_name
    video_template = str(output_dir / f"{base_name}.%(ext)s")

    cmd = [
        YTDLP_PATH,
        "--remote-components", "ejs:github",
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
        subprocess.run(cmd, capture_output=True, text=True, check=True)

        video_path = next(output_dir.glob(f"{base_name}.mp4"), None)
        srt_path = next(output_dir.glob(f"{base_name}.en.srt"), None)
        if not srt_path:
            srt_path = next(output_dir.glob(f"{base_name}*.srt"), None)
        # Fallback to old "video.*" naming for backward compat with existing projects
        if not video_path:
            video_path = next(output_dir.glob("video.mp4"), None)
        if not srt_path:
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
            title=meta["title"] if meta else None,
            video_id=meta["video_id"] if meta else None,
            upload_date=meta["upload_date"] if meta else None,
            project_name=project_name,
        )

    except subprocess.CalledProcessError as e:
        return DownloadResult(False, error=f"Download failed: {e.stderr[-500:] if e.stderr else 'unknown'}")
    except Exception as e:
        return DownloadResult(False, error=str(e))
