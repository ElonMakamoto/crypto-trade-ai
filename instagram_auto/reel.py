"""Build a 9:16 Reel: slow zoom on the photo, headline + story lines, optional music."""
import random
import shutil
import subprocess
import sys

import config
import render

FPS = 30


def ffmpeg_exe():
    """System ffmpeg, else the copy bundled with the imageio-ffmpeg package."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def build_reel(photos, pick, workdir, out_path):
    """photos: one path or a list; each story line gets the next photo with its own slow zoom."""
    photos = photos if isinstance(photos, list) else [photos]
    seconds = config.REEL_SECONDS
    lines = [l for l in (pick.get("reel_lines") or []) if l][:3] or [""]
    seg_frames = seconds * FPS // len(lines)

    inputs, chain = [], []
    for i, line in enumerate(lines):
        bg = render.reel_background(photos[i % len(photos)], workdir / f"reel_bg{i}.jpg")
        ov = render.reel_overlay(pick["headline"], pick.get("highlight"), line, workdir / f"reel_ov{i}.png")
        inputs += ["-i", str(bg), "-loop", "1", "-i", str(ov)]
        # Ken Burns zoom on this segment's photo, with its story line on top
        chain.append(f"[{2 * i}:v]scale=1296:2304,zoompan=z='min(zoom+0.0009,1.2)':d={seg_frames}"
                     f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={FPS},setsar=1[b{i}]")
        chain.append(f"[b{i}][{2 * i + 1}:v]overlay=0:0:shortest=1[s{i}]")
    chain.append("".join(f"[s{i}]" for i in range(len(lines))) + f"concat=n={len(lines)}:v=1:a=0,format=yuv420p[vout]")

    music = sorted(config.MUSIC_DIR.glob("*.mp3")) if config.MUSIC_DIR.exists() else []
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(random.choice(music))]
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    audio_idx = 2 * len(lines)
    afilter = f"[{audio_idx}:a]afade=t=out:st={seconds - 1}:d=1,volume=0.6[aout]"

    cmd = [
        ffmpeg_exe(), "-y", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(chain + [afilter]),
        "-map", "[vout]", "-map", "[aout]", "-t", str(seconds),
        "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out_path),
    ]
    _run(cmd)
    return out_path


def still_video(image_path, out_path, seconds=6):
    """A short silent-audio video of one image (for posting a design through the Reels API)."""
    _run([ffmpeg_exe(), "-y", "-loglevel", "error", "-loop", "1", "-i", str(image_path),
          "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
          "-t", str(seconds), "-r", str(FPS), "-vf", "scale=1080:-2,format=yuv420p",
          "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-tune", "stillimage",
          "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out_path)])
    return out_path


def extract_cover(video_path, out_path, at=1.0):
    """9:16 cover frame for the reel (also used as the upload thumbnail)."""
    _run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", str(at), "-i", str(video_path),
          "-frames:v", "1", "-q:v", "2", str(out_path)])
    return out_path


def _run(cmd):
    # no console window flashing up from the desktop app
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
    if result.returncode:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[-500:]}")
