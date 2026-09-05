"""Stream YouTube audio into the local Whisper authoring pipeline."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

from video_catalog import clean_segments, segment_text


SAMPLE_RATE = 16_000
MIN_USEFUL_SPEECH_SECONDS = 3.0
YOUTUBE_ORIGINAL_AUDIO_FORMAT = "bestaudio[format_note*=original]/bestaudio/best"


class YouTubeAcquisitionError(RuntimeError):
    """A classified failure to acquire one public YouTube audio stream."""

    def __init__(self, message: str, classification: str, retryable: bool):
        super().__init__(message)
        self.classification = classification
        self.retryable = retryable


class NoSpeechDetected(RuntimeError):
    """The audio contains too little speech to author from."""

    def __init__(self, audio_seconds: float, speech_seconds: float):
        super().__init__(
            f"only {speech_seconds:.1f}s of speech detected in "
            f"{audio_seconds:.1f}s of audio"
        )
        self.audio_seconds = audio_seconds
        self.speech_seconds = speech_seconds


def youtube_video_id(value: str) -> str:
    """Return one stable video ID from supported YouTube URL forms or an ID."""
    candidate = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        return candidate
    parsed = urllib.parse.urlparse(candidate)
    host = (parsed.hostname or "").casefold()
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        if parsed.path == "/watch":
            video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/embed/", "/shorts/", "/live/")):
            video_id = parsed.path.rstrip("/").split("/")[-1]
        else:
            video_id = ""
    else:
        video_id = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError(f"Not a recognizable YouTube video URL or ID: {value}")
    return video_id


def canonical_youtube_url(value: str) -> str:
    return f"https://www.youtube.com/watch?v={youtube_video_id(value)}"


def yt_dlp_command(executable: str | None = None) -> list[str]:
    """Use the yt-dlp module installed beside the active Python by default."""
    if executable:
        return [executable]
    return [sys.executable, "-m", "yt_dlp"]


def command_version(command: list[str]) -> str:
    try:
        result = subprocess.run(
            [*command, "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            "yt-dlp is unavailable. Reinstall authoring/requirements.txt in the "
            "Python 3.13 authoring environment."
        ) from error
    return result.stdout.strip()


def yt_dlp_audio_command(url: str, command: list[str]) -> list[str]:
    """Build a yt-dlp stream command with Node available for YouTube challenges."""
    return [
        *command,
        "--ignore-config",
        "--quiet",
        "--no-warnings",
        "--no-playlist",
        "--js-runtimes",
        "node",
        "--format",
        YOUTUBE_ORIGINAL_AUDIO_FORMAT,
        "--output",
        "-",
        url,
    ]


def yt_dlp_audio_download_command(
    url: str,
    command: list[str],
    destination: Path,
    maximum_bytes: int,
) -> list[str]:
    """Build a deterministic, single-item original-audio download command."""
    metadata_template = (
        'after_move:{"video_id":%(id)j,"duration":%(duration)j,'
        '"format_id":%(format_id)j,"language":%(language)j,'
        '"extension":%(ext)j}'
    )
    return [
        *command,
        "--ignore-config",
        "--quiet",
        "--no-warnings",
        "--no-playlist",
        "--js-runtimes",
        "node",
        "--format",
        YOUTUBE_ORIGINAL_AUDIO_FORMAT,
        "--max-filesize",
        str(maximum_bytes),
        "--output",
        str(destination),
        "--print",
        metadata_template,
        url,
    ]


def classify_youtube_acquisition_failure(message: str) -> tuple[str, bool]:
    normalized = message.casefold()
    if "http error 429" in normalized or "too many requests" in normalized:
        return "source_rate_limited", True
    if any(
        marker in normalized
        for marker in (
            "please sign in",
            "sign in to confirm",
            "age-restricted",
            "members-only",
            "private video",
        )
    ):
        return "source_access_denied", False
    if "video unavailable" in normalized or "has been removed" in normalized:
        return "source_unavailable", False
    return "source_acquisition_failed", True


def download_youtube_audio(
    value: str,
    destination: Path,
    *,
    maximum_bytes: int,
    maximum_duration_seconds: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Acquire one public original audio stream and return its observed identity."""
    video_id = youtube_video_id(value)
    url = canonical_youtube_url(video_id)
    if maximum_bytes < 1 or maximum_duration_seconds < 1 or timeout_seconds < 1:
        raise ValueError("YouTube acquisition limits must be positive")
    command = yt_dlp_command()
    try:
        version = command_version(command)
    except RuntimeError as error:
        raise YouTubeAcquisitionError(
            str(error), "worker_dependency_missing", False
        ) from error
    download_command = yt_dlp_audio_download_command(
        url,
        command,
        destination,
        maximum_bytes,
    )
    try:
        completed = subprocess.run(
            download_command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        destination.unlink(missing_ok=True)
        raise YouTubeAcquisitionError(
            f"YouTube audio acquisition timed out after {timeout_seconds}s",
            "source_acquisition_timeout",
            True,
        ) from error
    except OSError as error:
        destination.unlink(missing_ok=True)
        raise YouTubeAcquisitionError(
            f"Could not start yt-dlp: {error}",
            "worker_dependency_missing",
            False,
        ) from error
    if completed.returncode != 0:
        destination.unlink(missing_ok=True)
        detail = " ".join(completed.stderr.split())[:400]
        classification, retryable = classify_youtube_acquisition_failure(detail)
        raise YouTubeAcquisitionError(
            f"yt-dlp could not acquire YouTube audio: {detail or 'unknown error'}",
            classification,
            retryable,
        )
    if not destination.is_file():
        raise YouTubeAcquisitionError(
            "yt-dlp completed without producing an audio file",
            "source_media_rejected",
            False,
        )

    byte_length = destination.stat().st_size
    if byte_length < 1 or byte_length > maximum_bytes:
        destination.unlink(missing_ok=True)
        raise YouTubeAcquisitionError(
            f"YouTube audio has {byte_length} bytes; limit is {maximum_bytes}",
            "source_media_rejected",
            False,
        )
    try:
        metadata = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        destination.unlink(missing_ok=True)
        raise YouTubeAcquisitionError(
            "yt-dlp returned invalid acquisition metadata",
            "source_acquisition_failed",
            True,
        ) from error
    duration = metadata.get("duration") if isinstance(metadata, dict) else None
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or duration <= 0
        or duration > maximum_duration_seconds
    ):
        destination.unlink(missing_ok=True)
        raise YouTubeAcquisitionError(
            f"YouTube audio duration {duration!r}s exceeds or violates the "
            f"{maximum_duration_seconds}s limit",
            "source_media_rejected",
            False,
        )
    if metadata.get("video_id") != video_id:
        destination.unlink(missing_ok=True)
        raise YouTubeAcquisitionError(
            "yt-dlp returned media for a different YouTube video",
            "source_identity_mismatch",
            False,
        )

    digest = hashlib.sha256()
    with destination.open("rb") as source:
        while chunk := source.read(64 * 1024):
            digest.update(chunk)
    return {
        "provider": "youtube",
        "video_id": video_id,
        "canonical_url": url,
        "yt_dlp_version": version,
        "format_id": metadata.get("format_id"),
        "audio_language": metadata.get("language"),
        "container": metadata.get("extension"),
        "duration_seconds": round(float(duration), 3),
        "algorithm": "sha256",
        "digest": digest.hexdigest(),
        "byte_length": byte_length,
    }


def stream_youtube_audio(url: str, command: list[str]) -> Any:
    """Decode a remote audio stream into an in-memory mono float32 waveform."""
    try:
        import numpy as np
    except ImportError as error:
        raise RuntimeError("numpy is required by the Whisper environment") from error

    source_command = yt_dlp_audio_command(url, command)
    decode_command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        "pipe:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-acodec",
        "pcm_f32le",
        "-f",
        "f32le",
        "pipe:1",
    ]
    with tempfile.TemporaryFile() as source_stderr:
        try:
            source = subprocess.Popen(
                source_command,
                stdout=subprocess.PIPE,
                stderr=source_stderr,
            )
        except OSError as error:
            raise RuntimeError(f"Could not start yt-dlp: {error}") from error
        if source.stdout is None:
            source.kill()
            raise RuntimeError("Could not open the yt-dlp audio stream")
        try:
            try:
                decoder = subprocess.run(
                    decode_command,
                    stdin=source.stdout,
                    capture_output=True,
                )
            except OSError as error:
                raise RuntimeError(f"Could not start FFmpeg: {error}") from error
            finally:
                source.stdout.close()
            source_status = source.wait()
            source_stderr.seek(0)
            source_error = source_stderr.read().decode(
                "utf-8", errors="replace"
            ).strip()
        finally:
            if source.poll() is None:
                source.kill()
                source.wait()

    if source_status != 0:
        detail = f": {source_error}" if source_error else ""
        raise RuntimeError(f"yt-dlp could not stream the audio{detail}")
    if decoder.returncode != 0:
        decoder_error = decoder.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg could not decode the audio stream: {decoder_error}")
    waveform = np.frombuffer(decoder.stdout, dtype=np.float32).copy()
    if not waveform.size:
        raise RuntimeError("YouTube produced an empty audio stream")
    return waveform


def merge_speech_ranges(
    ranges: list[tuple[float, float]],
    *,
    maximum_gap_seconds: float = 2.0,
) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in ranges:
        if end <= start:
            continue
        if merged and start - merged[-1][1] <= maximum_gap_seconds:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def detect_speech_ranges(audio: Any) -> list[tuple[float, float]]:
    try:
        import torch
        from silero_vad import get_speech_timestamps, load_silero_vad
    except ImportError as error:
        raise RuntimeError(
            "Silero VAD could not be loaded. Reinstall authoring/requirements.txt."
        ) from error

    model = load_silero_vad()
    timestamps = get_speech_timestamps(
        torch.from_numpy(audio),
        model,
        sampling_rate=SAMPLE_RATE,
        min_speech_duration_ms=250,
        min_silence_duration_ms=1_500,
        speech_pad_ms=500,
    )
    ranges = [
        (float(timestamp["start"]) / SAMPLE_RATE, float(timestamp["end"]) / SAMPLE_RATE)
        for timestamp in timestamps
    ]
    return merge_speech_ranges(ranges)


def youtube_audio_transcript(
    video_id: str,
    language: str,
    model: str,
    *,
    executable: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Generate a transcript without retaining the source audio or video."""
    try:
        import mlx_whisper
    except ImportError as error:
        raise RuntimeError(
            "MLX Whisper could not be loaded. Install authoring/requirements.txt "
            "and run authoring on an Apple Silicon Mac with Metal available."
        ) from error

    command = yt_dlp_command(executable)
    version = command_version(command)
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"  streaming audio with yt-dlp {version}", flush=True)
    audio = stream_youtube_audio(url, command)
    audio_seconds = len(audio) / SAMPLE_RATE
    speech_ranges = detect_speech_ranges(audio)
    speech_seconds = sum(end - start for start, end in speech_ranges)
    if speech_seconds < MIN_USEFUL_SPEECH_SECONDS:
        raise NoSpeechDetected(audio_seconds, speech_seconds)
    speech_percentage = speech_seconds / audio_seconds * 100
    print(
        f"  detected {speech_seconds:.1f}s of speech in {len(speech_ranges)} "
        f"range(s) ({speech_percentage:.1f}% of {audio_seconds:.1f}s)",
        flush=True,
    )
    clip_timestamps = [value for speech_range in speech_ranges for value in speech_range]
    print("  transcribing speech ranges with local Whisper", flush=True)
    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=model,
        language=language,
        task="transcribe",
        word_timestamps=True,
        # Bound runtime for music-heavy instructional videos instead of retrying
        # every low-confidence window at five successively higher temperatures.
        temperature=0.0,
        condition_on_previous_text=False,
        hallucination_silence_threshold=2.0,
        clip_timestamps=clip_timestamps,
        verbose=False,
    )
    del audio
    segments, discarded_segments = clean_segments(list(result.get("segments", [])))
    return segments, {
        "source": "youtube-audio",
        "language": result.get("language") or language,
        "model": model,
        "url": url,
        "yt_dlp_version": version,
        "audio_duration_seconds": round(audio_seconds, 3),
        "speech_duration_seconds": round(speech_seconds, 3),
        "speech_range_count": len(speech_ranges),
        "speech_coverage": round(speech_seconds / audio_seconds, 4),
        "audio_retained": False,
    }, discarded_segments
