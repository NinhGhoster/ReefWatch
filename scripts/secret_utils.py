#!/usr/bin/env python3
"""Helpers for loading local env config and checking secret presence safely."""

from __future__ import annotations

import os
from pathlib import Path


PLACEHOLDER_PREFIXES = (
    "your_",
    "replace_",
    "example",
    "changeme",
)

DEFAULT_PLANET_QUALITY = "standard"
VALID_PLANET_QUALITY_VALUES = {"standard", "test"}


def load_dotenv_if_present(base_dir: str | Path) -> Path | None:
    """Load simple KEY=VALUE pairs from a local .env file if present.

    Existing environment variables win over .env values.
    """
    env_path = Path(base_dir) / ".env"
    if not env_path.is_file():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)

    return env_path


def read_local_env_value(base_dir: str | Path, key: str) -> str | None:
    env_path = Path(base_dir) / ".env"
    if not env_path.is_file():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, value = line.split("=", 1)
        if current_key.strip() != key:
            continue
        cleaned = value.strip().strip('"').strip("'")
        return cleaned or None
    return None


def is_placeholder_secret(value: str | None) -> bool:
    if value is None:
        return True
    cleaned = value.strip()
    if not cleaned:
        return True

    lowered = cleaned.lower()
    return any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def get_configured_secret(base_dir: str | Path, key: str) -> str | None:
    load_dotenv_if_present(base_dir)
    env_value = os.environ.get(key)
    if env_value is not None and not is_placeholder_secret(env_value):
        return env_value.strip()

    local_value = read_local_env_value(base_dir, key)
    if local_value is not None and not is_placeholder_secret(local_value):
        return local_value.strip()

    return None


def has_configured_secret(base_dir: str | Path, key: str) -> bool:
    return get_configured_secret(base_dir, key) is not None


def get_validated_env_choice(
    base_dir: str | Path,
    key: str,
    *,
    default: str,
    valid_values: set[str],
) -> str:
    """Return a normalized env/.env choice, falling back to a safe default.

    Existing environment variables win over .env values, matching load order for
    the rest of the repo's config handling.
    """
    load_dotenv_if_present(base_dir)
    raw_value = os.environ.get(key, default)
    value = raw_value.strip().lower() if isinstance(raw_value, str) else default
    if value in valid_values:
        return value
    return default


def get_planet_quality_preference(base_dir: str | Path) -> str:
    """Return the validated Planet quality preference from env/.env."""
    return get_validated_env_choice(
        base_dir,
        "PLANET_QUALITY",
        default=DEFAULT_PLANET_QUALITY,
        valid_values=VALID_PLANET_QUALITY_VALUES,
    )
