"""
lens_video.py - video extraction library for Lens.

YouTube URLs route through Supadata API (bypasses cloud-IP blocking).
Other URLs use yt-dlp. Local files use ffmpeg directly.
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


def extract_video_data(source, *, max_frames=30, start=0.0, end=None,
                      output_root="data", progress=None):
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    def _say(msg):
        if progress:
            progress(msg)

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

        if meta.get("is_supadata"):
            _say("Using YouTube thumbnail as visual reference...")
            frames = _frames_from_thumbnail(meta["thumbnail_path"], frames_dir)
        else:
            _say(f"Extracting up to {max_frames} frames...")
            frames = _extract_frames(
                video_path=meta["video_path"], duration=duration,
                start=start_t, end=end_t, max_frames=max_frames,
                frames_dir=frames_dir,
            )

    meta_blob = {
        "title": meta["title"], "source": source, "duration": duration,
        "transcript_source": transcript_source,
        "frame_count": len(frames), "cue_count": len(cues),
        "extracted_at": int(time.time()),
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta_blob, indent=2))

    _say("Done.")
    return VideoData(
        title=meta["title"], source=source, duration=duration,
        transcript=cues, frames=frames,
        transcript_source=transcript_source, work_dir=out_dir,
    )


def _resolve_source(source, tmpdir, say):
    if source.startswith(("http://", "https://", "www.")):
        if "youtube" in source or "youtu.be" in source:
            yt = _try_supadata(source, tmpdir, say)
            if yt:
                return yt
            say("Supadata failed, trying Cobalt + Whisper fallback...")
            yt = _try_cobalt(source, tmpdir, say)
            if yt:
                return yt
            say("Cobalt failed, trying yt-dlp as last resort...")
        return _download_url(source, tmpdir, say)

    p = Path(source).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Local file not found: {source}")
    duration = _probe_duration(p)
    return {"title": p.stem, "video_id": _slugify(p.stem),
            "duration": duration, "video_path": p, "captions_path": None}


def _try_supadata(url, tmpdir, say):
    api_key = os.environ.get("SUPADATA_API_KEY")
    if not api_key:
        say("SUPADATA_API_KEY env var is EMPTY - check Streamlit secrets.")
        return None
    say(f"Supadata key present (len={len(api_key)}, starts {api_key[:4]}...).")

    m = re.search(r"(?:v=|/embed/|/shorts/|/v/|youtu\.be/)([0-9A-Za-z_-]{11})", url)
    if not m:
        say("Could not parse YouTube ID from URL.")
        return None
    yt_id = m.group(1)

    import requests
    endpoint = "https://api.supadata.ai/v1/transcript"

    def _call(mode):
        say(f"Calling Supadata universal transcript API (mode={mode}) for {yt_id}...")
        try:
            r = requests.get(
                endpoint,
                params={"url": url, "mode": mode, "text": "false"},
                headers={"x-api-key": api_key},
                timeout=60,
            )
        except Exception as e:
            say(f"Supadata HTTP error: {e}")
            return None
        if r.status_code not in (200, 202):
            say(f"Supadata returned HTTP {r.status_code}: {r.text[:300]}")
            return None
        try:
            return r.json()
        except Exception as e:
            say(f"Supadata JSON parse failed: {e}; body: {r.text[:200]}")
            return None

    data = _call("auto")
    if data is None:
        return None

    # Async job: {"jobId": "..."} means audio is being transcribed via Whisper
    if "jobId" in data and not (data.get("content") or data.get("transcript")):
        job_id = data["jobId"]
        say(f"Supadata is transcribing audio via Whisper (job {job_id[:8]}...). This may take 30-120s.")
        data = _supadata_poll_job(job_id, api_key, say)
        if not data:
            return None

    segments = data.get("content") or data.get("transcript") or []

    # mode=auto returned empty - force ASR with mode=generate
    if not segments:
        say(f"mode=auto returned empty (keys: {list(data.keys())}). Forcing ASR with mode=generate...")
        data = _call("generate")
        if data is None:
            return None
        if "jobId" in data and not (data.get("content") or data.get("transcript")):
            job_id = data["jobId"]
            say(f"ASR job started (job {job_id[:8]}...). This may take 30-120s.")
            data = _supadata_poll_job(job_id, api_key, say)
            if not data:
                return None
        segments = data.get("content") or data.get("transcript") or []

    if not segments:
        say(f"Supadata returned no segments even with mode=generate. Keys: {list(data.keys())}. Likely quota exhausted on Supadata free tier.")
        return None
    say(f"Supadata returned {len(segments)} transcript segments.")

    cues = []
    for s in segments:
        offset = s.get("offset")
        if offset is not None:
            start_s = float(offset) / 1000.0
        else:
            start_s = float(s.get("start", 0))
        dur_raw = s.get("duration", 2.0)
        if isinstance(dur_raw, (int, float)) and dur_raw > 100:
            dur_s = float(dur_raw) / 1000.0
        else:
            dur_s = float(dur_raw)
        end_s = start_s + dur_s
        text = (s.get("text") or "").strip()
        if text:
            cues.append(VideoCue(start=start_s, end=end_s, text=text))

    if not cues:
        return None

    total_duration = cues[-1].end

    title = yt_id
    try:
        oembed = requests.get(
            f"https://www.youtube.com/oembed?url={url}&format=json", timeout=10
        )
        if oembed.status_code == 200:
            title = oembed.json().get("title", yt_id)
    except Exception:
        pass

    say("Fetching thumbnail...")
    thumb_path = tmpdir / f"{yt_id}_thumb.jpg"
    for variant in ("maxresdefault", "sddefault", "hqdefault", "mqdefault"):
        try:
            tr = requests.get(f"https://img.youtube.com/vi/{yt_id}/{variant}.jpg", timeout=15)
            if tr.status_code == 200 and len(tr.content) > 1000:
                thumb_path.write_bytes(tr.content)
                break
        except Exception:
            continue
    if not thumb_path.exists():
        return None

    captions_path = tmpdir / f"{yt_id}.vtt"
    _write_cues_as_vtt(cues, captions_path)

    return {
        "title": title, "video_id": yt_id, "duration": total_duration,
        "video_path": None, "captions_path": captions_path,
        "thumbnail_path": thumb_path, "is_supadata": True,
        "preloaded_cues": cues,
    }


def _try_cobalt(url, tmpdir, say):
    """Bypass YouTube bot-flagging via Cobalt's open-source downloader API.

    Cobalt (cobalt.tools) handles YouTube's bot detection server-side and
    returns a clean direct-download URL. We fetch the audio, run it through
    our existing Groq Whisper transcription, and use the YouTube thumbnail
    as the visual reference (same pattern as the Supadata path).

    Note: api.cobalt.tools is a community-run public instance with rate
    limits and bot protection. For heavy production use, self-host Cobalt
    on your own server (it's a small Node.js app).
    """
    import requests

    m = re.search(r"(?:v=|/embed/|/shorts/|/v/|youtu\.be/)([0-9A-Za-z_-]{11})", url)
    if not m:
        say("Could not parse YouTube ID from URL.")
        return None
    yt_id = m.group(1)

    # Prefer a self-hosted Cobalt URL via env var. The public api.cobalt.tools
    # now requires Turnstile auth, so it won't work without it. Self-hosted
    # instances are open by default.
    cobalt_base = os.environ.get("COBALT_API_URL", "https://api.cobalt.tools/")
    if not cobalt_base.endswith("/"):
        cobalt_base += "/"

    say(f"Calling Cobalt API ({cobalt_base}) for audio download of {yt_id}...")
    try:
        r = requests.post(
            cobalt_base,
            json={
                "url": url,
                "downloadMode": "audio",
                "audioFormat": "mp3",
                "audioBitrate": "128",
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "lens-video-intel/1.0",
            },
            timeout=45,
        )
    except Exception as e:
        say(f"Cobalt request failed: {e}")
        return None

    if r.status_code not in (200, 201):
        say(f"Cobalt returned HTTP {r.status_code}: {r.text[:300]}")
        return None

    try:
        data = r.json()
    except Exception as e:
        say(f"Cobalt JSON parse failed: {e}; body: {r.text[:200]}")
        return None

    status = (data.get("status") or "").lower()

    if status == "error":
        err = data.get("error") or {}
        code = err.get("code") if isinstance(err, dict) else str(err)
        say(f"Cobalt error: {code}")
        return None

    # Cobalt returns 'tunnel' (proxied download) or 'redirect' (direct CDN URL)
    # for simple audio cases. 'picker' and 'local-processing' are more complex
    # and we treat as failure for v1.
    if status not in ("tunnel", "redirect"):
        say(f"Cobalt returned unsupported status '{status}' (need tunnel or redirect).")
        return None

    download_url = data.get("url")
    if not download_url:
        say("Cobalt response missing download URL.")
        return None

    say("Downloading audio from Cobalt...")
    audio_path = tmpdir / f"{yt_id}_cobalt.mp3"
    try:
        with requests.get(
            download_url,
            stream=True,
            timeout=180,
            headers={"User-Agent": "lens-video-intel/1.0"},
        ) as audio_resp:
            audio_resp.raise_for_status()
            with audio_path.open("wb") as f:
                for chunk in audio_resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
    except Exception as e:
        say(f"Audio download failed: {e}")
        return None

    if not audio_path.exists() or audio_path.stat().st_size < 5000:
        say("Cobalt audio file is empty or truncated.")
        return None

    size_kb = audio_path.stat().st_size // 1024
    say(f"Got {size_kb}KB audio. Transcribing with Groq Whisper...")
    try:
        cues = _whisper_groq(audio_path)
    except Exception as e:
        say(f"Whisper transcription failed: {e}")
        return None

    if not cues:
        say("Whisper returned no transcript segments.")
        return None
    say(f"Whisper produced {len(cues)} transcript segments.")

    # Title via YouTube's oEmbed (works without auth)
    title = yt_id
    try:
        oembed = requests.get(
            f"https://www.youtube.com/oembed?url={url}&format=json", timeout=10
        )
        if oembed.status_code == 200:
            title = oembed.json().get("title", yt_id)
    except Exception:
        pass

    # Thumbnail for visual reference
    say("Fetching thumbnail...")
    thumb_path = tmpdir / f"{yt_id}_thumb.jpg"
    for variant in ("maxresdefault", "sddefault", "hqdefault", "mqdefault"):
        try:
            tr = requests.get(
                f"https://img.youtube.com/vi/{yt_id}/{variant}.jpg", timeout=15
            )
            if tr.status_code == 200 and len(tr.content) > 1000:
                thumb_path.write_bytes(tr.content)
                break
        except Exception:
            continue
    if not thumb_path.exists():
        say("Could not fetch YouTube thumbnail.")
        return None

    total_duration = max((c.end for c in cues), default=0.0)
    captions_path = tmpdir / f"{yt_id}.vtt"
    _write_cues_as_vtt(cues, captions_path)

    return {
        "title": title,
        "video_id": yt_id,
        "duration": total_duration,
        "video_path": None,
        "captions_path": captions_path,
        "thumbnail_path": thumb_path,
        "is_supadata": True,  # reuses the thumbnail-only frame path in extract_video_data
        "preloaded_cues": cues,
    }


def _supadata_poll_job(job_id, api_key, say, max_wait=180, interval=4):
    import requests
    endpoint = f"https://api.supadata.ai/v1/transcript/{job_id}"
    waited = 0
    while waited < max_wait:
        try:
            r = requests.get(endpoint, headers={"x-api-key": api_key}, timeout=30)
        except Exception as e:
            say(f"Supadata job poll error: {e}")
            return None
        if r.status_code != 200:
            say(f"Supadata job poll HTTP {r.status_code}: {r.text[:200]}")
            return None
        try:
            data = r.json()
        except Exception as e:
            say(f"Supadata job poll JSON error: {e}")
            return None
        status = (data.get("status") or "").lower()
        if data.get("content") or data.get("transcript") or status == "completed":
            return data
        if status in ("failed", "error"):
            err = data.get("error") or data.get("message") or str(data)[:200]
            say(f"Supadata job failed: {err}")
            return None
        say(f"Still transcribing... ({waited}s elapsed, status: {status or 'queued'})")
        time.sleep(interval)
        waited += interval
    say(f"Supadata job timed out after {max_wait}s.")
    return None


def _write_cues_as_vtt(cues, path):
    lines = ["WEBVTT", ""]
    for c in cues:
        lines.append(f"{_vtt_time(c.start)} --> {_vtt_time(c.end)}")
        lines.append(c.text.replace("\n", " "))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _vtt_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _frames_from_thumbnail(thumb_path, frames_dir):
    out_path = frames_dir / "frame_0001_00m00s.jpg"
    shutil.copy(str(thumb_path), str(out_path))
    with out_path.open("rb") as fh:
        b64 = base64.standard_b64encode(fh.read()).decode("ascii")
    return [VideoFrame(index=1, timestamp=0.0, path=out_path, base64_jpeg=b64)]


def _download_url(url, tmpdir, say):
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp not installed.")
    say("Fetching video metadata via yt-dlp...")
    meta_proc = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-playlist", "--skip-download", url],
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
         "--no-playlist", "-o", out_template, url],
        capture_output=True, text=True,
    )
    if dl.returncode != 0:
        say("Subtitles unavailable - retrying without captions...")
        dl = subprocess.run(
            ["yt-dlp", "-f", "bv*[height<=720]+ba/b[height<=720]/best",
             "--merge-output-format", "mp4", "--no-playlist",
             "-o", out_template, url],
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
    if meta.get("preloaded_cues"):
        return meta["preloaded_cues"], "youtube_captions"
    captions_path = meta.get("captions_path")
    if captions_path and Path(captions_path).exists():
        say("Using captions...")
        cues = _parse_vtt(Path(captions_path))
        if cues:
            return cues, "captions"
    if not meta.get("video_path"):
        return [], "none"
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
        return _whisper_groq(audio_path), "whisper"
    except Exception as e:
        say(f"Whisper failed: {e}")
        return [], "none"


def _parse_vtt(path):
    cues = []
    text = path.read_text(encoding="utf-8", errors="replace")
    timing_re = re.compile(r"(\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}\.\d{3})")
    for block in re.split(r"\n\s*\n", text):
        m = timing_re.search(block)
        if not m:
            continue
        start_s = _vtt_to_seconds(m.group(1))
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
        cues.append(VideoCue(start=start_s, end=end_t, text=cue_text))
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
            files={"file": (audio.name, f, "audio/mpeg")}, timeout=600,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Groq transcription failed ({resp.status_code}): {resp.text}")
    segs = resp.json().get("segments") or []
    return [VideoCue(start=float(s["start"]), end=float(s["end"]), text=s["text"].strip())
            for s in segs]


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
