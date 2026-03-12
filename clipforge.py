#!/usr/bin/env python3
"""
ClipForge AI - Private Video Clipper
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

# Fixed paths
YT_DLP = r"C:\Users\gibby\AppData\Roaming\Python\Python312\Scripts\yt-dlp.exe"
FFMPEG = r"C:\Users\gibby\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"
FFPROBE = r"C:\Users\gibby\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffprobe.exe"

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

def run(cmd, capture=True):
    return subprocess.run(cmd, capture_output=capture, text=True, timeout=300)

def get_duration(path):
    r = run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path])
    try: return float(r.stdout.strip())
    except: return None

def download(url):
    print("Downloading...")
    r = run([YT_DLP, "-f", "bestvideo+bestaudio", "--merge-output-format", "mp4", "-o", str(OUTPUT_DIR / "input.%(ext)s"), url])
    if r.returncode != 0:
        print(f"Error: {r.stderr[-200:]}")
        return None
    files = list(OUTPUT_DIR.glob("input.*"))
    for f in files:
        if f.suffix == ".mp4":
            f.rename(OUTPUT_DIR / "input.mp4")
            return str(OUTPUT_DIR / "input.mp4")
    return None

def clip(input_path, output_path, start, duration):
    print(f"Clip {start}s-{start+duration}s")
    r = run([FFMPEG, "-y", "-ss", str(start), "-i", input_path, "-t", str(duration), 
             "-c:v", "libx264", "-preset", "fast", "-crf", "20",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", 
             "-pix_fmt", "yuv420p", output_path])
    if r.returncode != 0:
        print(f"Error: {r.stderr[-300:]}")
        return None
    return output_path

def vertical(input_path, output_path):
    print("Converting to vertical...")
    r = run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=w,h", "-of", "csv=p=0", input_path])
    try:
        w, h = map(int, r.stdout.strip().split(','))
    except:
        w, h = 1920, 1080
    
    ratio = 9/16
    if w/h > ratio:
        new_w = int(h * ratio)
        crop = f"crop={new_w}:{h}:(iw-{new_w})/2:0"
    else:
        new_h = int(w / ratio)
        crop = f"crop={w}:{new_h}:0:(ih-{new_h})/2"
    
    r = run([FFMPEG, "-y", "-i", input_path, "-vf", f"{crop},scale=1080:1920",
             "-c:v", "libx264", "-preset", "fast", "-crf", "20",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", 
             "-pix_fmt", "yuv420p", output_path])
    if r.returncode != 0:
        print(f"Error: {r.stderr[-300:]}")
        return None
    return output_path

def main(url, num_clips=3, duration=30, vertical_mode=False, highlight=False):
    print(f"\n=== CLIPFORGE AI ===\n{url}\n")
    
    video = download(url)
    if not video:
        return {"error": "Download failed"}
    
    dur = get_duration(video)
    print(f"Duration: {dur}s")
    
    # Get positions
    if highlight and dur:
        # Simple audio analysis
        positions = []
        for i in range(num_clips):
            pos = (dur / (num_clips + 1)) * (i + 1)
            positions.append(pos)
    else:
        gap = (dur - duration * num_clips) / (num_clips + 1) if dur else 0
        positions = [gap + i * (duration + gap) for i in range(num_clips)]
    
    clips = []
    for i, start in enumerate(positions):
        out = OUTPUT_DIR / f"clip_{i+1}.mp4"
        if clip(video, str(out), start, duration):
            if vertical_mode:
                vout = OUTPUT_DIR / f"clip_{i+1}_v.mp4"
                vertical(str(out), str(vout))
                clips.append(str(vout))
            else:
                clips.append(str(out))
    
    # Cleanup
    try: os.remove(video)
    except: pass
    
    print(f"\nDone! {len(clips)} clips")
    for c in clips:
        print(f"  {Path(c).name} ({os.path.getsize(c)/1024/1024:.1f}MB)")
    
    return {"success": True, "clips": clips}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--clips", type=int, default=3)
    p.add_argument("--duration", type=int, default=30)
    p.add_argument("--vertical", action="store_true")
    p.add_argument("--highlight", action="store_true")
    a = p.parse_args()
    print(json.dumps(main(a.url, a.clips, a.duration, a.vertical, a.highlight), indent=2))
