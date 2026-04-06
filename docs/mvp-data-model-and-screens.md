# ReefWatch MVP Data Model and Screens

## MVP Data Model

The current repo already has useful raw inputs. The missing piece is a stable app-facing model.

### 1. Feature

Represents one monitored island / reef / outpost.

```json
{
  "id": "feature:fiery_cross_reef",
  "key": "fiery_cross_reef",
  "name": "Fiery Cross Reef",
  "group": "spratly",
  "claimant": "China",
  "lat": 9.53,
  "lon": 112.88,
  "priority": 1,
  "tags": ["airstrip", "harbor", "construction"]
}
```

### 2. Imagery Scene

Represents one fetched image or thumbnail.

```json
{
  "id": "scene:planet:fiery_cross_reef:2026-04-02",
  "featureId": "feature:fiery_cross_reef",
  "source": "planet",
  "providerSceneId": "20260402_...",
  "capturedAt": "2026-04-02T03:14:22Z",
  "publishedDate": "2026-04-02",
  "assetKind": "thumbnail",
  "resolutionMeters": 4,
  "cloudCover": 0.07,
  "quality": "standard",
  "path": "imagery_history/fiery_cross_reef_planet_2026-04-02.png",
  "status": "ready"
}
```

### 3. Change Event

A candidate or confirmed change derived from comparing two scenes.

```json
{
  "id": "change:fiery_cross_reef:2026-03-28:2026-04-02",
  "featureId": "feature:fiery_cross_reef",
  "source": "planet",
  "beforeSceneId": "scene:planet:fiery_cross_reef:2026-03-28",
  "afterSceneId": "scene:planet:fiery_cross_reef:2026-04-02",
  "detectedAt": "2026-04-02T04:00:00Z",
  "classification": "significant_change",
  "confidence": 0.71,
  "metrics": {
    "ssim": 0.88,
    "pixelDiffPct": 5.4,
    "brightnessChangePct": 3.1
  },
  "reviewStatus": "pending"
}
```

### 4. Traffic Observation

Normalized aircraft or vessel event near a feature.

```json
{
  "id": "obs:aircraft:a1b2c3:2026-04-02T05:15:00Z",
  "featureId": "feature:woody_island",
  "domain": "aircraft",
  "source": "opensky",
  "capturedAt": "2026-04-02T05:15:00Z",
  "identity": {
    "icao24": "a1b2c3",
    "callsign": "ABC123"
  },
  "position": {
    "lat": 16.83,
    "lon": 112.33,
    "altitudeM": 7620,
    "speedMps": 211
  },
  "distanceKm": 11.4,
  "reviewStatus": "raw"
}
```

### 5. Analyst Note

Human context layered on top of detections.

```json
{
  "id": "note:fiery_cross_reef:2026-04-02:01",
  "featureId": "feature:fiery_cross_reef",
  "createdAt": "2026-04-02T09:10:00Z",
  "author": "analyst",
  "kind": "assessment",
  "text": "Possible apron expansion on western edge; verify with next clear Sentinel-2 pass."
}
```

## Recommended Storage Layout

- `data/target_features.json` stays the canonical feature seed
- `imagery_history/` stores source image artifacts
- `derived/features.jsonl` stores normalized feature records
- `derived/scenes.jsonl` stores normalized scene records
- `derived/changes.jsonl` stores candidate/confirmed changes
- `derived/traffic.jsonl` stores normalized traffic observations
- `derived/notes.jsonl` stores analyst notes
- `derived/feature_status.jsonl` stores one app-facing summary row per feature for list/triage screens
- `derived/review_queue.json` stores the sorted pending-review worklist with feature metadata, before/after scene refs, and latest analyst note
- `derived/source_health.json` stores secret-safe ingest/config health

Current repo bridge: `python3 scripts/export_mvp_snapshot.py` builds the `derived/` layer from existing script outputs without exposing secret values.

Additional bridge outputs:
- `derived/overview.json` — daily-brief friendly summary for the Overview screen
- `derived/feature_status.jsonl` — feature list / inbox-style summary with latest scene, latest change, latest traffic, and pending-review flags
- `derived/review_queue.json` — explicit change-review worklist sorted for analyst triage
- `derived/notes.jsonl` — normalized analyst notes when `analyst_notes.jsonl` exists

## MVP Screens

### 1. Overview / Daily Brief

Purpose: answer “what needs attention today?”

Show:
- features with new imagery in last 24-72h
- pending change reviews
- unusual aircraft / vessel observations
- counts by priority tier

### 2. Feature List

Purpose: browse and filter monitored features

Backed by: `derived/feature_status.jsonl`

Show:
- feature name
- claimant
- priority
- latest imagery date/source
- latest change status
- recent traffic indicator
- pending review flag
- recent Planet imagery flag

Derived field semantics:
- `counts.scenes` / `counts.trafficObservations` = lifetime totals currently materialized in the repo
- `counts.recentScenes72h` = imagery seen in the last 72 hours
- `counts.recentTraffic24h` = traffic observations seen in the last 24 hours
- `flags.hasRecentPlanetImagery` = at least one Planet scene in the last 72 hours, not merely historical presence

Filters:
- group (Spratly / Paracel)
- claimant
- priority
- has pending review
- has recent Planet imagery

### 3. Feature Detail

Purpose: one canonical page per reef / island / outpost

Show:
- feature metadata and tags
- latest imagery stack by source
- before/after comparison cards
- recent traffic observations
- analyst notes and review history

### 4. Change Review Queue

Purpose: fast triage of machine-generated detections

Backed by: `derived/review_queue.json`

Show:
- candidate changes sorted by feature priority, confidence, and recency
- before / after thumbs
- metrics summary
- latest analyst note, if any
- actions: confirm, dismiss, defer, annotate

### 5. Source Health / Ingest Status

Purpose: keep the system trustworthy

Show:
- last successful fetch time per source
- rate limit / auth failures
- number of pending or failed downloads
- secret/config status without exposing secret values

Current export contract:
- `derived/source_health.json` reports `latestSceneAt` per imagery source when known
- Planet health includes `configured`, `latestFetchAt`, `sceneCount`, `recentSceneCount72h`, `changeCount`, and `pendingChangeCount`
- traffic health includes `latestObservationAt`, total observations, and `recentObservationCount24h`

## Suggested Near-Term API Shapes

- `GET /features`
- `GET /features/:id`
- `GET /features/:id/scenes`
- `GET /features/:id/changes`
- `GET /review-queue`
- `GET /notes`
- `GET /overview`
- `GET /source-health`

## Why This Model

This keeps ReefWatch centered on **features**, which matches how analysts think, while still preserving raw-source provenance and reviewability.
