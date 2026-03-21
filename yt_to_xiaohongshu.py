#!/usr/bin/env python3
"""
YouTube → 小红书 Pipeline
Downloads a YouTube video, gets English subtitles, translates to Chinese,
burns bilingual subtitles into the video for sharing on 小红书.

Prerequisites:
    pip install yt-dlp anthropic
    brew install ffmpeg  (or apt install ffmpeg)

Usage:
    python yt_to_xiaohongshu.py "https://www.youtube.com/watch?v=h3AtWdeu_G0"

    # Optional: specify output name
    python yt_to_xiaohongshu.py "URL" --output "bernie_claude_ai"

    # Skip translation if you already have a Chinese SRT
    python yt_to_xiaohongshu.py "URL" --chinese-srt existing_chinese.srt
"""

import subprocess
import sys
import re
import json
import argparse
from pathlib import Path


def download_video_and_subs(url: str, output_dir: Path, name: str) -> tuple[Path, Path]:
    """Download video + English subtitles using yt-dlp."""
    video_out = output_dir / f"{name}.%(ext)s"
    
    cmd = [
        "/Users/yuanzheng/Library/Python/3.11/bin/yt-dlp",
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--merge-output-format", "mp4",
        "--write-auto-subs",
        "--write-subs",
        "--sub-langs", "en",
        "--sub-format", "srt",
        "--convert-subs", "srt",
        "-o", str(video_out),
        url,
    ]
    
    print("📥 Downloading video and subtitles...")
    subprocess.run(cmd, check=True)
    
    # Find the downloaded files
    video_file = next(output_dir.glob(f"{name}.mp4"), None)
    # yt-dlp names subs as name.en.srt
    srt_file = next(output_dir.glob(f"{name}.en.srt"), None)
    
    if not video_file:
        # Sometimes yt-dlp uses a different extension
        video_file = next(output_dir.glob(f"{name}.*"), None)
    
    if not srt_file:
        # Try auto-generated sub naming
        srt_file = next(output_dir.glob(f"{name}*.srt"), None)
    
    if not video_file:
        raise FileNotFoundError("Video download failed")
    if not srt_file:
        raise FileNotFoundError(
            "No English subtitles found. The video may not have captions.\n"
            "Try: yt-dlp --list-subs <URL>  to check available subtitles."
        )
    
    print(f"  ✅ Video: {video_file.name}")
    print(f"  ✅ Subtitles: {srt_file.name}")
    return video_file, srt_file


def parse_srt(srt_path: Path) -> list[dict]:
    """Parse SRT file into list of {index, time, text}."""
    content = srt_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\n+", content.strip())
    entries = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            entries.append({
                "index": lines[0].strip(),
                "time": lines[1].strip(),
                "text": " ".join(lines[2:]).strip(),
            })
    return entries


def write_srt(entries: list[dict], path: Path):
    """Write entries back to SRT format."""
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(f"{e['index']}\n{e['time']}\n{e['text']}\n\n")


def translate_srt_with_gemini(entries: list[dict], output_path: Path, batch_size: int = 40):
    """Translate SRT entries to Chinese using Google Gemini API. Produces bilingual SRT."""
    from google import genai
    import os

    client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))
    model_id = "gemini-2.0-flash"

    bilingual_entries = []
    total = len(entries)

    for i in range(0, total, batch_size):
        batch = entries[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size
        print(f"  🌐 Translating batch {batch_num}/{total_batches}...")

        # Build the text block for translation
        lines_for_translation = []
        for j, e in enumerate(batch):
            lines_for_translation.append(f"[{j}] {e['text']}")

        prompt = (
            "Translate the following English subtitle lines to Simplified Chinese. "
            "Return ONLY a JSON array of strings, one translation per line, "
            "preserving the [index] order. Keep translations concise for subtitles. "
            "Do not include the [index] prefix in the translations.\n\n"
            + "\n".join(lines_for_translation)
        )

        response = client.models.generate_content(model=model_id, contents=prompt)

        response_text = response.text.strip()
        # Extract JSON array from response
        json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
        if json_match:
            translations = json.loads(json_match.group())
        else:
            print(f"    ⚠️  Failed to parse batch {batch_num}, using original text")
            translations = [e["text"] for e in batch]

        # Build bilingual entries: Chinese on top, English below
        for j, e in enumerate(batch):
            cn_text = translations[j] if j < len(translations) else e["text"]
            bilingual_entries.append({
                "index": e["index"],
                "time": e["time"],
                "text": f"{cn_text}\n{e['text']}",
            })

    write_srt(bilingual_entries, output_path)
    print(f"  ✅ Bilingual SRT: {output_path.name}")
    return output_path


def has_chinese(text: str) -> bool:
    """Check if text contains Chinese characters."""
    return bool(re.search(r'[\u4e00-\u9fff]', text))


def translate_batch_with_context(client, model_id: str, batch: list[dict],
                                  context_before: list[dict], context_after: list[dict],
                                  max_retries: int = 3) -> list[str]:
    """
    Translate a batch of subtitle lines with surrounding context.
    Uses marker-based approach to maintain line alignment.
    """
    import time

    # Build context paragraphs
    before_text = " ".join([e['text'] for e in context_before]) if context_before else ""
    after_text = " ".join([e['text'] for e in context_after]) if context_after else ""

    # Build the lines to translate with markers
    lines_with_markers = []
    for i, e in enumerate(batch):
        lines_with_markers.append(f"<{i}>{e['text']}</{i}>")

    prompt = f"""Translate English subtitles to Simplified Chinese for video subtitles.

CONTEXT (for understanding only, do NOT translate):
Before: {before_text}
After: {after_text}

TRANSLATE THESE {len(batch)} LINES (keep the <N></N> markers exactly):
{chr(10).join(lines_with_markers)}

RULES:
1. Keep EXACTLY {len(batch)} translations with markers <0></0>, <1></1>, etc.
2. Understand the FULL context before translating - lines may be fragments of sentences
3. Translate naturally for Chinese viewers - do NOT translate word-by-word
4. Keep translations concise (subtitle length)
5. Output ONLY the translated lines with markers, nothing else"""

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
            response_text = response.choices[0].message.content.strip()

            # Parse translations from markers
            translations = []
            for i in range(len(batch)):
                pattern = f"<{i}>(.*?)</{i}>"
                match = re.search(pattern, response_text, re.DOTALL)
                if match:
                    trans = match.group(1).strip()
                    translations.append(trans)
                else:
                    raise ValueError(f"Missing marker <{i}> in response")

            # Validate all have Chinese
            for i, t in enumerate(translations):
                if not has_chinese(t):
                    raise ValueError(f"Line {i} has no Chinese: {t}")

            return translations

        except Exception as e:
            print(f"      ⚠️ Attempt {attempt + 1}/{max_retries} failed: {str(e)[:100]}")
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                raise RuntimeError(f"Batch translation failed after {max_retries} attempts")


def translate_srt_with_openai(entries: list[dict], output_path: Path, batch_size: int = 12):
    """
    Translate SRT entries to Chinese using context-aware batch translation.
    Each batch is translated with surrounding context for better accuracy.
    """
    from openai import OpenAI
    import os

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    model_id = "gpt-4o-mini"
    context_size = 5  # Lines of context before/after each batch

    bilingual_entries = []
    total = len(entries)
    total_batches = (total + batch_size - 1) // batch_size

    print(f"  🌐 Translating {total} lines in {total_batches} context-aware batches...")

    for i in range(0, total, batch_size):
        batch = entries[i:i + batch_size]
        batch_num = i // batch_size + 1

        # Get context
        context_before = entries[max(0, i - context_size):i]
        context_after = entries[i + len(batch):i + len(batch) + context_size]

        print(f"      Batch {batch_num}/{total_batches} ({len(batch)} lines)...")

        translations = translate_batch_with_context(
            client, model_id, batch, context_before, context_after
        )

        for j, e in enumerate(batch):
            bilingual_entries.append({
                "index": e["index"],
                "time": e["time"],
                "text": f"{translations[j]}\n{e['text']}",
            })

    write_srt(bilingual_entries, output_path)
    print(f"  ✅ Bilingual SRT: {output_path.name} ({total} lines)")
    return output_path


def burn_subtitles(video_path: Path, srt_path: Path, output_path: Path):
    """Burn subtitles into video using ffmpeg. Optimized for 小红书."""

    # Style: white text, slight black outline, readable at phone size
    # FontSize=20 works well for bilingual (2 lines per entry)
    style = (
        "FontName=Arial,FontSize=20,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,Outline=2,Shadow=1,"
        "Alignment=2,MarginV=30"
    )

    # Use absolute path and escape for ffmpeg subtitles filter
    srt_abs = srt_path.resolve()
    # Escape special chars: \ -> /, : -> \:, ' -> \'
    srt_escaped = str(srt_abs).replace("'", "'\\''")

    # Build filter string separately for clarity
    vf_filter = f"subtitles={srt_escaped}:force_style='{style}'"

    cmd = [
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", vf_filter,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    print("🔥 Burning subtitles into video...")
    subprocess.run(cmd, check=True)
    print(f"  ✅ Output: {output_path.name}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="YouTube → 小红书 bilingual subtitle pipeline")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--output", "-o", default=None, help="Output filename (no extension)")
    parser.add_argument("--chinese-srt", default=None, help="Skip translation, use existing Chinese SRT")
    parser.add_argument("--output-dir", default=".", help="Output directory")
    parser.add_argument("--skip-download", action="store_true", help="Skip download (reuse existing files)")
    parser.add_argument("--provider", "-p", choices=["openai", "gemini"], default="openai",
                        help="Translation API provider (default: openai)")
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    name = args.output or "video"
    
    # Step 1: Download
    if args.skip_download:
        video_file = next(output_dir.glob(f"{name}.mp4"), None)
        srt_file = next(output_dir.glob(f"{name}*.srt"), None)
        if not video_file or not srt_file:
            print("❌ Cannot find existing files. Run without --skip-download first.")
            sys.exit(1)
    else:
        video_file, srt_file = download_video_and_subs(args.url, output_dir, name)
    
    # Step 2: Translate
    bilingual_srt = output_dir / f"{name}.bilingual.srt"
    
    if args.chinese_srt:
        # User provided Chinese SRT, merge with English
        cn_entries = parse_srt(Path(args.chinese_srt))
        en_entries = parse_srt(srt_file)
        merged = []
        for cn, en in zip(cn_entries, en_entries):
            merged.append({
                "index": en["index"],
                "time": en["time"],
                "text": f"{cn['text']}\n{en['text']}",
            })
        write_srt(merged, bilingual_srt)
        print(f"  ✅ Merged bilingual SRT: {bilingual_srt.name}")
    else:
        en_entries = parse_srt(srt_file)
        if args.provider == "openai":
            translate_srt_with_openai(en_entries, bilingual_srt)
        else:
            translate_srt_with_gemini(en_entries, bilingual_srt)
    
    # Step 3: Burn subtitles
    final_output = output_dir / f"{name}_小红书.mp4"
    burn_subtitles(video_file, bilingual_srt, final_output)
    
    print(f"\n🎉 Done! Upload this to 小红书: {final_output}")
    print(f"   File size: {final_output.stat().st_size / 1024 / 1024:.1f} MB")
    print("\n💡 Tips for 小红书:")
    print("   - Add a catchy Chinese title + your take on the video")
    print("   - Tag: #AI #人工智能 #BernieSanders #Claude #科技前沿")
    print("   - 小红书 prefers 9:16 vertical, but 16:9 works for commentary videos")


if __name__ == "__main__":
    main()
