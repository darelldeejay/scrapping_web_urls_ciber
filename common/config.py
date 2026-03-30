# common/config.py
# -*- coding: utf-8 -*-
"""
Central configuration management.

All tuneable constants live here so that callers never hard-code values and
environment-variable overrides are documented in a single place.
"""
from __future__ import annotations

import os
import re

# ---------------------------------------------------------------------------
# Browser / Selenium
# ---------------------------------------------------------------------------

#: Default User-Agent string (overridable via SCRAPER_UA env var).
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

#: Seconds to wait for a page to reach ``document.readyState == 'complete'``.
PAGE_LOAD_TIMEOUT: int = 60

#: Seconds to wait for JavaScript execution.
SCRIPT_TIMEOUT: int = 30

#: Seconds for ``wait_for_page`` (readyState complete).
PAGE_READY_TIMEOUT: int = 20

#: Seconds cap for ``go()`` navigation before calling ``window.stop()``.
NAV_TIMEOUT: int = 45

# ---------------------------------------------------------------------------
# HTTP / Notification
# ---------------------------------------------------------------------------

#: Default timeout (seconds) for outbound HTTP requests (statuspage API calls).
HTTP_REQUEST_TIMEOUT: int = 20

#: Timeout (seconds) for Telegram sendMessage requests.
TELEGRAM_SEND_TIMEOUT: int = 30

#: Timeout (seconds) for Teams webhook requests.
TEAMS_SEND_TIMEOUT: int = 30

#: Maximum characters per Telegram message chunk (Telegram hard-limit is 4096).
TELEGRAM_CHUNK_LIMIT: int = 3900

# ---------------------------------------------------------------------------
# Default filesystem paths
# ---------------------------------------------------------------------------

#: Directory where per-vendor JSON exports are written.
VENDORS_OUT_DIR: str = ".github/out/vendors"

#: Base output directory for digest artefacts.
DIGEST_OUT_DIR: str = ".github/out"

#: Directory for dry-run preview output files.
PREVIEW_OUT_DIR: str = ".github/out/preview"

# ---------------------------------------------------------------------------
# Security / Validation
# ---------------------------------------------------------------------------

#: Pattern that a valid vendor slug must fully match.
VALID_SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def get_user_agent() -> str:
    """Return the User-Agent string, honouring the ``SCRAPER_UA`` env var."""
    return os.getenv("SCRAPER_UA") or DEFAULT_USER_AGENT


def is_valid_slug(slug: str) -> bool:
    """Return ``True`` if *slug* is a safe, well-formed vendor identifier."""
    return bool(VALID_SLUG_RE.match(slug))
