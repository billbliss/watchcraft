#!/usr/bin/env python3
"""Compare a private Whisper transcript from YouTube audio with its captions."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from video_catalog import (
    default_model,
    render_readable_transcript,
    render_srt,
)
from watchcraft_author import youtube_transcript, youtube_video_id
from youtube_audio import (
    SAMPLE_RATE,
    command_version,
    detect_speech_ranges,
    stream_youtube_audio,
    yt_dlp_command,
)



def normalized_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.casefold())


def transcript_comparison(caption_text: str, whisper_text: str) -> dict[str, Any]:
    caption_words = normalized_words(caption_text)
    whisper_words = normalized_words(whisper_text)
    matcher = difflib.SequenceMatcher(
        None,
        caption_words,
        whisper_words,
        autojunk=False,
    )
    return {
        "caption_word_count": len(caption_words),
        "whisper_word_count": len(whisper_words),
        "word_count_difference": len(whisper_words) - len(caption_words),
        "sequence_similarity": round(matcher.ratio(), 4),
        "matching_words": sum(match.size for match in matcher.get_matching_blocks()),
    }


def whisper_transcript(
    audio: Any,
    model: str,
    language: str,
    clip_timestamps: list[float],
) -> dict[str, Any]:
    try:
        import mlx_whisper
    except ImportError as error:
        raise RuntimeError(
            "mlx-whisper is not installed. Install authoring/requirements.txt."
        ) from error

    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=model,
        language=language,
        task="transcribe",
        word_timestamps=True,
        temperature=0.0,
        condition_on_previous_text=False,
        hallucination_silence_threshold=2.0,
        clip_timestamps=clip_timestamps,
        verbose=False,
    )
    from video_catalog import clean_segments, segment_text

    segments, discarded_segments = clean_segments(list(result.get("segments", [])))
    return {
        "language": result.get("language") or language,
        "segments": segments,
        "discarded_segments": discarded_segments,
        "text": " ".join(segment_text(segment) for segment in segments),
    }


def load_caption_transcript(
    video_id: str,
    language: str,
    transcript_path: Path | None,
) -> tuple[dict[str, Any], str]:
    if transcript_path is not None:
        payload = json.loads(transcript_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list):
            raise ValueError(f"Invalid caption transcript: {transcript_path}")
        return payload, str(transcript_path)

    segments, metadata = youtube_transcript(video_id, language)
    payload = {
        "schema_version": 1,
        "video": f"{video_id}.youtube",
        "model": "youtube-captions",
        "language": metadata["language"],
        "text": " ".join(segment["text"] for segment in segments),
        "segments": segments,
        "discarded_segments": [],
        "provenance": metadata,
    }
    return payload, "downloaded YouTube captions"


def caption_path_for_workspace(workspace: Path | None, video_id: str) -> Path | None:
    if workspace is None:
        return None
    candidate = workspace.expanduser().resolve() / "transcripts" / f"{video_id}.transcript.json"
    return candidate if candidate.is_file() else None


def excerpt(text: str, limit: int = 700) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else f"{compact[:limit].rstrip()}…"


def render_report(
    *,
    video_id: str,
    url: str,
    caption_source: str,
    caption_text: str,
    whisper_text: str,
    comparison: dict[str, Any],
    elapsed_seconds: float,
    audio_seconds: float,
    yt_dlp_version: str,
    model: str,
) -> str:
    similarity = comparison["sequence_similarity"] * 100
    return (
        "# YouTube audio transcription PoC\n\n"
        f"- Video: [{video_id}]({url})\n"
        f"- Caption source: `{caption_source}`\n"
        f"- yt-dlp: `{yt_dlp_version}`\n"
        f"- Whisper model: `{model}`\n"
        f"- Audio duration: {audio_seconds:.1f} seconds\n"
        f"- Audio streaming + transcription time: {elapsed_seconds:.1f} seconds\n"
        f"- Caption words: {comparison['caption_word_count']}\n"
        f"- Whisper words: {comparison['whisper_word_count']}\n"
        f"- Word-count difference: {comparison['word_count_difference']:+d}\n"
        f"- Ordered word-sequence similarity: {similarity:.1f}%\n\n"
        "## Caption excerpt\n\n"
        f"{excerpt(caption_text)}\n\n"
        "## Whisper excerpt\n\n"
        f"{excerpt(whisper_text)}\n"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="YouTube video URL or ID")
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Use a cached caption transcript from this authoring workspace",
    )
    parser.add_argument(
        "--caption-transcript",
        type=Path,
        help="Use this existing caption transcript JSON instead of downloading captions",
    )
    parser.add_argument("--language", default="en")
    parser.add_argument("--model", default=default_model())
    parser.add_argument(
        "--yt-dlp",
        help=(
            "Override the yt-dlp executable; by default the tool runs the yt_dlp "
            "module installed in the active Python environment"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Private result directory; defaults to the system temporary directory",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    video_id = youtube_video_id(args.video)
    url = f"https://www.youtube.com/watch?v={video_id}"
    caption_path = args.caption_transcript or caption_path_for_workspace(
        args.workspace,
        video_id,
    )
    output_dir = args.output_dir or (
        Path(tempfile.gettempdir()) / "watchcraft-youtube-audio-poc" / video_id
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    yt_dlp = yt_dlp_command(args.yt_dlp)
    yt_dlp_version = command_version(yt_dlp)
    captions, caption_source = load_caption_transcript(
        video_id,
        args.language,
        caption_path,
    )
    caption_text = str(captions.get("text") or " ".join(
        str(segment.get("text") or "") for segment in captions["segments"]
    ))

    print(f"Streaming audio with yt-dlp {yt_dlp_version}…", flush=True)
    started = time.monotonic()
    audio = stream_youtube_audio(url, yt_dlp)
    audio_seconds = len(audio) / SAMPLE_RATE
    speech_ranges = detect_speech_ranges(audio)
    speech_seconds = sum(end - start for start, end in speech_ranges)
    clip_timestamps = [value for speech_range in speech_ranges for value in speech_range]
    print(
        f"Transcribing {speech_seconds:.1f}s of detected speech from "
        f"{audio_seconds:.1f}s of audio with Whisper…",
        flush=True,
    )
    whisper = whisper_transcript(
        audio,
        args.model,
        args.language,
        clip_timestamps,
    )
    elapsed_seconds = time.monotonic() - started
    comparison = transcript_comparison(caption_text, whisper["text"])

    whisper_payload = {
        "schema_version": 1,
        "video": f"{video_id}.youtube",
        "model": args.model,
        "language": whisper["language"],
        "text": whisper["text"],
        "segments": whisper["segments"],
        "discarded_segments": whisper["discarded_segments"],
        "provenance": {
            "source": "youtube-audio-stream",
            "url": url,
            "yt_dlp_version": yt_dlp_version,
            "audio_retained": False,
        },
    }
    (output_dir / "whisper.transcript.json").write_text(
        json.dumps(whisper_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "whisper.transcript.txt").write_text(
        render_readable_transcript(whisper["segments"]),
        encoding="utf-8",
    )
    (output_dir / "whisper.srt").write_text(
        render_srt(whisper["segments"]),
        encoding="utf-8",
    )
    comparison_payload = {
        "video_id": video_id,
        "url": url,
        "caption_source": caption_source,
        "yt_dlp_version": yt_dlp_version,
        "whisper_model": args.model,
        "audio_seconds": round(audio_seconds, 3),
        "elapsed_seconds": round(elapsed_seconds, 3),
        **comparison,
    }
    (output_dir / "comparison.json").write_text(
        json.dumps(comparison_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "comparison.md").write_text(
        render_report(
            video_id=video_id,
            url=url,
            caption_source=caption_source,
            caption_text=caption_text,
            whisper_text=whisper["text"],
            comparison=comparison,
            elapsed_seconds=elapsed_seconds,
            audio_seconds=audio_seconds,
            yt_dlp_version=yt_dlp_version,
            model=args.model,
        ),
        encoding="utf-8",
    )
    print(f"Comparison written to {output_dir}", flush=True)
    print(f"Ordered word-sequence similarity: {comparison['sequence_similarity'] * 100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
