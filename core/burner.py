"""FFmpeg subtitle burning for video output."""
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import Callable
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import FFMPEG_PATH, DEFAULT_FONT, DEFAULT_FONT_SIZE, DEFAULT_OUTLINE


@dataclass
class BurnConfig:
    font: str = DEFAULT_FONT
    font_size: int = 21              # CSS px as shown in preview slider
    position_bottom_pct: float = 12.0  # % from bottom, as shown in preview slider
    outline: int = DEFAULT_OUTLINE
    font_color_hex: str = "#FFFFFF"  # HTML hex color from preview color picker
    bg_opacity: int = 20             # 0–100 % background opacity from preview slider


@dataclass
class BurnResult:
    success: bool
    output_path: Path | None = None
    error: str | None = None


def hex_to_ass_color(hex_color: str, alpha: int = 0) -> str:
    """
    Convert HTML #RRGGBB to ASS &HAABBGGRR format.
    ASS alpha: 0 = fully opaque, 255 = fully transparent.
    """
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join(c * 2 for c in hex_color)
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def srt_time_to_ass(time_str: str) -> str:
    """Convert SRT time (00:00:00,000) to ASS time (H:MM:SS.cc)."""
    time_str = time_str.strip().replace(',', '.')
    parts = time_str.split(':')
    h = int(parts[0])
    m = int(parts[1])
    s_parts = parts[2].split('.')
    s = int(s_parts[0])
    ms = int(s_parts[1][:3].ljust(3, '0')) if len(s_parts) > 1 else 0
    cs = ms // 10
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def get_video_dimensions(video_path: Path) -> tuple[int, int]:
    """Get video width and height via ffprobe. Returns (width, height)."""
    try:
        ffprobe_path = FFMPEG_PATH.replace("ffmpeg", "ffprobe")
        cmd = [
            ffprobe_path, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        parts = result.stdout.strip().split(',')
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return 1920, 1080


def _get_video_duration(video_path: Path) -> float:
    """Get video duration in seconds using ffprobe."""
    try:
        ffprobe_path = FFMPEG_PATH.replace("ffmpeg", "ffprobe")
        cmd = [
            ffprobe_path, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except Exception:
        return 0


def _detect_hw_encoder() -> str | None:
    """Check for hardware video encoder. Returns encoder name or None."""
    try:
        result = subprocess.run(
            [FFMPEG_PATH, "-encoders"],
            capture_output=True, text=True,
        )
        # macOS: VideoToolbox H.264 (fastest on Apple Silicon)
        if "h264_videotoolbox" in result.stdout:
            return "h264_videotoolbox"
        # Linux: VAAPI or NVENC
        if "h264_vaapi" in result.stdout:
            return "h264_vaapi"
        if "h264_nvenc" in result.stdout:
            return "h264_nvenc"
    except Exception:
        pass
    return None


def srt_to_ass(
    srt_path: Path,
    config: BurnConfig,
    video_width: int,
    video_height: int,
) -> Path:
    """
    Convert SRT to a properly-styled ASS file matched to the video dimensions
    and preview settings, so burned output matches what was shown in preview.

    Scaling:
    - Font: css_font_size * video_width / 900  (900 = preview container max-width)
    - Position: (bottom_pct / 100) * video_height
    """
    from .subtitles import parse_srt

    entries = parse_srt(srt_path)
    ass_path = srt_path.with_suffix('.ass')

    # Font size: CSS preview px → ASS absolute px at PlayResY
    ass_font_size = round(config.font_size * video_width / 900)

    # Position: CSS bottom % → ASS MarginV px
    margin_v = round(config.position_bottom_pct / 100 * video_height)

    # Colors
    primary_color = hex_to_ass_color(config.font_color_hex, alpha=0)
    outline_color = "&H00000000"

    # Background: ASS alpha 0=opaque, 255=transparent
    bg_alpha = round((1.0 - config.bg_opacity / 100) * 255)
    bg_alpha = max(0, min(255, bg_alpha))
    back_color = f"&H{bg_alpha:02X}000000"

    # BorderStyle=3: opaque box with BackColour; Outline = box padding
    # BorderStyle=1: text outline only (no box)
    if config.bg_opacity > 0:
        border_style = 3
        outline_size = max(config.outline, round(ass_font_size * 0.15))
    else:
        border_style = 1
        outline_size = config.outline

    ass_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {video_width}",
        f"PlayResY: {video_height}",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        (
            f"Style: Default,{config.font},{ass_font_size},"
            f"{primary_color},&H000000FF,{outline_color},{back_color},"
            f"0,0,0,0,100,100,0,0,{border_style},{outline_size},0,"
            f"2,10,10,{margin_v},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for entry in entries:
        start = srt_time_to_ass(entry.start_time)
        end = srt_time_to_ass(entry.end_time)
        text = entry.text.replace('{', r'\{').replace('\n', r'\N')
        ass_lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    ass_path.write_text('\n'.join(ass_lines) + '\n', encoding='utf-8')
    return ass_path


def burn_subtitles(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    config: BurnConfig | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> BurnResult:
    """
    Burn subtitles into video using FFmpeg.

    Generates a proper ASS file from the SRT, then encodes with the `ass` filter.
    Progress is reported via callback (0.0–1.0).

    Uses a temp file for -progress output to avoid the classic stdout/stderr
    pipe deadlock that causes ffmpeg to hang.
    """
    if config is None:
        config = BurnConfig()

    if not video_path.exists():
        return BurnResult(False, error=f"Video not found: {video_path}")
    if not srt_path.exists():
        return BurnResult(False, error=f"Subtitle not found: {srt_path}")

    duration = _get_video_duration(video_path)
    video_width, video_height = get_video_dimensions(video_path)

    # Generate ASS file
    ass_path = srt_to_ass(srt_path, config, video_width, video_height)

    # Use a temp file for progress instead of pipe:1 to avoid deadlock
    with tempfile.NamedTemporaryFile(mode='r', suffix='.log', delete=False) as pf:
        progress_file = pf.name

    ass_str = str(ass_path).replace(":", r"\:")
    filter_str = f"ass={ass_str}"

    # Detect hardware encoder availability (macOS VideoToolbox is ~10-20x faster)
    hw_encoder = _detect_hw_encoder()

    cmd = [
        FFMPEG_PATH,
        "-i", str(video_path),
        "-vf", filter_str,
    ]
    if hw_encoder:
        cmd += ["-c:v", hw_encoder, "-q:v", "65"]
    cmd += [
        "-c:a", "copy",
        "-y",
        "-progress", progress_file,
        str(output_path),
    ]

    try:
        # Run ffmpeg — stderr goes to PIPE for error capture, progress to file
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

        # Poll progress file while ffmpeg runs
        import time
        while process.poll() is None:
            try:
                with open(progress_file, 'r') as f:
                    content = f.read()
                # Find the last out_time_ms value
                for line in reversed(content.split('\n')):
                    if line.startswith('out_time_ms='):
                        try:
                            time_ms = int(line.split('=')[1])
                            if duration > 0 and progress_callback:
                                progress = min((time_ms / 1_000_000) / duration, 1.0)
                                progress_callback(progress)
                        except (ValueError, IndexError):
                            pass
                        break
            except (FileNotFoundError, IOError):
                pass
            time.sleep(0.5)

        stderr_output = process.stderr.read()

        # Clean up progress file
        try:
            Path(progress_file).unlink()
        except OSError:
            pass

        if process.returncode != 0:
            return BurnResult(False, error=f"FFmpeg error (code {process.returncode}): {stderr_output[-500:]}")

        if not output_path.exists():
            return BurnResult(False, error="Output file not created")

        if progress_callback:
            progress_callback(1.0)

        return BurnResult(success=True, output_path=output_path)

    except Exception as e:
        try:
            Path(progress_file).unlink()
        except OSError:
            pass
        return BurnResult(False, error=str(e))
