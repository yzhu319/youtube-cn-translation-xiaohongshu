# Real-Time Subtitle Preview Requirements

## Core Requirement
An interactive preview window where users can see the effect of Chinese subtitle overlays on the video **in real time** as they adjust styling parameters.

## User Flow

1. **Input**: Paste YouTube URL, download video + subtitles
2. **Translate**: Run context-aware translation (existing functionality)
3. **Interactive Preview** (NEW):
   - Video player embedded in the app
   - Chinese subtitles rendered as an overlay on top of the video
   - Controls for font size, position, color, outline, etc.
   - **Real-time updates**: When user adjusts any parameter, the subtitle overlay updates immediately without re-encoding
4. **Export**: Once satisfied, burn subtitles into final MP4

## Preview Window Specifications

### Video Player
- Embedded HTML5 video player
- Play/pause, seek, volume controls
- Video plays while user adjusts subtitle settings

### Subtitle Overlay
- Rendered as a CSS/HTML layer on top of the video (not burned in)
- Synced to video playback time
- Shows Chinese translation text

### Real-Time Controls
| Control | Type | Range | Default |
|---------|------|-------|---------|
| Font Size | Slider | 12-48px | 24px |
| Position (from bottom) | Slider | 5%-40% | 15% |
| Font Color | Color picker | - | White |
| Outline/Shadow | Toggle + slider | 0-5px | 2px black |
| Background | Toggle + opacity | 0-100% | 50% black |
| Font Family | Dropdown | PingFang SC, Heiti, etc. | PingFang SC |

### Behavior
- All changes apply **instantly** to the preview (no button click needed)
- Video continues playing during adjustments
- User can seek to any part of the video to check different subtitles
- Current subtitle highlights in a subtitle list panel (optional)

## Technical Approach

### Option A: Pure CSS Overlay (Recommended)
- Parse SRT into JavaScript array with timestamps
- Use `requestAnimationFrame` or `timeupdate` event to sync subtitles
- Render subtitle as absolutely positioned `<div>` over `<video>`
- CSS properties controlled by Streamlit sliders via `st.components.v1.html()`

### Option B: WebVTT with ::cue styling
- Limited styling options
- Browser-dependent rendering
- Not recommended for precise control

## Implementation Notes

1. Video and subtitle data passed to HTML component as base64
2. JavaScript handles subtitle timing synchronization
3. Streamlit sliders update component via `st.session_state`
4. Use `key` parameter to force component re-render on setting change

## Success Criteria
- [ ] Video plays smoothly with subtitle overlay
- [ ] Changing font size updates preview within 100ms
- [ ] Changing position updates preview within 100ms
- [ ] Subtitle timing stays in sync during playback
- [ ] Final burn uses the same settings user previewed
