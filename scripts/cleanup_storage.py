#!/usr/bin/env python3
"""
Disk Cleanup Utility for ReefWatch
Removes raw NISAR HDF5 files (.h5) older than 14 days to prevent disk quota issues on Spartan.
"""
import os
import time
import glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGERY_DIR = os.path.join(SCRIPT_DIR, "..", "imagery_history")

def main():
    now = time.time()
    retention_days = 14
    retention_seconds = retention_days * 86400

    h5_files = glob.glob(os.path.join(IMAGERY_DIR, "*.h5"))
    deleted = 0
    freed_bytes = 0

    print(f"🧹 Scanning for .h5 files older than {retention_days} days...")
    
    for f in h5_files:
        # Check file modification time
        mtime = os.path.getmtime(f)
        if (now - mtime) > retention_seconds:
            size = os.path.getsize(f)
            try:
                os.remove(f)
                deleted += 1
                freed_bytes += size
                print(f"  [DELETED] {os.path.basename(f)} ({(size / 1024**2):.1f} MB)")
            except Exception as e:
                print(f"  [ERROR] Failed to delete {f}: {e}")
                
    print(f"\n✅ Cleanup complete. Deleted {deleted} files, freed {(freed_bytes / 1024**3):.2f} GB.")

if __name__ == "__main__":
    main()
