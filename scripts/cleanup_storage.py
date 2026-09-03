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
        try:
            # Use lstat to not follow broken symlinks when getting mtime
            # or just handle the error gracefully
            mtime = os.lstat(f).st_mtime
            
            # If it's a symlink, it doesn't take up much space, but we should clean up 
            # broken symlinks if they are old or broken
            is_sym = os.path.islink(f)
            
            if is_sym:
                if not os.path.exists(f):  # Broken symlink
                    os.unlink(f)
                    deleted += 1
                    print(f"  [DELETED] Broken symlink {os.path.basename(f)}")
                continue
                
            if (now - mtime) > retention_seconds:
                size = os.path.getsize(f)
                os.remove(f)
                deleted += 1
                freed_bytes += size
                print(f"  [DELETED] {os.path.basename(f)} ({(size / 1024**2):.1f} MB)")
        except Exception as e:
            print(f"  [ERROR] Failed to process {f}: {e}")
                
    print(f"\n✅ Cleanup complete. Deleted {deleted} files, freed {(freed_bytes / 1024**3):.2f} GB.")

if __name__ == "__main__":
    main()
