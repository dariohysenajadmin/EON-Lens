"""
lens_video.py - video extraction library for Lens.

Wraps yt-dlp + ffmpeg + Whisper to turn any video URL or local file into:
  - timestamped transcript (list of cues)
  - frame screenshots (list of base64-encoded JPEGs, with timestamps)
  - composite frame-grid image via lens_grid (single-image vision strategy)
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


# YouTube extractor args - bypasses JS runtime requirement on cloud envs
YT_EXTRACTOR_ARGS = "youtube:player_client=tv,web_safari,mweb"


@dataclass
class VideoCue:
    start: float
    end: float
    text: str

    def clock(self) -> str:
        return _fmt_clock(self.start)


@dataclass
class VideoFrame:
    index: int
    timestamp: float
    path: Path
    base64_jpeg: str

    def clock(self) -> str:
        return _fmt_clock(self.timestamp)


@dataclass
class VideoData:
    title: str
    source: str
    duration: float
    transcript: list
    frames: list
    transcript_source: str
    work_dir: Path

    def transcript_text(self, start: float = 0.0, end: Optional[float] = None) -> str:
        end = end if end is not None else self.duration
        lines = []
        for cue in self.transcript:
            if cue.end < start or cue.start > end:
                continue
            lines.append(f"[{cue.clock()}] {cue.text}")
        return "\n".join(lines)

    def frame_grid_base64(self, max_size_kb: int = 3500):
        from lens_grid import build_frame_grid
        return build_frame_grid(self.frames, max_size_kb=max_size_kb)


def extract_video_data(
    source: str,
    *,
    max_frames: int = 30,
    start: float = 0.0,
    end: Optional[float] = None,
    output_root="data",
    progress: Optional[Callable[[str], None]] = None,
) -> VideoData:
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    def _say(msg):
        if progress:
            progress(msg)

    _check_dependencies()

    with tempfile.TemporaryDirectory(prefix="lens-dl-") as tmp:
        tmpdir = Path(tmp)
        _say("Resolving video source...")
        meta = _resolve_source(source, tmpdir, _say)
        out_dir = output_root / meta["video_id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        frames_dir = out_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        duration = meta["duration"]
        end_t = duration if end is None else min(end, duration)
        start_t = max(0.0, start)
        if end_t <= start_t:
            end_t = duration

        _say("Building transcript...")
        cues, transcript_source = _build_transcript(meta, tmpdir, _say)

        _say(f"Extracting up to {max_frames} frames...")
        frames = _extract_frames(
            video_path=meta["video_path"],
            duration=duration,
            start=start_t,
            end=end_t,
            max_frames=max_frames,
            frames_dir=frames_dir,
        )

    meta_blob = {
        "title": meta["title"],
        "source": source,
        "duration": duration,
        "transcript_source": transcript_source,
        "frame_count": len(frames),
        "cue_count": len(cues),
        "extracted_at": int(time.time()),
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta_blob, indent=2))

    _say("Done.")
    return VideoData(
        title=meta["title"],
        source=source,
        duration=duration,
        transcript=cues,
        frames=frames,
        transcript_source=transcript_source,
        work_dir=out_dir,
    )


def _check_dependencies():
    missing = [b for b in ("yt-dlp", "ffmpeg", "ffprobe") if not shutil.which(b)]
    if missing:
        raise RuntimeError(f"Missing required binaries: {', '.join(missing)}.")


def _resolve_source(source, tmpdir, say):
    if source.startswith(("http://", "https://", "www.")):
        return _download_url(source, tmpdir, say)
    p = Path(source).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Local file not found: {source}")
    duration = _probe_duration(p)
    return {"title": p.stem, "video_id": _slugify(p.stem),
            "duration": duration, "video_path": p, "captions_path": None}


def _download_url(url, tmpdir, say):
    say("Fetching video metadata via yt-dlp...")
    meta_proc = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-playlist", "--skip-download",
         "--extractor-args", YT_EXTRACTOR_ARGS, url],
        capture_output=True, text=True,
    )
    if meta_proc.returncode != 0:
        raise RuntimeError(f"yt-dlp metadata fetch failed:\n{meta_proc.stderr}")
    meta = json.loads(meta_proc.stdout.splitlines()[0])
    video_id = meta.get("id") or _slugify(meta.get("title", "video"))
    title = meta.get("title", video_id)
    duration = float(meta.get("duration") or 0.0)

    say(f"Downloading: {title}")
    out_template = str(tmpdir / f"{video_id}.%(ext)s")
    dl = subprocess.run(
        ["yt-dlp", "-f", "bv*[height<=720]+ba/b[height<=720]/best",
         "--merge-output-format", "mp4", "--write-auto-subs", "--write-subs",
         "--sub-langs", "en,en-orig,en-US", "--sub-format", "vtt",
         "--extractor-args", YT_EXTRACTOR_ARGS,
         "--no-playlist", "-o", out_template, url],
        capture_output=True, text=True,
    )
    if dl.returncode != 0:
        say("Subtitles unavailable - retrying without captions...")
        dl = subprocess.run(
            ["yt-dlp", "-f", "bv*[height<=720]+ba/b[height<=720]/best",
             "--merge-output-format", "mp4",
             "--extractor-args", YT_EXTRACTOR_ARGS,
             "--no-playlist", "-o", out_template, url],
            capture_output=True, text=True,
        )
        if dl.returncode != 0:
            raise RuntimeError(f"yt-dlp download failed:\n{dl.stderr}")

    video_path = None
    captions_path = None
    for f in tmpdir.iterdir():
        if not f.name.startswith(video_id):
            continue
        if f.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}:
            video_path = f
        elif f.suffix.lower() == ".vtt":
            captions_path = f
    if not video_path:
        raise RuntimeError("yt-dlp completed but no video file produced.")
    if duration == 0.0:
        duration = _probe_duration(video_path)
    return {"title": title, "video_id": video_id, "duration": duration,
            "video_path": video_path, "captions_path": captions_path}


def _probe_duration(path):
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def _build_transcript(meta, tmpdir, say):
    captions_path = meta.get("captions_path")
    if captions_path and Path(captions_path).exists():
        say("Using free YouTube captions...")
        cues = _parse_vtt(Path(captions_path))
        if cues:
            return cues, "youtube_captions"
    say("Extracting audio for Whisper transcription...")
    audio_path = tmpdir / "audio.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(meta["video_path"]),
         "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(audio_path)],
        capture_output=True,
    )
    if not audio_path.exists():
        return [], "none"
    say("Transcribing with Groq Whisper...")
    try:
        cues = _whisper_groq(audio_path)
        return cues, "whisper"
    except Exception as e:
        say(f"Whisper failed: {e}")
        return [], "none"


def _parse_vtt(path):
    cues = []
    text = path.read_text(encoding="utf-8", errors="replace")
    timing_re = re.compile(r"(\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}\.\d{3})")
    blocks = re.split(r"\n\s*\n", text)
    for block in blocks:
        m = timing_re.search(block)
        if not m:
            continue
        start = _vtt_to_seconds(m.group(1))
        end_t = _vtt_to_seconds(m.group(2))
        lines = []
        for ln in block.splitlines():
            if timing_re.search(ln) or ln.strip().startswith(("WEBVTT", "NOTE", "STYLE")):
                continue
            ln = re.sub(r"<[^>]+>", "", ln).strip()
            if ln:
                lines.append(ln)
        if not lines:
            continue
        cue_text = " ".join(lines)
        if cues and cues[-1].text.endswith(cue_text):
            continue
        cues.append(VideoCue(start=start, end=end_t, text=cue_text))
    return cues


def _vtt_to_seconds(stamp):
    h, m, s = stamp.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _whisper_groq(audio):
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set.")
    import requests
    with audio.open("rb") as f:
        resp = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            data={"model": "whisper-large-v3-turbo",
                  "response_format": "verbose_json",
                  "timestamp_granularities[]": "segment"},
            files={"file": (audio.name, f, "audio/mpeg")},
            timeout=600,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Groq transcription failed ({resp.status_code}): {resp.text}")
    segments = resp.json().get("segments") or []
    return [VideoCue(start=float(s["start"]), end=float(s["end"]), text=s["text"].strip())
            for s in segments]


def _extract_frames(*, video_path, duration, start, end, max_frames, frames_dir):
    window = max(1.0, end - start)
    target = min(max_frames, max(8, int(window // 6)))
    interval = window / target
    frames = []
    for i in range(target):
        t = start + interval * (i + 0.5)
        if t >= duration:
            break
        out_path = frames_dir / f"frame_{i+1:04d}_{int(t)//60:02d}m{int(t)%60:02d}s.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(video_path),
             "-frames:v", "1", "-vf", "scale='min(1024,iw)':-2", "-q:v", "5",
             str(out_path)],
            capture_output=True,
        )
        if out_path.exists():
            with out_path.open("rb") as fh:
                b64 = base64.standard_b64encode(fh.read()).decode("ascii")
            frames.append(VideoFrame(index=i + 1, timestamp=t, path=out_path, base64_jpeg=b64))
    return frames


def _fmt_clock(seconds):
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _slugify(s, max_len=60):
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", s).strip("-").lower()
    return s[:max_len] or "video"
