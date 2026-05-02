"""Compliance helpers: PII hashing for audit, suppression-list checks, PECR.

Hard rules baked in:
- Audit log NEVER stores raw email/phone — only sha256 hex hash.
- All outbound is blocked unless SOLARREACH_LIVE_OUTBOUND=true AND recipient
  passes the suppression check.
- Voice agent system prompt MUST contain "AI" + "disclos" tokens at boot
  (PECR + ICO emerging guidance) — see check_ai_disclosure().
"""

from __future__ import annotations

import hashlib
import os
import re

# ---------------------------------------------------------------------------
# Recipient hashing — used by audit log
# ---------------------------------------------------------------------------
def hash_recipient(value: str) -> str:
    """Lowercase + strip + sha256 hex. Stable across runs and services."""

    if not value:
        return ""
    normalised = value.strip().lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# UK postcode + phone normalisation (for suppression list lookup)
# ---------------------------------------------------------------------------
_POSTCODE_RE = re.compile(r"^([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})$", re.IGNORECASE)


def normalise_postcode(pc: str) -> str | None:
    """'ec1y8af' -> 'EC1Y 8AF'. Returns None if not a valid format."""

    if not pc:
        return None
    m = _POSTCODE_RE.match(pc.strip())
    if not m:
        return None
    return f"{m.group(1).upper()} {m.group(2).upper()}"


def normalise_phone_e164(phone: str, default_country: str = "44") -> str | None:
    """Strip non-digits, add +country if missing. Crude — enough for hashing."""

    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = default_country + digits[1:]
    elif not digits.startswith(default_country):
        digits = default_country + digits
    return f"+{digits}"


# ---------------------------------------------------------------------------
# Outbound gate — read by voice + email send paths
# ---------------------------------------------------------------------------
def is_live_outbound_enabled() -> bool:
    """Reads SOLARREACH_LIVE_OUTBOUND env. Default: False."""

    return os.environ.get("SOLARREACH_LIVE_OUTBOUND", "false").strip().lower() in {"1", "true", "yes"}


def check_outbound_allowed(*, recipient_hash: str, suppressed_hashes: set[str]) -> tuple[bool, str | None]:
    """Returns (allowed, reason_if_blocked).

    Blocks if LIVE_OUTBOUND not enabled OR recipient is on the suppression list."""

    if not is_live_outbound_enabled():
        return False, "LIVE_OUTBOUND_DISABLED"
    if recipient_hash in suppressed_hashes:
        return False, "SUPPRESSED"
    return True, None


# ---------------------------------------------------------------------------
# Voice agent disclosure — PECR + emerging ICO AI guidance
# ---------------------------------------------------------------------------
_AI_TOKEN_RE = re.compile(r"\bAI\b|\bartificial intelligence\b", re.IGNORECASE)
_DISCLOSE_TOKEN_RE = re.compile(r"\bdisclos\w*\b|\bautomated\b", re.IGNORECASE)


def check_ai_disclosure(system_prompt: str) -> tuple[bool, str | None]:
    """Returns (ok, reason_if_failing). Voice service hard-fails boot on bad."""

    if not _AI_TOKEN_RE.search(system_prompt):
        return False, "system prompt missing 'AI' / 'artificial intelligence' token"
    if not _DISCLOSE_TOKEN_RE.search(system_prompt):
        return False, "system prompt missing disclosure token (e.g. 'disclose', 'automated')"
    return True, None
