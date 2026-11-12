"""Build a 9:16 Reel from the post slides (one cut per slide), optional music."""
import random
import shutil
import subprocess
import sys

import config
import render

FPS = 30
# Instagram's Reels spec: H.264 4:2:0, closed GOP, keyframe every 2 s; AAC at most 48 kHz and 128 kbps
IG_VIDEO = ["-c:v", "libx264", "-preset", "slow", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-g", str(FPS * 2), "-maxrate", "12M", "-bufsize", "24M"]
IG_AUDIO = ["-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k"]


def ffmpeg_exe():
    """System ffmpeg, else the copy bundled with the imageio-ffmpeg package."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def slideshow(slides, out_path, workdir, voices=None):
    """slides: [(post image, seconds)] or [(post image, seconds, (video, overlay png))] -> 9:16 reel, one scene per
    slide, with music. A scene with a clip plays that video (muted, filling the frame) under its text overlay; the
    others show the post slide still.

    voices: optional [(wav, seconds) or None] per slide; a scene stays up until its narration has finished, and the
    music is turned down under the voice.
    """
    voices = voices or [None] * len(slides)
    lead, tail = 0.3, 0.6  # silence before / after each narration clip
    timing = [max(slide[1], round(lead + v[1] + tail, 2)) if v else slide[1] for slide, v in zip(slides, voices)]
    inputs, chain, n = [], [], 0  # n: ffmpeg input number of the next input
    for i, ((image, _, *clip), seconds) in enumerate(zip(slides, timing)):
        clip = clip[0] if clip else None
        if clip:
            video, overlay = clip
            inputs += ["-stream_loop", "-1", "-t", str(seconds), "-i", str(video),
                       "-loop", "1", "-framerate", str(FPS), "-t", str(seconds), "-i", str(overlay)]
            chain.append(f"[{n}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                         f"fps={FPS},setsar=1,format=yuv420p[bg{i}]")
            chain.append(f"[bg{i}][{n + 1}:v]overlay=0:0:shortest=1,setsar=1,format=yuv420p[s{i}]")
            n += 2
        else:
            frame = render.reel_frame(image, workdir / f"reel_frame{i}.jpg")
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", str(seconds), "-i", str(frame)]
            chain.append(f"[{n}:v]setsar=1,format=yuv420p[s{i}]")
            n += 1
    cuts = "".join(f"[s{i}]" for i in range(len(slides)))
    chain.append(f"{cuts}concat=n={len(slides)}:v=1:a=0,format=yuv420p[vout]")
    total = round(sum(timing), 2)
    moving = any(len(slide) > 2 and slide[2] for slide in slides)

    music = sorted(config.MUSIC_DIR.glob("*.mp3")) if config.MUSIC_DIR.exists() else []
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(random.choice(music))]
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    narrated = any(voices)
    chain.append(f"[{n}:a]atrim=0:{total},volume={0.18 if narrated else 0.6}[music]")
    n += 1
    mix, start = ["[music]"], 0.0
    for i, (clip, seconds) in enumerate(zip(voices, timing)):
        if clip:
            inputs += ["-i", str(clip[0])]
            delay = int((start + lead) * 1000)
            chain.append(f"[{n}:a]aresample=44100,aformat=channel_layouts=stereo,"
                         f"adelay={delay}|{delay},volume=1.6[v{i}]")
            mix.append(f"[v{i}]")
            n += 1
        start += seconds
    chain.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,"
                 f"afade=t=out:st={max(total - 1, 0)}:d=1[aout]")

    _run([
        ffmpeg_exe(), "-y", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(chain),
        "-map", "[vout]", "-map", "[aout]", "-t", str(total),
        *IG_VIDEO, "-crf", "18" if moving else "17", *([] if moving else ["-tune", "stillimage"]), *IG_AUDIO,
        "-movflags", "+faststart", str(out_path),
    ])
    return out_path


def instagram_safe(video_path):
    """A plainer re-encode for when Meta can't process a reel: the same settings as the still videos that
    upload fine (x264 defaults, CRF 21, 44.1 kHz AAC), with the bitrate capped."""
    out = video_path.with_name(video_path.stem + "-safe.mp4")
    _run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(video_path),
          "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-maxrate", "6M", "-bufsize", "12M",
          "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-ar", "44100", "-b:a", "128k",
          "-movflags", "+faststart", str(out)])
    return out


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
