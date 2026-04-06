# ReefWatch Product Direction

## Product Goal

ReefWatch should become a small, opinionated monitoring product for **change over time in disputed South China Sea features**, not a generic intelligence platform.

That means the MVP should answer three questions well:

1. **What changed?**
2. **Where did it change?**
3. **How confident are we that it matters?**

## Primary User

A solo analyst or small OSINT team doing recurring monitoring of reefs, outposts, airstrips, ports, and nearby traffic.

## Core Jobs To Be Done

- Review the latest satellite imagery per monitored feature
- Compare recent observations against prior baselines
- See aircraft / vessel activity near strategic features
- Keep a durable log of observations and analyst notes
- Avoid losing context across repeated monitoring runs

## What ReefWatch Is

- A feature-centric monitoring workflow
- A lightweight evidence log for imagery and traffic observations
- A way to turn noisy data sources into a shortlist of analyst-worthy changes

## What ReefWatch Is Not

- Not a live battlefield command system
- Not a fully automated truth engine
- Not a broad maritime analytics platform
- Not dependent on one paid provider

## MVP Shape

### MVP Outcome

For each priority feature, show a timeline of imagery, detected changes, nearby traffic signals, and analyst notes in one place.

### MVP Scope

1. **Feature registry**
   - canonical list of monitored reefs/islands/outposts
   - strategic priority and tags
2. **Imagery ingest**
   - Sentinel-2 as baseline free source
   - Planet thumbnails as optional higher-resolution layer
3. **Observation log**
   - machine-generated detections plus analyst-confirmed notes
4. **Daily summary**
   - changed features, newest imagery, unresolved review queue
5. **Manual analyst review flow**
   - accept/reject/annotate candidate changes

### Deferred Until Later

- vessel identity enrichment from paid AIS APIs
- collaborative multi-user workflows
- map-heavy custom frontend
- automated alert delivery to external channels by default
- model-based image interpretation beyond simple heuristics

## Prioritized Monitoring Targets

### Tier 1

Airstrip and major construction features:
- Woody Island
- Fiery Cross Reef
- Subi Reef
- Mischief Reef
- Thitu Island

### Tier 2

Helipad / logistics / harbor-capable features

### Tier 3

Smaller reefs, shoals, and lower-signal sites

## Success Metrics for MVP

- A new analyst can understand the current state of a feature in under 2 minutes
- Daily run highlights only a manageable review queue
- All observations are traceable back to a source image or traffic record
- Planet integration is optional and secret-safe

## Recommended Build Order

1. Clean and stabilize source-of-truth data model
2. Standardize output artifacts from current scripts
3. Add a review-friendly summary layer
4. Add a minimal UI or static report flow around the review queue
5. Expand higher-resolution imagery and vessel enrichment later
