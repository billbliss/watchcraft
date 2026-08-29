#!/usr/bin/env python3
"""Local-first, resumable transcription and analysis for educational videos."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}
REMOTE_DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo-q4"
ANALYSIS_MODEL_ENV = "VIDEO_CATALOG_ANALYSIS_MODEL"
BUILTIN_ANALYSIS_MODEL = "gpt-5-nano"
LOCAL_DEFAULT_MODEL = (
    Path(__file__).resolve().parent / "models" / "whisper-large-v3-turbo-q4"
)


def default_model() -> str:
    if (LOCAL_DEFAULT_MODEL / "weights.npz").is_file():
        return str(LOCAL_DEFAULT_MODEL)
    return REMOTE_DEFAULT_MODEL


def default_analysis_model() -> str:
    return os.environ.get(ANALYSIS_MODEL_ENV, BUILTIN_ANALYSIS_MODEL)
CATALOG_DIR_NAME = "Video Catalog"
AUTHORING_CONFIG_NAME = "watchcraft-authoring.json"
DOMAIN_PROMPT = (
    "Advanced landscape photography instruction. Adobe Photoshop, Adobe Camera Raw, "
    "ACR, luminosity masks, layer masks, manual exposure blending, clone paint, "
    "History Brush, History Select, Puppet Warp, transform, dodge and burn, "
    "tonal color adjustments, directional light, sun star, focus stacking, "
    "panorama stitching, sky replacement, flare removal."
)


def catalog_root(root: Path) -> Path:
    """Return the metadata directory for legacy libraries or authoring workspaces."""
    if (root / AUTHORING_CONFIG_NAME).is_file():
        return root
    return root / CATALOG_DIR_NAME


@dataclass(frozen=True)
class VideoInfo:
    relative_path: str
    size_bytes: int
    duration_seconds: float | None


def discover_videos(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in VIDEO_EXTENSIONS
            and CATALOG_DIR_NAME not in path.parts
        ),
        key=lambda path: str(path.relative_to(root)).casefold(),
    )


def probe_duration(video: Path) -> float | None:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def inventory(root: Path, include_duration: bool = True) -> list[VideoInfo]:
    records: list[VideoInfo] = []
    for video in discover_videos(root):
        records.append(
            VideoInfo(
                relative_path=str(video.relative_to(root)),
                size_bytes=video.stat().st_size,
                duration_seconds=probe_duration(video) if include_duration else None,
            )
        )
    return records


def format_clock(seconds: float, *, srt: bool = False) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        seconds = 0
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = "," if srt else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def segment_text(segment: dict[str, Any]) -> str:
    return " ".join(str(segment.get("text", "")).strip().split())


def looks_repetitive(text: str) -> bool:
    tokens = re.findall(r"[a-z0-9']+", text.casefold())
    if len(tokens) < 30:
        return False
    counts = Counter(tokens)
    unique_ratio = len(counts) / len(tokens)
    dominant_ratio = counts.most_common(1)[0][1] / len(tokens)
    return unique_ratio < 0.2 or dominant_ratio > 0.5


def clean_segments(
    segments: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for segment in segments:
        text = segment_text(segment)
        if not text or looks_repetitive(text):
            rejected.append(segment)
        else:
            accepted.append(segment)
    return accepted, rejected


def render_srt(segments: Iterable[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for segment in segments:
        text = segment_text(segment)
        if not text:
            continue
        start = format_clock(float(segment.get("start", 0)), srt=True)
        end = format_clock(float(segment.get("end", 0)), srt=True)
        index = len(blocks) + 1
        blocks.append(f"{index}\n{start} --> {end}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def render_readable_transcript(segments: Iterable[dict[str, Any]]) -> str:
    lines: list[str] = []
    for segment in segments:
        text = segment_text(segment)
        if text:
            lines.append(f"[{format_clock(float(segment.get('start', 0)))}] {text}")
    return "\n".join(lines) + ("\n" if lines else "")


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def output_paths(root: Path, video: Path) -> tuple[Path, Path, Path]:
    relative = video.relative_to(root)
    transcript_root = catalog_root(root) / "transcripts"
    srt_path = transcript_root / relative.with_suffix(".srt")
    text_path = transcript_root / relative.with_suffix(".transcript.txt")
    state_path = transcript_root / relative.with_suffix(
        ".transcript.json"
    )
    return srt_path, text_path, state_path


def migrate_transcript_sidecars(root: Path, *, dry_run: bool = False) -> tuple[int, int]:
    """Move legacy video-adjacent transcript files into the central transcript tree."""
    moved = 0
    already_central = 0
    for video in discover_videos(root):
        targets = output_paths(root, video)[:2]
        sources = (video.with_suffix(".srt"), video.with_suffix(".transcript.txt"))
        for source, target in zip(sources, targets):
            if target.exists():
                if source.exists():
                    raise RuntimeError(
                        f"Both legacy and centralized transcript files exist: {source}"
                    )
                already_central += 1
                continue
            if not source.exists():
                continue
            moved += 1
            if dry_run:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
    return moved, already_central


def resolve_video(root: Path, requested: str) -> Path:
    candidate = Path(requested).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("The selected video must be inside the collection root") from error
    if not candidate.is_file() or candidate.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError(f"Not a supported video file: {candidate}")
    return candidate


def transcribe_video(root: Path, video: Path, model: str, force: bool) -> str:
    srt_path, text_path, state_path = output_paths(root, video)
    if not force and srt_path.exists() and text_path.exists() and state_path.exists():
        return "skipped"

    try:
        import mlx_whisper
    except ImportError as error:
        raise RuntimeError(
            "mlx-whisper is not installed. Install requirements.txt in the project environment."
        ) from error

    result = mlx_whisper.transcribe(
        str(video),
        path_or_hf_repo=model,
        language="en",
        task="transcribe",
        word_timestamps=True,
        initial_prompt=DOMAIN_PROMPT,
        condition_on_previous_text=False,
        hallucination_silence_threshold=2.0,
        verbose=False,
    )
    raw_segments = list(result.get("segments", []))
    segments, discarded_segments = clean_segments(raw_segments)
    atomic_write_text(srt_path, render_srt(segments))
    atomic_write_text(text_path, render_readable_transcript(segments))

    payload = {
        "schema_version": 1,
        "video": str(video.relative_to(root)),
        "model": model,
        "language": result.get("language"),
        "text": " ".join(segment_text(segment) for segment in segments),
        "segments": segments,
        "discarded_segments": discarded_segments,
    }
    atomic_write_text(
        state_path,
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2) + "\n",
    )
    return "completed"


def validated_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise argparse.ArgumentTypeError(f"Collection folder does not exist: {root}")
    return root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory_parser = subparsers.add_parser(
        "inventory", help="List videos without changing them"
    )
    inventory_parser.add_argument("--root", required=True, type=validated_root)
    inventory_parser.add_argument(
        "--fast", action="store_true", help="Skip duration probing"
    )
    inventory_parser.add_argument("--json", type=Path, help="Optional inventory output")

    transcribe_parser = subparsers.add_parser(
        "transcribe", help="Create centralized local transcript files"
    )
    transcribe_parser.add_argument("--root", required=True, type=validated_root)
    selection = transcribe_parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--video", help="One absolute or root-relative video path")
    selection.add_argument("--all", action="store_true", help="Process every video")
    transcribe_parser.add_argument("--model", default=default_model())
    transcribe_parser.add_argument("--force", action="store_true")

    analyze_parser = subparsers.add_parser(
        "analyze", help="Create searchable summaries and timelines"
    )
    analyze_parser.add_argument("--root", required=True, type=validated_root)
    analyze_selection = analyze_parser.add_mutually_exclusive_group(required=True)
    analyze_selection.add_argument(
        "--video", help="One absolute or root-relative video path"
    )
    analyze_selection.add_argument(
        "--all", action="store_true", help="Analyze every completed transcript"
    )
    analyze_parser.add_argument(
        "--analysis-model",
        default=default_analysis_model(),
        help=f"Analysis/summarization model (env: {ANALYSIS_MODEL_ENV})",
    )
    analyze_parser.add_argument(
        "--limit", type=int, help="Process at most this many transcripts"
    )
    analyze_parser.add_argument(
        "--retries", type=int, default=5, help="Retries for a failed API request"
    )
    analyze_parser.add_argument(
        "--timeout", type=float, default=300, help="API timeout in seconds"
    )
    analyze_parser.add_argument(
        "--max-transcript-chars", type=int, default=1_500_000
    )
    analyze_parser.add_argument("--force", action="store_true")
    analyze_parser.add_argument(
        "--dry-run", action="store_true", help="Report pending work without API calls"
    )
    analyze_parser.add_argument(
        "--no-rebuild", action="store_true", help="Do not update collection/CSV after each video"
    )

    process_parser = subparsers.add_parser(
        "process", help="Transcribe and analyze the same unfinished videos"
    )
    process_parser.add_argument("--root", required=True, type=validated_root)
    process_selection = process_parser.add_mutually_exclusive_group(required=True)
    process_selection.add_argument(
        "--video", help="One absolute or root-relative video path"
    )
    process_selection.add_argument(
        "--all", action="store_true", help="Process unfinished videos"
    )
    process_parser.add_argument(
        "--limit", type=int, help="Process at most this many unfinished videos"
    )
    process_parser.add_argument(
        "--transcription-model", default=default_model(), help="MLX Whisper model"
    )
    process_parser.add_argument(
        "--analysis-model",
        default=default_analysis_model(),
        help=f"Analysis/summarization model (env: {ANALYSIS_MODEL_ENV})",
    )
    process_parser.add_argument(
        "--retries", type=int, default=5, help="Retries for a failed API request"
    )
    process_parser.add_argument(
        "--timeout", type=float, default=300, help="API timeout in seconds"
    )
    process_parser.add_argument(
        "--max-transcript-chars", type=int, default=1_500_000
    )
    process_parser.add_argument("--force-transcription", action="store_true")
    process_parser.add_argument("--force-analysis", action="store_true")
    process_parser.add_argument(
        "--dry-run", action="store_true", help="Show the paired plan without doing work"
    )
    process_parser.add_argument(
        "--no-rebuild", action="store_true", help="Do not update collection/CSV after analysis"
    )

    migration_parser = subparsers.add_parser(
        "migrate-transcripts",
        help="Move legacy video-adjacent SRT/text files into Video Catalog",
    )
    migration_parser.add_argument("--root", required=True, type=validated_root)
    migration_parser.add_argument(
        "--dry-run", action="store_true", help="Report files without moving them"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "inventory":
        records = inventory(args.root, include_duration=not args.fast)
        total_bytes = sum(record.size_bytes for record in records)
        total_duration = sum(record.duration_seconds or 0 for record in records)
        summary = {
            "root": str(args.root),
            "video_count": len(records),
            "total_bytes": total_bytes,
            "total_duration_seconds": total_duration,
            "videos": [asdict(record) for record in records],
        }
        if args.json:
            atomic_write_text(
                args.json.resolve(), json.dumps(summary, indent=2) + "\n"
            )
        print(
            f"{len(records)} videos | {total_bytes / 2**30:.1f} GiB | "
            f"{total_duration / 3600:.1f} hours"
        )
        return 0

    if args.command == "transcribe":
        videos = (
            discover_videos(args.root)
            if args.all
            else [resolve_video(args.root, args.video)]
        )
        for index, video in enumerate(videos, start=1):
            relative = video.relative_to(args.root)
            print(f"[{index}/{len(videos)}] {relative}", flush=True)
            status = transcribe_video(args.root, video, args.model, args.force)
            print(f"  {status}", flush=True)
        return 0

    if args.command == "analyze":
        if args.limit is not None and args.limit < 1:
            raise ValueError("--limit must be at least 1")
        if args.retries < 0:
            raise ValueError("--retries cannot be negative")
        if args.max_transcript_chars < 1:
            raise ValueError("--max-transcript-chars must be positive")
        from analyze_catalog import run_from_args

        return run_from_args(args)

    if args.command == "process":
        if args.limit is not None and args.limit < 1:
            raise ValueError("--limit must be at least 1")
        if args.retries < 0:
            raise ValueError("--retries cannot be negative")
        if args.max_transcript_chars < 1:
            raise ValueError("--max-transcript-chars must be positive")
        from process_catalog import run_from_args

        return run_from_args(args)

    if args.command == "migrate-transcripts":
        moved, already_central = migrate_transcript_sidecars(
            args.root, dry_run=args.dry_run
        )
        action = "would move" if args.dry_run else "moved"
        print(
            f"{action} {moved} transcript files | "
            f"{already_central} already centralized"
        )
        return 0

    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
