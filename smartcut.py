"""
Smart Cut — Remove dead silences and filler words from video clips.

Two-stage pipeline:
1. **Filler-word + transcript-gap pass** (this module)
   - Reads Whisper word-level timestamps
   - Drops filler words ("ehm", "uhm", "like", ...)  in 5 languages
   - Drops gaps > SILENCE_THRESHOLD between words
   - Renders the cuts via auto-editor's v3 JSON timeline (frame-accurate,
     single-pass) — falls back to FFmpeg concat demuxer if auto-editor
     isn't installed.
2. **Audio-loudness polish pass**
   - Runs auto-editor with `--edit audio:threshold=0.04` on the result of
     stage 1 to catch silences the transcript missed (low mumble, music
     gaps, ambient quiet). Skipped silently if auto-editor is unavailable.

Public API (unchanged): smart_cut(clip_path, transcript, clip_start, clip_end, language)
"""

import logging
import os
import json
import shutil
import subprocess
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)


# Filler words by language (lowercase, stripped of punctuation)
FILLER_WORDS = {
    "it": {"ehm", "uhm", "eh", "ah", "mhm", "cioe", "cioè", "tipo", "praticamente",
           "diciamo", "insomma", "ecco", "allora", "niente", "vabbè", "vabbe"},
    "en": {"um", "uh", "uh huh", "like", "you know", "basically", "actually",
           "so yeah", "i mean", "right", "well", "anyway"},
    "es": {"ehm", "pues", "bueno", "o sea", "tipo", "digamos", "este"},
    "fr": {"euh", "ben", "genre", "en fait", "du coup", "voilà", "bah"},
    "de": {"ähm", "also", "halt", "sozusagen", "quasi", "na ja"},
}

DEFAULT_LANG = "en"

# Gaps longer than this between words are considered "dead silence"
SILENCE_THRESHOLD = 0.8

# Minimum silence kept around the cut (one breath, avoids whiplash edits)
SILENCE_KEEP = 0.3

# Audio polish pass: amplitude threshold under which audio is considered silent.
# 0.04 ≈ -28 dB. Conservative — won't touch normal speech, only true quiet.
# Tunable via env var without rebuilding the image.
AUDIO_POLISH_THRESHOLD = os.environ.get("AE_AUDIO_THRESHOLD", "0.04")
AUDIO_POLISH_MARGIN = os.environ.get("AE_MARGIN", "0.2sec")

# Hard cap on any single auto-editor invocation. Prevents a frozen binary
# from blocking a worker forever. 5 minutes is generous for typical clips.
SUBPROCESS_TIMEOUT_SECONDS = int(os.environ.get("AE_TIMEOUT_SECONDS", "300"))

# If stage 1 already shaved off this much, skip the audio polish pass —
# the clip is probably already tight and the polish won't earn its overhead.
SKIP_POLISH_IF_SAVED_OVER = float(os.environ.get("AE_SKIP_POLISH_THRESHOLD", "8.0"))


# ---------------------------------------------------------------------------
# Subprocess + probe helpers (cached)
# ---------------------------------------------------------------------------

# In-process cache for video probe results, keyed by (path, size, mtime).
# Smartcut + audio polish pass + compose pipeline can otherwise probe the
# same source 3-4 times for a single download.
_PROBE_CACHE: dict[tuple, dict] = {}

# Cache for `auto-editor --version` output. Refreshed when the binary
# changes (auto_editor_updater swaps a new file in).
_AE_VERSION_CACHE: dict[str, Optional[str]] = {}


def _run(cmd: list[str], *, timeout: Optional[int] = None) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr).

    Wraps subprocess.run with a uniform timeout, captured streams, and
    string decoding so callers don't repeat the boilerplate everywhere.
    """
    try:
        r = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout if timeout is not None else SUBPROCESS_TIMEOUT_SECONDS,
        )
        return r.returncode, r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")
    except subprocess.TimeoutExpired as e:
        logger.warning("subprocess timed out: %s", " ".join(cmd[:3]))
        return -1, "", f"timeout after {e.timeout}s"
    except FileNotFoundError as e:
        return -1, "", f"command not found: {e.filename}"


# ---------------------------------------------------------------------------
# Stage 1A — analyze the transcript
# ---------------------------------------------------------------------------

def analyze_silences(transcript, clip_start, clip_end, language=None):
    """
    Inspect word timestamps and produce a list of (start, end) segments to KEEP,
    expressed in seconds relative to `clip_start`. Identical to the legacy
    behaviour — auto-editor only enters at the rendering stage.
    """
    lang = (language or DEFAULT_LANG).lower()[:2]
    fillers = FILLER_WORDS.get(lang, FILLER_WORDS[DEFAULT_LANG])

    words = []
    for segment in transcript.get('segments', []):
        for word_info in segment.get('words', []):
            if word_info['end'] > clip_start and word_info['start'] < clip_end:
                words.append({
                    'word': word_info['word'].strip(),
                    'start': max(0, word_info['start'] - clip_start),
                    'end': max(0, word_info['end'] - clip_start),
                })

    if not words:
        return [], {"error": "No words found in clip range"}

    clip_duration = clip_end - clip_start
    segments_to_keep = []
    removed_silences = 0
    removed_fillers = 0
    silence_time_saved = 0.0

    current_start = 0.0

    for i, word in enumerate(words):
        is_filler = word['word'].lower().strip('.,!?') in fillers

        if is_filler:
            if current_start < word['start']:
                segments_to_keep.append((current_start, word['start']))
            current_start = word['end']
            removed_fillers += 1
            continue

        if i > 0:
            prev_end = words[i - 1]['end']
            gap = word['start'] - prev_end
            if gap > SILENCE_THRESHOLD:
                segments_to_keep.append((current_start, prev_end + SILENCE_KEEP))
                current_start = max(0, word['start'] - 0.05)
                removed_silences += 1
                silence_time_saved += gap - SILENCE_KEEP

    if words:
        segments_to_keep.append((current_start, min(clip_duration, words[-1]['end'] + 0.2)))

    # Merge near-touching segments (gap < 0.1s)
    merged = []
    for seg in segments_to_keep:
        if merged and seg[0] - merged[-1][1] < 0.1:
            merged[-1] = (merged[-1][0], seg[1])
        else:
            merged.append(seg)

    new_duration = sum(end - start for start, end in merged)
    stats = {
        "original_duration": round(clip_duration, 1),
        "new_duration": round(new_duration, 1),
        "time_saved": round(clip_duration - new_duration, 1),
        "silences_removed": removed_silences,
        "fillers_removed": removed_fillers,
        "segments": len(merged),
    }
    return merged, stats


# ---------------------------------------------------------------------------
# Stage 1B — auto-editor v3 JSON renderer (replaces FFmpeg concat)
# ---------------------------------------------------------------------------

def _has_auto_editor() -> bool:
    """True if the `auto-editor` binary is on PATH."""
    return shutil.which("auto-editor") is not None


def _auto_editor_version() -> Optional[str]:
    """Return the cached output of `auto-editor --version`. Cached per-binary
    path so a runtime swap by the updater is picked up next call.
    """
    binary = shutil.which("auto-editor")
    if not binary:
        return None
    cache_key = f"{binary}:{os.path.getmtime(binary) if os.path.exists(binary) else 0}"
    if cache_key in _AE_VERSION_CACHE:
        return _AE_VERSION_CACHE[cache_key]
    rc, out, _ = _run([binary, "--version"], timeout=10)
    version = out.strip().split()[-1] if (rc == 0 and out.strip()) else None
    _AE_VERSION_CACHE[cache_key] = version
    return version


def _probe_video(clip_path: str) -> dict | None:
    """Probe a video file for fps, resolution, and audio sample rate.
    Cached per (path, size, mtime).

    Returns a dict with keys: fps_num, fps_den, width, height, samplerate.
    Returns None on failure (caller should fall back).
    """
    try:
        st = os.stat(clip_path)
        cache_key = (os.path.abspath(clip_path), st.st_size, st.st_mtime)
    except OSError:
        return None
    cached = _PROBE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    rc, out, _ = _run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-of", "json",
        clip_path,
    ], timeout=15)
    if rc != 0:
        return None
    try:
        v = json.loads(out)["streams"][0]
        fps_str = v["r_frame_rate"]
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps_num, fps_den = int(num), int(den)
        else:
            fps_num, fps_den = int(float(fps_str) * 1000), 1000
        width, height = int(v["width"]), int(v["height"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None

    rc, out, _ = _run([
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate",
        "-of", "json",
        clip_path,
    ], timeout=15)
    samplerate = 48000
    if rc == 0:
        try:
            a_streams = json.loads(out).get("streams", [])
            if a_streams:
                samplerate = int(a_streams[0]["sample_rate"])
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    result = {
        "fps_num": fps_num,
        "fps_den": fps_den,
        "width": width,
        "height": height,
        "samplerate": samplerate,
    }
    _PROBE_CACHE[cache_key] = result
    # Bound the cache so it doesn't leak memory in long-running workers.
    if len(_PROBE_CACHE) > 256:
        _PROBE_CACHE.pop(next(iter(_PROBE_CACHE)))
    return result


def _build_v3_timeline(
    clip_path: str,
    segments: list[tuple[float, float]],
    probe: dict,
) -> dict:
    """Build an auto-editor v3 timeline JSON for the given keep-segments.

    Schema confirmed against auto-editor src/exports/json.nim and
    src/imports/json.nim. All numeric fields are in *frames* (timebase units).
    """
    fps = probe["fps_num"] / probe["fps_den"]
    abs_src = os.path.abspath(clip_path)

    video_clips: list[dict] = []
    audio_clips: list[dict] = []
    out_pos = 0  # cumulative output frame position

    for seg_start_sec, seg_end_sec in segments:
        start_f = int(round(seg_start_sec * fps))
        dur_f = int(round((seg_end_sec - seg_start_sec) * fps))
        if dur_f <= 0:
            continue
        clip_obj_v = {
            "name": "video",
            "src": abs_src,
            "start": out_pos,
            "dur": dur_f,
            "offset": start_f,
            "stream": 0,
        }
        clip_obj_a = {**clip_obj_v, "name": "audio"}
        video_clips.append(clip_obj_v)
        audio_clips.append(clip_obj_a)
        out_pos += dur_f

    return {
        "version": "3",
        "timebase": f"{probe['fps_num']}/{probe['fps_den']}",
        "background": "#000000",
        "resolution": [probe["width"], probe["height"]],
        "samplerate": probe["samplerate"],
        "layout": "stereo",
        "langs": ["und"],
        "v": [video_clips],
        "a": [audio_clips],
    }


def _render_with_auto_editor(
    clip_path: str,
    segments: list[tuple[float, float]],
    output_path: str,
) -> bool:
    """Render the keep-segments via auto-editor v3 JSON timeline.

    Returns True on success, False on any failure (caller should fall back to
    the legacy FFmpeg concat path).
    """
    probe = _probe_video(clip_path)
    if probe is None:
        return False

    timeline = _build_v3_timeline(clip_path, segments, probe)
    if not timeline["v"][0]:
        return False

    tmp_dir = tempfile.mkdtemp(prefix="ae_v3_")
    timeline_path = os.path.join(tmp_dir, "plan.json")
    try:
        with open(timeline_path, "w") as f:
            json.dump(timeline, f)

        rc, _, stderr = _run(
            ["auto-editor", timeline_path, "-o", output_path, "--no-open"]
        )
        ok = rc == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0
        if not ok:
            logger.warning("auto-editor render failed (rc=%s): %s", rc, stderr.strip()[:300])
        return ok
    except Exception as e:
        logger.warning("auto-editor render exception: %s", e)
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stage 1C — legacy FFmpeg concat fallback (used if auto-editor is missing)
# ---------------------------------------------------------------------------

def _render_with_ffmpeg(
    clip_path: str,
    segments: list[tuple[float, float]],
    output_path: str,
) -> bool:
    """Original FFmpeg concat-demuxer renderer. Slower (N re-encodes + concat)
    but has zero external deps beyond ffmpeg, so it's the safe fallback.
    """
    temp_dir = tempfile.mkdtemp(prefix="smartcut_")
    try:
        segment_files = []
        for i, (start, end) in enumerate(segments):
            seg_path = os.path.join(temp_dir, f"seg_{i:03d}.mp4")
            rc, _, _ = _run([
                "ffmpeg", "-y",
                "-ss", str(start), "-to", str(end),
                "-i", clip_path,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac",
                "-avoid_negative_ts", "make_zero",
                seg_path,
            ])
            if rc == 0 and os.path.exists(seg_path):
                segment_files.append(seg_path)

        if len(segment_files) < 2:
            return False

        concat_list = os.path.join(temp_dir, "concat.txt")
        with open(concat_list, "w") as f:
            for seg_path in segment_files:
                f.write(f"file '{seg_path.replace(chr(92), '/')}'\n")

        rc, _, stderr = _run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac",
            "-pix_fmt", "yuv420p",
            output_path,
        ])
        if rc != 0:
            logger.warning("ffmpeg concat fallback failed: %s", stderr.strip()[:300])
        return rc == 0 and os.path.exists(output_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stage 2 — audio-loudness polish pass via auto-editor
# ---------------------------------------------------------------------------

def _audio_polish_pass(input_path: str) -> tuple[str, float]:
    """Run auto-editor in audio-threshold mode on `input_path` to remove
    silences the transcript missed.

    Returns (output_path, seconds_saved). If the polish step is unavailable
    or doesn't reduce duration meaningfully, returns (input_path, 0.0) so the
    caller can keep the stage-1 output.
    """
    if not _has_auto_editor():
        return input_path, 0.0

    polished_path = input_path.replace(".mp4", "_polished.mp4")
    rc, _, stderr = _run([
        "auto-editor", input_path,
        "--edit", f"audio:threshold={AUDIO_POLISH_THRESHOLD}",
        "--margin", AUDIO_POLISH_MARGIN,
        "--no-open",
        "-o", polished_path,
    ], timeout=min(SUBPROCESS_TIMEOUT_SECONDS, 180))

    if rc != 0 or not os.path.exists(polished_path):
        if rc != 0:
            logger.info("audio polish skipped (rc=%s): %s", rc, stderr.strip()[:200])
        return input_path, 0.0

    in_dur = _probe_duration(input_path)
    out_dur = _probe_duration(polished_path)
    saved = (in_dur - out_dur) if (in_dur and out_dur) else 0.0

    if saved < 0.5:
        try:
            os.remove(polished_path)
        except OSError:
            pass
        return input_path, 0.0

    try:
        os.remove(input_path)
    except OSError:
        pass
    os.rename(polished_path, input_path)
    return input_path, saved


def _probe_duration(path: str) -> float:
    rc, out, _ = _run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ], timeout=10)
    if rc != 0:
        return 0.0
    try:
        return float(out.strip())
    except (ValueError, AttributeError):
        return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def smart_cut(clip_path, transcript, clip_start, clip_end, language=None):
    """Generate a tighter version of `clip_path` by removing silences and fillers.

    Pipeline:
      1. analyze_silences()  →  list of keep-segments (transcript-based)
      2. _render_with_auto_editor()  →  v3 timeline render (frame-accurate)
         · falls back to _render_with_ffmpeg() if auto-editor isn't available
      3. _audio_polish_pass()  →  optional second pass that catches silences
         the transcript missed (skipped silently if auto-editor missing)

    Returns:
        (output_path, stats)  on success
        (None, stats)         on no-op or failure
    """
    segments, stats = analyze_silences(transcript, clip_start, clip_end, language)

    if not segments or len(segments) < 2:
        stats["skipped"] = True
        return None, stats
    if stats["time_saved"] < 1.0:
        stats["skipped"] = True
        return None, stats

    output_path = os.path.splitext(clip_path)[0] + "_smartcut.mp4"
    if os.path.exists(output_path):
        os.remove(output_path)

    use_ae = _has_auto_editor()
    stage1_ok = False
    if use_ae:
        stage1_ok = _render_with_auto_editor(clip_path, segments, output_path)
        if stage1_ok:
            stats["renderer"] = "auto-editor-v3"
            ver = _auto_editor_version()
            if ver:
                stats["renderer_version"] = ver
        else:
            logger.warning("auto-editor v3 render failed, falling back to FFmpeg concat")

    if not stage1_ok:
        stage1_ok = _render_with_ffmpeg(clip_path, segments, output_path)
        if stage1_ok:
            stats["renderer"] = "ffmpeg-concat"

    if not stage1_ok:
        stats["error"] = "render failed (both auto-editor and ffmpeg)"
        return None, stats

    # Stage 2 — audio polish pass (best effort, never fatal).
    # Skip when stage 1 already shaved off plenty: extra invocation overhead
    # rarely earns more than a second on already-tight clips.
    if stats["time_saved"] >= SKIP_POLISH_IF_SAVED_OVER:
        logger.info(
            "skipping audio polish: stage-1 already saved %.1fs (threshold %.1fs)",
            stats["time_saved"], SKIP_POLISH_IF_SAVED_OVER,
        )
        polish_saved = 0.0
    else:
        _, polish_saved = _audio_polish_pass(output_path)

    if polish_saved > 0:
        stats["audio_polish_saved"] = round(polish_saved, 1)
        stats["new_duration"] = round(_probe_duration(output_path), 1)
        stats["time_saved"] = round(stats["original_duration"] - stats["new_duration"], 1)

    msg_parts = [
        f"✂️  Smart Cut: {stats['original_duration']}s → {stats['new_duration']}s",
        f"(-{stats['time_saved']}s, {stats['silences_removed']} silences,",
        f"{stats['fillers_removed']} fillers",
    ]
    if "audio_polish_saved" in stats:
        msg_parts.append(f", audio polish -{stats['audio_polish_saved']}s")
    msg_parts.append(f", renderer={stats.get('renderer', '?')}")
    if "renderer_version" in stats:
        msg_parts.append(f" v{stats['renderer_version']}")
    msg_parts.append(")")
    logger.info(" ".join(msg_parts))

    return output_path, stats
