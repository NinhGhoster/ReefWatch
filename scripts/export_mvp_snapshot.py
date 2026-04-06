#!/usr/bin/env python3
"""Export a normalized MVP snapshot into derived/.

This script bridges the current script-first ReefWatch repo with the app-facing
model described in docs/mvp-data-model-and-screens.md. It intentionally avoids
exposing secret values: source health reports only whether required auth is
configured.

Outputs (all under derived/):
- features.jsonl
- scenes.jsonl
- changes.jsonl
- traffic.jsonl
- notes.jsonl
- overview.json
- source_health.json

Usage:
    python3 scripts/export_mvp_snapshot.py
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
IMAGERY_DIR = BASE_DIR / "imagery_history"
DERIVED_DIR = BASE_DIR / "derived"

TARGET_FEATURES = DATA_DIR / "target_features.json"
PLANET_CHANGES = BASE_DIR / "planet_changes.jsonl"
PLANET_FETCH_LOG = BASE_DIR / "planet_fetch_log.jsonl"
ANALYST_NOTES_LOG = BASE_DIR / "analyst_notes.jsonl"
AIRCRAFT_LOGS = [
    BASE_DIR / "aircraft_detections.jsonl",
    BASE_DIR / "detections.jsonl",
]
SHIP_LOGS = [
    BASE_DIR / "ships_log.jsonl",
]

PRIORITY_1_KEYS = {
    "woody_island",
    "fiery_cross_reef",
    "subi_reef",
    "mischief_reef",
    "thitu_island",
}

SCENE_PATTERN = re.compile(r"^(?P<key>.+?)_(?P<source>planet|sentinel2|modis)_(?P<date>\d{4}-\d{2}-\d{2})\.(?:png|jpg|jpeg|tif|tiff)$")


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def slug_group(group: str) -> str:
    return group.replace("_islands", "")


def derive_priority(feature: dict[str, Any]) -> int:
    if feature["key"] in PRIORITY_1_KEYS:
        return 1
    if feature.get("has_airport") or feature.get("has_helipad"):
        return 2
    return 3


def derive_tags(feature: dict[str, Any]) -> list[str]:
    tags = []
    if feature.get("has_airport"):
        tags.append("airstrip")
    if feature.get("has_helipad"):
        tags.append("helipad")
    if feature["key"].startswith("dk1_"):
        tags.append("platform")
    if any(k in feature["key"] for k in ("reef", "shoal")):
        tags.append("reef")
    if "island" in feature["key"]:
        tags.append("island")
    if feature["key"] in PRIORITY_1_KEYS:
        tags.append("priority_watch")
    return sorted(set(tags))


def export_features() -> list[dict[str, Any]]:
    features = load_json(TARGET_FEATURES, [])
    rows = []
    for feature in features:
        rows.append(
            {
                "id": f"feature:{feature['key']}",
                "key": feature["key"],
                "name": feature["name"],
                "group": slug_group(feature["group"]),
                "claimant": feature["country"],
                "lat": feature["lat"],
                "lon": feature["lon"],
                "priority": derive_priority(feature),
                "tags": derive_tags(feature),
            }
        )
    write_jsonl(DERIVED_DIR / "features.jsonl", rows)
    return rows


def export_scenes(features_by_key: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    if IMAGERY_DIR.exists():
        for path in sorted(IMAGERY_DIR.iterdir()):
            if not path.is_file():
                continue
            match = SCENE_PATTERN.match(path.name)
            if not match:
                continue
            feature_key = match.group("key")
            source = match.group("source")
            captured_date = match.group("date")
            if feature_key not in features_by_key:
                continue
            ext = path.suffix.lower()
            asset_kind = "image"
            if source == "planet":
                asset_kind = "thumbnail"
            resolution = {"planet": 4, "sentinel2": 10, "modis": 250}.get(source)
            rows.append(
                {
                    "id": f"scene:{source}:{feature_key}:{captured_date}",
                    "featureId": f"feature:{feature_key}",
                    "source": source,
                    "providerSceneId": None,
                    "capturedAt": f"{captured_date}T00:00:00Z",
                    "publishedDate": captured_date,
                    "assetKind": asset_kind,
                    "resolutionMeters": resolution,
                    "cloudCover": None,
                    "quality": None,
                    "path": os.path.relpath(path, BASE_DIR),
                    "status": "ready",
                    "format": ext.lstrip("."),
                    "bytes": path.stat().st_size,
                }
            )
    write_jsonl(DERIVED_DIR / "scenes.jsonl", rows)
    return rows


def export_changes(features_by_key: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for raw in load_jsonl(PLANET_CHANGES):
        feature_key = raw.get("feature") or raw.get("feature_key")
        if feature_key not in features_by_key:
            continue
        before_date = raw.get("date1") or raw.get("before_date")
        after_date = raw.get("date2") or raw.get("after_date")
        if not before_date or not after_date:
            continue
        rows.append(
            {
                "id": f"change:{feature_key}:{before_date}:{after_date}",
                "featureId": f"feature:{feature_key}",
                "source": raw.get("source", "planet"),
                "beforeSceneId": f"scene:planet:{feature_key}:{before_date}",
                "afterSceneId": f"scene:planet:{feature_key}:{after_date}",
                "detectedAt": raw.get("timestamp") or now_iso(),
                "classification": raw.get("change_type") or raw.get("classification") or ("significant_change" if raw.get("changed") else "no_material_change"),
                "confidence": raw.get("confidence"),
                "metrics": {
                    "ssim": raw.get("ssim"),
                    "pixelDiffPct": raw.get("pixel_diff_pct"),
                    "brightnessChangePct": raw.get("brightness_change_pct"),
                },
                "reviewStatus": "pending" if raw.get("changed") else "dismissed",
                "raw": {k: v for k, v in raw.items() if k not in {"api_key", "PLANET_API_KEY"}},
            }
        )
    write_jsonl(DERIVED_DIR / "changes.jsonl", rows)
    return rows


def make_observation_id(domain: str, feature_key: str, captured_at: str, suffix: str) -> str:
    return f"obs:{domain}:{feature_key}:{captured_at}:{suffix}".replace(" ", "_")


def normalize_aircraft_row(raw: dict[str, Any], features_by_key: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    feature_key = raw.get("feature") or raw.get("feature_key") or raw.get("location")
    if feature_key not in features_by_key:
        return None
    captured_at = raw.get("timestamp") or raw.get("time") or now_iso()
    identity = {
        "icao24": raw.get("icao24") or raw.get("icao"),
        "callsign": raw.get("callsign"),
    }
    position = {
        "lat": raw.get("lat") or raw.get("latitude"),
        "lon": raw.get("lon") or raw.get("longitude"),
        "altitudeM": raw.get("altitude_m") or raw.get("altitude"),
        "speedMps": raw.get("velocity") or raw.get("speed_mps"),
    }
    suffix = identity["icao24"] or identity["callsign"] or "unknown"
    return {
        "id": make_observation_id("aircraft", feature_key, captured_at, str(suffix)),
        "featureId": f"feature:{feature_key}",
        "domain": "aircraft",
        "source": raw.get("source", "opensky"),
        "capturedAt": captured_at,
        "identity": identity,
        "position": position,
        "distanceKm": raw.get("distance_km"),
        "reviewStatus": "raw",
    }


def normalize_ship_row(raw: dict[str, Any], features_by_key: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    feature_key = raw.get("feature") or raw.get("feature_key")
    if feature_key not in features_by_key:
        return None
    captured_at = raw.get("timestamp") or raw.get("time") or now_iso()
    identity = {
        "mmsi": raw.get("mmsi"),
        "name": raw.get("name") or raw.get("ship_name"),
        "imo": raw.get("imo"),
    }
    suffix = identity["mmsi"] or identity["imo"] or identity["name"] or "unknown"
    return {
        "id": make_observation_id("vessel", feature_key, captured_at, str(suffix)),
        "featureId": f"feature:{feature_key}",
        "domain": "vessel",
        "source": raw.get("source", "ais"),
        "capturedAt": captured_at,
        "identity": identity,
        "position": {
            "lat": raw.get("lat") or raw.get("latitude"),
            "lon": raw.get("lon") or raw.get("longitude"),
        },
        "distanceKm": raw.get("distance_km"),
        "reviewStatus": "raw",
    }


def export_traffic(features_by_key: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for path in AIRCRAFT_LOGS:
        for raw in load_jsonl(path):
            normalized = normalize_aircraft_row(raw, features_by_key)
            if normalized:
                rows.append(normalized)
    for path in SHIP_LOGS:
        for raw in load_jsonl(path):
            normalized = normalize_ship_row(raw, features_by_key)
            if normalized:
                rows.append(normalized)
    rows.sort(key=lambda row: row.get("capturedAt", ""), reverse=True)
    write_jsonl(DERIVED_DIR / "traffic.jsonl", rows)
    return rows


def export_notes(features_by_key: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for idx, raw in enumerate(load_jsonl(ANALYST_NOTES_LOG), start=1):
        feature_key = raw.get("feature") or raw.get("feature_key")
        if feature_key not in features_by_key:
            continue
        created_at = raw.get("createdAt") or raw.get("timestamp") or now_iso()
        rows.append(
            {
                "id": raw.get("id") or f"note:{feature_key}:{created_at}:{idx:02d}",
                "featureId": f"feature:{feature_key}",
                "createdAt": created_at,
                "author": raw.get("author", "analyst"),
                "kind": raw.get("kind", "assessment"),
                "text": raw.get("text") or raw.get("note") or "",
                "source": raw.get("source", "manual"),
                "relatedChangeId": raw.get("relatedChangeId") or raw.get("related_change_id"),
            }
        )
    rows.sort(key=lambda row: row.get("createdAt", ""), reverse=True)
    write_jsonl(DERIVED_DIR / "notes.jsonl", rows)
    return rows


def export_overview(
    features: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    changes: list[dict[str, Any]],
    traffic: list[dict[str, Any]],
    notes: list[dict[str, Any]],
) -> dict[str, Any]:
    recent_scenes = sorted(scenes, key=lambda row: row.get("capturedAt", ""), reverse=True)[:10]
    pending_changes = [row for row in changes if row.get("reviewStatus") == "pending"]
    recent_traffic = traffic[:10]
    payload = {
        "generatedAt": now_iso(),
        "counts": {
            "features": len(features),
            "priority1Features": sum(1 for feature in features if feature["priority"] == 1),
            "scenes": len(scenes),
            "changes": len(changes),
            "pendingChanges": len(pending_changes),
            "trafficObservations": len(traffic),
            "notes": len(notes),
        },
        "reviewQueue": pending_changes[:10],
        "recentScenes": recent_scenes,
        "recentTraffic": recent_traffic,
        "recentNotes": notes[:10],
    }
    write_json(DERIVED_DIR / "overview.json", payload)
    return payload


def export_source_health(
    features: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    changes: list[dict[str, Any]],
    traffic: list[dict[str, Any]],
) -> dict[str, Any]:
    source_counts = Counter(scene["source"] for scene in scenes)
    planet_key_present = bool(os.environ.get("PLANET_API_KEY", "").strip())
    payload = {
        "generatedAt": now_iso(),
        "features": {
            "total": len(features),
            "priority1": sum(1 for feature in features if feature["priority"] == 1),
        },
        "sources": {
            "planet": {
                "configured": planet_key_present,
                "secretSafe": True,
                "latestFetchAt": latest_timestamp(load_jsonl(PLANET_FETCH_LOG)),
                "sceneCount": source_counts.get("planet", 0),
                "changeCount": len(changes),
                "status": "ready" if planet_key_present else "missing_config",
            },
            "sentinel2": {
                "configured": True,
                "secretSafe": True,
                "sceneCount": source_counts.get("sentinel2", 0),
                "status": "ready",
            },
            "modis": {
                "configured": True,
                "secretSafe": True,
                "sceneCount": source_counts.get("modis", 0),
                "status": "ready",
            },
            "traffic": {
                "configured": True,
                "secretSafe": True,
                "observationCount": len(traffic),
                "status": "ready",
            },
        },
    }
    write_json(DERIVED_DIR / "source_health.json", payload)
    return payload


def latest_timestamp(rows: list[dict[str, Any]]) -> str | None:
    stamps = [row.get("timestamp") or row.get("time") for row in rows if row.get("timestamp") or row.get("time")]
    if not stamps:
        return None
    return sorted(stamps)[-1]


def main() -> None:
    features = export_features()
    features_by_key = {feature["key"]: feature for feature in features}
    scenes = export_scenes(features_by_key)
    changes = export_changes(features_by_key)
    traffic = export_traffic(features_by_key)
    notes = export_notes(features_by_key)
    overview = export_overview(features, scenes, changes, traffic, notes)
    health = export_source_health(features, scenes, changes, traffic)

    print("Exported MVP snapshot:")
    print(f"- features: {len(features)}")
    print(f"- scenes: {len(scenes)}")
    print(f"- changes: {len(changes)}")
    print(f"- traffic observations: {len(traffic)}")
    print(f"- notes: {len(notes)}")
    print(f"- pending review: {overview['counts']['pendingChanges']}")
    print(f"- planet configured: {health['sources']['planet']['configured']}")
    print(f"- output dir: {DERIVED_DIR}")


if __name__ == "__main__":
    main()
