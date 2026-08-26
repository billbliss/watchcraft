#!/usr/bin/env python3
"""Create and process source-neutral Watchcraft collection workspaces."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from analyze_catalog import (
    analysis_with_publisher_chapters,
    analysis_path,
    analyze_state,
    create_openai_client,
    discover_transcript_states,
    load_transcript_state,
)
from build_collection import write_collection
from repair_timelines import repair_one
from video_catalog import (
    AUTHORING_CONFIG_NAME,
    atomic_write_text,
    default_analysis_model,
    render_readable_transcript,
    render_srt,
)

AUTHORING_SCHEMA_VERSION = 1
MIN_USEFUL_TIMELINE_SECTIONS = 3
USER_AGENT = "Mozilla/5.0 (compatible; WatchcraftAuthor/0.1; +https://watchcraft.dev)"


def workspace_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def youtube_video_id(value: str) -> str:
    candidate = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        return candidate
    parsed = urllib.parse.urlparse(candidate)
    host = (parsed.hostname or "").casefold()
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
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


def request_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(f"Could not retrieve {url}: {error}") from error


def first_json_string(page: str, name: str) -> str:
    match = re.search(rf'"{re.escape(name)}":"((?:\\.|[^"\\])*)"', page)
    if not match:
        return ""
    try:
        return str(json.loads(f'"{match.group(1)}"'))
    except json.JSONDecodeError:
        return html.unescape(match.group(1))


def youtube_description_chapters(
    description: str, duration_seconds: int | None
) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    for line in description.splitlines():
        match = re.match(
            r"^\s*((?:\d{1,2}:)?\d{1,2}:\d{2})\s+(.+?)\s*$", line
        )
        if not match:
            continue
        parts = [int(part) for part in match.group(1).split(":")]
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + part
        title = " ".join(match.group(2).split())
        if not title or (duration_seconds is not None and seconds >= duration_seconds):
            continue
        if chapters and seconds <= chapters[-1]["start_seconds"]:
            continue
        chapters.append({"start_seconds": seconds, "title": title})
    if len(chapters) < 3 or chapters[0]["start_seconds"] != 0:
        return []
    return chapters


def youtube_metadata(video_id: str) -> dict[str, Any]:
    canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    oembed_url = "https://www.youtube.com/oembed?" + urllib.parse.urlencode(
        {"url": canonical_url, "format": "json"}
    )
    try:
        embed = json.loads(request_text(oembed_url))
    except json.JSONDecodeError as error:
        raise RuntimeError("YouTube returned invalid embed metadata") from error
    page = request_text(canonical_url)
    duration = first_json_string(page, "lengthSeconds")
    duration_seconds = int(duration) if duration.isdigit() else None
    published_at = first_json_string(page, "publishDate") or first_json_string(
        page, "uploadDate"
    )
    description = first_json_string(page, "shortDescription")
    return {
        "source_id": f"youtube:{video_id}",
        "type": "youtube",
        "video_id": video_id,
        "url": canonical_url,
        "title": str(embed.get("title") or video_id),
        "publisher": str(embed.get("author_name") or ""),
        "publisher_url": str(embed.get("author_url") or ""),
        "thumbnail_url": str(embed.get("thumbnail_url") or ""),
        "duration_seconds": duration_seconds,
        "published_at": published_at,
        "chapters": youtube_description_chapters(description, duration_seconds),
    }


def youtube_transcript(video_id: str, language: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as error:
        raise RuntimeError(
            "youtube-transcript-api is not installed. Install authoring/prototype/requirements.txt."
        ) from error
    try:
        transcript_list = YouTubeTranscriptApi().list(video_id)
        transcript = transcript_list.find_transcript([language])
        fetched = transcript.fetch()
    except Exception as error:
        raise RuntimeError(f"Could not retrieve YouTube captions: {error}") from error
    segments = [
        {
            "start": float(snippet.start),
            "end": float(snippet.start + snippet.duration),
            "text": " ".join(str(snippet.text).split()),
        }
        for snippet in fetched
        if str(snippet.text).strip()
    ]
    return segments, {
        "language": transcript.language_code,
        "language_name": transcript.language,
        "generated": bool(transcript.is_generated),
        "source": "youtube-captions",
    }


def load_authoring_config(workspace: Path) -> dict[str, Any]:
    path = workspace / AUTHORING_CONFIG_NAME
    if not path.is_file():
        return {
            "kind": "watchcraft.authoring",
            "schema_version": AUTHORING_SCHEMA_VERSION,
            "collection": {},
            "sources": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read {path}: {error}") from error
    if payload.get("kind") != "watchcraft.authoring":
        raise RuntimeError(f"Not a Watchcraft authoring workspace: {path}")
    return payload


def write_authoring_config(workspace: Path, config: dict[str, Any]) -> None:
    atomic_write_text(
        workspace / AUTHORING_CONFIG_NAME,
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
    )


def import_youtube(
    workspace: Path,
    url: str,
    *,
    collection_title: str | None,
    language: str,
    force: bool,
    position: int | None = None,
) -> dict[str, Any]:
    video_id = youtube_video_id(url)
    key = f"{video_id}.youtube"
    config = load_authoring_config(workspace)
    state_path = workspace / "transcripts" / f"{video_id}.transcript.json"
    if key in config.get("sources", {}) and state_path.is_file() and not force:
        return config["sources"][key]
    metadata = youtube_metadata(video_id)
    if position is not None:
        if position < 1:
            raise ValueError("YouTube source position must be at least 1")
        metadata["position"] = position
    segments, caption_metadata = youtube_transcript(video_id, language)
    if not segments:
        raise RuntimeError("YouTube returned an empty transcript")
    config.setdefault("collection", {})
    if collection_title:
        config["collection"]["title"] = collection_title
    config["collection"].setdefault("title", metadata["title"])
    config["collection"].setdefault(
        "collection_id",
        re.sub(r"[^a-z0-9]+", "-", config["collection"]["title"].casefold()).strip("-"),
    )
    config["collection"].setdefault(
        "description", "A Watchcraft collection of public instructional videos."
    )
    config["collection"].setdefault(
        "source", {"type": "youtube", "publisher": metadata["publisher"]}
    )
    metadata["captions"] = caption_metadata
    config.setdefault("sources", {})[key] = metadata
    write_authoring_config(workspace, config)

    transcript_root = workspace / "transcripts"
    atomic_write_text(transcript_root / f"{video_id}.srt", render_srt(segments))
    atomic_write_text(
        transcript_root / f"{video_id}.transcript.txt",
        render_readable_transcript(segments),
    )
    transcript_state = {
        "schema_version": 1,
        "video": key,
        "model": "youtube-captions",
        "language": caption_metadata["language"],
        "text": " ".join(segment["text"] for segment in segments),
        "segments": segments,
        "discarded_segments": [],
        "provenance": caption_metadata,
    }
    atomic_write_text(
        state_path,
        json.dumps(transcript_state, ensure_ascii=False, indent=2) + "\n",
    )
    return metadata


def process_workspace(args: argparse.Namespace) -> int:
    states = discover_transcript_states(args.workspace)
    pending = []
    repairs = []
    chapter_updates: list[tuple[Path, dict[str, Any]]] = []
    for state_path in states:
        state = load_transcript_state(state_path)
        output = analysis_path(args.workspace, state["video"])
        if args.force or not output.is_file():
            pending.append(state_path)
        else:
            analysis = json.loads(output.read_text(encoding="utf-8"))
            aligned = analysis_with_publisher_chapters(
                args.workspace, state["video"], analysis
            )
            if aligned != analysis:
                chapter_updates.append((output, aligned))
            if len(aligned.get("sections", [])) < MIN_USEFUL_TIMELINE_SECTIONS:
                repairs.append(state_path)
    print(
        f"{len(states)} transcripts | {len(pending)} pending analyses | "
        f"{len(repairs)} timeline repairs | "
        f"{len(chapter_updates)} publisher chapter updates",
        flush=True,
    )
    if args.dry_run:
        for path in pending:
            print(f"  analyze: {load_transcript_state(path)['video']}")
        for path in repairs:
            print(f"  repair: {load_transcript_state(path)['video']}")
        for _, analysis in chapter_updates:
            print(f"  publisher chapters: {analysis['video']}")
        return 0
    for output, analysis in chapter_updates:
        atomic_write_text(
            output, json.dumps(analysis, ensure_ascii=False, indent=2) + "\n"
        )
    if pending or repairs:
        client = create_openai_client(args.timeout)
    if pending:
        for index, state_path in enumerate(pending, start=1):
            state = load_transcript_state(state_path)
            print(f"[{index}/{len(pending)}] {state['video']}", flush=True)
            status = analyze_state(
                args.workspace,
                state_path,
                client=client,
                model=args.analysis_model,
                force=args.force,
                retries=args.retries,
                max_transcript_chars=args.max_transcript_chars,
            )
            print(f"  {status}", flush=True)
            output = analysis_path(args.workspace, state["video"])
            analysis = json.loads(output.read_text(encoding="utf-8"))
            if len(analysis.get("sections", [])) < MIN_USEFUL_TIMELINE_SECTIONS:
                print("  repairing underspecified timeline…", flush=True)
                count = repair_one(
                    args.workspace,
                    state_path,
                    client=client,
                    model=args.analysis_model,
                    retries=args.retries,
                    max_transcript_chars=args.max_transcript_chars,
                )
                print(f"  timeline: {count} sections", flush=True)
    for index, state_path in enumerate(repairs, start=1):
        state = load_transcript_state(state_path)
        print(f"[repair {index}/{len(repairs)}] {state['video']}", flush=True)
        count = repair_one(
            args.workspace,
            state_path,
            client=client,
            model=args.analysis_model,
            retries=args.retries,
            max_transcript_chars=args.max_transcript_chars,
        )
        print(f"  timeline: {count} sections", flush=True)
    write_collection(args.workspace)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    youtube = commands.add_parser("youtube", help="Import public YouTube sources")
    youtube_commands = youtube.add_subparsers(dest="youtube_command", required=True)
    add = youtube_commands.add_parser("add", help="Add one public video and its captions")
    add.add_argument("url")
    add.add_argument("--workspace", required=True, type=workspace_path)
    add.add_argument("--collection-title")
    add.add_argument("--language", default="en")
    add.add_argument("--force", action="store_true")
    add.add_argument(
        "--position",
        type=int,
        help="One-based lesson position retained by future collection rebuilds",
    )

    process = commands.add_parser("process", help="Analyze pending sources and build collection")
    process.add_argument("--workspace", required=True, type=workspace_path)
    process.add_argument("--analysis-model", default=default_analysis_model())
    process.add_argument("--retries", type=int, default=5)
    process.add_argument("--timeout", type=float, default=300)
    process.add_argument("--max-transcript-chars", type=int, default=1_500_000)
    process.add_argument("--force", action="store_true")
    process.add_argument("--dry-run", action="store_true")

    build = commands.add_parser("build", help="Rebuild collection without AI calls")
    build.add_argument("--workspace", required=True, type=workspace_path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "youtube":
        metadata = import_youtube(
            args.workspace,
            args.url,
            collection_title=args.collection_title,
            language=args.language,
            force=args.force,
            position=args.position,
        )
        duration = metadata.get("duration_seconds")
        duration_label = f"{duration // 60}:{duration % 60:02d}" if duration else "unknown"
        print(f"added {metadata['title']} ({duration_label})")
        return 0
    if args.command == "process":
        return process_workspace(args)
    if args.command == "build":
        states = discover_transcript_states(args.workspace)
        for state_path in states:
            state = load_transcript_state(state_path)
            output = analysis_path(args.workspace, state["video"])
            if not output.is_file():
                continue
            analysis = json.loads(output.read_text(encoding="utf-8"))
            aligned = analysis_with_publisher_chapters(
                args.workspace, state["video"], analysis
            )
            if aligned != analysis:
                atomic_write_text(
                    output,
                    json.dumps(aligned, ensure_ascii=False, indent=2) + "\n",
                )
        write_collection(args.workspace)
        return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
