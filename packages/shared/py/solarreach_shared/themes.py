"""Theme tokens for deck rendering and UI.

CRITICAL: Do NOT name custom colors `base`, `sm`, `lg` — those collide with
Tailwind utility shortcuts and silently make text invisible. We namespace
everything as `app-*` or `gotham-*`.
"""

from __future__ import annotations

from typing import Final

GOTHAM_DARK: Final[dict[str, str]] = {
    "app-bg": "#0B0F19",
    "app-surface": "#111827",
    "app-surface-2": "#1F2937",
    "app-fg": "#F9FAFB",
    "app-fg-muted": "#9CA3AF",
    "app-accent": "#FFD93D",         # signature yellow
    "app-magenta": "#EC4899",        # spend-tracker high-warning
    "app-amber": "#F59E0B",          # spend-tracker mid-warning
    "app-success": "#10B981",
    "app-danger": "#EF4444",
}


GREENSOLAR_BRAND: Final[dict[str, str]] = {
    "primary": "#0E9F6E",   # green
    "accent": "#FFD93D",
    "ink": "#0B0F19",
    "paper": "#FFFFFF",
}


def deck_theme(client_primary: str | None = None, client_accent: str | None = None) -> dict[str, str]:
    """Theme used by codex.deck. Falls back to GREENSOLAR brand."""

    base = dict(GREENSOLAR_BRAND)
    if client_primary:
        base["primary"] = client_primary
    if client_accent:
        base["accent"] = client_accent
    return base
