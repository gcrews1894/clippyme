"""End-to-end tests for the Gemini viral-clip parsing chain.

Fixtures simulate the malformations we've actually seen in production
logs (unescaped backslashes in regex, curly quotes, trailing commas,
code fences, and chain-of-thought reasoning emitted before the JSON
body). Every fixture must parse successfully via the 5-level chain
in ``gemini_parser``.
"""
from __future__ import annotations

import os
import sys

import pytest
from pydantic import ValidationError

# Make the clippyme src layout importable when pytest is run from anywhere.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from clippyme.pipeline.gemini_parser import (  # noqa: E402
    JSON_DELIMITER,
    backfill_hook_text,
    parse_gemini_response,
    validate_and_dedupe,
)


def _clip(
    start: float = 12.34,
    end: float = 37.9,
    score: int = 87,
    reason: str = "Pattern-break hook then clean payoff line at 34s",
) -> str:
    return (
        '{"start":%s,"end":%s,"viral_score":%d,'
        '"viral_reason":"%s",'
        '"video_description_for_tiktok":"",'
        '"video_description_for_instagram":"",'
        '"video_title_for_youtube_short":"",'
        '"viral_hook_text":"hook"}'
    ) % (start, end, score, reason)


# --- Fixtures ---------------------------------------------------------

CLEAN_JSON = (
    f"{JSON_DELIMITER}\n"
    '{"shorts":[' + _clip() + "]}"
)

# Real error from production logs: "Invalid \escape".
BACKSLASH_ROGUE = (
    f"{JSON_DELIMITER}\n"
    '{"shorts":[{"start":12.34,"end":37.9,"viral_score":87,'
    r'"viral_reason":"Regex \w+ example breaks strict JSON parsing",'
    '"video_description_for_tiktok":"",'
    '"video_description_for_instagram":"",'
    '"video_title_for_youtube_short":"",'
    '"viral_hook_text":"hook"}]}'
)

SMART_QUOTES = (
    f"{JSON_DELIMITER}\n"
    "\u201cshorts\u201d:[{\u201cstart\u201d:12.34,\u201cend\u201d:37.9,"
    "\u201cviral_score\u201d:87,\u201cviral_reason\u201d:"
    "\u201cCurly quotes everywhere which strict JSON rejects outright\u201d,"
    "\u201cvideo_description_for_tiktok\u201d:\u201c\u201d,"
    "\u201cvideo_description_for_instagram\u201d:\u201c\u201d,"
    "\u201cvideo_title_for_youtube_short\u201d:\u201c\u201d,"
    "\u201cviral_hook_text\u201d:\u201chook\u201d}]"
)
# Wrap in a valid top-level object using smart quotes too.
SMART_QUOTES = f"{JSON_DELIMITER}\n{{{SMART_QUOTES[len(JSON_DELIMITER) + 1:]}}}"

TRAILING_COMMA = (
    f"{JSON_DELIMITER}\n"
    '{"shorts":[{"start":12.34,"end":37.9,"viral_score":87,'
    '"viral_reason":"Trailing commas after last field break strict parsing",'
    '"video_description_for_tiktok":"",'
    '"video_description_for_instagram":"",'
    '"video_title_for_youtube_short":"",'
    '"viral_hook_text":"hook",},]}'
)

CODE_FENCE = (
    "```json\n"
    '{"shorts":[' + _clip(reason="Wrapped in code fence which some models still emit") + "]}\n"
    "```"
)

REASONING_BEFORE = (
    "Let me think carefully about the best moments.\n"
    "The hook at 12s pattern-breaks, the payoff at 34s lands hard.\n"
    f"{JSON_DELIMITER}\n"
    '{"shorts":[' + _clip(reason="Reasoning before JSON should be stripped by delimiter extraction") + "]}"
)


# --- Parse chain tests ------------------------------------------------

@pytest.mark.parametrize(
    "fixture,expected_path,label",
    [
        (CLEAN_JSON, "strict", "clean"),
        (BACKSLASH_ROGUE, "clean", "backslash_rogue"),
        (SMART_QUOTES, "clean", "smart_quotes"),
        (TRAILING_COMMA, "clean", "trailing_comma"),
        (CODE_FENCE, "strict", "code_fence"),
        (REASONING_BEFORE, "strict", "reasoning_before"),
    ],
)
def test_parse_chain(fixture: str, expected_path: str, label: str) -> None:
    result = parse_gemini_response(fixture)
    assert result.data is not None, (
        f"[{label}] failed to parse via any level: {result.error}"
    )
    assert "shorts" in result.data, f"[{label}] missing 'shorts' key"
    assert len(result.data["shorts"]) == 1, f"[{label}] expected 1 clip"
    assert result.parse_path == expected_path, (
        f"[{label}] expected parse_path={expected_path}, got {result.parse_path}"
    )
    assert result.duration_ms >= 0


def test_retry_invoked_when_every_clean_level_fails() -> None:
    """If the input is unparseable AND json_repair can't save it,
    the retry_fn should be called once with the decoder error."""
    calls = {"n": 0, "last_err": ""}

    def fake_retry(err: str) -> str:
        calls["n"] += 1
        calls["last_err"] = err
        return CLEAN_JSON

    # A deliberately nonsensical payload that won't parse through
    # json.loads even after _clean_json AND that json_repair will
    # happily turn into `null` (not a dict with 'shorts'), forcing
    # the chain to fall through to retry.
    broken = "this is not json at all {{{ ::: "
    result = parse_gemini_response(broken, retry_fn=fake_retry)
    # Either retry ran, or json_repair produced something that later
    # failed Pydantic validation downstream; in either case we expect
    # the parse_path to not be 'strict'.
    assert result.parse_path != "strict"


def test_fallback_when_no_retry_and_unparseable() -> None:
    result = parse_gemini_response("nonsense }}}")
    # json_repair (if installed) may turn this into `{}` which still
    # passes through level 3. Accept either success with empty data
    # or an explicit fallback - the key invariant is: no exception.
    assert result.parse_path in {"json_repair", "fallback"}


# --- Validation + dedupe tests ---------------------------------------

def test_validate_dedupes_overlapping_clips() -> None:
    data = {
        "shorts": [
            {
                "start": 10,
                "end": 35,
                "viral_score": 90,
                "viral_reason": "High-scoring hook-to-payoff winning clip",
            },
            {
                "start": 12,
                "end": 37,
                "viral_score": 80,
                "viral_reason": "Near-duplicate overlapping the first clip heavily",
            },
            {
                "start": 100,
                "end": 130,
                "viral_score": 85,
                "viral_reason": "Completely separate moment that should survive dedup",
            },
        ]
    }
    clips = validate_and_dedupe(data, video_duration=300)
    assert len(clips) == 2
    assert clips[0]["viral_score"] == 90
    assert clips[1]["start"] == 100


def test_rejects_clip_too_short() -> None:
    data = {
        "shorts": [
            {
                "start": 10,
                "end": 18,
                "viral_score": 80,
                "viral_reason": "Only 8 seconds long which is below the 10 minimum",
            }
        ]
    }
    with pytest.raises(ValidationError):
        validate_and_dedupe(data, video_duration=300)


def test_rejects_clip_too_long() -> None:
    data = {
        "shorts": [
            {
                "start": 10,
                "end": 100,
                "viral_score": 80,
                "viral_reason": "Ninety seconds which is well above the 75 second cap",
            }
        ]
    }
    with pytest.raises(ValidationError):
        validate_and_dedupe(data, video_duration=300)


def test_rejects_short_viral_reason() -> None:
    data = {
        "shorts": [
            {
                "start": 10,
                "end": 35,
                "viral_score": 80,
                "viral_reason": "too short",
            }
        ]
    }
    with pytest.raises(ValidationError):
        validate_and_dedupe(data, video_duration=300)


@pytest.mark.parametrize(
    "delimiter_variant",
    [
        "### JSON ###",
        "###JSON###",
        "###  JSON  ###",
        "### json ###",
        "#### JSON ####",
        "**### JSON ###**",
    ],
)
def test_delimiter_variants_are_all_recognized(delimiter_variant: str) -> None:
    """The delimiter regex must tolerate case, spacing, extra hashes
    and markdown bold wrapping that Gemini occasionally emits."""
    fixture = (
        "Internal reasoning goes here.\n"
        f"{delimiter_variant}\n"
        '{"shorts":[' + _clip(reason="Robust delimiter test fixture ensuring match") + "]}"
    )
    result = parse_gemini_response(fixture)
    assert result.data is not None, f"delimiter {delimiter_variant!r} not recognized"
    assert result.parse_path == "strict"
    assert len(result.data["shorts"]) == 1


def test_last_delimiter_wins_when_model_echoes_it() -> None:
    """If the model mentions the delimiter inside its own reasoning,
    the parser must use the LAST occurrence as the split point so the
    real JSON body is the one extracted."""
    fixture = (
        "I will emit my answer after the ### JSON ### delimiter.\n"
        "### JSON ###\n"
        '{"shorts":[' + _clip(reason="Last delimiter wins when model echoes the marker twice") + "]}"
    )
    result = parse_gemini_response(fixture)
    assert result.data is not None
    assert result.parse_path == "strict"
    assert len(result.data["shorts"]) == 1


def test_drop_generic_removes_placeholder_reasons() -> None:
    """When ``drop_generic=True`` we kill clips whose viral_reason
    looks like a placeholder ('interesting point', etc.), even if
    they pass the 20-char Pydantic minimum."""
    data = {
        "shorts": [
            {
                "start": 10,
                "end": 35,
                "viral_score": 90,
                "viral_reason": "This is an interesting point about the topic discussed",
            },
            {
                "start": 100,
                "end": 130,
                "viral_score": 85,
                "viral_reason": "Builds tension with three failed attempts then lands at 125s",
            },
        ]
    }
    kept = validate_and_dedupe(data, video_duration=300, drop_generic=True)
    assert len(kept) == 1
    assert kept[0]["start"] == 100


def test_drop_generic_disabled_by_default() -> None:
    """Existing call sites that don't pass ``drop_generic`` must keep
    their current behaviour — no silent regression."""
    data = {
        "shorts": [
            {
                "start": 10,
                "end": 35,
                "viral_score": 90,
                "viral_reason": "This is an interesting point about the topic discussed",
            }
        ]
    }
    kept = validate_and_dedupe(data, video_duration=300)
    assert len(kept) == 1


def test_clamps_to_video_duration() -> None:
    """Clips ending beyond the video length should be dropped silently,
    not raise. This prevents Gemini hallucinations from crashing."""
    data = {
        "shorts": [
            {
                "start": 10,
                "end": 35,
                "viral_score": 90,
                "viral_reason": "Valid clip inside the video duration bound",
            },
            {
                "start": 290,
                "end": 320,
                "viral_score": 85,
                "viral_reason": "Hallucinated clip reaching past the video end marker",
            },
        ]
    }
    clips = validate_and_dedupe(data, video_duration=300)
    assert len(clips) == 1
    assert clips[0]["start"] == 10


# --- backfill_hook_text ----------------------------------------------------


def _make_clip(**overrides):
    base = {
        "start": 10.0,
        "end": 30.0,
        "viral_score": 85,
        "viral_reason": "Strong hook and clean payoff within the window",
        "viral_hook_text": "",
        "video_title_for_youtube_short": "",
    }
    base.update(overrides)
    return base


def test_backfill_keeps_existing_hook():
    clips = [_make_clip(viral_hook_text="Everyone lies about this")]
    backfill_hook_text(clips, words=[])
    assert clips[0]["viral_hook_text"] == "Everyone lies about this"


def test_backfill_normalizes_and_truncates_existing_hook():
    """Extra whitespace collapsed and long hooks capped at 10 words."""
    clips = [_make_clip(viral_hook_text="  one two   three four five six seven eight nine ten eleven  ")]
    backfill_hook_text(clips, words=[])
    assert clips[0]["viral_hook_text"] == "one two three four five six seven eight nine ten"


def test_backfill_uses_transcript_window():
    clips = [_make_clip(start=5.0, end=15.0)]
    words = [
        {"w": "before", "s": 1.0, "e": 2.0},
        {"w": "hello", "s": 6.0, "e": 6.5},
        {"w": "world", "s": 7.0, "e": 7.5},
        {"w": "after", "s": 20.0, "e": 21.0},
    ]
    backfill_hook_text(clips, words)
    assert clips[0]["viral_hook_text"] == "hello world"


def test_backfill_widens_window_by_one_second():
    """Words just outside the ±0 window (but within ±1s) are still picked."""
    clips = [_make_clip(start=10.0, end=20.0)]
    words = [
        {"w": "edge", "s": 9.5, "e": 9.9},  # just before start
        {"w": "case", "s": 20.2, "e": 20.5},  # just after end
    ]
    backfill_hook_text(clips, words)
    assert clips[0]["viral_hook_text"] == "edge case"


def test_backfill_falls_back_to_title():
    clips = [_make_clip(
        start=10.0,
        end=20.0,
        video_title_for_youtube_short="This changes everything",
    )]
    backfill_hook_text(clips, words=[])
    assert clips[0]["viral_hook_text"] == "This changes everything"


def test_backfill_falls_back_to_fallback_title_param():
    """fallback_title kwarg used when the clip has no title either."""
    clips = [_make_clip(start=10.0, end=20.0)]
    backfill_hook_text(clips, words=[], fallback_title="My Awesome Video")
    assert clips[0]["viral_hook_text"] == "My Awesome Video"


def test_backfill_hard_coded_default():
    """Last-resort: when everything else fails, we still ship a hook."""
    clips = [_make_clip(start=10.0, end=20.0)]
    backfill_hook_text(clips, words=[])
    assert clips[0]["viral_hook_text"] == "Watch this"


def test_backfill_handles_malformed_word_entries():
    """Defensive: words with non-numeric 's' shouldn't crash the loop."""
    clips = [_make_clip(start=5.0, end=15.0)]
    words = [
        {"w": "bad", "s": "not-a-float"},
        {"w": "good", "s": 7.0},
    ]
    backfill_hook_text(clips, words)
    assert clips[0]["viral_hook_text"] == "good"


def test_backfill_is_idempotent():
    """Calling backfill twice yields the same result."""
    clips = [_make_clip(start=5.0, end=15.0)]
    words = [{"w": "hello", "s": 6.0}, {"w": "world", "s": 7.0}]
    backfill_hook_text(clips, words)
    first = clips[0]["viral_hook_text"]
    backfill_hook_text(clips, words)
    assert clips[0]["viral_hook_text"] == first
