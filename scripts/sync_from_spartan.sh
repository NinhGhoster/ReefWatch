#!/bin/bash
# Sync derived data from Spartan HPC to local machine
# Run this locally after Spartan jobs complete

set -e

SPARTAN_HOST="spartan"
REMOTE_BASE="/data/gpfs/projects/punim1990/haninhn/ReefWatch"
LOCAL_BASE="/Users/haninhn/Downloads/ReefWatch"

echo "=== Syncing from Spartan HPC ==="
echo "Remote: $SPARTAN_HOST:$REMOTE_BASE"
echo "Local:  $LOCAL_BASE"
echo ""

# Sync derived data (small, critical)
echo "1. Syncing derived/ (MVP snapshots)..."
rsync -avz --progress \
  $SPARTAN_HOST:$REMOTE_BASE/derived/ \
  $LOCAL_BASE/derived/

# Sync change logs
echo ""
echo "2. Syncing change logs..."
rsync -avz --progress \
  $SPARTAN_HOST:$REMOTE_BASE/nisar_changes.jsonl \
  $LOCAL_BASE/nisar_changes.jsonl

rsync -avz --progress \
  $SPARTAN_HOST:$REMOTE_BASE/s2_correlation.jsonl \
  $LOCAL_BASE/s2_correlation.jsonl 2>/dev/null || true

rsync -avz --progress \
  $SPARTAN_HOST:$REMOTE_BASE/osint_crossref.jsonl \
  $LOCAL_BASE/osint_crossref.jsonl 2>/dev/null || true

# Sync derived reports
echo ""
echo "3. Syncing reports..."
rsync -avz --progress \
  $SPARTAN_HOST:$REMOTE_BASE/derived/s2_correlation_report.json \
  $LOCAL_BASE/derived/s2_correlation_report.json 2>/dev/null || true

rsync -avz --progress \
  $SPARTAN_HOST:$REMOTE_BASE/derived/osint_crossref_report.json \
  $LOCAL_BASE/derived/osint_crossref_report.json 2>/dev/null || true

echo ""
echo "=== Sync Complete ==="
echo "Run 'python3 scripts/validate_mvp_snapshot.py' to verify"