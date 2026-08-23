#!/usr/bin/env python3
"""
Monitor Spartan HPC job status for NISAR processing jobs.
Run locally to check job status without SSH.
"""

import subprocess
import sys
import json
from datetime import datetime, timezone

def run_ssh(cmd):
    """Run command on Spartan via SSH."""
    result = subprocess.run(
        ["ssh", "spartan", cmd],
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout, result.stderr

def get_job_status(job_id):
    """Get status of a specific job."""
    code, stdout, stderr = run_ssh(f"sacct -j {job_id} --format=JobID,JobName,State,ExitCode,Elapsed,AllocNodes")
    if code != 0:
        return {"job_id": job_id, "error": stderr}
    
    lines = stdout.strip().split('\n')
    if len(lines) < 3:
        return {"job_id": job_id, "status": "UNKNOWN"}
    
    # Parse sacct output
    header = lines[0].split()
    data = lines[2].split()
    
    return {
        "job_id": job_id,
        "job_name": data[1] if len(data) > 1 else "UNKNOWN",
        "state": data[2] if len(data) > 2 else "UNKNOWN",
        "exit_code": data[3] if len(data) > 3 else "UNKNOWN",
        "elapsed": data[4] if len(data) > 4 else "UNKNOWN",
        "node": data[5] if len(data) > 5 else "UNKNOWN",
    }

def get_queue_status():
    """Get overall queue status for sapphire partition."""
    code, stdout, stderr = run_ssh("squeue -p sapphire --format='%.10i %.20j %.8u %.2t %.10M %.6D %.20R'")
    if code != 0:
        return {"error": stderr}
    return {"queue": stdout}

def get_user_jobs():
    """Get all jobs for current user."""
    code, stdout, stderr = run_ssh("squeue -u haninhn --format='%.10i %.20j %.8u %.2t %.10M %.6D %.20R'")
    if code != 0:
        return {"error": stderr}
    return {"jobs": stdout}

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Monitor Spartan NISAR jobs")
    parser.add_argument("--job", help="Specific job ID to check")
    parser.add_argument("--all", action="store_true", help="Show all user jobs")
    parser.add_argument("--queue", action="store_true", help="Show sapphire queue status")
    parser.add_argument("--watch", type=int, default=0, help="Watch interval in seconds")
    args = parser.parse_args()

    if args.job:
        status = get_job_status(args.job)
        print(json.dumps(status, indent=2))
    elif args.all:
        print("=== User Jobs ===")
        result = get_user_jobs()
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(result["jobs"])
    elif args.queue:
        print("=== Sapphire Partition Queue ===")
        result = get_queue_status()
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(result["queue"])
    else:
        # Default: check known recent jobs
        known_jobs = [29526692, 29526174, 29526164, 29526144, 29526100]
        print("=== Recent NISAR Jobs ===")
        for job_id in known_jobs:
            status = get_job_status(job_id)
            print(f"  Job {job_id}: {status.get('state', 'UNKNOWN')} ({status.get('job_name', 'N/A')}) - {status.get('elapsed', 'N/A')}")

if __name__ == "__main__":
    main()