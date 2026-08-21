#!/usr/bin/env python3
"""Repair missing video timelines without changing other analysis metadata."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from analyze_catalog import (
    DEFAULT_MAX_TRANSCRIPT_CHARS,
    TIMELINE_REPAIR_PROMPT_VERSION,
    analysis_path,
    clock_seconds,
    create_openai_client,
    discover_transcript_states,
    load_transcript_state,
    request_timeline_repair,
    selected_states,
    source_context,
    transcript_text,
    unique_strings,
)
from build_catalog import write_catalog
from video_catalog import atomic_write_text, default_analysis_model, validated_root


def transcript_duration(state: dict) -> str:
    segments = state.get("segments") or []
    seconds = max(
        (float(segment.get("end", 0)) for segment in segments if isinstance(segment, dict)),
        default=0,
    )
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def pending_repairs(root: Path, requested_video: str | None, force: bool) -> list[Path]:
    states = (
        selected_states(root, requested_video)
        if requested_video
        else discover_transcript_states(root)
    )
    pending = []
    for state_path in states:
        state = load_transcript_state(state_path)
        output = analysis_path(root, state["video"])
        if not output.is_file():
            continue
        analysis = json.loads(output.read_text(encoding="utf-8"))
        if force or not analysis.get("sections"):
            pending.append(state_path)
    return pending


def repair_one(
    root: Path,
    state_path: Path,
    *,
    client: object,
    model: str,
    retries: int,
    max_transcript_chars: int,
) -> int:
    state = load_transcript_state(state_path)
    relative_video = state["video"]
    output = analysis_path(root, relative_video)
    analysis = json.loads(output.read_text(encoding="utf-8"))
    transcript = transcript_text(state)
    if len(transcript) > max_transcript_chars:
        raise RuntimeError(
            f"Transcript is {len(transcript):,} characters, exceeding the configured "
            f"limit of {max_transcript_chars:,}; increase --max-transcript-chars"
        )
    generated = request_timeline_repair(
        client,
        model=model,
        context=source_context(root, relative_video),
        existing_analysis=analysis,
        transcript=transcript,
        transcript_duration=transcript_duration(state),
        retries=retries,
    )
    sections = [section.model_dump() for section in generated.sections]
    for section in sections:
        section["concepts"] = unique_strings(section["concepts"], maximum=15)
    sections.sort(key=lambda section: clock_seconds(section["start"]))
    analysis["sections"] = sections
    analysis["timeline_repair_model"] = model
    analysis["timeline_repair_prompt_version"] = TIMELINE_REPAIR_PROMPT_VERSION
    analysis["timeline_repaired_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_text(
        output, json.dumps(analysis, ensure_ascii=False, indent=2) + "\n"
    )
    return len(sections)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=validated_root)
    parser.add_argument("--video", help="Repair one video by relative path")
    parser.add_argument("--analysis-model", default=default_analysis_model())
    parser.add_argument("--limit", type=int)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument(
        "--max-transcript-chars", type=int, default=DEFAULT_MAX_TRANSCRIPT_CHARS
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-rebuild", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    pending = pending_repairs(args.root, args.video, args.force)
    if args.limit is not None:
        pending = pending[: args.limit]
    print(
        f"{len(pending)} missing timeline(s) selected | model {args.analysis_model}",
        flush=True,
    )
    if args.dry_run or not pending:
        for path in pending:
            print(f"  {load_transcript_state(path)['video']}")
        return 0
    client = create_openai_client(args.timeout)
    for index, state_path in enumerate(pending, start=1):
        video = load_transcript_state(state_path)["video"]
        print(f"Repairing {index}/{len(pending)}: {video}", flush=True)
        count = repair_one(
            args.root,
            state_path,
            client=client,
            model=args.analysis_model,
            retries=args.retries,
            max_transcript_chars=args.max_transcript_chars,
        )
        print(f"  saved {count} sections", flush=True)
    if not args.no_rebuild:
        write_catalog(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
