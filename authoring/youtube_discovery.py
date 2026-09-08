"""Source-only YouTube discovery shared by legacy and queued authoring."""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable


USER_AGENT = "Mozilla/5.0 (compatible; WatchcraftAuthor/0.1; +https://watchcraft.dev)"


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
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not retrieve {url}: {error}") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"YouTube returned an invalid JSON response from {url}")
    return result


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


def youtube_initial_player_response(page: str) -> dict[str, Any] | None:
    match = re.search(
        r'(?:var\s+ytInitialPlayerResponse|window\["ytInitialPlayerResponse"\])'
        r"\s*=\s*",
        page,
    )
    if not match:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(page[match.end() :])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


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


def youtube_text(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.split())
    if not isinstance(value, dict):
        return ""
    simple_text = value.get("simpleText")
    if isinstance(simple_text, str):
        return " ".join(simple_text.split())
    runs = value.get("runs")
    if isinstance(runs, list):
        text = "".join(
            str(run.get("text") or "") for run in runs if isinstance(run, dict)
        )
        return " ".join(text.split())
    return ""


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


def discover_youtube_playlist(
    value: str,
    *,
    fetch_text: Callable[[str], str] = request_text,
    fetch_json: Callable[[str, dict[str, Any]], dict[str, Any]] = request_json,
) -> dict[str, Any]:
    playlist_id = youtube_playlist_id(value)
    canonical_url = "https://www.youtube.com/playlist?" + urllib.parse.urlencode(
        {"list": playlist_id}
    )
    page = fetch_text(f"{canonical_url}&hl=en")
    initial_data = youtube_initial_data(page)
    metadata = first_nested_mapping(initial_data, "playlistMetadataRenderer") or {}
    title = youtube_text(metadata.get("title"))
    description = youtube_text(metadata.get("description"))
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
        response = fetch_json(
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

    unique_video_ids = list(dict.fromkeys(video_ids))
    return {
        "playlist_id": playlist_id,
        "url": canonical_url,
        "title": title or playlist_id,
        "description": description,
        "entries": video_ids,
        "video_ids": unique_video_ids,
        "duplicate_count": len(video_ids) - len(unique_video_ids),
    }


def youtube_description_chapters(
    description: str, duration_seconds: int | None
) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    for line in description.splitlines():
        match = re.match(r"^\s*((?:\d{1,2}:)?\d{1,2}:\d{2})\s+(.+?)\s*$", line)
        if not match:
            continue
        seconds = 0
        for part in (int(part) for part in match.group(1).split(":")):
            seconds = seconds * 60 + part
        title = " ".join(match.group(2).split())
        if not title or (duration_seconds is not None and seconds >= duration_seconds):
            continue
        if chapters and seconds <= chapters[-1]["start_seconds"]:
            continue
        chapters.append({"start_seconds": seconds, "title": title})
    return chapters if len(chapters) >= 3 and chapters[0]["start_seconds"] == 0 else []


def discover_youtube_video(
    video_id: str,
    *,
    fetch_text: Callable[[str], str] = request_text,
) -> dict[str, Any]:
    canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    page = fetch_text(canonical_url)
    player_response = youtube_initial_player_response(page)
    playability = (
        player_response.get("playabilityStatus", {})
        if isinstance(player_response, dict)
        else {}
    )
    if isinstance(playability, dict) and playability.get("playableInEmbed") is False:
        raise RuntimeError("the video owner does not allow embedded playback in Watchcraft")
    oembed_url = "https://www.youtube.com/oembed?" + urllib.parse.urlencode(
        {"url": canonical_url, "format": "json"}
    )
    try:
        embed = json.loads(fetch_text(oembed_url))
    except json.JSONDecodeError as error:
        raise RuntimeError("YouTube returned invalid embed metadata") from error
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
