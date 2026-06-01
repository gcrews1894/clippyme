"""Tests for clippyme.integrations.social_publisher.

Covers the two pure, network-free pieces:
- _safe_zernio_base_url() — the SSRF-by-configuration guard on ZERNIO_BASE_URL.
- SmartScheduler.find_slot() — the deterministic (seeded) prime-time slot picker.
"""
import random
from datetime import date, datetime, time

import pytest

from clippyme.integrations import social_publisher as sp
from clippyme.integrations.social_publisher import SmartScheduler


DEFAULT = "https://zernio.com/api/v1"


# --- _safe_zernio_base_url (SSRF guard) ------------------------------------

def test_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("ZERNIO_BASE_URL", raising=False)
    assert sp._safe_zernio_base_url() == DEFAULT


def test_honours_official_https_apex(monkeypatch):
    monkeypatch.setenv("ZERNIO_BASE_URL", "https://zernio.com/api/v2")
    assert sp._safe_zernio_base_url() == "https://zernio.com/api/v2"


def test_honours_official_subdomain(monkeypatch):
    monkeypatch.setenv("ZERNIO_BASE_URL", "https://eu.zernio.com/api/v1")
    assert sp._safe_zernio_base_url() == "https://eu.zernio.com/api/v1"


def test_rejects_non_https_scheme(monkeypatch):
    # http:// to the official host is still rejected — downgrade attack.
    monkeypatch.setenv("ZERNIO_BASE_URL", "http://zernio.com/api/v1")
    assert sp._safe_zernio_base_url() == DEFAULT


def test_rejects_foreign_host(monkeypatch):
    monkeypatch.setenv("ZERNIO_BASE_URL", "https://attacker.example.com/api/v1")
    assert sp._safe_zernio_base_url() == DEFAULT


def test_rejects_lookalike_suffix_host(monkeypatch):
    # 'notzernio.com' must NOT match the '.zernio.com' subdomain rule.
    monkeypatch.setenv("ZERNIO_BASE_URL", "https://evilzernio.com/api/v1")
    assert sp._safe_zernio_base_url() == DEFAULT


def test_empty_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("ZERNIO_BASE_URL", "   ")
    assert sp._safe_zernio_base_url() == DEFAULT


# --- SmartScheduler --------------------------------------------------------

def _scheduler(seed=42):
    return SmartScheduler(rng=random.Random(seed))


def test_find_slot_lands_in_a_prime_time_window():
    day = date(2026, 6, 1)
    s = _scheduler()
    now = datetime.combine(day, time(0, 0))
    slot = s.find_slot(day, occupied=[], now=now)
    assert slot.date() == day
    windows = s._windows_for(day.weekday())
    assert any(w[0] <= slot.hour < w[1] for w in windows), \
        f"hour {slot.hour} not in any window {windows}"


def test_find_slot_is_deterministic_under_same_seed():
    day = date(2026, 6, 1)
    now = datetime.combine(day, time(0, 0))
    a = _scheduler(7).find_slot(day, occupied=[], now=now)
    b = _scheduler(7).find_slot(day, occupied=[], now=now)
    assert a == b


def test_find_slot_is_in_the_future():
    day = date(2026, 6, 1)
    now = datetime.combine(day, time(0, 0))
    slot = _scheduler().find_slot(day, occupied=[], now=now)
    assert slot > now


def test_is_window_free_detects_occupancy():
    day = date(2026, 6, 1)
    s = _scheduler()
    window = (12, 14)
    occupied = [datetime.combine(day, time(13, 0))]
    assert s._is_window_free(day, window, occupied) is False
    assert s._is_window_free(day, (18, 21), occupied) is True


def test_gap_ok_enforces_minimum_gap():
    s = SmartScheduler(rng=random.Random(1), min_gap_seconds=5400)  # 90 min
    base = datetime(2026, 6, 1, 12, 0)
    occupied = [base]
    assert s._gap_ok(base.replace(hour=14), occupied) is True       # 2h away
    assert s._gap_ok(base.replace(minute=30), occupied) is False    # 30 min away
