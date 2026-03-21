# 小红书 Video Pipeline

This project downloads YouTube videos, adds bilingual (Chinese + English) subtitles, 
and produces videos ready for upload to 小红书.

## Stack
- Python 3, yt-dlp, ffmpeg, anthropic SDK
- Main script: yt_to_xiaohongshu.py

## Workflow
1. yt-dlp downloads video + English auto-subs
2. Claude API translates SRT to Chinese (batched)
3. ffmpeg burns bilingual subs into MP4

## Key Commands
- Process a video: `python yt_to_xiaohongshu.py "YOUTUBE_URL" -o output_name`
- List available subs: `yt-dlp --list-subs "URL"`
- Re-translate only: `python yt_to_xiaohongshu.py "URL" -o name --skip-download`

## 小红书 specs
- MP4, H.264, AAC audio
- 16:9 or 9:16, 1080p preferred
- Upload via app or creator.xiaohongshu.com
