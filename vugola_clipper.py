#!/usr/bin/env python3
"""
ClipForge AI - Using Vugola API for AI-powered clipping
"""

import os
import sys
import time
import json
import argparse
import requests
from pathlib import Path

# Config
VUGOLA_API_KEY = "vug_sk_ibjzgocR76M3no3V8o47asC73KXa1CyflKd3ibjzgocR76M3no3V8o47asC73KXa1CyflKd3"
VUGOLA_API = "https://api.vugolaai.com"

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

def start_clip_job(video_url, num_clips=3, min_length=30, max_length=60):
    """Start a Vugola clip job"""
    print(f"Starting clip job for: {video_url}")
    
    resp = requests.post(
        f"{VUGOLA_API}/clip",
        headers={
            "Authorization": f"Bearer {VUGOLA_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "video_url": video_url,
            "num_clips": num_clips,
            "min_clip_length": min_length,
            "max_clip_length": max_length
        }
    )
    
    if resp.status_code != 200:
        print(f"Error: {resp.status_code} {resp.text}")
        return None
    
    data = resp.json()
    job_id = data.get("job_id")
    print(f"Job started: {job_id}")
    return job_id

def poll_job(job_id, max_attempts=120):
    """Poll for job completion"""
    print(f"Polling job {job_id}...")
    
    headers = {"Authorization": f"Bearer {VUGOLA_API_KEY}"}
    
    for attempt in range(max_attempts):
        time.sleep(5)
        
        resp = requests.get(f"{VUGOLA_API}/clip/{job_id}", headers=headers)
        
        if resp.status_code != 200:
            print(f"Poll error: {resp.status_code}")
            continue
        
        data = resp.json()
        status = data.get("status", "")
        progress = data.get("progress", "")
        
        print(f"   [{attempt+1}] Status: {status} {f'({progress}%)' if progress else ''}")
        
        if status in ("completed", "complete", "done"):
            print("Job complete!")
            return data
        
        if status in ("failed", "error"):
            print(f"Job failed: {data}")
            return None
    
    print("Timeout waiting for job")
    return None

def download_clips(job_id, clips):
    """Download all clips"""
    headers = {"Authorization": f"Bearer {VUGOLA_API_KEY}"}
    
    # Sort by virality score
    clips.sort(key=lambda c: c.get("virality_score", 0), reverse=True)
    
    downloaded = []
    
    for i, clip in enumerate(clips):
        idx = clip.get("clip_index", i + 1)
        title = clip.get("title", f"clip-{idx}")
        score = clip.get("virality_score", 0)
        duration = clip.get("duration", 0)
        
        # Use download endpoint
        dl_url = f"{VUGOLA_API}/clip/{job_id}/download/{idx}"
        
        resp = requests.get(dl_url, headers=headers)
        
        if resp.status_code != 200:
            print(f"Download failed for clip {idx}: {resp.status_code}")
            continue
        
        # Save file
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)[:40]
        filename = f"{idx}-{safe_title}.mp4"
        filepath = OUTPUT_DIR / filename
        
        with open(filepath, "wb") as f:
            f.write(resp.content)
        
        size_mb = len(resp.content) / 1024 / 1024
        rank = "ðŸ¥‡" if i == 0 else "ðŸ¥ˆ" if i == 1 else "ðŸ¥‰" if i == 2 else f"#{i+1}"
        print(f"  {rank} [{score} virality | {duration:.0f}s] {filename} -> {size_mb:.1f} MB")
        
        downloaded.append(str(filepath))
    
    return downloaded

def clip_video(url, num_clips=3, min_length=30, max_length=60):
    """Main function - clip video using Vugola AI"""
    print(f"\n{'='*50}")
    print(f" CLIPFORGE AI - Powered by Vugola")
    print(f"{'='*50}")
    print(f"Video: {url}")
    print(f"Clips: {num_clips} ({min_length}s-{max_length}s each)")
    print(f"{'='*50}\n")
    
    # Start job
    job_id = start_clip_job(url, num_clips, min_length, max_length)
    if not job_id:
        return {"error": "Failed to start clip job"}
    
    # Poll for completion
    result = poll_job(job_id)
    if not result:
        return {"error": "Job failed or timed out"}
    
    # Get clips
    clips = result.get("clips", [])
    if not clips:
        return {"error": "No clips generated"}
    
    print(f"\nDownloading {len(clips)} clips...")
    
    # Download
    downloaded = download_clips(job_id, clips)
    
    print(f"\n{'='*50}")
    print(f"Done! Downloaded {len(downloaded)} clips")
    print(f"{'='*50}")
    
    return {
        "success": True,
        "clips": downloaded,
        "count": len(downloaded),
        "job_id": job_id,
        "virality": [{"title": c.get("title"), "score": c.get("virality_score")} for c in clips[:3]]
    }

def main():
    parser = argparse.ArgumentParser(description="ClipForge AI - Vugola Powered")
    parser.add_argument("url", help="YouTube URL")
    parser.add_argument("--clips", type=int, default=3)
    parser.add_argument("--min-length", type=int, default=30)
    parser.add_argument("--max-length", type=int, default=60)
    
    args = parser.parse_args()
    
    result = clip_video(args.url, args.clips, args.min_length, args.max_length)
    
    print("\n" + json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
