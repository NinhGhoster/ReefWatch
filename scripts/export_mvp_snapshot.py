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
- feature_status.jsonl
- review_queue.json
- overview.json
- source_health.json

Usage:
    python3 scripts/export_mvp_snapshot.py
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from secret_utils import has_configured_secret

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
RECENT_SCENE_WINDOW = timedelta(hours=72)
RECENT_TRAFFIC_WINDOW = timedelta(hours=24)
SECRET_KEY_MARKERS = (
    "api_key",
    "planet_api_key",
    "authorization",
    "auth",
    "token",
    "password",
    "secret",
)
SECRET_VALUE_MARKERS = (
    "basic ",
    "bearer ",
)


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_iso() -> str:
    return now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def is_recent(value: str | None, window: timedelta) -> bool:
    parsed = parse_timestamp(value)
    if not parsed:
        return False
    return parsed >= now_utc() - window


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


def sanitize_secret_safe(value: Any, key_hint: str | None = None) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            lowered = key.lower()
            if any(marker in lowered for marker in SECRET_KEY_MARKERS):
                continue
            cleaned[key] = sanitize_secret_safe(child, key_hint=key)
        return cleaned

    if isinstance(value, list):
        return [sanitize_secret_safe(item, key_hint=key_hint) for item in value]

    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SECRET_VALUE_MARKERS):
            return "[redacted]"
        if key_hint and any(marker in key_hint.lower() for marker in SECRET_KEY_MARKERS):
            return "[redacted]"
        return value

    return value


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
                "raw": sanitize_secret_safe(raw),
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


def export_feature_status(
    features: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    changes: list[dict[str, Any]],
    traffic: list[dict[str, Any]],
    notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    latest_scene_by_feature: dict[str, dict[str, Any]] = {}
    scene_count_by_feature: defaultdict[str, int] = defaultdict(int)
    recent_scene_count_by_feature: defaultdict[str, int] = defaultdict(int)
    has_recent_planet_by_feature: defaultdict[str, bool] = defaultdict(bool)
    for scene in sorted(scenes, key=lambda row: row.get("capturedAt", ""), reverse=True):
        feature_id = scene["featureId"]
        if feature_id not in latest_scene_by_feature:
            latest_scene_by_feature[feature_id] = scene
        scene_count_by_feature[feature_id] += 1
        if is_recent(scene.get("capturedAt"), RECENT_SCENE_WINDOW):
            recent_scene_count_by_feature[feature_id] += 1
            if scene.get("source") == "planet":
                has_recent_planet_by_feature[feature_id] = True

    latest_change_by_feature: dict[str, dict[str, Any]] = {}
    pending_change_count_by_feature: defaultdict[str, int] = defaultdict(int)
    for change in sorted(changes, key=lambda row: row.get("detectedAt", ""), reverse=True):
        feature_id = change["featureId"]
        if feature_id not in latest_change_by_feature:
            latest_change_by_feature[feature_id] = change
        if change.get("reviewStatus") == "pending":
            pending_change_count_by_feature[feature_id] += 1

    latest_traffic_by_feature: dict[str, dict[str, Any]] = {}
    traffic_count_by_feature: defaultdict[str, int] = defaultdict(int)
    recent_traffic_count_by_feature: defaultdict[str, int] = defaultdict(int)
    for observation in sorted(traffic, key=lambda row: row.get("capturedAt", ""), reverse=True):
        feature_id = observation["featureId"]
        if feature_id not in latest_traffic_by_feature:
            latest_traffic_by_feature[feature_id] = observation
        traffic_count_by_feature[feature_id] += 1
        if is_recent(observation.get("capturedAt"), RECENT_TRAFFIC_WINDOW):
            recent_traffic_count_by_feature[feature_id] += 1

    latest_note_by_feature: dict[str, dict[str, Any]] = {}
    for note in sorted(notes, key=lambda row: row.get("createdAt", ""), reverse=True):
        feature_id = note["featureId"]
        if feature_id not in latest_note_by_feature:
            latest_note_by_feature[feature_id] = note

    rows = []
    for feature in sorted(features, key=lambda row: (row["priority"], row["name"])):
        feature_id = feature["id"]
        latest_scene = latest_scene_by_feature.get(feature_id)
        latest_change = latest_change_by_feature.get(feature_id)
        latest_observation = latest_traffic_by_feature.get(feature_id)
        latest_note = latest_note_by_feature.get(feature_id)
        rows.append(
            {
                "featureId": feature_id,
                "featureKey": feature["key"],
                "name": feature["name"],
                "group": feature["group"],
                "claimant": feature["claimant"],
                "priority": feature["priority"],
                "tags": feature["tags"],
                "latestScene": {
                    "capturedAt": latest_scene.get("capturedAt") if latest_scene else None,
                    "source": latest_scene.get("source") if latest_scene else None,
                    "sceneId": latest_scene.get("id") if latest_scene else None,
                },
                "latestChange": {
                    "detectedAt": latest_change.get("detectedAt") if latest_change else None,
                    "classification": latest_change.get("classification") if latest_change else None,
                    "reviewStatus": latest_change.get("reviewStatus") if latest_change else None,
                    "changeId": latest_change.get("id") if latest_change else None,
                },
                "latestTraffic": {
                    "capturedAt": latest_observation.get("capturedAt") if latest_observation else None,
                    "domain": latest_observation.get("domain") if latest_observation else None,
                    "source": latest_observation.get("source") if latest_observation else None,
                    "observationId": latest_observation.get("id") if latest_observation else None,
                },
                "latestNote": {
                    "createdAt": latest_note.get("createdAt") if latest_note else None,
                    "kind": latest_note.get("kind") if latest_note else None,
                    "noteId": latest_note.get("id") if latest_note else None,
                },
                "flags": {
                    "hasPendingReview": pending_change_count_by_feature[feature_id] > 0,
                    "hasRecentPlanetImagery": has_recent_planet_by_feature[feature_id],
                    "hasTraffic": recent_traffic_count_by_feature[feature_id] > 0,
                },
                "counts": {
                    "scenes": scene_count_by_feature[feature_id],
                    "recentScenes72h": recent_scene_count_by_feature[feature_id],
                    "pendingChanges": pending_change_count_by_feature[feature_id],
                    "trafficObservations": traffic_count_by_feature[feature_id],
                    "recentTraffic24h": recent_traffic_count_by_feature[feature_id],
                },
            }
        )
    write_jsonl(DERIVED_DIR / "feature_status.jsonl", rows)
    return rows


def export_review_queue(
    features_by_id: dict[str, dict[str, Any]],
    changes: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    def sortable_timestamp(value: str | None) -> float:
        parsed = parse_timestamp(value)
        if not parsed:
            return float("-inf")
        return parsed.timestamp()

    scenes_by_id = {scene["id"]: scene for scene in scenes}
    notes_by_feature: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for note in notes:
        notes_by_feature[note["featureId"]].append(note)

    rows = []
    for change in changes:
        if change.get("reviewStatus") != "pending":
            continue
        feature = features_by_id.get(change["featureId"])
        if not feature:
            continue
        before_scene = scenes_by_id.get(change.get("beforeSceneId"))
        after_scene = scenes_by_id.get(change.get("afterSceneId"))
        feature_notes = notes_by_feature.get(change["featureId"], [])
        latest_note = feature_notes[0] if feature_notes else None
        rows.append(
            {
                "changeId": change["id"],
                "featureId": change["featureId"],
                "featureKey": feature["key"],
                "featureName": feature["name"],
                "priority": feature["priority"],
                "claimant": feature["claimant"],
                "group": feature["group"],
                "classification": change.get("classification"),
                "confidence": change.get("confidence"),
                "detectedAt": change.get("detectedAt"),
                "metrics": change.get("metrics") or {},
                "beforeScene": {
                    "sceneId": before_scene.get("id") if before_scene else change.get("beforeSceneId"),
                    "capturedAt": before_scene.get("capturedAt") if before_scene else None,
                    "source": before_scene.get("source") if before_scene else change.get("source"),
                    "path": before_scene.get("path") if before_scene else None,
                },
                "afterScene": {
                    "sceneId": after_scene.get("id") if after_scene else change.get("afterSceneId"),
                    "capturedAt": after_scene.get("capturedAt") if after_scene else None,
                    "source": after_scene.get("source") if after_scene else change.get("source"),
                    "path": after_scene.get("path") if after_scene else None,
                },
                "latestNote": {
                    "noteId": latest_note.get("id") if latest_note else None,
                    "createdAt": latest_note.get("createdAt") if latest_note else None,
                    "kind": latest_note.get("kind") if latest_note else None,
                    "text": latest_note.get("text") if latest_note else None,
                },
            }
        )

    rows.sort(
        key=lambda row: (
            row.get("priority", 99),
            -(row.get("confidence") if isinstance(row.get("confidence"), (int, float)) else -1),
            -sortable_timestamp(row.get("detectedAt")),
            row.get("featureName", ""),
        )
    )
    write_json(DERIVED_DIR / "review_queue.json", {"generatedAt": now_iso(), "items": rows})
    return rows


def export_overview(
    features: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    changes: list[dict[str, Any]],
    traffic: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    feature_status: list[dict[str, Any]],
    review_queue: list[dict[str, Any]],
) -> dict[str, Any]:
    recent_scenes = [
        row
        for row in sorted(scenes, key=lambda row: row.get("capturedAt", ""), reverse=True)
        if is_recent(row.get("capturedAt"), RECENT_SCENE_WINDOW)
    ][:10]
    pending_changes = [row for row in changes if row.get("reviewStatus") == "pending"]
    recent_traffic = [row for row in traffic if is_recent(row.get("capturedAt"), RECENT_TRAFFIC_WINDOW)][:10]
    payload = {
        "generatedAt": now_iso(),
        "counts": {
            "features": len(features),
            "priority1Features": sum(1 for feature in features if feature["priority"] == 1),
            "scenes": len(scenes),
            "recentScenes72h": sum(1 for scene in scenes if is_recent(scene.get("capturedAt"), RECENT_SCENE_WINDOW)),
            "changes": len(changes),
            "pendingChanges": len(pending_changes),
            "trafficObservations": len(traffic),
            "recentTraffic24h": sum(1 for row in traffic if is_recent(row.get("capturedAt"), RECENT_TRAFFIC_WINDOW)),
            "notes": len(notes),
        },
        "reviewQueue": review_queue[:10],
        "featureStatus": sorted(
            feature_status,
            key=lambda row: (
                not row["flags"]["hasPendingReview"],
                row["priority"],
                -row["counts"].get("recentScenes72h", 0),
                row["name"],
            ),
        )[:10],
        "recentScenes": recent_scenes,
        "recentTraffic": recent_traffic,
        "recentNotes": notes[:10],
    }
    write_json(DERIVED_DIR / "overview.json", payload)
    return payload


def summarize_source_scene_coverage(rows: list[dict[str, Any]]) -> dict[str, int]:
    feature_ids = {row.get("featureId") for row in rows if row.get("featureId")}
    recent_feature_ids = {
        row.get("featureId")
        for row in rows
        if row.get("featureId") and is_recent(row.get("capturedAt"), RECENT_SCENE_WINDOW)
    }
    return {
        "featuresWithScenes": len(feature_ids),
        "featuresWithRecentScenes72h": len(recent_feature_ids),
    }



def source_status(configured: bool, total_count: int, recent_count: int) -> str:
    if not configured:
        return "missing_config"
    if total_count == 0:
        return "configured_no_data"
    if recent_count == 0:
        return "stale"
    return "ready"



def export_source_health(
    features: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    changes: list[dict[str, Any]],
    traffic: list[dict[str, Any]],
) -> dict[str, Any]:
    source_counts = Counter(scene["source"] for scene in scenes)
    scenes_by_source: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for scene in scenes:
        scenes_by_source[scene["source"]].append(scene)
    planet_key_present = has_configured_secret(BASE_DIR, "PLANET_API_KEY")
    planet_rows = scenes_by_source.get("planet", [])
    sentinel_rows = scenes_by_source.get("sentinel2", [])
    modis_rows = scenes_by_source.get("modis", [])
    recent_planet_count = sum(1 for row in planet_rows if is_recent(row.get("capturedAt"), RECENT_SCENE_WINDOW))
    recent_sentinel_count = sum(1 for row in sentinel_rows if is_recent(row.get("capturedAt"), RECENT_SCENE_WINDOW))
    recent_modis_count = sum(1 for row in modis_rows if is_recent(row.get("capturedAt"), RECENT_SCENE_WINDOW))
    recent_traffic_count = sum(1 for row in traffic if is_recent(row.get("capturedAt"), RECENT_TRAFFIC_WINDOW))
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
                "qualityPreference": os.environ.get("PLANET_QUALITY", "standard").strip().lower() or "standard",
                "latestFetchAt": latest_timestamp(load_jsonl(PLANET_FETCH_LOG)),
                "latestSceneAt": latest_timestamp(planet_rows, keys=("capturedAt", "publishedDate")),
                "sceneCount": source_counts.get("planet", 0),
                "recentSceneCount72h": recent_planet_count,
                "coverage": summarize_source_scene_coverage(planet_rows),
                "changeCount": sum(1 for row in changes if row.get("source") == "planet"),
                "pendingChangeCount": sum(1 for row in changes if row.get("source") == "planet" and row.get("reviewStatus") == "pending"),
                "status": source_status(planet_key_present, source_counts.get("planet", 0), recent_planet_count),
            },
            "sentinel2": {
                "configured": True,
                "secretSafe": True,
                "latestSceneAt": latest_timestamp(sentinel_rows, keys=("capturedAt", "publishedDate")),
                "sceneCount": source_counts.get("sentinel2", 0),
                "recentSceneCount72h": recent_sentinel_count,
                "coverage": summarize_source_scene_coverage(sentinel_rows),
                "status": source_status(True, source_counts.get("sentinel2", 0), recent_sentinel_count),
            },
            "modis": {
                "configured": True,
                "secretSafe": True,
                "latestSceneAt": latest_timestamp(modis_rows, keys=("capturedAt", "publishedDate")),
                "sceneCount": source_counts.get("modis", 0),
                "recentSceneCount72h": recent_modis_count,
                "coverage": summarize_source_scene_coverage(modis_rows),
                "status": source_status(True, source_counts.get("modis", 0), recent_modis_count),
            },
            "traffic": {
                "configured": True,
                "secretSafe": True,
                "latestObservationAt": latest_timestamp(traffic, keys=("capturedAt", "timestamp", "time")),
                "observationCount": len(traffic),
                "recentObservationCount24h": recent_traffic_count,
                "featureCoverage": {
                    "featuresWithObservations": len({row.get("featureId") for row in traffic if row.get("featureId")}),
                    "featuresWithRecentObservations24h": len({
                        row.get("featureId")
                        for row in traffic
                        if row.get("featureId") and is_recent(row.get("capturedAt"), RECENT_TRAFFIC_WINDOW)
                    }),
                },
                "status": source_status(True, len(traffic), recent_traffic_count),
            },
        },
    }
    write_json(DERIVED_DIR / "source_health.json", payload)
    return payload


def latest_timestamp(rows: list[dict[str, Any]], keys: tuple[str, ...] = ("timestamp", "time")) -> str | None:
    stamps = []
    for row in rows:
        for key in keys:
            value = row.get(key)
            if value:
                stamps.append(value)
                break
    if not stamps:
        return None
    return sorted(stamps)[-1]




def main() -> None:
    features = export_features()
    features_by_key = {feature["key"]: feature for feature in features}
    features_by_id = {feature["id"]: feature for feature in features}
    scenes = export_scenes(features_by_key)
    changes = export_changes(features_by_key)
    traffic = export_traffic(features_by_key)
    notes = export_notes(features_by_key)
    feature_status = export_feature_status(features, scenes, changes, traffic, notes)
    review_queue = export_review_queue(features_by_id, changes, scenes, notes)
    overview = export_overview(features, scenes, changes, traffic, notes, feature_status, review_queue)
    health = export_source_health(features, scenes, changes, traffic)

    assert len(feature_status) == len(features), "feature_status should include every feature"

    print("Exported MVP snapshot:")
    print(f"- features: {len(features)}")
    print(f"- scenes: {len(scenes)}")
    print(f"- changes: {len(changes)}")
    print(f"- traffic observations: {len(traffic)}")
    print(f"- notes: {len(notes)}")
    print(f"- feature status rows: {len(feature_status)}")
    print(f"- review queue items: {len(review_queue)}")
    print(f"- pending review: {overview['counts']['pendingChanges']}")
    print(f"- planet configured: {health['sources']['planet']['configured']}")
    print(f"- output dir: {DERIVED_DIR}")


if __name__ == "__main__":
    main()
