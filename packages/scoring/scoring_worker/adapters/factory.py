"""Pluggable adapter factory.

Each adapter can be requested in mock or real mode. Default = mock.
Override globally with SOLARREACH_ADAPTER_MODE=real, or per-adapter with
e.g. SOLARREACH_SOLAR_MODE=real.
"""

from __future__ import annotations

import os
from typing import Any

from . import mocks, real

_MOCK_INSTANCES: dict[str, Any] | None = None
_REAL_INSTANCES: dict[str, Any] | None = None


def _resolve_mode(adapter_name: str) -> str:
    per = os.environ.get(f"SOLARREACH_{adapter_name.upper()}_MODE")
    if per:
        return per.strip().lower()
    return os.environ.get("SOLARREACH_ADAPTER_MODE", "mock").strip().lower()


def get_adapter(name: str, *, mode: str | None = None) -> Any:
    """Return the named adapter. mode='mock' or 'real' overrides env."""

    global _MOCK_INSTANCES, _REAL_INSTANCES
    chosen = (mode or _resolve_mode(name)).lower()
    if chosen not in {"mock", "real"}:
        raise ValueError(f"adapter mode must be 'mock' or 'real' (got {chosen!r})")

    if chosen == "mock":
        if _MOCK_INSTANCES is None:
            _MOCK_INSTANCES = mocks.all_mocks()
        if name not in _MOCK_INSTANCES:
            raise KeyError(f"no mock adapter named {name!r}")
        return _MOCK_INSTANCES[name]

    if _REAL_INSTANCES is None:
        _REAL_INSTANCES = real.all_real()
    if name not in _REAL_INSTANCES:
        raise KeyError(f"no real adapter named {name!r}")
    return _REAL_INSTANCES[name]
