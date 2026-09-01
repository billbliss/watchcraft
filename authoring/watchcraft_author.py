#!/usr/bin/env python3
"""Create and process source-neutral Watchcraft collection workspaces."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

# Load local authoring credentials while preserving explicit shell overrides.
load_dotenv(Path(__file__).resolve().parents[1] / ".env.local")

from analyze_catalog import (
    analysis_with_publisher_chapters,
    analysis_path,
    analyze_state,
    create_openai_client,
    discover_transcript_states,
    load_transcript_state,
    transcript_has_timeline_evidence,
)
from build_collection import write_collection
from normalize_topics import (
    DEFAULT_BATCH_SIZE as DEFAULT_NORMALIZATION_BATCH_SIZE,
    default_normalization_model,
    run as run_topic_normalization,
)
from repair_timelines import repair_one
from video_catalog import (
    AUTHORING_CONFIG_NAME,
    atomic_write_text,
    default_analysis_model,
    default_model,
    render_readable_transcript,
    render_srt,
)
from youtube_audio import NoSpeechDetected, youtube_audio_transcript

AUTHORING_SCHEMA_VERSION = 1
MIN_USEFUL_TIMELINE_SECTIONS = 3
TRANSCRIPT_SOURCES = ("audio", "captions")
USER_AGENT = "Mozilla/5.0 (compatible; WatchcraftAuthor/0.1; +https://watchcraft.dev)"
YOUTUBE_PROXY_URL_ENV = "WATCHCRAFT_YOUTUBE_PROXY_URL"
YOUTUBE_WEBSHARE_USERNAME_ENV = "WATCHCRAFT_YOUTUBE_WEBSHARE_USERNAME"
YOUTUBE_WEBSHARE_PASSWORD_ENV = "WATCHCRAFT_YOUTUBE_WEBSHARE_PASSWORD"
CATEGORY_SYSTEM_PROMPT = """Classify an instructional-video collection into one broad, durable category.

Reuse one of the supplied existing categories exactly whenever it reasonably fits. Create a new
category only when none of the existing choices describes the collection well. New category labels
must be concise Title Case noun phrases, no more than 40 characters, and broad enough to reuse for
future collections. Return only the structured result."""


class CategoryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    rationale: str


class YouTubeIpBlocked(RuntimeError):
    """YouTube rejected caption traffic from the current egress IP."""


class YouTubeCaptionsUnavailable(RuntimeError):
    """The requested YouTube captions are not available for this video."""

    def __init__(self, message: str, *, reason: str):
        super().__init__(message)
        self.reason = reason


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


def youtube_playlist_id(value: str) -> str:
    candidate = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{10,100}", candidate):
        return candidate
    parsed = urllib.parse.urlparse(candidate)
    host = (parsed.hostname or "").casefold()
    playlist_id = (
        urllib.parse.parse_qs(parsed.query).get("list", [""])[0]
        if host == "youtube.com" or host.endswith(".youtube.com")
        else ""
    )
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,100}", playlist_id):
        raise ValueError(f"Not a recognizable YouTube playlist URL or ID: {value}")
    return playlist_id


def request_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(f"Could not retrieve {url}: {error}") from error


def request_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not retrieve {url}: {error}") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"YouTube returned an invalid JSON response from {url}")
    return result


def first_json_string(page: str, name: str) -> str:
    match = re.search(rf'"{re.escape(name)}":"((?:\\.|[^"\\])*)"', page)
    if not match:
        return ""
    try:
        return str(json.loads(f'"{match.group(1)}"'))
    except json.JSONDecodeError:
        return html.unescape(match.group(1))


def youtube_initial_data(page: str) -> dict[str, Any]:
    match = re.search(
        r'(?:var\s+ytInitialData|window\["ytInitialData"\])\s*=\s*', page
    )
    if not match:
        raise RuntimeError("YouTube did not expose public playlist data")
    try:
        payload, _ = json.JSONDecoder().raw_decode(page[match.end() :])
    except json.JSONDecodeError as error:
        raise RuntimeError("YouTube returned invalid public playlist data") from error
    if not isinstance(payload, dict):
        raise RuntimeError("YouTube returned invalid public playlist data")
    return payload


def first_nested_mapping(value: Any, key: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        candidate = value.get(key)
        if isinstance(candidate, dict):
            return candidate
        for child in value.values():
            found = first_nested_mapping(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = first_nested_mapping(child, key)
            if found is not None:
                return found
    return None


def playlist_watch_endpoint(value: Any, playlist_id: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        endpoint = value.get("watchEndpoint")
        if (
            isinstance(endpoint, dict)
            and endpoint.get("playlistId") == playlist_id
            and isinstance(endpoint.get("videoId"), str)
            and "index" in endpoint
        ):
            return endpoint
        for child in value.values():
            found = playlist_watch_endpoint(child, playlist_id)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = playlist_watch_endpoint(child, playlist_id)
            if found is not None:
                return found
    return None


def playlist_continuation_token(value: Any) -> str | None:
    if isinstance(value, dict):
        command = value.get("continuationCommand")
        if (
            isinstance(command, dict)
            and command.get("request") == "CONTINUATION_REQUEST_TYPE_BROWSE"
            and isinstance(command.get("token"), str)
        ):
            return command["token"]
        for child in value.values():
            found = playlist_continuation_token(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = playlist_continuation_token(child)
            if found:
                return found
    return None


def youtube_playlist_batch(
    payload: dict[str, Any], playlist_id: str
) -> tuple[list[str], str | None]:
    candidates: list[tuple[list[str], str | None]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            video_ids = []
            for child in value:
                endpoint = playlist_watch_endpoint(child, playlist_id)
                if endpoint is not None:
                    video_ids.append(endpoint["videoId"])
            if video_ids:
                candidates.append((video_ids, playlist_continuation_token(value)))
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)

    visit(payload)
    if not candidates:
        return [], None
    return max(candidates, key=lambda candidate: len(candidate[0]))


def youtube_playlist(value: str) -> dict[str, Any]:
    playlist_id = youtube_playlist_id(value)
    canonical_url = "https://www.youtube.com/playlist?" + urllib.parse.urlencode(
        {"list": playlist_id}
    )
    page = request_text(f"{canonical_url}&hl=en")
    initial_data = youtube_initial_data(page)
    metadata = first_nested_mapping(initial_data, "playlistMetadataRenderer") or {}
    title = " ".join(str(metadata.get("title") or "").split())
    video_ids, continuation = youtube_playlist_batch(initial_data, playlist_id)
    if not video_ids:
        raise RuntimeError(
            "The YouTube playlist is unavailable, private, empty, or has no visible videos"
        )

    api_key = first_json_string(page, "INNERTUBE_API_KEY")
    client_version = first_json_string(page, "INNERTUBE_CLIENT_VERSION")
    if continuation and (not api_key or not client_version):
        raise RuntimeError("YouTube did not expose playlist pagination data")

    seen_tokens: set[str] = set()
    while continuation:
        if continuation in seen_tokens:
            raise RuntimeError("YouTube repeated a playlist continuation token")
        seen_tokens.add(continuation)
        response = request_json(
            f"https://www.youtube.com/youtubei/v1/browse?key={api_key}",
            {
                "context": {
                    "client": {
                        "clientName": "WEB",
                        "clientVersion": client_version,
                        "hl": "en",
                    }
                },
                "continuation": continuation,
            },
        )
        batch, continuation = youtube_playlist_batch(response, playlist_id)
        if not batch:
            break
        video_ids.extend(batch)

    unique_video_ids = []
    seen_video_ids = set()
    for video_id in video_ids:
        if video_id not in seen_video_ids:
            unique_video_ids.append(video_id)
            seen_video_ids.add(video_id)
    return {
        "playlist_id": playlist_id,
        "url": canonical_url,
        "title": title or playlist_id,
        "video_ids": unique_video_ids,
        "duplicate_count": len(video_ids) - len(unique_video_ids),
    }


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


def youtube_transcript_client() -> Any:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api.proxies import (
            GenericProxyConfig,
            WebshareProxyConfig,
        )
    except ImportError as error:
        raise RuntimeError(
            "youtube-transcript-api is not installed. Install authoring/requirements.txt."
        ) from error
    proxy_url = os.environ.get(YOUTUBE_PROXY_URL_ENV, "").strip()
    webshare_username = os.environ.get(YOUTUBE_WEBSHARE_USERNAME_ENV, "").strip()
    webshare_password = os.environ.get(YOUTUBE_WEBSHARE_PASSWORD_ENV, "")
    if bool(webshare_username) != bool(webshare_password):
        raise ValueError(
            f"Set both {YOUTUBE_WEBSHARE_USERNAME_ENV} and "
            f"{YOUTUBE_WEBSHARE_PASSWORD_ENV}"
        )
    if proxy_url and webshare_username:
        raise ValueError(
            f"Use either {YOUTUBE_PROXY_URL_ENV} or the Webshare credentials, not both"
        )
    if webshare_username:
        print("YouTube captions: using rotating residential proxies", flush=True)
        return YouTubeTranscriptApi(
            proxy_config=WebshareProxyConfig(
                proxy_username=webshare_username,
                proxy_password=webshare_password,
                filter_ip_locations=["us"],
            )
        )
    if proxy_url:
        print("YouTube captions: using configured proxy", flush=True)
        return YouTubeTranscriptApi(
            proxy_config=GenericProxyConfig(
                http_url=proxy_url,
                https_url=proxy_url,
            )
        )
    return YouTubeTranscriptApi()


def youtube_transcript(
    video_id: str,
    language: str,
    *,
    transcript_api: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from youtube_transcript_api import (
            IpBlocked,
            NoTranscriptFound,
            RequestBlocked,
            TranscriptsDisabled,
        )
    except ImportError as error:
        raise RuntimeError(
            "youtube-transcript-api is not installed. Install authoring/requirements.txt."
        ) from error
    try:
        client = transcript_api or youtube_transcript_client()
        transcript_list = client.list(video_id)
        transcript = transcript_list.find_transcript([language])
        fetched = transcript.fetch()
    except (IpBlocked, RequestBlocked) as error:
        raise YouTubeIpBlocked(
            "YouTube blocked caption requests from this IP. Retry from another "
            f"network, set {YOUTUBE_PROXY_URL_ENV}, or set the two "
            "WATCHCRAFT_YOUTUBE_WEBSHARE_* credentials for rotating residential "
            "proxies. The import is resumable."
        ) from error
    except NoTranscriptFound as error:
        raise YouTubeCaptionsUnavailable(
            f"YouTube has no captions for the requested language {language!r}",
            reason="requested-language-unavailable",
        ) from error
    except TranscriptsDisabled as error:
        raise YouTubeCaptionsUnavailable(
            "YouTube captions are disabled for this video",
            reason="captions-disabled",
        ) from error
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


def set_collection_listing(workspace: Path, *, unlisted: bool) -> None:
    config = load_authoring_config(workspace)
    collection = config.setdefault("collection", {})
    if unlisted:
        collection["listed"] = False
    else:
        collection.setdefault("listed", True)
    write_authoring_config(workspace, config)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def collection_workspace_path(collections_repo: Path, slug: str) -> Path:
    collections_root = collections_repo.expanduser().resolve() / "collections"
    if not collections_root.is_dir():
        raise ValueError(
            f"Collections repository has no collections/ directory: {collections_repo}"
        )
    if slugify(slug) != slug or not slug:
        raise ValueError(f"Collection slug must be lowercase kebab-case: {slug}")
    return collections_root / slug


def collection_directory_categories(collections_repo: Path) -> list[str]:
    directory_path = collections_repo.expanduser().resolve() / "site" / "collections.json"
    if not directory_path.is_file():
        return []
    try:
        directory = json.loads(directory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read collection directory: {directory_path}") from error
    entries = directory.get("collections")
    if not isinstance(entries, list):
        raise RuntimeError(f"Collection directory has no collections list: {directory_path}")
    categories = {
        " ".join(str(entry.get("category") or "").split())
        for entry in entries
        if isinstance(entry, dict)
    }
    return sorted(
        (category for category in categories if category),
        key=str.casefold,
    )


def request_collection_category(
    client: Any,
    *,
    model: str,
    collection: dict[str, Any],
    sources: dict[str, Any],
    existing_categories: list[str],
    retries: int,
) -> tuple[str, bool]:
    payload = {
        "title": str(collection.get("title") or ""),
        "description": str(collection.get("description") or ""),
        "publisher": str(collection.get("publisher") or ""),
        "video_titles": [
            str(source.get("title"))
            for source in sources.values()
            if isinstance(source, dict) and source.get("title")
        ][:50],
        "existing_categories": existing_categories,
    }
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = client.responses.parse(
                model=model,
                input=[
                    {"role": "system", "content": CATEGORY_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                text_format=CategoryProposal,
            )
            proposal = response.output_parsed
            if proposal is None:
                raise RuntimeError("The category model returned no structured output")
            category = " ".join(proposal.category.split())
            if not category or len(category) > 40:
                raise RuntimeError(
                    "The category model returned an empty or overly long category"
                )
            existing_by_key = {
                existing.casefold(): existing for existing in existing_categories
            }
            reused = existing_by_key.get(category.casefold())
            return (reused or category, reused is not None)
        except Exception as error:  # SDK error classes vary between releases.
            last_error = error
            if attempt >= retries:
                break
            delay = min(30, 2**attempt)
            print(
                f"  category API attempt {attempt + 1} failed; "
                f"retrying in {delay}s",
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError(
        f"Category request failed after {retries + 1} attempts: {last_error}"
    )


def ensure_collection_category(
    collections_repo: Path,
    workspace: Path,
    args: argparse.Namespace,
) -> str | None:
    directory_path = collections_repo.expanduser().resolve() / "site" / "collections.json"
    if args.unlisted or not directory_path.is_file():
        return None
    config = load_authoring_config(workspace)
    collection = config.setdefault("collection", {})
    explicit = " ".join(str(args.category or "").split())
    saved = " ".join(str(collection.get("category") or "").split())
    if saved and not explicit:
        return saved
    existing_categories = collection_directory_categories(collections_repo)
    existing_by_key = {
        existing.casefold(): existing for existing in existing_categories
    }
    if explicit:
        if len(explicit) > 40:
            raise ValueError("--category must be 40 characters or fewer")
        category = existing_by_key.get(explicit.casefold(), explicit)
        reused = category.casefold() in existing_by_key
    else:
        print("Choosing collection category…", flush=True)
        category, reused = request_collection_category(
            create_openai_client(args.timeout),
            model=args.analysis_model,
            collection=collection,
            sources=config.get("sources", {}),
            existing_categories=existing_categories,
            retries=args.retries,
        )
    collection["category"] = category
    write_authoring_config(workspace, config)
    disposition = "existing category" if reused else "new category"
    print(f"category: {category} ({disposition})", flush=True)
    return category


def render_collection_readme(
    playlist: dict[str, Any],
    collection_title: str,
    publisher: str,
    publisher_url: str,
    video_count: int,
) -> str:
    publisher_label = publisher or "YouTube"
    if publisher_url:
        publisher_label = f"[{publisher_label}]({publisher_url})"
    return (
        f"# {collection_title}\n\n"
        "A Watchcraft collection generated from a public YouTube playlist.\n\n"
        f"- Source: [{collection_title}]({playlist['url']})\n"
        f"- Publisher: {publisher_label}\n"
        f"- Videos: {video_count}\n\n"
        "The published collection contains YouTube references, generated summaries, "
        "topics, and navigable chapters. Transcripts remain private authoring inputs "
        "and are intentionally excluded from Git.\n"
    )


def import_youtube(
    workspace: Path,
    url: str,
    *,
    collection_title: str | None,
    language: str,
    force: bool,
    position: int | None = None,
    transcript_source: str = "audio",
    transcription_model: str | None = None,
    transcript_api: Any | None = None,
) -> dict[str, Any]:
    video_id = youtube_video_id(url)
    key = f"{video_id}.youtube"
    config = load_authoring_config(workspace)
    state_path = workspace / "transcripts" / f"{video_id}.transcript.json"
    if not force and youtube_import_is_complete(workspace, video_id):
        return config["sources"][key]
    metadata = youtube_metadata(video_id)
    if position is not None:
        if position < 1:
            raise ValueError("YouTube source position must be at least 1")
        metadata["position"] = position
    if transcript_source == "audio":
        model = transcription_model or default_model()
        segments, transcript_metadata, discarded_segments = youtube_audio_transcript(
            video_id,
            language,
            model,
        )
        transcript_model = model
    elif transcript_source == "captions":
        segments, transcript_metadata = youtube_transcript(
            video_id, language, transcript_api=transcript_api
        )
        discarded_segments = []
        transcript_model = "youtube-captions"
    else:
        raise ValueError(
            f"Unknown transcript source {transcript_source!r}; "
            f"choose one of {', '.join(TRANSCRIPT_SOURCES)}"
        )
    if not segments:
        raise RuntimeError(f"YouTube {transcript_source} produced an empty transcript")
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
    metadata["transcript"] = transcript_metadata
    if transcript_source == "captions":
        metadata["captions"] = transcript_metadata
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
        "model": transcript_model,
        "language": transcript_metadata["language"],
        "text": " ".join(segment["text"] for segment in segments),
        "segments": segments,
        "discarded_segments": discarded_segments,
        "provenance": transcript_metadata,
    }
    atomic_write_text(
        state_path,
        json.dumps(transcript_state, ensure_ascii=False, indent=2) + "\n",
    )
    return metadata


def youtube_import_is_complete(workspace: Path, video_id: str) -> bool:
    key = f"{video_id}.youtube"
    config = load_authoring_config(workspace)
    source = config.get("sources", {}).get(key)
    state_path = workspace / "transcripts" / f"{video_id}.transcript.json"
    if not isinstance(source, dict) or not state_path.is_file():
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(state, dict) and state.get("video") == key


def playlist_completion_issues(
    workspace: Path,
    video_ids: list[str],
    *,
    require_analysis: bool,
) -> list[str]:
    config = load_authoring_config(workspace)
    sources = config.get("sources", {})
    issues = []
    for video_id in video_ids:
        key = f"{video_id}.youtube"
        source = sources.get(key) if isinstance(sources, dict) else None
        if not isinstance(source, dict):
            issues.append(f"{video_id}: missing source metadata")
            continue
        state_path = workspace / "transcripts" / f"{video_id}.transcript.json"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            issues.append(f"{video_id}: missing transcript")
            continue
        except (OSError, json.JSONDecodeError):
            issues.append(f"{video_id}: invalid transcript state")
            continue
        if not isinstance(state, dict) or state.get("video") != key:
            issues.append(f"{video_id}: transcript belongs to another source")
            continue
        if not require_analysis:
            continue
        output = analysis_path(workspace, key)
        try:
            analysis = json.loads(output.read_text(encoding="utf-8"))
        except FileNotFoundError:
            issues.append(f"{video_id}: missing analysis")
            continue
        except (OSError, json.JSONDecodeError):
            issues.append(f"{video_id}: invalid analysis")
            continue
        if not isinstance(analysis, dict) or analysis.get("video") != key:
            issues.append(f"{video_id}: analysis belongs to another source")
    return issues


def require_playlist_complete(
    workspace: Path,
    video_ids: list[str],
    *,
    require_analysis: bool,
) -> None:
    issues = playlist_completion_issues(
        workspace, video_ids, require_analysis=require_analysis
    )
    if not issues:
        return
    preview = "; ".join(issues[:5])
    suffix = f"; and {len(issues) - 5} more" if len(issues) > 5 else ""
    phase = "analysis" if require_analysis else "import"
    raise RuntimeError(
        f"Collection {phase} is incomplete: {preview}{suffix}. "
        "Rerun the same command to resume; completed work was preserved."
    )


def import_youtube_playlist(
    workspace: Path,
    value: str,
    *,
    collection_title: str | None,
    language: str,
    force: bool,
    start_position: int = 1,
    transcript_source: str = "audio",
    transcription_model: str | None = None,
    playlist_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if start_position < 1:
        raise ValueError("YouTube playlist start position must be at least 1")
    playlist = playlist_data or youtube_playlist(value)
    config = load_authoring_config(workspace)
    collection = config.setdefault("collection", {})
    if collection_title:
        collection["title"] = collection_title
    collection.setdefault("title", playlist["title"])
    collection.setdefault(
        "collection_id",
        re.sub(r"[^a-z0-9]+", "-", collection["title"].casefold()).strip("-"),
    )
    collection.setdefault(
        "description", "A Watchcraft collection of public instructional videos."
    )
    effective_collection_title = str(collection["title"])
    source = collection.get("source")
    if not isinstance(source, dict):
        source = {}
        collection["source"] = source
    source.update({
        "type": "youtube-playlist",
        "playlist_id": playlist["playlist_id"],
        "url": playlist["url"],
    })
    write_authoring_config(workspace, config)

    completed = 0
    added = 0
    cached = 0
    failures = []
    video_ids = playlist["video_ids"]
    transcript_api = (
        youtube_transcript_client() if transcript_source == "captions" else None
    )
    for offset, video_id in enumerate(video_ids):
        position = start_position + offset
        print(f"[{offset + 1}/{len(video_ids)}] {video_id}", flush=True)
        was_cached = not force and youtube_import_is_complete(workspace, video_id)
        try:
            metadata = import_youtube(
                workspace,
                video_id,
                collection_title=effective_collection_title,
                language=language,
                force=force,
                position=position,
                transcript_source=transcript_source,
                transcription_model=transcription_model,
                transcript_api=transcript_api,
            )
            latest_config = load_authoring_config(workspace)
            source = latest_config.get("sources", {}).get(f"{video_id}.youtube")
            if isinstance(source, dict) and source.get("position") != position:
                source["position"] = position
                write_authoring_config(workspace, latest_config)
            outcome = "cached" if was_cached else "added"
            print(f"  {outcome} {metadata['title']}", flush=True)
            completed += 1
            if was_cached:
                cached += 1
            else:
                added += 1
        except YouTubeIpBlocked:
            raise
        except YouTubeCaptionsUnavailable as error:
            failures.append(
                {
                    "video_id": video_id,
                    "error": str(error),
                    "type": "captions-unavailable",
                    "reason": error.reason,
                    "language": language,
                }
            )
            print(f"  skipped: {error}", file=sys.stderr, flush=True)
        except NoSpeechDetected as error:
            failures.append(
                {
                    "video_id": video_id,
                    "error": str(error),
                    "type": "no-speech",
                    "reason": "no-speech-detected",
                    "audio_seconds": round(error.audio_seconds, 3),
                    "speech_seconds": round(error.speech_seconds, 3),
                }
            )
            print(f"  skipped: {error}", file=sys.stderr, flush=True)
        except (RuntimeError, ValueError) as error:
            failures.append(
                {
                    "video_id": video_id,
                    "error": str(error),
                    "type": "import-error",
                }
            )
            print(f"  skipped: {error}", file=sys.stderr, flush=True)
    if not completed:
        raise RuntimeError("No videos from the YouTube playlist could be imported")
    return {
        **playlist,
        "imported_count": completed,
        "completed_count": completed,
        "added_count": added,
        "cached_count": cached,
        "failures": failures,
    }


def process_and_normalize_collection(
    workspace: Path,
    args: argparse.Namespace,
    *,
    expected_video_ids: list[str] | None = None,
) -> int:
    process_args = argparse.Namespace(
        workspace=workspace,
        analysis_model=args.analysis_model,
        retries=args.retries,
        timeout=args.timeout,
        max_transcript_chars=args.max_transcript_chars,
        force=args.force,
        dry_run=False,
        defer_build=True,
    )
    process_status = process_workspace(process_args)
    if process_status:
        return process_status
    if expected_video_ids is not None:
        require_playlist_complete(
            workspace, expected_video_ids, require_analysis=True
        )
    print("Normalizing collection topics…", flush=True)
    normalization_args = argparse.Namespace(
        root=workspace,
        normalization_model=args.normalization_model,
        limit=None,
        batch_size=args.normalization_batch_size,
        retries=args.retries,
        timeout=args.timeout,
        force=args.force,
        rebuild_related=False,
        rebuild_display_labels=False,
        dry_run=False,
        no_rebuild=False,
    )
    return run_topic_normalization(normalization_args)


def create_playlist_collection(args: argparse.Namespace) -> int:
    playlist = youtube_playlist(args.from_youtube_playlist)
    collection_title = " ".join(
        str(args.collection_title or playlist["title"]).split()
    )
    collection_slug = args.slug or slugify(collection_title)
    if not collection_slug:
        raise ValueError("Could not derive a collection slug; pass --slug")
    excluded_video_ids = []
    for value in args.exclude:
        video_id = youtube_video_id(value)
        if video_id not in excluded_video_ids:
            excluded_video_ids.append(video_id)
    excluded = set(excluded_video_ids)
    candidate_video_ids = [
        video_id for video_id in playlist["video_ids"] if video_id not in excluded
    ]
    if not candidate_video_ids:
        raise RuntimeError("No playlist videos remain to import")
    workspace = collection_workspace_path(args.collections_repo, collection_slug)
    existing = load_authoring_config(workspace)
    existing_source = existing.get("collection", {}).get("source", {})
    saved_caption_exclusions = []
    saved_audio_exclusions = []
    if (
        args.transcript_source == "captions"
        and args.skip_missing_captions
        and not args.force
        and isinstance(existing_source, dict)
    ):
        raw_exclusions = existing_source.get("caption_exclusions", [])
        if isinstance(raw_exclusions, list):
            saved_caption_exclusions = [
                exclusion
                for exclusion in raw_exclusions
                if isinstance(exclusion, dict)
                and exclusion.get("video_id") in candidate_video_ids
                and exclusion.get("language") == args.language
            ]
    if (
        args.transcript_source == "audio"
        and not args.force
        and isinstance(existing_source, dict)
    ):
        raw_exclusions = existing_source.get("audio_exclusions", [])
        if isinstance(raw_exclusions, list):
            saved_audio_exclusions = [
                exclusion
                for exclusion in raw_exclusions
                if isinstance(exclusion, dict)
                and exclusion.get("video_id") in candidate_video_ids
            ]
    saved_exclusion_ids = {
        str(exclusion["video_id"])
        for exclusion in [*saved_caption_exclusions, *saved_audio_exclusions]
    }
    selected_video_ids = [
        video_id
        for video_id in candidate_video_ids
        if video_id not in saved_exclusion_ids
    ]
    if args.limit is not None:
        selected_video_ids = selected_video_ids[: args.limit]
    if not selected_video_ids:
        raise RuntimeError("No playlist videos remain to import")
    playlist = {**playlist, "video_ids": selected_video_ids}
    print(
        f"{collection_title} | {len(selected_video_ids)} videos | {workspace}",
        flush=True,
    )
    if saved_caption_exclusions:
        print(
            f"  reusing {len(saved_caption_exclusions)} saved caption exclusions",
            flush=True,
        )
    if saved_audio_exclusions:
        print(
            f"  reusing {len(saved_audio_exclusions)} saved no-speech exclusions",
            flush=True,
        )
    if args.dry_run:
        for index, video_id in enumerate(selected_video_ids, start=1):
            print(f"  {index:>3}. https://www.youtube.com/watch?v={video_id}")
        return 0

    config_path = workspace / AUTHORING_CONFIG_NAME
    if workspace.is_dir() and any(workspace.iterdir()) and not config_path.is_file():
        raise RuntimeError(
            f"Refusing to write into a non-empty directory without "
            f"{AUTHORING_CONFIG_NAME}: {workspace}"
        )
    workspace.mkdir(parents=True, exist_ok=True)
    existing_playlist_id = (
        existing_source.get("playlist_id")
        if isinstance(existing_source, dict)
        else None
    )
    if existing_playlist_id and existing_playlist_id != playlist["playlist_id"]:
        raise RuntimeError(
            f"Workspace already belongs to YouTube playlist {existing_playlist_id}"
        )
    if existing.get("sources") and not existing_playlist_id:
        raise RuntimeError(
            "Workspace already contains non-playlist sources and cannot be repurposed"
        )

    result = import_youtube_playlist(
        workspace,
        playlist["url"],
        collection_title=collection_title,
        language=args.language,
        force=args.force,
        transcript_source=args.transcript_source,
        transcription_model=args.transcription_model,
        playlist_data=playlist,
    )
    caption_failures = [
        failure
        for failure in result["failures"]
        if failure.get("type") == "captions-unavailable"
    ]
    skipped_caption_failures = (
        caption_failures if args.skip_missing_captions else []
    )
    skipped_audio_failures = [
        failure
        for failure in result["failures"]
        if failure.get("type") == "no-speech"
        and args.transcript_source == "audio"
    ]
    newly_skipped_ids = {
        str(failure["video_id"])
        for failure in [*skipped_caption_failures, *skipped_audio_failures]
    }
    expected_video_ids = [
        video_id
        for video_id in selected_video_ids
        if video_id not in newly_skipped_ids
    ]
    unresolved_failures = [
        failure
        for failure in result["failures"]
        if failure not in skipped_caption_failures
        and failure not in skipped_audio_failures
    ]

    config = load_authoring_config(workspace)
    collection = config.setdefault("collection", {})
    collection["collection_id"] = collection_slug
    if args.unlisted:
        collection["listed"] = False
    else:
        collection.setdefault("listed", True)
    collection["description"] = (
        f"A Watchcraft collection generated from the {collection_title} "
        "YouTube playlist."
    )
    source = collection.setdefault("source", {})
    caption_exclusions_by_id = {
        str(exclusion["video_id"]): exclusion
        for exclusion in saved_caption_exclusions
    }
    for failure in skipped_caption_failures:
        video_id = str(failure["video_id"])
        caption_exclusions_by_id[video_id] = {
            "video_id": video_id,
            "language": str(failure["language"]),
            "reason": str(failure["reason"]),
        }
    caption_exclusions = [
        caption_exclusions_by_id[video_id]
        for video_id in candidate_video_ids
        if video_id in caption_exclusions_by_id
    ]
    audio_exclusions_by_id = {
        str(exclusion["video_id"]): exclusion
        for exclusion in saved_audio_exclusions
    }
    for failure in skipped_audio_failures:
        video_id = str(failure["video_id"])
        audio_exclusions_by_id[video_id] = {
            "video_id": video_id,
            "reason": str(failure["reason"]),
            "audio_seconds": float(failure["audio_seconds"]),
            "speech_seconds": float(failure["speech_seconds"]),
        }
    audio_exclusions = [
        audio_exclusions_by_id[video_id]
        for video_id in candidate_video_ids
        if video_id in audio_exclusions_by_id
    ]
    all_excluded_video_ids = list(excluded_video_ids)
    for exclusion in [*caption_exclusions, *audio_exclusions]:
        video_id = str(exclusion["video_id"])
        if video_id not in all_excluded_video_ids:
            all_excluded_video_ids.append(video_id)
    source["excluded_video_ids"] = all_excluded_video_ids
    if caption_exclusions:
        source["caption_exclusions"] = caption_exclusions
    else:
        source.pop("caption_exclusions", None)
    if audio_exclusions:
        source["audio_exclusions"] = audio_exclusions
    else:
        source.pop("audio_exclusions", None)

    positions = {
        video_id: position
        for position, video_id in enumerate(expected_video_ids, start=1)
    }
    for key, item in config.get("sources", {}).items():
        if not isinstance(item, dict) or not key.endswith(".youtube"):
            continue
        video_id = str(item.get("video_id") or key.removesuffix(".youtube"))
        if video_id in positions:
            item["position"] = positions[video_id]
    first_source = next(iter(config.get("sources", {}).values()), {})
    publisher = str(first_source.get("publisher") or "")
    publisher_url = str(first_source.get("publisher_url") or "")
    if publisher:
        collection["publisher"] = publisher
        source["publisher"] = publisher
    if publisher_url:
        source["publisher_url"] = publisher_url
    write_authoring_config(workspace, config)
    atomic_write_text(
        workspace / "README.md",
        render_collection_readme(
            playlist,
            collection_title,
            publisher,
            publisher_url,
            result["imported_count"],
        ),
    )
    if skipped_caption_failures or saved_caption_exclusions:
        print(
            f"{result['imported_count']} imported; "
            f"{len(caption_exclusions)} excluded because {args.language!r} "
            "captions were unavailable",
            flush=True,
        )
    if skipped_audio_failures or saved_audio_exclusions:
        print(
            f"{result['imported_count']} imported; "
            f"{len(audio_exclusions)} excluded because insufficient speech was detected",
            flush=True,
        )
    if unresolved_failures:
        failures = unresolved_failures
        preview = "; ".join(
            f"{failure['video_id']}: {failure['error']}"
            for failure in failures[:5]
        )
        suffix = f"; and {len(failures) - 5} more" if len(failures) > 5 else ""
        raise RuntimeError(
            f"Collection import is incomplete: {len(failures)} of "
            f"{len(selected_video_ids)} videos failed ({preview}{suffix}). "
            "Rerun the same command to resume; completed imports were preserved."
        )
    require_playlist_complete(
        workspace, expected_video_ids, require_analysis=False
    )
    ensure_collection_category(args.collections_repo, workspace, args)
    if args.import_only:
        print("import complete; analysis was skipped")
        return 0
    return process_and_normalize_collection(
        workspace, args, expected_video_ids=expected_video_ids
    )


def process_workspace(args: argparse.Namespace) -> int:
    states = discover_transcript_states(args.workspace)
    pending = []
    repairs = []
    skipped_repairs = []
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
                if transcript_has_timeline_evidence(
                    state, MIN_USEFUL_TIMELINE_SECTIONS
                ):
                    repairs.append(state_path)
                else:
                    skipped_repairs.append(state_path)
    print(
        f"{len(states)} transcripts | {len(pending)} pending analyses | "
        f"{len(repairs)} timeline repairs | "
        f"{len(skipped_repairs)} skipped timeline repairs | "
        f"{len(chapter_updates)} publisher chapter updates",
        flush=True,
    )
    if args.dry_run:
        for path in pending:
            print(f"  analyze: {load_transcript_state(path)['video']}")
        for path in repairs:
            print(f"  repair: {load_transcript_state(path)['video']}")
        for path in skipped_repairs:
            print(
                "  skip timeline (insufficient timed speech): "
                f"{load_transcript_state(path)['video']}"
            )
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
                if transcript_has_timeline_evidence(
                    state, MIN_USEFUL_TIMELINE_SECTIONS
                ):
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
                else:
                    print(
                        "  timeline skipped: insufficient timed speech",
                        flush=True,
                    )
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
    if not getattr(args, "defer_build", False):
        write_collection(args.workspace)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    youtube = commands.add_parser("youtube", help="Import public YouTube sources")
    youtube_commands = youtube.add_subparsers(dest="youtube_command", required=True)
    add = youtube_commands.add_parser(
        "add", help="Add one public video or every video in a public playlist"
    )
    add.add_argument("url", nargs="?")
    add.add_argument(
        "--playlist",
        metavar="URL_OR_ID",
        help="Import every visible video from a public or unlisted playlist",
    )
    add.add_argument("--workspace", required=True, type=workspace_path)
    add.add_argument("--collection-title")
    add.add_argument("--language", default="en")
    add.add_argument(
        "--transcript-source",
        choices=TRANSCRIPT_SOURCES,
        default="audio",
        help=(
            "Generate a local transcript from streamed audio (default), or retrieve "
            "YouTube captions"
        ),
    )
    add.add_argument("--transcription-model", default=default_model())
    add.add_argument("--force", action="store_true")
    add.add_argument(
        "--unlisted",
        action="store_true",
        help="Keep this collection out of the website directory",
    )
    add.add_argument(
        "--position",
        type=int,
        help="One-based lesson position retained by future collection rebuilds",
    )

    collection = commands.add_parser("collection", help="Create collection workspaces")
    collection_commands = collection.add_subparsers(
        dest="collection_command", required=True
    )
    create = collection_commands.add_parser(
        "create", help="Generate a collection from a public source"
    )
    create.add_argument("--from-youtube-playlist", required=True)
    create.add_argument("--collections-repo", required=True, type=Path)
    create.add_argument("--slug")
    create.add_argument("--collection-title")
    create.add_argument(
        "--category",
        help="Use this public-directory category instead of choosing one automatically",
    )
    create.add_argument("--language", default="en")
    create.add_argument(
        "--transcript-source",
        choices=TRANSCRIPT_SOURCES,
        default="audio",
        help=(
            "Generate local transcripts from streamed audio (default), or retrieve "
            "YouTube captions"
        ),
    )
    create.add_argument("--transcription-model", default=default_model())
    create.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="VIDEO",
        help="Omit a video URL or ID; may be repeated",
    )
    create.add_argument(
        "--skip-missing-captions",
        action="store_true",
        help=(
            "Exclude videos whose requested caption language is unavailable or "
            "whose captions are disabled"
        ),
    )
    create.add_argument("--limit", type=int)
    create.add_argument("--import-only", action="store_true")
    create.add_argument(
        "--unlisted",
        action="store_true",
        help="Publish by URL without advertising the collection on the website",
    )
    create.add_argument("--dry-run", action="store_true")
    create.add_argument("--analysis-model", default=default_analysis_model())
    create.add_argument(
        "--normalization-model", default=default_normalization_model()
    )
    create.add_argument(
        "--normalization-batch-size",
        type=int,
        default=DEFAULT_NORMALIZATION_BATCH_SIZE,
    )
    create.add_argument("--retries", type=int, default=5)
    create.add_argument("--timeout", type=float, default=300)
    create.add_argument("--max-transcript-chars", type=int, default=1_500_000)
    create.add_argument("--force", action="store_true")

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
        if bool(args.url) == bool(args.playlist):
            raise ValueError("Provide either one YouTube video or --playlist, but not both")
        if args.playlist:
            result = import_youtube_playlist(
                args.workspace,
                args.playlist,
                collection_title=args.collection_title,
                language=args.language,
                force=args.force,
                start_position=args.position or 1,
                transcript_source=args.transcript_source,
                transcription_model=args.transcription_model,
            )
            skipped = len(result["failures"])
            duplicates = result["duplicate_count"]
            detail = []
            if skipped:
                detail.append(f"{skipped} skipped")
            if duplicates:
                detail.append(f"{duplicates} duplicate entries ignored")
            suffix = f" ({', '.join(detail)})" if detail else ""
            print(
                f"completed {result['completed_count']} videos from {result['title']} "
                f"({result['added_count']} added, {result['cached_count']} cached)"
                f"{suffix}"
            )
            set_collection_listing(args.workspace, unlisted=args.unlisted)
            return 0
        metadata = import_youtube(
            args.workspace,
            args.url,
            collection_title=args.collection_title,
            language=args.language,
            force=args.force,
            position=args.position,
            transcript_source=args.transcript_source,
            transcription_model=args.transcription_model,
        )
        set_collection_listing(args.workspace, unlisted=args.unlisted)
        duration = metadata.get("duration_seconds")
        duration_label = f"{duration // 60}:{duration % 60:02d}" if duration else "unknown"
        print(f"added {metadata['title']} ({duration_label})")
        return 0
    if args.command == "collection" and args.collection_command == "create":
        if args.limit is not None and args.limit < 1:
            raise ValueError("--limit must be at least 1")
        if args.normalization_batch_size < 1 or args.normalization_batch_size > 100:
            raise ValueError("--normalization-batch-size must be between 1 and 100")
        if args.skip_missing_captions and args.transcript_source != "captions":
            raise ValueError(
                "--skip-missing-captions requires --transcript-source captions"
            )
        return create_playlist_collection(args)
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


def entrypoint(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(entrypoint())
