#!/usr/bin/env python3
"""Validate the derived/ MVP snapshot contract.

This is a lightweight guardrail for the current script-first ReefWatch repo.
It checks that export_mvp_snapshot.py produced the expected files, that key
records contain the fields documented in docs/mvp-data-model-and-screens.md,
and that Planet/source health remains secret-safe.

Usage:
    python3 scripts/export_mvp_snapshot.py
    python3 scripts/validate_mvp_snapshot.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DERIVED_DIR = BASE_DIR / "derived"
ENV_EXAMPLE = BASE_DIR / ".env.example"

REQUIRED_FILES = [
    "features.jsonl",
    "scenes.jsonl",
    "changes.jsonl",
    "traffic.jsonl",
    "notes.jsonl",
    "feature_status.jsonl",
    "review_queue.json",
    "overview.json",
    "source_health.json",
]

FEATURE_REQUIRED_KEYS = {"id", "key", "name", "group", "claimant", "lat", "lon", "priority", "tags"}
FEATURE_STATUS_REQUIRED_KEYS = {"featureId", "featureKey", "name", "priority", "flags", "counts"}
OVERVIEW_REQUIRED_KEYS = {"generatedAt", "counts", "reviewQueue", "featureStatus", "recentScenes", "recentTraffic", "recentNotes"}
SOURCE_HEALTH_REQUIRED_KEYS = {"generatedAt", "features", "sources"}
PLANET_HEALTH_REQUIRED_KEYS = {
    "configured",
    "secretSafe",
    "latestFetchAt",
    "latestSceneAt",
    "sceneCount",
    "recentSceneCount72h",
    "changeCount",
    "pendingChangeCount",
    "status",
}
FORBIDDEN_SECRET_MARKERS = ["api_key", "planet_api_key", "authorization", "basic "]
PLACEHOLDER_PREFIXES = ("your_", "replace_", "example", "changeme")


class ValidationError(Exception):
    pass


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"{path.name}:{line_no} is not valid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValidationError(f"{path.name}:{line_no} must contain JSON objects")
            rows.append(row)
    return rows


def assert_keys(obj: dict[str, Any], required: set[str], label: str) -> None:
    missing = sorted(required - obj.keys())
    if missing:
        raise ValidationError(f"{label} missing keys: {', '.join(missing)}")


def assert_no_secret_strings(value: Any, label: str) -> None:
    lowered = json.dumps(value, ensure_ascii=False).lower()
    for marker in FORBIDDEN_SECRET_MARKERS:
        if marker in lowered:
            raise ValidationError(f"{label} appears to contain secret-like material ({marker})")


def assert_env_example_is_safe(path: Path) -> None:
    if not path.exists():
        raise ValidationError(".env.example is missing")

    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    if "PLANET_API_KEY" not in values:
        raise ValidationError(".env.example must include PLANET_API_KEY")

    api_key = values["PLANET_API_KEY"]
    if not api_key:
        raise ValidationError(".env.example PLANET_API_KEY must use a placeholder value")

    lowered = api_key.lower()
    if not any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES):
        raise ValidationError(
            ".env.example PLANET_API_KEY must stay a placeholder, not a real-looking secret"
        )


def main() -> int:
    assert_env_example_is_safe(ENV_EXAMPLE)

    missing_files = [name for name in REQUIRED_FILES if not (DERIVED_DIR / name).exists()]
    if missing_files:
        raise ValidationError(f"derived/ is missing required files: {', '.join(missing_files)}")

    features = read_jsonl(DERIVED_DIR / "features.jsonl")
    feature_status = read_jsonl(DERIVED_DIR / "feature_status.jsonl")
    scenes = read_jsonl(DERIVED_DIR / "scenes.jsonl")
    changes = read_jsonl(DERIVED_DIR / "changes.jsonl")
    traffic = read_jsonl(DERIVED_DIR / "traffic.jsonl")
    notes = read_jsonl(DERIVED_DIR / "notes.jsonl")
    review_queue = read_json(DERIVED_DIR / "review_queue.json")
    overview = read_json(DERIVED_DIR / "overview.json")
    source_health = read_json(DERIVED_DIR / "source_health.json")

    if not features:
        raise ValidationError("features.jsonl should not be empty")

    assert_keys(features[0], FEATURE_REQUIRED_KEYS, "features[0]")
    assert_keys(feature_status[0], FEATURE_STATUS_REQUIRED_KEYS, "feature_status[0]")
    assert_keys(overview, OVERVIEW_REQUIRED_KEYS, "overview.json")
    assert_keys(source_health, SOURCE_HEALTH_REQUIRED_KEYS, "source_health.json")

    if len(feature_status) != len(features):
        raise ValidationError(
            f"feature_status.jsonl row count ({len(feature_status)}) must match features.jsonl ({len(features)})"
        )

    if not isinstance(review_queue, dict) or "items" not in review_queue:
        raise ValidationError("review_queue.json must be an object with an 'items' array")

    sources = source_health.get("sources")
    if not isinstance(sources, dict) or "planet" not in sources:
        raise ValidationError("source_health.json must include sources.planet")
    assert_keys(sources["planet"], PLANET_HEALTH_REQUIRED_KEYS, "source_health.sources.planet")

    if sources["planet"].get("secretSafe") is not True:
        raise ValidationError("source_health.sources.planet.secretSafe must be true")

    assert_no_secret_strings(source_health, "source_health.json")
    assert_no_secret_strings(overview, "overview.json")
    assert_no_secret_strings(review_queue, "review_queue.json")
    assert_no_secret_strings(changes, "changes.jsonl")

    feature_ids = {row["id"] for row in features}
    for idx, row in enumerate(scenes, start=1):
        feature_id = row.get("featureId")
        if feature_id not in feature_ids:
            raise ValidationError(f"scenes.jsonl row {idx} references unknown featureId {feature_id!r}")
    for idx, row in enumerate(changes, start=1):
        feature_id = row.get("featureId")
        if feature_id not in feature_ids:
            raise ValidationError(f"changes.jsonl row {idx} references unknown featureId {feature_id!r}")
    for idx, row in enumerate(traffic, start=1):
        feature_id = row.get("featureId")
        if feature_id not in feature_ids:
            raise ValidationError(f"traffic.jsonl row {idx} references unknown featureId {feature_id!r}")
    for idx, row in enumerate(notes, start=1):
        feature_id = row.get("featureId")
        if feature_id not in feature_ids:
            raise ValidationError(f"notes.jsonl row {idx} references unknown featureId {feature_id!r}")

    print("MVP snapshot validation passed")
    print(f"- features: {len(features)}")
    print(f"- feature_status: {len(feature_status)}")
    print(f"- scenes: {len(scenes)}")
    print(f"- changes: {len(changes)}")
    print(f"- traffic: {len(traffic)}")
    print(f"- notes: {len(notes)}")
    print(f"- review_queue_items: {len(review_queue.get('items', []))}")
    print(f"- planet_configured: {sources['planet']['configured']}")
    print(f"- env_example_safe: yes")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
