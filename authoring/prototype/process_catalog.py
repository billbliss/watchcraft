#!/usr/bin/env python3
"""Run transcription and structured analysis as one resumable pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from analyze_catalog import (
    analysis_path,
    analyze_state,
    create_openai_client,
    rebuild_catalog,
)
from video_catalog import discover_videos, output_paths, resolve_video, transcribe_video


@dataclass(frozen=True)
class ProcessItem:
    video: Path
    transcribe: bool
    analyze: bool

    @property
    def stages(self) -> str:
        if self.transcribe and self.analyze:
            return "transcribe + analyze"
        if self.transcribe:
            return "transcribe"
        return "analyze"


def inspect_video(
    root: Path,
    video: Path,
    *,
    force_transcription: bool = False,
    force_analysis: bool = False,
) -> ProcessItem:
    srt_path, text_path, state_path = output_paths(root, video)
    transcript_complete = all(
        path.is_file() for path in (srt_path, text_path, state_path)
    )
    needs_transcription = force_transcription or not transcript_complete
    output = analysis_path(root, video.relative_to(root).as_posix())
    # A newly generated transcript invalidates an older analysis of that video.
    needs_analysis = force_analysis or needs_transcription or not output.is_file()
    return ProcessItem(
        video=video, transcribe=needs_transcription, analyze=needs_analysis
    )


def select_work(
    root: Path,
    *,
    requested_video: str | None,
    limit: int | None,
    force_transcription: bool = False,
    force_analysis: bool = False,
) -> tuple[list[ProcessItem], int]:
    videos = (
        discover_videos(root)
        if requested_video is None
        else [resolve_video(root, requested_video)]
    )
    pending = [
        item
        for item in (
            inspect_video(
                root,
                video,
                force_transcription=force_transcription,
                force_analysis=force_analysis,
            )
            for video in videos
        )
        if item.transcribe or item.analyze
    ]
    total_pending = len(pending)
    if limit is not None:
        pending = pending[:limit]
    return pending, total_pending


def run_from_args(args: Any) -> int:
    work, total_pending = select_work(
        args.root,
        requested_video=args.video,
        limit=args.limit,
        force_transcription=args.force_transcription,
        force_analysis=args.force_analysis,
    )
    total_videos = len(discover_videos(args.root)) if args.video is None else 1
    print(
        f"{total_videos} videos | {total_pending} needing work | "
        f"{len(work)} selected",
        flush=True,
    )
    for index, item in enumerate(work, start=1):
        print(
            f"[{index}/{len(work)}] {item.video.relative_to(args.root)} "
            f"[{item.stages}]",
            flush=True,
        )
    if args.dry_run or not work:
        return 0

    client = create_openai_client(args.timeout)
    for index, item in enumerate(work, start=1):
        relative = item.video.relative_to(args.root)
        print(f"\n[{index}/{len(work)}] {relative}", flush=True)
        if item.transcribe:
            print("  transcribing…", flush=True)
            status = transcribe_video(
                args.root,
                item.video,
                args.transcription_model,
                args.force_transcription,
            )
            print(f"  transcription: {status}", flush=True)
        else:
            print("  transcription: already completed", flush=True)

        if item.analyze:
            state_path = output_paths(args.root, item.video)[2]
            print("  analyzing…", flush=True)
            status = analyze_state(
                args.root,
                state_path,
                client=client,
                model=args.analysis_model,
                force=args.force_analysis or item.transcribe,
                retries=args.retries,
                max_transcript_chars=args.max_transcript_chars,
            )
            print(f"  analysis: {status}", flush=True)
            if status == "completed" and not args.no_rebuild:
                rebuild_catalog(args.root)

    if args.no_rebuild:
        print("Catalog rebuild skipped (--no-rebuild).", flush=True)
    return 0
