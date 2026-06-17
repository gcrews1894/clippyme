"""Pydantic request schemas for the ClippyMe FastAPI app."""
from typing import List, Optional

from pydantic import BaseModel, Field

# ViralClip / ViralClipsResponse moved to the neutral clippyme.schemas module so
# the pipeline no longer imports from clippyme.api. Re-exported here for
# backward compatibility (existing imports from clippyme.api.schemas keep working).
from clippyme.schemas import ViralClip, ViralClipsResponse  # noqa: F401


class ProcessRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    # Optional per-job knobs — mirror the BatchRequest so single and batch
    # jobs expose the same surface area to the frontend. All three are
    # validated downstream (reframe_mode by argparse choices, language by
    # ALLOWED_LANGUAGES in job_results.build_main_cmd, instructions by
    # length cap).
    instructions: Optional[str] = Field(None, max_length=2000)
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled)$")
    aspect: Optional[str] = Field(None, pattern=r"^(9:16|1:1|16:9)$")
    language: Optional[str] = Field(None, max_length=16)
    no_zoom: Optional[bool] = False
    skip_analysis: Optional[bool] = False


class BatchRequest(BaseModel):
    urls: List[str] = Field(..., min_length=1, max_length=20)
    instructions: Optional[str] = Field(None, max_length=2000)
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled)$")
    aspect: Optional[str] = Field(None, pattern=r"^(9:16|1:1|16:9)$")
    # Optional per-batch ASR language override. When omitted the pipeline
    # uses its default (Deepgram `multi` for EN+IT code-switching). Setting
    # this to a single-language code ("en", "it", "es", …) improves both
    # transcription accuracy AND speaker diarization reliability on audio
    # that isn't actually multilingual.
    language: Optional[str] = Field(None, max_length=16)
    no_zoom: Optional[bool] = False
    skip_analysis: Optional[bool] = False


class ConfigUpdateRequest(BaseModel):
    keys: dict


class ReframeRequest(BaseModel):
    """Switch a clip between reframe modes after it has been generated.

    Only valid when the per-clip 16:9 source slice was preserved on disk
    (i.e. jobs produced after the post-hoc reframe feature landed).
    """
    reframe_mode: Optional[str] = Field(None, pattern=r"^(auto|disabled)$")


class ComposeRequest(BaseModel):
    toggles: dict = {}
    hook_params: dict = {}
    subtitle_params: dict = {}


class PublishRequest(BaseModel):
    """Schedule a clip on social platforms via Zernio.

    schedule_mode:
      - "now"     → publish immediately
      - "auto"    → SmartScheduler picks the next optimal slot
      - "manual"  → caller passes scheduled_for (ISO 8601)

    platforms is a list of {platform, accountId, platformSpecificData?} dicts
    matching Zernio's create-post schema.
    """
    title: str = ""
    caption: str = ""
    platforms: List[dict] = Field(..., min_length=1, max_length=14)
    schedule_mode: str = Field("now", pattern=r"^(now|auto|manual)$")
    scheduled_for: Optional[str] = None
    # Optional YYYY-MM-DD that defines the day the SmartScheduler should
    # start picking slots from when schedule_mode="auto". Ignored by
    # "now" / "manual". Defaults to today if omitted.
    start_date: Optional[str] = None
    timezone: str = "Europe/Rome"
    tiktok_settings: Optional[dict] = None
    # If true, force a fresh compose pass before upload using the supplied
    # toggles. If omitted, the latest composed clip on disk is used.
    compose_first: bool = False
    toggles: Optional[dict] = None
    hook_params: Optional[dict] = None
    subtitle_params: Optional[dict] = None


class ZernioConfigRequest(BaseModel):
    """Persisted Zernio settings (saved to data/config.json)."""
    api_key: Optional[str] = None
    accounts: Optional[dict] = None  # {"tiktok": "...", "instagram": "...", "youtube": "..."}
    timezone: Optional[str] = None
