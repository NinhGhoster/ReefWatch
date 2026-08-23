#!/bin/bash
#SBATCH --job-name=nisar_coherence
#SBATCH --partition=sapphire
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=24:00:00
#SBATCH --output=/data/gpfs/projects/punim1990/haninhn/ReefWatch/logs/coherence_%j.out
#SBATCH --error=/data/gpfs/projects/punim1990/haninhn/ReefWatch/logs/coherence_%j.err

# Load modules
module load Mambaforge/23.1.0-4

# Activate conda environment
eval "$(conda shell.bash hook)"
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
        --tile-size 1024 \
        --overlap 128 \
        --changelog

    if [ $? -ne 0 ]; then
        echo "ERROR: $feat failed, continuing..."
    fi

    # Brief pause between features
    sleep 10
done

echo "All features completed at $(date)"