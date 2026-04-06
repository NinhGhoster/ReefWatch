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
