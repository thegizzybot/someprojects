#!/usr/bin/env python3
"""
ClipForge AI - Private Video Clipper with Whisper + Vugola AI
"""

import os
import sys
import json
import argparse
import subprocess
import tempfile
import time
import requests
from pathlib import Path

# Fixed paths
YT_DLP = r"C:\Users\gibby\AppData\Roaming\Python\Python312\Scripts\yt-dlp.exe"
FFMPEG = r"C:\Users\gibby\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"
FFPROBE = r"C:\Users\gibby\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffprobe.exe"

# Vugola API
VUGOLA_API_KEY = "vug_sk_ibjzgocR76M3no3V8o47asC73KXa1CyflKd3ibjzgocR76M3no3V8o47asC73KXa1CyflKd3"
VUGOLA_API = "https://api.vugolaai.com"

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ============ VUGOLA BACKEND ============

def vugola_clip(url, num_clips=3, min_length=30, max_length=60):
    """Use Vugola AI to clip video - includes virality scoring"""
    print(f"\nðŸ¤– Using Vugola AI Backend")
    
    # Start job
    print(f"Starting clip job for: {url}")
    resp = requests.post(
        f"{VUGOLA_API}/clip",
        headers={
            "Authorization": f"Bearer {VUGOLA_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "video_url": url,
            "num_clips": num_clips,
            "min_clip_length": min_length,
            "max_clip_length": max_length
        }
    )
    
    if resp.status_code != 200:
        print(f"Vugola error: {resp.status_code} {resp.text}")
        return None
    
    data = resp.json()
    job_id = data.get("job_id")
    print(f"Job ID: {job_id}")
    
    # Poll for completion
    headers = {"Authorization": f"Bearer {VUGOLA_API_KEY}"}
    for attempt in range(120):
        time.sleep(5)
        
        resp = requests.get(f"{VUGOLA_API}/clip/{job_id}", headers=headers)
        if resp.status_code != 200:
            continue
        
        data = resp.json()
        status = data.get("status", "")
        progress = data.get("progress", "")
        
        print(f"   [{attempt+1}] {status} {f'({progress}%)' if progress else ''}")
        
        if status in ("completed", "complete", "done"):
            break
        if status in ("failed", "error"):
            print(f"Job failed: {data}")
            return None
    
    # Download clips
    clips = data.get("clips", [])
    clips.sort(key=lambda c: c.get("virality_score", 0), reverse=True)
    
    downloaded = []
    for i, clip in enumerate(clips):
        idx = clip.get("clip_index", i + 1)
        title = clip.get("title", f"clip-{idx}")
        score = clip.get("virality_score", 0)
        
        dl_url = f"{VUGOLA_API}/clip/{job_id}/download/{idx}"
        resp = requests.get(dl_url, headers=headers)
        
        if resp.status_code != 200:
            continue
        
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)[:40]
        filename = f"vugola_{idx}-{safe_title}.mp4"
        filepath = OUTPUT_DIR / filename
        
        with open(filepath, "wb") as f:
            f.write(resp.content)
        
        size_mb = len(resp.content) / 1024 / 1024
        print(f"  #{i+1} [{score} virality] {filename} ({size_mb:.1f}MB)")
        downloaded.append({"path": str(filepath), "virality": score, "title": title})
    
    return {"success": True, "clips": downloaded, "backend": "vugola"}

# ============ LOCAL BACKEND ============

def run(cmd, capture=True, timeout=300):
    return subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout, shell=True)

def get_duration(path):
    r = run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path])
    try: return float(r.stdout.strip())
    except: return None

def get_resolution(path):
    r = run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=w,h", "-of", "csv=p=0", path])
    try:
        w, h = map(int, r.stdout.strip().split(','))
        return w, h
    except:
        return 1920, 1080

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

def transcribe_whisper(audio_path, model_size="base"):
    """Transcribe audio using faster-whisper"""
    try:
        from faster_whisper import WhisperModel
        
        print(f"Loading Whisper {model_size} model...")
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        
        print("Transcribing...")
        segments, info = model.transcribe(audio_path, beam_size=5)
        
        subtitles = []
        for seg in segments:
            subtitles.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip()
            })
        
        return subtitles
    except ImportError:
        print("faster-whisper not installed. Run: pip install faster-whisper")
        return None
    except Exception as e:
        print(f"Whisper error: {e}")
        return None

def create_srt(subtitles, output_path):
    """Create SRT file from whisper output"""
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, sub in enumerate(subtitles, 1):
            start = format_time(sub['start'])
            end = format_time(sub['end'])
            f.write(f"{i}\n{start} --> {end}\n{sub['text']}\n\n")
    return output_path

def format_time(seconds):
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"

def burn_subtitles(video_path, srt_path, output_path):
    """Burn subtitles into video"""
    print("Burning subtitles...")
    force_style = "FontSize=24,PrimaryColour=&Hffffff,MarginV=20"
    
    cmd = f'''{FFMPEG} -y -i "{video_path}" -vf "subtitles='{srt_path}':force_style='{force_style}'" \
-c:v libx264 -preset fast -crf 18 -c:a aac -b:a 192k -movflags +faststart \
-pix_fmt yuv420p "{output_path}"'''
    
    r = run(cmd)
    if r.returncode != 0:
        print(f"Subtitle burn error: {r.stderr[-300:]}")
        return None
    return output_path

def clip_local(input_path, output_path, start, duration, quality="high"):
    """Extract clip with quality settings"""
    if quality == "high":
        crf, preset, bitrate = "18", "slow", "4M"
    elif quality == "medium":
        crf, preset, bitrate = "20", "medium", "2M"
    else:
        crf, preset, bitrate = "23", "fast", "1M"
    
    cmd = f'''{FFMPEG} -y -ss {start} -i "{input_path}" -t {duration} \
-c:v libx264 -preset {preset} -crf {crf} -b:v {bitrate} \
-c:a aac -b:a 192k -movflags +faststart -pix_fmt yuv420p "{output_path}"'''
    
    r = run(cmd)
    if r.returncode != 0:
        print(f"Error: {r.stderr[-300:]}")
        return None
    return output_path

def to_vertical(input_path, output_path, mode="crop"):
    """Convert to 9:16 vertical (1080x1920)"""
    w, h = get_resolution(input_path)
    target_ratio = 9/16
    
    if mode == "crop":
        if w/h > target_ratio:
            new_w = int(h * target_ratio)
            crop = f"crop={new_w}:{h}:(iw-{new_w})/2:0"
        else:
            new_h = int(w / target_ratio)
            crop = f"crop={w}:{new_h}:0:(ih-{new_h})/2"
        vf = f"{crop},scale=1080:1920"
    else:
        # Pad mode with blurred background
        scale = "scale='min(1080,iw)':min'(1920,ih)':force_original_aspect_ratio=decrease"
        bg = "boxblur=50:10,scale=1080:1920"
        overlay = "[bg][v]overlay=(W-w)/2:(H-h)/2"
        vf = f"{scale},setsar=1[v];{bg}{overlay}"
    
    cmd = f'''{FFMPEG} -y -i "{input_path}" -vf "{vf}" \
-c:v libx264 -preset fast -crf 18 -c:a aac -b:a 192k -movflags +faststart \
-pix_fmt yuv420p "{output_path}"'''
    
    r = run(cmd)
    if r.returncode != 0:
        # Fallback to simple crop
        cmd = f'''{FFMPEG} -y -i "{input_path}" -vf "crop=1080:1920:(iw-1080)/2:0,scale=1080:1920" \
-c:v libx264 -preset fast -crf 18 -c:a aac -b:a 192k -movflags +faststart \
-pix_fmt yuv420p "{output_path}"'''
        r = run(cmd)
        if r.returncode != 0:
            return None
    return output_path

def local_clip(video, num_clips, duration, vertical, subtitles, quality, vertical_mode):
    """Local backend - your own processing with Whisper"""
    dur = get_duration(video)
    print(f"Duration: {dur}s")
    
    # Transcribe for subtitles
    sub_data = None
    if subtitles:
        print("Generating subtitles...")
        audio_path = str(OUTPUT_DIR / "audio.wav")
        run(f'{FFMPEG} -y -i "{video}" -vn -acodec pcm_s16le -ar 16000 -ac 1 "{audio_path}"')
        
        sub_data = transcribe_whisper(audio_path)
        if sub_data:
            create_srt(sub_data, str(OUTPUT_DIR / "subs.srt"))
    
    # Simple equal distribution (could add highlight detection here)
    gap = (dur - duration * num_clips) / (num_clips + 1) if dur else 0
    positions = [gap + i * (duration + gap) for i in range(num_clips)]
    
    clips = []
    for i, start in enumerate(positions):
        out = OUTPUT_DIR / f"clip_{i+1}.mp4"
        
        if not clip_local(video, str(out), start, duration, quality):
            continue
        
        # Add subtitles
        if subtitles and sub_data:
            start_ts, end_ts = start, start + duration
            segment_subs = [s for s in sub_data if start_ts <= s['start'] and s['end'] <= end_ts]
            if segment_subs:
                seg_srt = OUTPUT_DIR / f"subs_{i+1}.srt"
                create_srt(segment_subs, str(seg_srt))
                subbed = OUTPUT_DIR / f"clip_{i+1}_sub.mp4"
                if burn_subtitles(str(out), str(seg_srt), str(subbed)):
                    out = subbed
        
        # Vertical
        if vertical:
            vout = OUTPUT_DIR / f"clip_{i+1}_v.mp4"
            if to_vertical(str(out), str(vout), vertical_mode):
                out = vout
        
        clips.append(str(out))
    
    return clips

# ============ MAIN ============

def main(url, backend="vugola", num_clips=3, duration=30, vertical=False, 
         subtitles=False, quality="high", vertical_mode="crop", min_length=30, max_length=60):
    print(f"\n=== CLIPFORGE AI ===")
    print(f"URL: {url}")
    print(f"Backend: {backend.upper()}")
    print(f"Clips: {num_clips} x {duration}s")
    print(f"Vertical: {vertical} | Subs: {subtitles} | Quality: {quality}\n")
    
    if backend == "vugola":
        # Use Vugola AI
        result = vugola_clip(url, num_clips, min_length, max_length)
        if not result:
            # Fallback to local
            print("Falling back to local processing...")
            backend = "local"
        else:
            return result
    
    if backend == "local" or backend == "local":
        # Local processing
        video = download(url)
        if not video:
            return {"error": "Download failed"}
        
        clips = local_clip(video, num_clips, duration, vertical, subtitles, quality, vertical_mode)
        
        # Cleanup
        try: 
            os.remove(video)
            for f in OUTPUT_DIR.glob("audio.*"):
                f.unlink()
        except: pass
        
        print(f"\nâœ… Done! {len(clips)} clips")
        for c in clips:
            size_mb = os.path.getsize(c) / 1024 / 1024
            print(f"  ðŸ“¹ {Path(c).name} ({size_mb:.1f}MB)")
        
        return {"success": True, "clips": [{"path": c} for c in cl], "backend": "local"}

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="ClipForge AI")
    p.add_argument("url", help="Video URL")
    p.add_argument("--backend", choices=["vugola", "local"], default="vugola",
                   help="Backend: vugola (AI, virality scores) or local (your own Whisper)")
    p.add_argument("--clips", type=int, default=3)
    p.add_argument("--duration", type=int, default=30)
    p.add_argument("--min-length", type=int, default=30, help="Vugola: min clip length")
    p.add_argument("--max-length", type=int, default=60, help="Vugola: max clip length")
    p.add_argument("--vertical", action="store_true", help="Convert to 9:16")
    p.add_argument("--vertical-mode", choices=["crop", "pad"], default="crop")
    p.add_argument("--subtitles", "-s", action="store_true", help="Add Whisper subtitles (local only)")
    p.add_argument("--quality", choices=["high", "medium", "low"], default="high")
    
    a = p.parse_args()
    result = main(
        a.url, backend=a.backend, num_clips=a.clips, duration=a.duration,
        vertical=a.vertical, subtitles=a.subtitles, quality=a.quality,
        vertical_mode=a.vertical_mode, min_length=a.min_length, max_length=a.max_length
    )
    print(json.dumps(result, indent=2))