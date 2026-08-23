#!/bin/bash
#SBATCH --job-name=nisar_coherence
#SBATCH --partition=interactive
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=2-00:00:00
#SBATCH --output=/data/gpfs/projects/punim1990/haninhn/ReefWatch/logs/coherence_interactive_%j.out
#SBATCH --error=/data/gpfs/projects/punim1990/haninhn/ReefWatch/logs/coherence_interactive_%j.err

# Initialize conda for batch environment
source /apps/easybuild-2022/easybuild/software/Core/Mambaforge/23.1.0-4/etc/profile.d/conda.sh
conda activate /data/gpfs/projects/punim1990/haninhn/nisar_envs/reefwatch

# Change to working directory
cd /data/gpfs/projects/punim1990/haninhn/ReefWatch

# Create logs directory
mkdir -p logs

# Features to process (only those with GSLC data - at least 2 dates)
FEATURES=(
    "fiery_cross_reef"
    "mischief_reef"
    "subi_reef"
    "cuarteron_reef"
    "gaven_reefs"
    "hughes_reef"
    "johnson_south_reef"
    "namyit_island"
    "sin_cowe_island"
    "taiping_island"
    "thitu_island"
    "swallow_reef"
)

echo "Starting NISAR GSLC Coherence processing at $(date)"
echo "Features: ${FEATURES[@]}"

for feat in "${FEATURES[@]}"; do
    echo "========================================"
    echo "Processing $feat at $(date)"
    echo "========================================"

    python3 scripts/nisar_coherence_chunked.py \
        --feature "$feat" \
        --polarization HH \
        --tile-size 512 \
        --overlap 64 \
        --changelog

    if [ $? -ne 0 ]; then
        echo "ERROR: $feat failed, continuing..."
    fi

    # Brief pause between features
    sleep 10
done

echo "All features completed at $(date)"