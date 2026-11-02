"""Build a 9:16 Reel from the post slides (one cut per slide), optional music."""
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


def slideshow(slides, out_path, workdir):
    """slides: [(post image, seconds)] -> 9:16 reel showing each post slide in turn, with a slow zoom and music."""
    inputs, chain = [], []
    for i, (image, seconds) in enumerate(slides):
        frame = render.reel_frame(image, workdir / f"reel_frame{i}.jpg")
        inputs += ["-i", str(frame)]
        frames = round(seconds * FPS)
        chain.append(f"[{i}:v]scale=1188:2112,zoompan=z='min(zoom+0.0006,1.06)':d={frames}"
                     f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={FPS},setsar=1[s{i}]")
    chain.append("".join(f"[s{i}]" for i in range(len(slides))) + f"concat=n={len(slides)}:v=1:a=0,format=yuv420p[vout]")
    total = sum(seconds for _, seconds in slides)

    music = sorted(config.MUSIC_DIR.glob("*.mp3")) if config.MUSIC_DIR.exists() else []
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(random.choice(music))]
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    afilter = f"[{len(slides)}:a]afade=t=out:st={total - 1}:d=1,volume=0.6[aout]"

    _run([
        ffmpeg_exe(), "-y", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(chain + [afilter]),
        "-map", "[vout]", "-map", "[aout]", "-t", str(total),
        "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out_path),
    ])
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
