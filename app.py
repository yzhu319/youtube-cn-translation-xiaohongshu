"""Streamlit app for YouTube to Xiaohongshu video processing with real-time preview."""
import streamlit as st
import time
import base64
import uuid
import json
from pathlib import Path

from config import (
    DATA_DIR, DEFAULT_FONT_SIZE, DEFAULT_MARGIN_V,
    DEFAULT_BATCH_SIZE, DEFAULT_CONTEXT_SIZE
)
from core import (
    download_video, translate_subtitles, parse_srt, write_srt,
    srt_to_vtt, burn_subtitles_async, get_burn_status, BurnConfig,
    fix_overlapping_subtitles
)

st.set_page_config(
    page_title="YouTube to Xiaohongshu",
    page_icon="🎬",
    layout="wide"
)

# Initialize session state
if "step" not in st.session_state:
    st.session_state.step = "input"
if "video_path" not in st.session_state:
    st.session_state.video_path = None
if "srt_path" not in st.session_state:
    st.session_state.srt_path = None
if "entries" not in st.session_state:
    st.session_state.entries = None
if "translated" not in st.session_state:
    st.session_state.translated = False
if "vtt_path" not in st.session_state:
    st.session_state.vtt_path = None
if "burn_job_id" not in st.session_state:
    st.session_state.burn_job_id = None
if "project_dir" not in st.session_state:
    st.session_state.project_dir = None
if "cn_srt_path" not in st.session_state:
    st.session_state.cn_srt_path = None


def reset_state():
    """Reset all state for new video."""
    st.session_state.step = "input"
    st.session_state.video_path = None
    st.session_state.srt_path = None
    st.session_state.entries = None
    st.session_state.translated = False
    st.session_state.vtt_path = None
    st.session_state.burn_job_id = None
    st.session_state.project_dir = None
    st.session_state.cn_srt_path = None


def parse_srt_time_to_seconds(time_str: str) -> float:
    """Convert SRT time format to seconds."""
    # Handle both comma and dot as decimal separator
    time_str = time_str.replace(',', '.')
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def get_realtime_preview_html(
    video_path: Path,
    entries: list,
    font_size: int,
    position_bottom: int,
    font_color: str,
    bg_opacity: int,
    outline_size: int,
    font_family: str
) -> str:
    """Generate HTML for real-time subtitle preview with CSS overlay."""
    video_data = base64.b64encode(video_path.read_bytes()).decode()

    # Convert entries to JSON for JavaScript
    subtitles_data = []
    for e in entries:
        if e.translation:
            subtitles_data.append({
                "start": parse_srt_time_to_seconds(e.start_time),
                "end": parse_srt_time_to_seconds(e.end_time),
                "text": e.translation
            })

    subtitles_json = json.dumps(subtitles_data, ensure_ascii=False)

    # Convert hex color to CSS
    bg_rgba = f"rgba(0, 0, 0, {bg_opacity / 100})"

    return f'''
<!DOCTYPE html>
<html>
<head>
<style>
    * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}
    .player-container {{
        position: relative;
        width: 100%;
        max-width: 900px;
        margin: 0 auto;
        background: #000;
    }}
    video {{
        width: 100%;
        display: block;
    }}
    .subtitle-overlay {{
        position: absolute;
        left: 0;
        right: 0;
        bottom: {position_bottom}%;
        text-align: center;
        pointer-events: none;
        padding: 0 20px;
    }}
    .subtitle-text {{
        display: inline-block;
        padding: 8px 16px;
        background: {bg_rgba};
        color: {font_color};
        font-size: {font_size}px;
        font-family: "{font_family}", "PingFang SC", "Microsoft YaHei", "Heiti SC", sans-serif;
        text-shadow:
            -{outline_size}px -{outline_size}px 0 #000,
            {outline_size}px -{outline_size}px 0 #000,
            -{outline_size}px {outline_size}px 0 #000,
            {outline_size}px {outline_size}px 0 #000;
        border-radius: 4px;
        max-width: 90%;
        line-height: 1.4;
    }}
    .controls-info {{
        position: absolute;
        top: 10px;
        right: 10px;
        background: rgba(0,0,0,0.7);
        color: #fff;
        padding: 5px 10px;
        font-size: 12px;
        border-radius: 4px;
        font-family: monospace;
    }}
</style>
</head>
<body>
<div class="player-container">
    <video id="video" controls>
        <source src="data:video/mp4;base64,{video_data}" type="video/mp4">
    </video>
    <div class="subtitle-overlay">
        <span id="subtitle" class="subtitle-text"></span>
    </div>
    <div class="controls-info">
        Font: {font_size}px | Position: {position_bottom}% | Outline: {outline_size}px
    </div>
</div>

<script>
const subtitles = {subtitles_json};
const video = document.getElementById('video');
const subtitleEl = document.getElementById('subtitle');

function updateSubtitle() {{
    const currentTime = video.currentTime;
    let currentSub = null;

    for (const sub of subtitles) {{
        if (currentTime >= sub.start && currentTime <= sub.end) {{
            currentSub = sub;
            break;
        }}
    }}

    if (currentSub) {{
        subtitleEl.textContent = currentSub.text;
        subtitleEl.style.display = 'inline-block';
    }} else {{
        subtitleEl.style.display = 'none';
    }}
}}

video.addEventListener('timeupdate', updateSubtitle);
video.addEventListener('seeked', updateSubtitle);

// Initial update
updateSubtitle();
</script>
</body>
</html>
'''


# Main content
st.title("YouTube to Xiaohongshu Converter")

# Step 1: Input URL
if st.session_state.step == "input":
    st.header("Step 1: Enter YouTube URL")

    url = st.text_input(
        "YouTube URL",
        placeholder="https://www.youtube.com/watch?v=...",
        key="url_input"
    )

    output_name = st.text_input(
        "Output Name (optional)",
        placeholder="Leave blank for auto-generated name",
        key="output_name"
    )

    # Check if download already exists
    existing_download = None
    if output_name:
        check_dir = DATA_DIR / output_name
        video_file = check_dir / "video.mp4"
        srt_file = check_dir / "video.en.srt"
        if video_file.exists() and srt_file.exists():
            existing_download = (video_file, srt_file, check_dir)

    if existing_download:
        st.success(f"Existing download found in `{output_name}/`")
        col_use, col_redownload = st.columns(2)
        with col_use:
            if st.button("Use Existing Download", type="primary", use_container_width=True):
                st.session_state.video_path = existing_download[0]
                st.session_state.srt_path = existing_download[1]
                st.session_state.project_dir = existing_download[2]
                st.session_state.step = "translate"
                st.rerun()
        with col_redownload:
            do_download = st.button("Re-download", use_container_width=True)
    else:
        do_download = st.button("Download Video", type="primary", disabled=not url)

    if do_download and url:
        with st.spinner("Downloading video and subtitles..."):
            result = download_video(url, output_name or None)

            if result.success:
                st.session_state.video_path = result.video_path
                st.session_state.srt_path = result.srt_path
                st.session_state.project_dir = result.video_path.parent
                st.session_state.step = "translate"
                st.success(f"Downloaded: {result.title or 'Video'}")
                st.rerun()
            else:
                st.error(f"Download failed: {result.error}")

# Step 2: Translate
elif st.session_state.step == "translate":
    st.header("Step 2: Translate Subtitles")

    col1, col2 = st.columns(2)
    with col1:
        st.info(f"Video: {st.session_state.video_path.name}")
    with col2:
        st.info(f"Subtitles: {st.session_state.srt_path.name}")

    # Parse subtitles
    if st.session_state.entries is None:
        st.session_state.entries = parse_srt(st.session_state.srt_path)

    st.write(f"Found **{len(st.session_state.entries)}** subtitle entries")

    # Check if translated subtitles already exist (use correct path format)
    srt_dir = st.session_state.srt_path.parent
    base_name = st.session_state.srt_path.stem.replace(".en", "")
    cn_srt_path = srt_dir / f"{base_name}.cn.srt"
    bilingual_srt_path = srt_dir / f"{base_name}.bilingual.srt"
    existing_translation = cn_srt_path.exists() or bilingual_srt_path.exists()

    if existing_translation:
        st.success(f"Existing translation found: `{cn_srt_path.name}`")
        col_skip, col_redo = st.columns(2)
        with col_skip:
            if st.button("Use Existing Translation", type="primary", use_container_width=True):
                # Load existing Chinese subtitles
                if cn_srt_path.exists():
                    cn_entries = parse_srt(cn_srt_path)
                    # Merge translations into entries
                    for i, e in enumerate(st.session_state.entries):
                        if i < len(cn_entries):
                            e.translation = cn_entries[i].text
                    st.session_state.cn_srt_path = cn_srt_path
                st.session_state.translated = True
                st.session_state.step = "preview"
                st.rerun()
        with col_redo:
            redo_translation = st.button("Re-translate (API call)", use_container_width=True)
    else:
        redo_translation = True  # No existing translation, must translate

    # Translation info
    num_lines = len(st.session_state.entries)
    num_chunks = (num_lines + 19) // 20  # 20 lines per chunk

    st.caption(f"Will analyze transcript, then translate in {num_chunks} chunks of ~20 lines each")

    # Show sample with timestamps
    with st.expander("Preview Original Subtitles (first 10)"):
        for e in st.session_state.entries[:10]:
            st.text(f"[{e.start_time} --> {e.end_time}] {e.text}")

    if existing_translation:
        start_button = redo_translation and st.button("Start Translation", type="secondary")
    else:
        start_button = st.button("Start Translation", type="primary")

    if start_button:
        progress_bar = st.progress(0)
        status_text = st.empty()

        def update_progress(batch_num, total_batches, message):
            progress = batch_num / total_batches
            progress_bar.progress(progress)
            status_text.text(message)

        result = translate_subtitles(
            st.session_state.entries,
            progress_callback=update_progress,
        )

        if result.success:
            st.session_state.entries = result.entries
            st.session_state.translated = True

            # Fix overlapping timestamps (common in YouTube auto-captions)
            st.session_state.entries = fix_overlapping_subtitles(st.session_state.entries)

            # Create proper output paths (handle video.en.srt -> video.cn.srt)
            srt_dir = st.session_state.srt_path.parent
            base_name = st.session_state.srt_path.stem.replace(".en", "")  # video.en -> video

            bilingual_path = srt_dir / f"{base_name}.bilingual.srt"
            cn_path = srt_dir / f"{base_name}.cn.srt"

            # Save bilingual SRT
            write_srt(st.session_state.entries, bilingual_path, bilingual=True)

            # Save Chinese-only SRT
            write_srt(st.session_state.entries, cn_path, bilingual=False)

            # Store the cn_path for burning
            st.session_state.cn_srt_path = cn_path

            progress_bar.progress(1.0)
            status_text.text("Translation complete!")
            st.session_state.step = "preview"
            time.sleep(0.5)
            st.rerun()
        else:
            st.error(f"Translation failed: {result.error}")

# Step 3: Real-Time Preview
elif st.session_state.step == "preview":
    st.header("Step 3: Real-Time Preview")
    st.caption("Adjust settings in the sidebar - preview updates instantly!")

    # Sidebar controls for real-time adjustment
    with st.sidebar:
        st.header("Subtitle Styling")
        st.caption("Changes apply instantly to preview")

        st.subheader("Font")
        font_size = st.slider("Font Size (px)", 16, 48, 28, key="font_size")
        font_family = st.selectbox(
            "Font Family",
            ["PingFang SC", "Heiti SC", "STHeiti", "Microsoft YaHei", "SimHei"],
            key="font_family"
        )
        font_color = st.color_picker("Font Color", "#FFFFFF", key="font_color")

        st.subheader("Position & Style")
        position_bottom = st.slider("Position from Bottom (%)", 5, 40, 12, key="position")
        outline_size = st.slider("Outline Size (px)", 0, 5, 2, key="outline")
        bg_opacity = st.slider("Background Opacity (%)", 0, 100, 60, key="bg_opacity")

        st.divider()
        if st.button("Start New Video", use_container_width=True):
            reset_state()
            st.rerun()

    # Real-time video preview
    preview_html = get_realtime_preview_html(
        st.session_state.video_path,
        st.session_state.entries,
        font_size,
        position_bottom,
        font_color,
        bg_opacity,
        outline_size,
        font_family
    )

    st.components.v1.html(preview_html, height=550, scrolling=False)

    # Show current settings summary
    st.info(f"Current: **{font_size}px** {font_family} | Position: **{position_bottom}%** from bottom | Outline: **{outline_size}px**")

    # Show translated samples
    with st.expander("View All Translations"):
        for i, e in enumerate(st.session_state.entries):
            if e.translation:
                st.markdown(f"**{e.index}** [{e.start_time}]: {e.translation}")
                st.caption(f"Original: {e.text}")
                if i < len(st.session_state.entries) - 1:
                    st.divider()

    # Action buttons
    col1, col2 = st.columns(2)

    with col1:
        st.write("")  # Spacer

    with col2:
        if st.button("Proceed to Burn Subtitles", type="primary", use_container_width=True):
            # Store current settings for burn
            # Scale font size: CSS px to ASS (ASS uses ~1.5x for similar visual at 1080p)
            # Scale position: CSS bottom % to ASS MarginV (rough: % * 5-6 for 1080p)
            st.session_state.burn_settings = {
                "font_size": int(font_size * 0.9),  # ASS font slightly smaller for same look
                "margin_v": int(position_bottom * 5.5),  # Convert % to ASS margin pixels
                "outline": outline_size,
            }
            st.session_state.step = "burn"
            st.rerun()

# Step 4: Burn
elif st.session_state.step == "burn":
    st.header("Step 4: Burn Subtitles into Video")

    # Get settings from preview or use defaults
    burn_settings = st.session_state.get("burn_settings", {
        "font_size": DEFAULT_FONT_SIZE,
        "margin_v": DEFAULT_MARGIN_V,
        "outline": 2,
    })

    st.info(
        "This process encodes the subtitles permanently into the video. "
        "This takes a few minutes depending on video length."
    )

    # Output path
    output_path = st.session_state.project_dir / "output_xiaohongshu.mp4"

    # Use stored cn_srt_path or construct it
    if hasattr(st.session_state, 'cn_srt_path') and st.session_state.cn_srt_path:
        cn_srt = st.session_state.cn_srt_path
    else:
        srt_dir = st.session_state.srt_path.parent
        base_name = st.session_state.srt_path.stem.replace(".en", "")
        cn_srt = srt_dir / f"{base_name}.cn.srt"

    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Input:** {st.session_state.video_path.name}")
        st.write(f"**Subtitles:** {cn_srt.name}")
    with col2:
        st.write(f"**Output:** {output_path.name}")
        st.write(f"**Font Size:** {burn_settings['font_size']}px")
        st.write(f"**Margin:** {burn_settings['margin_v']}")

    # Sidebar minimal during burn
    with st.sidebar:
        st.header("Burning...")
        if st.button("Start New Video", use_container_width=True):
            reset_state()
            st.rerun()

    # Start burn if not already started
    if st.session_state.burn_job_id is None:
        if st.button("Start Burning Process", type="primary"):
            job_id = str(uuid.uuid4())[:8]
            st.session_state.burn_job_id = job_id

            config = BurnConfig(
                font_size=burn_settings["font_size"],
                margin_v=burn_settings["margin_v"],
                outline=burn_settings["outline"],
            )

            burn_subtitles_async(
                job_id,
                st.session_state.video_path,
                cn_srt,
                output_path,
                config,
            )
            st.rerun()
    else:
        # Show progress
        status = get_burn_status(st.session_state.burn_job_id)

        if status["status"] == "burning":
            progress = status.get("progress", 0)
            st.progress(progress)
            st.write(f"Burning... {progress*100:.1f}%")
            time.sleep(1)
            st.rerun()

        elif status["status"] == "complete":
            st.success("Burn complete!")
            st.balloons()

            output_path = Path(status["output_path"])
            st.write(f"Output saved to: `{output_path}`")

            # Download button
            with open(output_path, "rb") as f:
                st.download_button(
                    "Download Video",
                    f,
                    file_name=output_path.name,
                    mime="video/mp4",
                    type="primary",
                )

            st.session_state.step = "done"

        elif status["status"] == "failed":
            st.error(f"Burn failed: {status.get('error', 'Unknown error')}")
            st.session_state.burn_job_id = None

        else:
            st.write(f"Status: {status['status']}")
            time.sleep(1)
            st.rerun()

# Step 5: Done
elif st.session_state.step == "done":
    st.header("Complete!")

    st.success("Your video is ready for Xiaohongshu!")

    output_path = st.session_state.project_dir / "output_xiaohongshu.mp4"

    # Sidebar
    with st.sidebar:
        st.header("Done!")
        if st.button("Process Another Video", use_container_width=True, type="primary"):
            reset_state()
            st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Output Files")
        st.write(f"- Video: `{output_path}`")
        st.write(f"- Chinese SRT: `{st.session_state.srt_path.with_suffix('.cn.srt')}`")
        st.write(f"- Bilingual SRT: `{st.session_state.srt_path.with_suffix('.bilingual.srt')}`")

    with col2:
        if output_path.exists():
            with open(output_path, "rb") as f:
                st.download_button(
                    "Download Video",
                    f,
                    file_name=output_path.name,
                    mime="video/mp4",
                    type="primary",
                    use_container_width=True,
                )

    if st.button("Process Another Video"):
        reset_state()
        st.rerun()
