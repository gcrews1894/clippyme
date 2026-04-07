"""Persistent configuration loader/saver for ClippyMe."""
import json
import logging
import os

logger = logging.getLogger("clippyme")

DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
VALID_CONFIG_KEYS = ("GEMINI_API_KEY", "GEMINI_MODEL", "YOUTUBE_COOKIES", "HF_TOKEN")


def load_persistent_config() -> dict:
    """Load config from JSON file if exists, falling back to environment variables."""
    config = {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
        "GEMINI_MODEL": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        "YOUTUBE_COOKIES": os.environ.get("YOUTUBE_COOKIES", ""),
        "HF_TOKEN": os.environ.get("HF_TOKEN", ""),
    }

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                persistent = json.load(f)
                filtered = {k: v for k, v in persistent.items() if k in VALID_CONFIG_KEYS}
                config.update(filtered)
        except Exception as e:
            logger.warning("Error loading config.json: %s", e)

    return config


def save_persistent_config(new_config: dict) -> bool:
    """Save new configuration to JSON file and mirror into os.environ."""
    try:
        current: dict = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                current = json.load(f)

        sanitized = {k: new_config.get(k) for k in VALID_CONFIG_KEYS if k in new_config}
        for key, value in sanitized.items():
            if value in (None, ""):
                current.pop(key, None)
                os.environ.pop(key, None)
            else:
                current[key] = value
                os.environ[key] = str(value)

        with open(CONFIG_FILE, "w") as f:
            json.dump(current, f, indent=4)
        return True
    except Exception as e:
        logger.error("Error saving config.json: %s", e)
        return False
