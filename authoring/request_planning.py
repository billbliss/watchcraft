"""Connect reviewed collection requests to the existing approval-bound planner.

This command enumerates metadata and runs only iterator/planner jobs. It never
approves a project execution, acquires audio, or runs model processing.
"""
from __future__ import annotations

import argparse
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from youtube_discovery import (
    discover_youtube_playlist, discover_youtube_video, first_json_string,
    request_json, request_text, youtube_initial_data, youtube_text,
)


def nested(value: Any, key: str) -> list[dict]:
    if isinstance(value, list):
        return [item for child in value for item in nested(child, key)]
    if not isinstance(value, dict):
        return []
    own = [value[key]] if isinstance(value.get(key), dict) else []
    return own + [item for child in value.values() for item in nested(child, key)]


def channel_members(url: str, popular: bool) -> list[str]:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.netloc != "www.youtube.com"
            or not re.fullmatch(r"/(?:channel/UC[\w-]{22}|@[\w.-]+)", parsed.path)):
        raise ValueError("The request has no verified channel link")
    page = request_text(f"{url}/videos?hl=en")
    data = youtube_initial_data(page)
    if not popular:
        metadata = nested(data, "channelMetadataRenderer")
        channel_id = metadata[0].get("externalId") if metadata else None
        if not isinstance(channel_id, str) or not re.fullmatch(r"UC[\w-]{22}", channel_id):
            raise ValueError("Could not resolve this channel's uploads playlist")
        return discover_youtube_playlist("UU" + channel_id[2:])["video_ids"]
    # Follow the explicitly labelled Popular control. Never infer popularity
    # from an ignored sort query parameter or the default Latest list.
    chips = nested(data, "chipViewModel")
    chip = next((c for c in chips if youtube_text(c.get("text")).lower() == "popular"), None)
    selected = bool(chip and chip.get("selected")) or any(
        c.get("isSelected") and youtube_text(c.get("text")).lower() == "popular"
        for c in nested(data, "chipCloudChipRenderer")
    )
    if not selected:
        token = ((chip or {}).get("tapCommand", {}).get("innertubeCommand", {})
                 .get("continuationCommand", {}).get("token"))
        version = first_json_string(page, "INNERTUBE_CLIENT_VERSION")
        if not token or not version:
            raise ValueError("YouTube's Popular list could not be verified; choose another scope")
        data = request_json("https://www.youtube.com/youtubei/v1/browse", {
            "context": {"client": {"clientName": "WEB", "clientVersion": version, "hl": "en"}},
            "continuation": token,
        })
    ids = [v.get("videoId") for v in nested(data, "videoRenderer")]
    ids += [v.get("contentId") for v in nested(data, "lockupViewModel")
            if v.get("contentType") == "LOCKUP_CONTENT_TYPE_VIDEO"]
    return list(dict.fromkeys(v for v in ids if isinstance(v, str)
                              and re.fullmatch(r"[\w-]{11}", v)))[:20]


def request_members(request: dict, max_videos: int) -> list[str]:
    scope = request["selected_scope"]
    target = next((o["targetUrl"] for o in request["options"] if o["scope"] == scope), None)
    if not target:
        raise ValueError("The selected scope is no longer available")
    anchor = request["source"].get("videoId")
    if scope == "video":
        ids = [anchor] if anchor else []
    elif scope == "playlist":
        parsed = urlparse(target)
        if parsed.scheme != "https" or parsed.netloc != "www.youtube.com" or parsed.path != "/playlist":
            raise ValueError("Invalid playlist target")
        ids = discover_youtube_playlist(target)["video_ids"]
    elif scope in {"popular", "channel"}:
        ids = channel_members(target, scope == "popular")
    else:
        raise ValueError("Unsupported request scope")
    ids = list(dict.fromkeys(ids))
    if not ids or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", v) for v in ids):
        raise ValueError("No complete, valid video list was found")
    if anchor and anchor not in ids:
        raise ValueError("The requested video is no longer in this scope; review the request again")
    if len(ids) > max_videos:
        raise ValueError(f"Found {len(ids)} videos, above the planning limit of {max_videos}; no partial plan was created")
    return ids


def request_project(request: dict, videos: list[dict]) -> dict:
    project_id = f"request-{request['_id']}-r{request['revision']}".lower()
    title = request["title"]
    scope = request["selected_scope"]
    if scope in {"popular", "channel"}:
        title = f"{request.get('channel') or title} — {'Popular videos' if scope == 'popular' else 'All videos'}"
    entries = []
    for video in videos:
        entry = {"item_id": f"youtube:{video['video_id']}", "title": video["title"],
                 "canonical_url": video["url"], "publisher": video["publisher"],
                 "media": [{"type": "youtube", "media_id": video["video_id"], "canonical_url": video["url"]}]}
        for key in ("duration_seconds", "publisher_url", "thumbnail_url", "published_at"):
            if video.get(key) is not None and video[key] != "":
                entry[key] = video[key]
        entries.append(entry)
    return {
        "kind": "watchcraft.catalog-project", "schema_version": 1, "project_id": project_id, "revision": 1,
        "collection_type": {"id": "watchcraft.video-collection", "version": "1", "configuration": {"structure": "ordered-list"}},
        "iterator": {"id": "watchcraft.explicit-membership", "version": "1",
            "configuration": {"canonical_url": request["source"]["url"],
                "nodes": [{"node_id": "request-root", "node_type": "collection-root", "title": title, "parent_node_id": None, "position": 1}],
                "entries": entries,
                "placements": [{"placement_id": f"request-placement:{i}", "item_id": entry["item_id"], "parent_node_id": "request-root", "position": i} for i, entry in enumerate(entries, 1)]},
            "access_profile": "public-anonymous", "refresh": {"mode": "on-demand", "stale_while_refresh": True}},
        "metadata": {"title": title}, "metadata_basis": {"title": {"origin": "editorial"}},
        "publication": {"collection_id": project_id, "listed": True},
    }


def prepare_request(args: argparse.Namespace, q: Any) -> int:
    if not 1 <= args.max_videos <= 5000 or not 1 <= args.timeout_seconds <= 900:
        raise ValueError("Use a video limit from 1 to 5000 and a job timeout from 1 to 900 seconds")
    control = q.operator_client(args.operator_token_source)
    request = control.post("/requests/get", {"request_id": args.request_id})
    if request and request["state"] == "planned" and request["revision"] == args.expected_revision + 1 and request.get("execution_id"):
        print("This request already has a plan in the portal.", flush=True)
        return 0
    if not request or request["state"] != "planning" or request["revision"] != args.expected_revision:
        raise ValueError("Select the current request revision marked for planning")
    attempt = str(uuid.uuid4())
    progress_args = {"request_id": args.request_id, "expected_revision": args.expected_revision, "attempt_id": attempt}
    def progress(stage: str):
        control.post("/requests/progress", {**progress_args, "stage": stage})
        print(f"Preparing request: {stage}", flush=True)
    def job_result(spec: dict, kind: str):
        result = q.submit_spec(control, request={"kind": kind, "request_id": args.request_id}, spec=spec)
        job = result["job"]
        approved = control.post("/submissions/approve", {"job_id": job["job_id"], "command_id": str(uuid.uuid4()),
            "expected_revision": job["revision"], "actor": "watchcraft-request-planner", "spec_sha256": job["spec_sha256"]})
        q.dispatch_submission(control, approved["job"])
        return q.wait_for_terminal_job(control, job["job_id"], args.timeout_seconds)["job"]
    progress("discovering")  # Acquiring the lease is outside the failure handler.
    try:
        project_id = f"request-{request['_id']}-r{request['revision']}".lower()
        project = request.get("prepared_project")
        if not project:
            ids = request_members(request, args.max_videos)
            videos = []
            for i, video_id in enumerate(ids):
                if i % 10 == 0:
                    progress("discovering")
                # Metadata only. Failure stops the plan instead of silently dropping a video.
                videos.append(discover_youtube_video(video_id))
            project = request_project(request, videos)
            q.validate_explicit_membership_project(project)
            control.post("/projects/import", {"command_id": str(uuid.uuid4()), "actor": "watchcraft-request-planner", "project": project})
        q.validate_explicit_membership_project(project)
        if len(project["iterator"]["configuration"]["entries"]) > args.max_videos:
            raise ValueError("The saved snapshot exceeds the requested planning limit")
        progress("snapshot")
        if not project["iterator"].get("accepted_snapshot"):
            observed = datetime.fromtimestamp(request["updated_at"] / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
            job = job_result(q.explicit_membership_iterator_spec(project, observed_at=observed), "collection-iteration")
            snapshot, payload = q.verified_json_result_bytes(job, args.r2_credentials_source)
            q.validate_iterator_snapshot(snapshot)
            accepted = control.post("/projects/accept-snapshot", {"project_id": project_id, "job_id": job["job_id"],
                "expected_revision": project["revision"], "command_id": str(uuid.uuid4()),
                "actor": "watchcraft-request-planner", "snapshot_json": payload.decode("utf-8")})
            project = accepted["project"]
        progress("estimating")
        job = job_result(q.project_processing_plan_spec(project), "project-processing-plan")
        # Reuse the normal plan validation and approval-bound execution builder.
        progress("linking")
        q.create_pending_project_execution(control, argparse.Namespace(
            plan_job_id=job["job_id"], r2_credentials_source=args.r2_credentials_source,
            item_id=None, limit=None, process_all=True, concurrency=2, submitted_by="watchcraft-request-planner", request_args=progress_args))
        print("Plan ready in the portal. Processing is waiting for owner approval.", flush=True)
        return 0
    except Exception:
        try:
            progress("failed")
        except Exception:
            pass  # Never overwrite a new request revision or obscure the original failure.
        raise
