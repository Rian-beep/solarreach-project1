"""Compliance helper tests."""

from __future__ import annotations

import os

import pytest

from solarreach_shared.compliance import (
    check_ai_disclosure,
    check_outbound_allowed,
    hash_recipient,
    is_live_outbound_enabled,
    normalise_phone_e164,
    normalise_postcode,
)


def test_hash_recipient_lowercases_and_strips() -> None:
    assert hash_recipient("Foo@Bar.com") == hash_recipient("  foo@bar.com  ")


def test_hash_recipient_is_64_hex_chars() -> None:
    h = hash_recipient("anyone@example.com")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_recipient_empty_returns_empty() -> None:
    assert hash_recipient("") == ""


def test_normalise_postcode_canonical_form() -> None:
    assert normalise_postcode("ec1y8af") == "EC1Y 8AF"
    assert normalise_postcode("EC1Y 8AF") == "EC1Y 8AF"
    assert normalise_postcode("  bs1 4dj  ") == "BS1 4DJ"


def test_normalise_postcode_invalid_returns_none() -> None:
    assert normalise_postcode("not-a-postcode") is None
    assert normalise_postcode("") is None
    assert normalise_postcode("12345") is None


def test_normalise_phone_e164_uk_numbers() -> None:
    # 07700 900123 -> +447700900123
    assert normalise_phone_e164("07700 900123") == "+447700900123"
    # international format kept
    assert normalise_phone_e164("+447700900123") == "+447700900123"
    # double-zero international -> +
    assert normalise_phone_e164("00447700900123") == "+447700900123"


def test_normalise_phone_e164_non_digits_returns_none() -> None:
    assert normalise_phone_e164("") is None
    assert normalise_phone_e164("abc") is None


def test_check_ai_disclosure_pass() -> None:
    prompt = "You are an AI agent calling on behalf of GreenSolar. You must disclose this is an automated call."
    ok, reason = check_ai_disclosure(prompt)
    assert ok is True
    assert reason is None


def test_check_ai_disclosure_missing_ai_token_fails() -> None:
    prompt = "You are a sales agent. Always disclose that this is automated."
    ok, reason = check_ai_disclosure(prompt)
    assert ok is False
    assert "AI" in (reason or "")


def test_check_ai_disclosure_missing_disclosure_token_fails() -> None:
    prompt = "You are an AI assistant who calls leads about solar."
    ok, reason = check_ai_disclosure(prompt)
    assert ok is False
    assert "disclos" in (reason or "")


def test_outbound_blocked_when_live_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOLARREACH_LIVE_OUTBOUND", raising=False)
    allowed, reason = check_outbound_allowed(recipient_hash="abc", suppressed_hashes=set())
    assert allowed is False
    assert reason == "LIVE_OUTBOUND_DISABLED"


def test_outbound_blocked_when_recipient_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLARREACH_LIVE_OUTBOUND", "true")
    allowed, reason = check_outbound_allowed(recipient_hash="abc", suppressed_hashes={"abc"})
    assert allowed is False
    assert reason == "SUPPRESSED"


def test_outbound_allowed_when_live_and_not_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLARREACH_LIVE_OUTBOUND", "true")
    allowed, reason = check_outbound_allowed(recipient_hash="abc", suppressed_hashes={"def"})
    assert allowed is True
    assert reason is None


def test_is_live_outbound_default_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOLARREACH_LIVE_OUTBOUND", raising=False)
    assert is_live_outbound_enabled() is False
