#!/usr/bin/env python3
"""
ClipForge AI - Private Video Clipper with Subtitles
"""

import os
import sys
import json
import argparse
import subprocess
import tempfile
from pathlib import Path

# Fixed paths
YT_DLP = r"C:\Users\gibby\AppData\Roaming\Python\Python312\Scripts\yt-dlp.exe"
FFMPEG = r"C:\Users\gibby\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"
FFPROBE = r"C:\Users\gibby\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffprobe.exe"

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Whisper model - using faster-whisper for speed
WHISPER_MODEL = "base"  # tiny/base/small/medium/large

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
        # Use CPU with int8 for speed
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
        print("faster-whisper not installed. Install with: pip install faster-whisper")
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
    """Format seconds to SRT time format"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"

def burn_subtitles(video_path, srt_path, output_path, font="Arial", font_size=24, color="white"):
    """Burn subtitles into video using ffmpeg"""
    print("Burning subtitles...")
    # Position: bottom center with padding
    force_style = f"FontSize={font_size},PrimaryColour=&H{color},MarginV=20"
    
    cmd = f'''{FFMPEG} -y -i "{video_path}" -vf "subtitles='{srt_path}':force_style='{force_style}'" \
-c:v libx264 -preset fast -crf 18 -c:a aac -b:a 192k -movflags +faststart \
-pix_fmt yuv420p "{output_path}"'''
    
    r = run(cmd)
    if r.returncode != 0:
        print(f"Subtitle burn error: {r.stderr[-300:]}")
        return None
    return output_path

def clip(input_path, output_path, start, duration, quality="high"):
    """Extract clip with high quality settings"""
    print(f"Clip {start}s-{start+duration}s")
    
    # Quality presets
    if quality == "high":
        crf = "18"  # Lower = better quality
        preset = "slow"
        bitrate = "4M"
    elif quality == "medium":
        crf = "20"
        preset = "medium"
        bitrate = "2M"
    else:
        crf = "23"
        preset = "fast"
        bitrate = "1M"
    
    cmd = f'''{FFMPEG} -y -ss {start} -i "{input_path}" -t {duration} \
-c:v libx264 -preset {preset} -crf {crf} -b:v {bitrate} \
-c:a aac -b:a 192k -movflags +faststart \
-pix_fmt yuv420p "{output_path}"'''
    
    r = run(cmd)
    if r.returncode != 0:
        print(f"Error: {r.stderr[-300:]}")
        return None
    return output_path

def to_vertical(input_path, output_path, mode="pad"):
    """Convert to 9:16 vertical (1080x1920)
    
    Modes:
    - crop: center crop (loses sides)
    - pad: add blurred background (keeps full frame)
    """
    w, h = get_resolution(input_path)
    target_ratio = 9/16
    
    if mode == "crop":
        # Center crop (for YouTube Shorts - no bars)
        if w/h > target_ratio:
            new_w = int(h * target_ratio)
            crop = f"crop={new_w}:{h}:(iw-{new_w})/2:0"
        else:
            new_h = int(w / target_ratio)
            crop = f"crop={w}:{new_h}:0:(ih-{new_h})/2"
        
        vf = f"{crop},scale=1080:1920"
    else:
        # Pad mode - scale to fit, add blurred background
        # Scale to fit within 1080x1920
        scale = "scale='min(1080,iw)':min'~(1920,ih)':force_original_aspect_ratio=decrease"
        
        # Create blurred background
        bg = f"boxblur=50:10,scale=1080:1920"
        
        # Overlay scaled video centered
        overlay = "[bg][v]overlay=(W-w)/2:(H-h)/2"
        vf = f"{scale},setsar=1[v];{bg}{overlay}"
    
    cmd = f'''{FFMPEG} -y -i "{input_path}" -vf "{vf}" \
-c:v libx264 -preset fast -crf 18 -c:a aac -b:a 192k -movflags +faststart \
-pix_fmt yuv420p "{output_path}"'''
    
    r = run(cmd)
    if r.returncode != 0:
        print(f"Vertical error: {r.stderr[-300:]}")
        # Fallback: simple scale
        cmd = f'''{FFMPEG} -y -i "{input_path}" -vf "crop=1080:1920:(iw-1080)/2:0,scale=1080:1920" \
-c:v libx264 -preset fast -crf 18 -c:a aac -b:a 192k -movflags +faststart \
-pix_fmt yuv420p "{output_path}"'''
        r = run(cmd)
        if r.returncode != 0:
            print(f"Fallback error: {r.stderr[-300:]}")
            return None
    return output_path

def add_watermark(video_path, output_path, text="Shorts"):
    """Add subtle watermark"""
    cmd = f'''{FFMPEG} -y -i "{video_path}" -vf "drawtext=text='{text}':fontsize=14:fontcolor=white@0.5:x=10:y=h-20" \
-c:v libx264 -preset fast -crf 18 -c:a copy -movflags +faststart \
-pix_fmt yuv420p "{output_path}"'''
    
    r = run(cmd)
    if r.returncode != 0:
        return None
    return output_path

def detect_highlights(audio_path, num clips=3):
    """Simple highlight detection using audio volume spikes"""
    # This is a placeholder - real implementation would use audio analysis
    # For now, just divide video into equal segments
    dur = get_duration(audio_path)
    if not dur:
        return None
    
    gap = (dur - 30 * clips) / (clips + 1)
    positions = [gap + i * (30 + gap) for i in range(clips)]
    return positions

def main(url, num_clips=3, duration=30, vertical=False, subtitles=False, 
         highlight=False, quality="high", vertical_mode="crop"):
    print(f"\n=== CLIPFORGE AI ===\n{url}")
    print(f"Clips: {num_clips} x {duration}s | Vertical: {vertical} | Subs: {subtitles} | Quality: {quality}\n")
    
    # Download
    video = download(url)
    if not video:
        return {"error": "Download failed"}
    
    dur = get_duration(video)
    print(f"Duration: {dur}s")
    
    # Transcribe if needed for subtitles
    sub_data = None
    if subtitles:
        print("Generating subtitles...")
        # Extract audio for whisper
        audio_path = str(OUTPUT_DIR / "audio.wav")
        run(f'{FFMPEG} -y -i "{video}" -vn -acodec pcm_s16le -ar 16000 -ac 1 "{audio_path}"')
        
        sub_data = transcribe_whisper(audio_path)
        if sub_data:
            srt_path = OUTPUT_DIR / "subs.srt"
            create_srt(sub_data, srt_path)
            print(f"Subtitles saved: {srt_path}")
        else:
            print("Subtitle generation failed, continuing without")
    
    # Get clip positions (simpleå‡åŒ€åˆ†å¸ƒ for now)
    if highlight and dur:
        positions = detect_highlights(video, num_clips)
    else:
        gap = (dur - duration * num_clips) / (num_clips + 1) if dur else 0
        positions = [gap + i * (duration + gap) for i in range(num_clips)]
    
    # Generate clips
    clips = []
    for i, start in enumerate(positions):
        clip_name = f"clip_{i+1}.mp4"
        out = OUTPUT_DIR / clip_name
        
        # Extract clip
        if not clip(video, str(out), start, duration, quality):
            continue
        
        # Add subtitles if requested
        if subtitles and sub_data:
            # Get subtitles in this time range
            start_ts = start
            end_ts = start + duration
            segment_subs = [s for s in sub_data if s['start'] >= start_ts and s['end'] <= end_ts]
            
            if segment_subs:
                # Create segment-specific SRT
                seg_srt = OUTPUT_DIR / f"subs_{i+1}.srt"
                create_srt(segment_subs, str(seg_srt))
                
                # Burn into clip
                subbed = OUTPUT_DIR / f"clip_{i+1}_sub.mp4"
                if burn_subtitles(str(out), str(seg_srt), str(subbed)):
                    out = subbed
        
        # Convert to vertical if requested
        if vertical:
            vout = OUTPUT_DIR / f"clip_{i+1}_v.mp4"
            if to_vertical(str(out), str(vout), vertical_mode):
                out = vout
        
        clips.append(str(out))
    
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
    
    return {"success": True, "clips": clips}

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="ClipForge AI - Video Clipper")
    p.add_argument("url", help="YouTube or video URL")
    p.add_argument("--clips", type=int, default=3, help="Number of clips")
    p.add_argument("--duration", type=int, default=30, help="Clip duration in seconds")
    p.add_argument("--vertical", action="store_true", help="Convert to 9:16 vertical")
    p.add_argument("--vertical-mode", choices=["crop", "pad"], default="crop", 
                   help="Vertical mode: crop (fullscreen) or pad (letterbox)")
    p.add_argument("--subtitles", "-s", action="store_true", help="Add Whisper subtitles")
    p.add_argument("--highlight", action="store_true", help="Auto-detect highlights")
    p.add_argument("--quality", choices=["high", "medium", "low"], default="high")
    
    a = p.parse_args()
    result = main(
        a.url, 
        num_clips=a.clips, 
        duration=a.duration, 
        vertical=a.vertical,
        subtitles=a.subtitles,
        highlight=a.highlight,
        quality=a.quality,
        vertical_mode=a.vertical_mode
    )
    print(json.dumps(result, indent=2))