/**
 * Frontend mirror of backend `subtitles.py:SUBTITLE_PRESETS`.
 *
 * These values MUST stay in sync with the Python side. Whenever you change
 * a preset's `fontsize`, `font`, or colors on the backend, update the
 * matching entry here — the SubtitleModal preview scales font sizes relative
 * to `REFERENCE_VIDEO_HEIGHT` so the previewed look stays faithful to the
 * final burned-in output.
 *
 * ClippyMe renders 9:16 clips at 1080 × 1920, and libass's ASS fontsize is
 * in pixels at the video resolution. A fontsize of 40 at 1920 px height
 * means the glyphs are ~40 px tall in the final video. The preview DOM
 * element has a different (typically smaller) height, so we scale:
 *
 *     previewFontPx = preset.fontsize * (renderedVideoHeightPx / 1920)
 *
 * Same scaling applies to `outlineWidth` so stroked fonts stay proportional.
 */

export const REFERENCE_VIDEO_HEIGHT = 1920;

export const SUBTITLE_PRESETS = {
    classic_white: {
        label: 'Classic',
        desc: 'TikTok standard',
        // Mirrors backend
        font: 'Montserrat-Black',
        fontsize: 40,
        textColor: '#FFFFFF',
        highlightColor: '#FFFF00',
        outlineColor: '#000000',
        outlineWidth: 4,
        borderStyle: 1, // 1 = outline, 3 = box/background
        uppercase: true,
    },
    hormozi_bold: {
        label: 'Hormozi',
        desc: 'Motivational',
        font: 'Bangers-Regular',
        fontsize: 43,
        textColor: '#FFFFFF',
        highlightColor: '#00FF00',
        outlineColor: '#000000',
        outlineWidth: 5,
        borderStyle: 1,
        uppercase: true,
    },
    neon_glow: {
        label: 'Neon',
        desc: 'Glow aesthetic',
        font: 'Montserrat-Black',
        fontsize: 40,
        textColor: '#FFFFFF',
        highlightColor: '#00FFFF',
        outlineColor: '#00AAAA',
        outlineWidth: 3,
        borderStyle: 1,
        uppercase: true,
        neonGlow: true, // extra CSS glow in preview to approximate libass shadow
    },
    mrbeast_box: {
        label: 'MrBeast',
        desc: 'Box background',
        font: 'Poppins-Black',
        fontsize: 38,
        textColor: '#FFFFFF',
        highlightColor: '#FFFF00',
        outlineColor: '#000000',
        outlineWidth: 1,
        borderStyle: 3, // box
        uppercase: false,
    },
    minimal_clean: {
        label: 'Minimal',
        desc: 'Clean sans',
        font: 'Poppins-Medium',
        fontsize: 35,
        textColor: '#FFFFFF',
        highlightColor: '#FFFFFF',
        outlineColor: '#000000',
        outlineWidth: 2,
        borderStyle: 1,
        uppercase: false,
    },
    fire_impact: {
        label: 'Fire',
        desc: 'Impact red',
        font: 'Anton-Regular',
        fontsize: 43,
        textColor: '#FFFFFF',
        highlightColor: '#FF4444',
        outlineColor: '#000000',
        outlineWidth: 5,
        borderStyle: 1,
        uppercase: true,
    },
};

/**
 * Scale a backend fontsize (reference 1920 px) to the actual rendered
 * preview video height. Falls back to 0.35× if the height is unknown so the
 * preview never explodes to 0 or huge.
 */
export function scaleFontToPreview(backendFontsize, renderedHeightPx) {
    if (!renderedHeightPx || renderedHeightPx <= 0) {
        return Math.max(10, backendFontsize * 0.35);
    }
    return (backendFontsize * renderedHeightPx) / REFERENCE_VIDEO_HEIGHT;
}

/**
 * Generate a CSS text-shadow string that approximates an libass outline of
 * `width` pixels in `color`. libass draws an 8-way stroke; we replicate with
 * 4 corners + 4 axis-aligned offsets. `width` should already be scaled to
 * the preview.
 */
export function outlineToTextShadow(width, color) {
    if (!width || width <= 0) return 'none';
    const w = width;
    return [
        `-${w}px -${w}px 0 ${color}`,
        `${w}px -${w}px 0 ${color}`,
        `-${w}px ${w}px 0 ${color}`,
        `${w}px ${w}px 0 ${color}`,
        `0 -${w}px 0 ${color}`,
        `0 ${w}px 0 ${color}`,
        `-${w}px 0 0 ${color}`,
        `${w}px 0 0 ${color}`,
    ].join(', ');
}
