# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import BinaryIO

from .storage import Ledger

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
ASPECTS = {
    "vertical": (1080, 1920),
    "square": (1080, 1080),
    "landscape": (1920, 1080),
}
MAX_UPLOAD_BYTES = 2_000_000_000
MAX_CLIP_SECONDS = 180


def media_root() -> Path:
    root = Ledger().home / "media"
    (root / "uploads").mkdir(parents=True, exist_ok=True)
    (root / "clips").mkdir(parents=True, exist_ok=True)
    (root / "thumbnails").mkdir(parents=True, exist_ok=True)
    return root


def media_tools_ready() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def store_upload(source: BinaryIO, filename: str, content_length: int) -> dict[str, object]:
    if content_length <= 0 or content_length > MAX_UPLOAD_BYTES:
        raise ValueError("Video upload must be between 1 byte and 2 GB.")
    suffix = Path(filename).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise ValueError("Choose an MP4, MOV, M4V, WebM, or MKV video.")
    file_id = uuid.uuid4().hex[:12]
    root = media_root()
    destination = root / "uploads" / f"{file_id}{suffix}"
    remaining = content_length
    try:
        with destination.open("wb") as output:
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("Upload ended before all video data arrived.")
                output.write(chunk)
                remaining -= len(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    try:
        duration = probe_duration(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    metadata = {"id": file_id, "filename": Path(filename).name, "size": content_length, "uploaded_at": time.time()}
    (root / "uploads" / f"{file_id}.json").write_text(json.dumps(metadata), encoding="utf-8")
    return {**metadata, "duration": duration, "url": f"/media/uploads/{file_id}{suffix}"}


def uploaded_video(file_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", file_id):
        raise ValueError("Invalid source video ID.")
    folder = media_root() / "uploads"
    matches = [path for path in folder.glob(f"{file_id}.*") if path.suffix.lower() in VIDEO_EXTENSIONS]
    if len(matches) != 1 or not matches[0].is_file():
        raise FileNotFoundError("Source video not found.")
    return matches[0]


def probe_duration(path: Path) -> float:
    binary = shutil.which("ffprobe")
    if not binary:
        raise RuntimeError("ffprobe is required. Install FFmpeg and restart GUADE.")
    result = subprocess.run(
        [binary, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    duration = float(json.loads(result.stdout)["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Could not read a valid duration from this video.")
    return duration


def render_clip(file_id: str, start: float, end: float, aspect: str) -> dict[str, object]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required. Install FFmpeg and restart GUADE.")
    if aspect not in ASPECTS:
        raise ValueError("Choose vertical, square, or landscape output.")
    source = uploaded_video(file_id)
    duration = probe_duration(source)
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError("Clip end time must be after its start time.")
    clip_duration = end - start
    if clip_duration > MAX_CLIP_SECONDS:
        raise ValueError("Clips are limited to 180 seconds.")
    if end > duration:
        raise ValueError(f"Clip end time exceeds source duration ({duration:.1f} seconds).")
    width, height = ASPECTS[aspect]
    output_id = uuid.uuid4().hex[:12]
    destination = media_root() / "clips" / f"{output_id}.mp4"
    scale_crop = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
        "-t",
        f"{clip_duration:.3f}",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        scale_crop,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "21",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "-y",
        str(destination),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True, timeout=300)
    except subprocess.CalledProcessError as exc:
        destination.unlink(missing_ok=True)
        detail = exc.stderr.strip()[-1200:] or "FFmpeg could not render this clip."
        raise RuntimeError(detail) from exc
    return {
        "id": output_id,
        "filename": destination.name,
        "duration": round(clip_duration, 2),
        "aspect": aspect,
        "size": destination.stat().st_size,
        "url": f"/media/clips/{destination.name}",
    }


def store_thumbnail(source: BinaryIO, filename: str, content_length: int) -> dict[str, object]:
    if content_length <= 0 or content_length > 20_000_000:
        raise ValueError("Thumbnail must be between 1 byte and 20 MB.")
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(filename).stem).strip("-")[:60] or "thumbnail"
    output_name = f"{int(time.time())}-{safe_stem}-{uuid.uuid4().hex[:6]}.png"
    destination = media_root() / "thumbnails" / output_name
    remaining = content_length
    try:
        with destination.open("wb") as output:
            while remaining:
                chunk = source.read(min(256 * 1024, remaining))
                if not chunk:
                    raise ValueError("Thumbnail upload ended early.")
                output.write(chunk)
                remaining -= len(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    with destination.open("rb") as image_file:
        if image_file.read(8) != b"\x89PNG\r\n\x1a\n":
            destination.unlink(missing_ok=True)
            raise ValueError("Thumbnail data is not a PNG image.")
    return {"filename": output_name, "size": content_length, "url": f"/media/thumbnails/{output_name}"}


def media_file(kind: str, filename: str) -> Path | None:
    root = media_root()
    if kind == "uploads" and re.fullmatch(r"[a-f0-9]{12}\.(mp4|mov|m4v|webm|mkv)", filename):
        path = root / "uploads" / filename
    elif kind == "clips" and re.fullmatch(r"[a-f0-9]{12}\.mp4", filename):
        path = root / "clips" / filename
    elif kind == "thumbnails" and re.fullmatch(r"[0-9]+-[a-zA-Z0-9_-]+-[a-f0-9]{6}\.png", filename):
        path = root / "thumbnails" / filename
    else:
        return None
    return path if path.is_file() else None
