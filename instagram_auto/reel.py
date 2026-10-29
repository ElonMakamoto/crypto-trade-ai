"""Build a 9:16 Reel: slow zoom on the photo, headline + story lines, optional music."""
import random
import subprocess

import config
import render

FPS = 30


def build_reel(photo_path, pick, workdir, out_path):
    seconds = config.REEL_SECONDS
    lines = [l for l in (pick.get("reel_lines") or []) if l][:3] or [""]
    bg = render.reel_background(photo_path, workdir / "reel_bg.jpg")
    overlays = [
        render.reel_overlay(pick["headline"], pick.get("highlight"), line, workdir / f"reel_ov{i}.png")
        for i, line in enumerate(lines)
    ]

    frames = seconds * FPS
    seg = seconds / len(overlays)
    inputs = ["-loop", "1", "-i", str(bg)]
    for ov in overlays:
        inputs += ["-loop", "1", "-i", str(ov)]

    music = sorted(config.MUSIC_DIR.glob("*.mp3")) if config.MUSIC_DIR.exists() else []
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(random.choice(music))]
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    audio_idx = len(overlays) + 1

    # Ken Burns zoom, then swap the overlay for each story line
    chain = [
        f"[0:v]scale=1296:2304,zoompan=z='min(zoom+0.0009,1.2)':d={frames}"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={FPS}[v0]"
    ]
    for i in range(len(overlays)):
        start, end = i * seg, (i + 1) * seg
        chain.append(f"[v{i}][{i + 1}:v]overlay=0:0:enable='between(t,{start:.2f},{end:.2f})'[v{i + 1}]")
    chain.append(f"[v{len(overlays)}]format=yuv420p[vout]")
    afilter = f"[{audio_idx}:a]afade=t=out:st={seconds - 1}:d=1,volume=0.6[aout]"

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(chain + [afilter]),
        "-map", "[vout]", "-map", "[aout]", "-t", str(seconds),
        "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out_path),
    ]
    subprocess.run(cmd, check=True)
    return out_path
