"""Subtitle parsing, writing, and format conversion."""
import re
from pathlib import Path
from dataclasses import dataclass


@dataclass
class SubtitleEntry:
    index: str
    start_time: str
    end_time: str
    text: str
    translation: str | None = None


def parse_srt(srt_path: Path) -> list[SubtitleEntry]:
    """Parse SRT file into list of SubtitleEntry."""
    content = srt_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\n+", content.strip())
    entries = []

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            index = lines[0].strip()
            time_line = lines[1].strip()

            # Parse time
            time_match = re.match(r"(.+?)\s*-->\s*(.+)", time_line)
            if time_match:
                start_time = time_match.group(1).strip()
                end_time = time_match.group(2).strip()
            else:
                continue

            text = " ".join(lines[2:]).strip()
            entries.append(SubtitleEntry(index, start_time, end_time, text))

    return entries


def write_srt(entries: list[SubtitleEntry], path: Path, bilingual: bool = False):
    """Write entries to SRT format."""
    lines = []
    for e in entries:
        if bilingual and e.translation:
            text = f"{e.translation}\n{e.text}"
        elif e.translation:
            text = e.translation
        else:
            text = e.text
        lines.append(f"{e.index}\n{e.start_time} --> {e.end_time}\n{text}\n")

    path.write_text("\n".join(lines), encoding="utf-8")


def srt_to_vtt(srt_path: Path, vtt_path: Path | None = None) -> Path:
    """Convert SRT to WebVTT format for HTML5 video preview."""
    if vtt_path is None:
        vtt_path = srt_path.with_suffix(".vtt")

    content = srt_path.read_text(encoding="utf-8")

    # Replace SRT time format with VTT format (comma -> dot)
    content = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", content)

    # Add VTT header
    vtt_content = "WEBVTT\n\n" + content

    vtt_path.write_text(vtt_content, encoding="utf-8")
    return vtt_path


def extract_chinese_srt(bilingual_path: Path, chinese_path: Path | None = None) -> Path:
    """Extract Chinese-only subtitles from bilingual SRT."""
    if chinese_path is None:
        chinese_path = bilingual_path.with_name(
            bilingual_path.stem.replace(".bilingual", "") + ".cn.srt"
        )

    content = bilingual_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\n+", content.strip())

    chinese_only = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            # First line is index, second is time, third is Chinese
            chinese_only.append(f"{lines[0]}\n{lines[1]}\n{lines[2]}\n")

    chinese_path.write_text("\n".join(chinese_only), encoding="utf-8")
    return chinese_path


def has_chinese(text: str) -> bool:
    """Check if text contains Chinese characters or common Chinese punctuation."""
    # Chinese characters + Chinese punctuation (。，！？、；：""''【】)
    return bool(re.search(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]', text))


def validate_translations(entries: list[SubtitleEntry]) -> tuple[bool, list[int]]:
    """Validate all entries have Chinese translations."""
    missing = []
    for i, e in enumerate(entries):
        if not e.translation or not has_chinese(e.translation):
            missing.append(i)
    return len(missing) == 0, missing


def time_to_ms(time_str: str) -> int:
    """Convert SRT time string to milliseconds."""
    time_str = time_str.replace(',', '.')
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    sec_parts = parts[2].split('.')
    seconds = int(sec_parts[0])
    ms = int(sec_parts[1]) if len(sec_parts) > 1 else 0
    return (hours * 3600 + minutes * 60 + seconds) * 1000 + ms


def ms_to_time(ms: int) -> str:
    """Convert milliseconds to SRT time string."""
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def fix_overlapping_subtitles(entries: list[SubtitleEntry], gap_ms: int = 50) -> list[SubtitleEntry]:
    """
    Fix overlapping subtitle timestamps.
    Ensures each subtitle ends before the next one starts.
    """
    if not entries:
        return entries

    fixed = []
    for i, entry in enumerate(entries):
        start_ms = time_to_ms(entry.start_time)
        end_ms = time_to_ms(entry.end_time)

        # Check if this subtitle overlaps with the next one
        if i < len(entries) - 1:
            next_start_ms = time_to_ms(entries[i + 1].start_time)
            if end_ms > next_start_ms - gap_ms:
                # Trim end time to just before next subtitle starts
                end_ms = next_start_ms - gap_ms

        # Ensure minimum duration of 500ms
        if end_ms - start_ms < 500:
            end_ms = start_ms + 500

        fixed.append(SubtitleEntry(
            index=entry.index,
            start_time=entry.start_time,  # Keep original start
            end_time=ms_to_time(end_ms),   # Fixed end
            text=entry.text,
            translation=entry.translation
        ))

    return fixed
