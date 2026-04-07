"""Compose-on-download pipeline (Smart Cut → Hook → Subtitles).

Extracted from app.py compose_clip endpoint. This module owns the layer
composition logic; the FastAPI endpoint stays a thin wrapper that handles
validation, path resolution and HTTP error mapping.
"""
import asyncio
import os
import shutil
from typing import Any

from fastapi import HTTPException

from smartcut import smart_cut
from subtitles import generate_ass_karaoke, generate_srt, burn_subtitles


_SIZE_MAP = {"S": 0.8, "M": 1.0, "L": 1.3}


async def _apply_smartcut(
    current_input: str, base_clip: str, metadata: dict, clip_info: dict
) -> str:
    smartcut_path = base_clip.replace(".mp4", "_smartcut.mp4")
    if os.path.exists(smartcut_path):
        return smartcut_path
    transcript = metadata.get("transcript", {})
    loop = asyncio.get_event_loop()
    sc_output, _ = await loop.run_in_executor(
        None,
        smart_cut,
        current_input,
        transcript,
        clip_info.get("start", 0),
        clip_info.get("end", 0),
        transcript.get("language"),
    )
    return sc_output or current_input


async def _apply_hook(
    current_input: str,
    job_dir: str,
    clip_index: int,
    hook_params: dict,
    intermediate_files: list,
) -> str:
    from hooks import add_hook_to_video

    hook_output = os.path.join(job_dir, f"composed_hook_{clip_index}.mp4")
    intermediate_files.append(hook_output)
    position = hook_params.get("position", "top")
    font_scale = _SIZE_MAP.get(hook_params.get("size", "M"), 1.0)
    offset_y = hook_params.get("offset_y", 0)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        add_hook_to_video,
        current_input,
        hook_params["text"],
        hook_output,
        position,
        font_scale,
        offset_y,
    )
    return hook_output


async def _apply_subtitles(
    current_input: str,
    job_dir: str,
    clip_index: int,
    metadata: dict,
    clip_info: dict,
    subtitle_params: dict,
    intermediate_files: list,
) -> str:
    sub_output = os.path.join(job_dir, f"composed_sub_{clip_index}.mp4")
    intermediate_files.append(sub_output)
    transcript = metadata.get("transcript", {})
    clip_start = clip_info.get("start", 0)
    clip_end = clip_info.get("end", 0)
    sub_mode = subtitle_params.get("mode", "karaoke")
    sub_offset_y = subtitle_params.get("offset_y", 0)
    loop = asyncio.get_event_loop()

    if sub_mode == "karaoke":
        ass_path = os.path.join(job_dir, f"composed_subs_{clip_index}.ass")
        intermediate_files.append(ass_path)
        success = await loop.run_in_executor(
            None,
            lambda: generate_ass_karaoke(
                transcript,
                clip_start,
                clip_end,
                ass_path,
                preset=subtitle_params.get("preset", "classic_white"),
                mode=subtitle_params.get("display_mode", "word_group"),
                uppercase=subtitle_params.get("uppercase", True),
                highlight_color=subtitle_params.get("highlight_color"),
                font_name=subtitle_params.get("font"),
                font_size=subtitle_params.get("font_size"),
                position=subtitle_params.get("position", "bottom"),
                offset_y=sub_offset_y,
            ),
        )
        if not success:
            raise HTTPException(status_code=400, detail="No words found for this clip range.")
        await loop.run_in_executor(
            None,
            burn_subtitles,
            current_input,
            ass_path,
            sub_output,
            2,
            16,
            "Verdana",
            "#FFFFFF",
            "#000000",
            2,
            "#000000",
            0.0,
            sub_offset_y,
        )
    else:
        srt_path = os.path.join(job_dir, f"composed_subs_{clip_index}.srt")
        intermediate_files.append(srt_path)
        success = await loop.run_in_executor(
            None, generate_srt, transcript, clip_start, clip_end, srt_path
        )
        if not success:
            raise HTTPException(status_code=400, detail="No words found for this clip range.")
        await loop.run_in_executor(
            None,
            lambda: burn_subtitles(
                current_input,
                srt_path,
                sub_output,
                alignment=subtitle_params.get("position", "bottom"),
                fontsize=subtitle_params.get("font_size", 16),
                font_name=subtitle_params.get("font", "Verdana"),
                font_color=subtitle_params.get("font_color", "#FFFFFF"),
                border_color=subtitle_params.get("border_color", "#000000"),
                border_width=subtitle_params.get("border_width", 2),
                bg_color=subtitle_params.get("bg_color", "#000000"),
                bg_opacity=subtitle_params.get("bg_opacity", 0.0),
                offset_y=sub_offset_y,
            ),
        )
    return sub_output


async def compose_layers(
    *,
    base_clip: str,
    job_dir: str,
    clip_index: int,
    metadata: dict,
    clip_info: dict,
    toggles: dict,
    hook_params: dict,
    subtitle_params: dict,
) -> str:
    """Run the active layer pipeline. Returns the final composed filename (basename).

    Cleans up intermediate files on success.
    """
    active = {k: v for k, v in toggles.items() if v}
    if not active:
        return os.path.basename(base_clip)

    current_input = base_clip
    intermediate_files: list[str] = []

    if active.get("smartcut"):
        current_input = await _apply_smartcut(current_input, base_clip, metadata, clip_info)

    if active.get("hook") and hook_params.get("text"):
        current_input = await _apply_hook(
            current_input, job_dir, clip_index, hook_params, intermediate_files
        )

    if active.get("subtitles"):
        current_input = await _apply_subtitles(
            current_input,
            job_dir,
            clip_index,
            metadata,
            clip_info,
            subtitle_params,
            intermediate_files,
        )

    composed_filename = f"composed_clip_{clip_index}.mp4"
    composed_path = os.path.join(job_dir, composed_filename)
    if os.path.abspath(current_input) != os.path.abspath(composed_path):
        shutil.copy2(current_input, composed_path)

    for temp_file in intermediate_files:
        if (
            temp_file
            and os.path.exists(temp_file)
            and os.path.abspath(temp_file) != os.path.abspath(composed_path)
        ):
            try:
                os.remove(temp_file)
            except OSError:
                pass

    return composed_filename
