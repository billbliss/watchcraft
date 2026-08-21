#!/usr/bin/env python3
"""Build searchable HTML and CSV catalogs from structured video analyses."""

from __future__ import annotations

import argparse
import hashlib
import csv
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from video_catalog import CATALOG_DIR_NAME, atomic_write_text, validated_root


TOKEN_ALIASES = {
    "beams": "beam", "blending": "blend", "brushes": "brush",
    "burning": "burn", "channels": "channel", "colors": "color",
    "composites": "composite", "compositing": "composite",
    "cropping": "crop", "curves": "curve", "dodging": "dodge",
    "filters": "filter", "grading": "grade", "gradients": "gradient",
    "highlights": "highlight", "layers": "layer", "masking": "mask",
    "masks": "mask", "rays": "ray", "reflections": "reflection",
    "selections": "selection", "shadows": "shadow",
    "sharpening": "sharpen", "textures": "texture", "tones": "tone",
    "toning": "tone", "warping": "warp",
}
MATCH_STOP_WORDS = {
    "a", "an", "and", "based", "for", "in", "of", "on", "or", "the",
    "to", "using", "with", "adobe", "photoshop", "technique", "tool",
}


def canonical_topic_key(value: str) -> str:
    """Match the browser's case-insensitive topic identity."""
    return " ".join(str(value or "").casefold().split())


def analysis_topics(analysis: dict) -> list[str]:
    """Return the analysis topics in source order."""
    topics = analysis.get("topics")
    return topics if isinstance(topics, list) else []


def normalized_phrase(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def normalized_tokens(value: str) -> set[str]:
    tokens = []
    for token in re.findall(r"[a-z0-9]+", str(value or "").casefold()):
        if token in MATCH_STOP_WORDS:
            continue
        token = TOKEN_ALIASES.get(token, token)
        if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        tokens.append(token)
    return set(tokens)


def topic_aliases(topic: str) -> list[str]:
    values = [topic, *re.split(r"[/|]", str(topic or ""))]
    aliases = []
    for value in values:
        normalized = normalized_phrase(value)
        if normalized and normalized not in aliases:
            aliases.append(normalized)
    return aliases


def exact_phrase_match(topic: str, text: str) -> bool:
    haystack = f" {normalized_phrase(text)} "
    return any(f" {alias} " in haystack for alias in topic_aliases(topic))


def related_term_match(topic: str, text: str) -> bool:
    if exact_phrase_match(topic, text):
        return True
    text_tokens = normalized_tokens(text)
    for alias in topic_aliases(topic):
        topic_tokens = normalized_tokens(alias)
        if topic_tokens and (len(topic_tokens) > 1 or len(next(iter(topic_tokens))) >= 4):
            if topic_tokens <= text_tokens:
                return True
    return False


def clock_seconds(value: str | float | int | None) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    try:
        total = 0.0
        for part in str(value or "0").split(":"):
            total = total * 60 + float(part)
        return total
    except ValueError:
        return -1.0


def section_for_time(sections: list[dict], timestamp: str | float | int) -> int | None:
    moment = clock_seconds(timestamp)
    for index, section in enumerate(sections):
        start = clock_seconds(section.get("start"))
        end = clock_seconds(section.get("end"))
        is_last = index == len(sections) - 1
        if start <= moment < end or (is_last and moment == end):
            return index
    return None


def build_topic_chapter_map(analysis: dict, transcript_segments: list[dict]) -> dict[str, list[int]]:
    """Derive conservative topic-to-chapter links without changing source analyses."""
    sections = analysis.get("sections", [])
    prepared_segments = [
        (segment, normalized_phrase(segment.get("text", "")))
        for segment in transcript_segments
    ]
    mapping: dict[str, list[int]] = {}

    for topic in analysis_topics(analysis):
        key = canonical_topic_key(topic)
        if not key or key in mapping:
            continue

        # Combine strong structured evidence; use prose/transcript only as fallback.
        hits = {
            index
            for index, section in enumerate(sections)
            if any(
                normalized_phrase(concept) in topic_aliases(topic)
                for concept in section.get("concepts", [])
            )
        }
        hits.update(
            index
            for index, section in enumerate(sections)
            if any(
                related_term_match(topic, concept)
                for concept in section.get("concepts", [])
            )
        )
        for technique in analysis.get("featured_techniques", []):
            if related_term_match(topic, technique.get("technique", "")):
                index = section_for_time(sections, technique.get("timestamp", ""))
                if index is not None:
                    hits.add(index)
        hits.update(
            index
            for index, section in enumerate(sections)
            if related_term_match(topic, section.get("title", ""))
        )

        if not hits:
            hits = {
                index
                for index, section in enumerate(sections)
                if exact_phrase_match(topic, section.get("description", ""))
            }

        if not hits:
            for segment, normalized_text in prepared_segments:
                if not related_term_match(topic, normalized_text):
                    continue
                midpoint = (
                    clock_seconds(segment.get("start"))
                    + clock_seconds(segment.get("end"))
                ) / 2
                index = section_for_time(sections, midpoint)
                if index is not None:
                    hits.add(index)

        if hits:
            mapping[key] = sorted(hits)
    return mapping


def load_topic_chapter_maps(root: Path, analyses: list[dict]) -> dict[str, dict[str, list[int]]]:
    maps = {}
    transcript_root = root / CATALOG_DIR_NAME / "transcripts"
    for analysis in analyses:
        video = analysis.get("video", "")
        transcript_path = transcript_root / Path(video).with_suffix(".transcript.json")
        segments = []
        if transcript_path.exists():
            with transcript_path.open(encoding="utf-8") as handle:
                segments = json.load(handle).get("segments", [])
        maps[video] = build_topic_chapter_map(analysis, segments)
    return maps


def load_analyses(root: Path) -> list[dict]:
    analysis_root = root / CATALOG_DIR_NAME / "analysis"
    analyses = []
    if not analysis_root.exists():
        return analyses
    for path in sorted(analysis_root.rglob("*.analysis.json")):
        with path.open(encoding="utf-8") as handle:
            analyses.append(json.load(handle))
    return analyses


COLLECTION_SCHEMA_VERSION = 2


def stable_id(prefix: str, value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:48]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{slug or 'item'}-{digest}"


def load_collection_manifest(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read collection manifest: {path}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"Collection manifest is not an object: {path}")
    return payload


def load_topic_normalization(root: Path) -> dict | None:
    path = root / CATALOG_DIR_NAME / "topic-normalization.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read topic normalization: {path}") from error
    if not isinstance(payload, dict) or payload.get("status") != "complete":
        return None
    return payload


def build_collection_manifest(
    root: Path,
    analyses: list[dict],
    topic_chapter_maps: dict[str, dict[str, list[int]]],
    previous: dict | None = None,
    normalization: dict | None = None,
) -> dict:
    """Build the Collection-scoped canonical index without rewriting resources."""
    previous = previous or {}
    title = str(previous.get("title") or root.name or "Video Collection")
    collection_id = str(
        previous.get("collection_id")
        or re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
        or "video-collection"
    )

    previous_items_by_path = {}
    for item_id, item in previous.get("items", {}).items():
        for media in item.get("media", []):
            if media.get("type") == "local-file" and media.get("relative_path"):
                previous_items_by_path[media["relative_path"]] = item_id

    normalization = normalization or {}
    assignments = normalization.get("assignments", {})
    normalized_families = normalization.get("families", {})

    def assignment_for(raw_topic: str) -> dict:
        source_key = canonical_topic_key(raw_topic)
        assignment = assignments.get(source_key, {})
        canonical_label = " ".join(
            str(assignment.get("canonical_label") or raw_topic).split()
        )
        return {
            "canonical_key": canonical_topic_key(canonical_label),
            "canonical_label": canonical_label,
            "family_ids": [
                family_id
                for family_id in assignment.get("family_ids", [])
                if family_id in normalized_families
            ],
        }

    topic_forms: dict[str, Counter] = defaultdict(Counter)
    topic_labels: dict[str, Counter] = defaultdict(Counter)
    topic_videos: dict[str, set[str]] = defaultdict(set)
    topic_family_ids: dict[str, set[str]] = defaultdict(set)
    family_videos: dict[str, set[str]] = defaultdict(set)
    for analysis in analyses:
        video = analysis.get("video", "")
        seen = set()
        for raw_topic in analysis_topics(analysis):
            label = " ".join(str(raw_topic).split())
            assignment = assignment_for(label)
            key = assignment["canonical_key"]
            if not key:
                continue
            topic_forms[key][label] += 1
            topic_labels[key][assignment["canonical_label"]] += 1
            topic_family_ids[key].update(assignment["family_ids"])
            for family_id in assignment["family_ids"]:
                family_videos[family_id].add(video)
            if key not in seen:
                topic_videos[key].add(video)
                seen.add(key)

    previous_topics_by_key = {
        topic.get("canonical_key"): topic_id
        for topic_id, topic in previous.get("topics", {}).items()
        if topic.get("canonical_key")
    }
    topic_ids = {
        key: previous_topics_by_key.get(key) or stable_id("topic", key)
        for key in sorted(topic_forms)
    }
    topics = {}
    for key, topic_id in topic_ids.items():
        forms = sorted(
            topic_forms[key].items(),
            key=lambda item: (-item[1], item[0].casefold(), item[0]),
        )
        labels = sorted(
            topic_labels[key].items(),
            key=lambda item: (-item[1], item[0].casefold(), item[0]),
        )
        label = labels[0][0]
        topics[topic_id] = {
            "topic_id": topic_id,
            "canonical_key": key,
            "label": label,
            "aliases": [form for form, _ in forms if form != label],
            "video_count": len(topic_videos[key]),
            "family_ids": sorted(topic_family_ids[key]),
            "related_topic_ids": [],
        }

    for source_key, related_keys in normalization.get("related", {}).items():
        source_id = topic_ids.get(source_key)
        if not source_id:
            continue
        topics[source_id]["related_topic_ids"] = sorted(
            topic_ids[key] for key in related_keys if key in topic_ids and key != source_key
        )

    families = {}
    for family_id, family in sorted(normalized_families.items()):
        member_ids = sorted(
            topic_id
            for key, topic_id in topic_ids.items()
            if family_id in topic_family_ids[key]
        )
        families[family_id] = {
            "family_id": family_id,
            "canonical_key": family.get("canonical_key", ""),
            "label": family.get("label", family_id),
            "description": family.get("description", ""),
            "topic_ids": member_ids,
            "video_count": len(family_videos[family_id]),
        }

    items = {}
    item_ids_by_video = {}
    for analysis in sorted(analyses, key=lambda item: item.get("video", "").casefold()):
        video = analysis.get("video", "")
        item_id = previous_items_by_path.get(video) or stable_id(
            "video", f"{collection_id}:{video}"
        )
        item_ids_by_video[video] = item_id
        relative = Path(video)
        ordered_topics = []
        ordered_families = []
        seen_topics = set()
        seen_families = set()
        for raw_topic in analysis_topics(analysis):
            assignment = assignment_for(raw_topic)
            topic_id = topic_ids.get(assignment["canonical_key"])
            if topic_id and topic_id not in seen_topics:
                ordered_topics.append(topic_id)
                seen_topics.add(topic_id)
            for family_id in assignment["family_ids"]:
                if family_id not in seen_families:
                    ordered_families.append(family_id)
                    seen_families.add(family_id)
        section_sets: dict[str, set[int]] = defaultdict(set)
        for source_key, indexes in topic_chapter_maps.get(video, {}).items():
            assignment = assignment_for(source_key)
            topic_id = topic_ids.get(assignment["canonical_key"])
            if topic_id:
                section_sets[topic_id].update(indexes)
        topic_sections = {
            topic_id: sorted(indexes) for topic_id, indexes in section_sets.items()
        }
        items[item_id] = {
            "item_id": item_id,
            "title": analysis.get("title") or relative.stem,
            "media": [{"type": "local-file", "relative_path": video}],
            "transcript": {
                "subtitles": (
                    Path("transcripts") / relative.with_suffix(".srt")
                ).as_posix(),
                "text": (
                    Path("transcripts") / relative.with_suffix(".transcript.txt")
                ).as_posix(),
                "segments": (
                    Path("transcripts") / relative.with_suffix(".transcript.json")
                ).as_posix(),
            },
            "analysis": {
                "path": (
                    Path("analysis") / relative.with_suffix(".analysis.json")
                ).as_posix(),
                "schema_version": analysis.get("schema_version"),
                "model": analysis.get("analysis_model"),
            },
            "summary": analysis.get("summary", ""),
            "date": analysis.get("date"),
            "locations": analysis.get("locations", []),
            "topic_ids": ordered_topics,
            "family_ids": ordered_families,
            "topic_sections": topic_sections,
            "chapter_count": len(analysis.get("sections", [])),
        }

    group_tree = {"groups": {}, "items": []}
    for video, item_id in sorted(item_ids_by_video.items(), key=lambda pair: pair[0].casefold()):
        node = group_tree
        for part in Path(video).parent.parts:
            node = node["groups"].setdefault(part, {"groups": {}, "items": []})
        node["items"].append(item_id)

    def serialize_group(node: dict, parts: tuple[str, ...], *, root_group: bool = False) -> dict:
        children = []
        for name, child in sorted(node["groups"].items(), key=lambda pair: pair[0].casefold()):
            children.append(serialize_group(child, (*parts, name)))
        children.extend(
            {"type": "video", "item_id": item_id}
            for item_id in sorted(node["items"], key=lambda value: items[value]["title"].casefold())
        )
        group_title = title if root_group else parts[-1]
        return {
            "type": "group",
            "group_id": "root" if root_group else stable_id(
                "group", f"{collection_id}:{'/'.join(parts)}"
            ),
            "title": group_title,
            "children": children,
        }

    manifest_body = {
        "schema_version": COLLECTION_SCHEMA_VERSION,
        "collection_id": collection_id,
        "title": title,
        "topic_scope": "collection",
        "topic_normalization": {
            "schema_version": normalization.get("schema_version"),
            "prompt_version": normalization.get("prompt_version"),
            "model": normalization.get("model"),
            "source_hash": normalization.get("source_hash"),
        } if normalization else None,
        "root": serialize_group(group_tree, (), root_group=True),
        "topics": topics,
        "topic_families": families,
        "items": items,
        "stats": {
            "video_count": len(items),
            "topic_count": len(topics),
            "topic_family_count": len(families),
        },
    }
    for field in ("description", "publisher", "metadata_url", "license", "source"):
        if field in previous:
            manifest_body[field] = previous[field]
    content_hash = hashlib.sha256(
        json.dumps(manifest_body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    previous_revision = int(previous.get("revision", 0) or 0)
    revision = (
        previous_revision
        if previous.get("content_hash") == content_hash and previous_revision
        else previous_revision + 1
    )
    return {
        **manifest_body,
        "revision": revision,
        "content_hash": content_hash,
    }


def primary_location(analysis: dict) -> str:
    locations = analysis.get("locations", [])
    return locations[0].get("name", "") if locations else ""


def render_csv(analyses: list[dict], collection_manifest: dict | None = None) -> str:
    item_topics_by_video = {}
    if collection_manifest:
        topic_registry = collection_manifest.get("topics", {})
        for item in collection_manifest.get("items", {}).values():
            media = item.get("media", [])
            if not media:
                continue
            video = media[0].get("relative_path")
            item_topics_by_video[video] = [
                topic_registry[topic_id]["label"]
                for topic_id in item.get("topic_ids", [])
                if topic_id in topic_registry
            ]
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "video", "title", "date", "location", "summary", "topics",
            "featured_techniques", "section_count",
        ],
    )
    writer.writeheader()
    for analysis in analyses:
        writer.writerow(
            {
                "video": analysis.get("video", ""),
                "title": analysis.get("title", ""),
                "date": analysis.get("date", {}).get("display", ""),
                "location": primary_location(analysis),
                "summary": analysis.get("summary", ""),
                "topics": "; ".join(
                    item_topics_by_video.get(
                        analysis.get("video", ""), analysis_topics(analysis)
                    )
                ),
                "featured_techniques": "; ".join(
                    f"{item.get('technique', '')} @ {item.get('timestamp', '')}"
                    for item in analysis.get("featured_techniques", [])
                ),
                "section_count": len(analysis.get("sections", [])),
            }
        )
    return output.getvalue()


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Watchcraft</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --bg: #0c100e; --panel: #141a16; --panel-2: #1a221d; --line: #2b3830;
      --muted: #91a098; --text: #edf3ee; --accent: #a8e3b9; --accent-bg: #24382b;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body { margin: 0; overflow: hidden; background: var(--bg); color: var(--text); }
    button, input { font: inherit; }
    button, a { -webkit-tap-highlight-color: transparent; }
    .app { height: 100%; display: grid; grid-template-columns: minmax(320px, 46%) 8px minmax(420px, 1fr); }
    .sidebar { min-width: 0; min-height: 0; overflow: hidden; display: flex; flex-direction: column; border-right: 1px solid var(--line); background: #101512; }
    .sidebar-head { padding: 25px 23px 16px; border-bottom: 1px solid var(--line); }
    .brand { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .brand-copy { min-width: 0; }
    .product-tagline { margin-top: 2px; color: var(--muted); font-size: .72rem; }
    .collection-title { margin-top: 5px; overflow: hidden; color: #c6d0c9; font-size: .8rem; text-overflow: ellipsis; white-space: nowrap; }
    .brand-meta { display: flex; align-items: center; gap: 8px; }
    h1 { margin: 0; font-size: 1.35rem; letter-spacing: -.025em; }
    .count { color: var(--muted); font-size: .82rem; white-space: nowrap; }
    .clear-all-filters { width: 28px; height: 28px; padding: 0; border: 1px solid #405047; border-radius: 50%; background: #1b241e; color: #cbd5ce; cursor: pointer; font-size: 1.2rem; line-height: 1; }
    .clear-all-filters:hover { border-color: #659175; background: #26362c; color: var(--text); }
    .search { width: 100%; margin-top: 16px; padding: 12px 14px; border: 1px solid #35443a; border-radius: 10px; background: var(--panel-2); color: inherit; outline: none; }
    .search:focus { border-color: #70aa81; box-shadow: 0 0 0 3px #70aa8126; }
    input[type="search"]::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }
    .filters { flex: 0 0 auto; max-height: 46%; overflow: hidden; border-bottom: 1px solid var(--line); background: #111713; }
    .filters > summary { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 22px; color: #c6d0c9; cursor: pointer; font-size: .86rem; font-weight: 650; list-style: none; }
    .filters > summary::-webkit-details-marker { display: none; }
    .filters > summary::before { content: "▸"; flex: 0 0 24px; width: 24px; height: 24px; display: inline-grid; place-items: center; margin-right: 7px; border: 1px solid #3a4a40; border-radius: 6px; background: #1a221d; color: #c9d5cc; font-size: 1.15rem; line-height: 1; }
    .filters > summary:hover::before { border-color: #659175; background: #243129; color: var(--text); }
    .filters[open] > summary::before { content: "▾"; }
    .filter-label { flex: 1; }
    .filter-badge { color: var(--accent); font-size: .75rem; font-weight: 500; }
    .filter-panel { padding: 0 14px 13px; }
    .threshold-row { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 5px 10px; color: var(--muted); font-size: .76rem; }
    .threshold-row input { grid-column: 1 / -1; width: 100%; accent-color: #76b489; }
    .topic-filter-search { width: 100%; margin-top: 10px; padding: 8px 10px; border: 1px solid #35443a; border-radius: 8px; background: var(--panel-2); color: inherit; outline: none; font-size: .82rem; }
    .filter-note { margin: 7px 1px; color: #748078; font-size: .69rem; }
    .facet-list { max-height: min(270px, 28vh); overflow-y: auto; display: grid; gap: 2px; padding-right: 3px; }
    .facet-heading { margin: 8px 7px 3px; color: #829087; font-size: .67rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
    .facet { display: grid; grid-template-columns: 18px minmax(0, 1fr) auto; align-items: center; gap: 7px; padding: 6px 7px; border-radius: 7px; color: #c9d2cb; cursor: pointer; font-size: .78rem; }
    .facet:hover { background: #1b241e; }
    .facet input { margin: 0; accent-color: #76b489; }
    .facet-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .facet-count { color: var(--muted); font-variant-numeric: tabular-nums; font-size: .7rem; }
    .filter-footer { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-top: 8px; color: var(--muted); font-size: .69rem; }
    .video-list { flex: 1; min-height: 0; overflow-y: auto; padding: 8px; }
    .video-row { width: 100%; display: block; padding: 14px 15px; border: 1px solid transparent; border-radius: 11px; background: transparent; color: inherit; text-align: left; cursor: pointer; }
    .video-row:hover { background: #19201b; }
    .video-row.active { background: var(--accent-bg); border-color: #3f6049; }
    .row-title { display: block; margin-bottom: 7px; font-weight: 650; line-height: 1.3; }
    .row-meta { display: flex; flex-wrap: wrap; gap: 5px 11px; color: var(--muted); font-size: .78rem; line-height: 1.35; }
    .empty { padding: 36px 18px; color: var(--muted); text-align: center; }
    .splitter { position: relative; cursor: col-resize; background: #0a0e0c; touch-action: none; }
    .splitter::after { content: ""; position: absolute; inset: 0 2px; border-radius: 3px; background: #2b3830; transition: background .15s; }
    .splitter:hover::after, .splitter.dragging::after { background: #77b188; }
    .detail { min-width: 0; overflow: hidden; background: var(--bg); }
    .detail-layout { height: 100%; display: grid; grid-template-rows: minmax(190px, 52%) 8px minmax(180px, 1fr); }
    .player-pane { min-height: 0; display: grid; place-items: center; padding: 18px 30px; background: #080b09; }
    .player-shell { position: relative; width: min(1020px, 100%); height: 100%; overflow: hidden; border: 1px solid #324038; border-radius: 14px; background: #050706; box-shadow: 0 18px 50px #0008; }
    video { width: 100%; height: 100%; display: block; object-fit: contain; background: #050706; }
    .horizontal-splitter { position: relative; cursor: row-resize; background: #0a0e0c; touch-action: none; }
    .horizontal-splitter::after { content: ""; position: absolute; inset: 2px 0; border-radius: 3px; background: #2b3830; transition: background .15s; }
    .horizontal-splitter:hover::after, .horizontal-splitter.dragging::after { background: #77b188; }
    .detail-scroll { min-height: 0; overflow-y: auto; }
    .detail-inner { width: min(1440px, 100%); margin: 0 auto; padding: 18px 30px 72px; }
    .detail-columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(420px, 100%), 1fr)); gap: 24px 32px; align-items: start; }
    .detail-column { min-width: 0; }
    .detail-chapters > h3 { margin-top: 0; }
    .kicker { margin: 0 0 7px; color: var(--muted); font-size: .78rem; letter-spacing: .04em; text-transform: uppercase; }
    h2 { margin: 0; max-width: 900px; font-size: clamp(1.65rem, 3vw, 2.6rem); line-height: 1.09; letter-spacing: -.035em; }
    .fact-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0 0; }
    .fact { border: 1px solid var(--line); border-radius: 999px; padding: 7px 10px; background: var(--panel); color: #c6d0c9; font-size: .84rem; }
    .actions { display: flex; flex-wrap: wrap; gap: 9px; margin: 18px 0 25px; }
    .action { display: inline-flex; align-items: center; min-height: 39px; padding: 8px 12px; border: 1px solid #405047; border-radius: 9px; background: #1b241e; color: var(--text); text-decoration: none; cursor: pointer; }
    .action.primary { border-color: #578c67; background: #2e5139; }
    .action:hover { filter: brightness(1.12); }
    .action:disabled { opacity: .52; cursor: default; filter: none; }
    .summary { margin: 0; max-width: 900px; color: #cad4cd; font-size: 1rem; line-height: 1.68; }
    h3 { margin: 30px 0 12px; font-size: 1.05rem; letter-spacing: -.01em; }
    .topics { display: flex; flex-wrap: wrap; gap: 7px; }
    .topic-pill { padding: 5px 9px; border: 1px solid #3c5745; border-radius: 999px; background: #18271d; color: #cce5d2; font-size: .78rem; }
    .topic-pill.navigable { cursor: pointer; }
    .topic-pill.navigable:hover { border-color: #70aa81; background: #213a29; }
    .topic-pill.navigable.active { border-color: #9be5af; background: #315c3e; color: #f1fff4; box-shadow: 0 0 0 2px #78bd8b33; }
    .topic-pill.navigable.active::before { content: "✓"; margin-right: 5px; font-size: .7rem; }
    .related-topics { margin-top: 12px; padding: 11px 12px; border: 1px solid var(--line); border-radius: 10px; background: #111713; }
    .related-label { display: block; margin-bottom: 8px; color: var(--muted); font-size: .72rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
    .related-empty { margin: 0; color: var(--muted); font-size: .82rem; line-height: 1.45; }
    .related-topic { cursor: pointer; }
    .related-topic:hover { border-color: #70aa81; background: #213a29; }
    .related-topic.selected::before { content: "✓"; margin-right: 5px; font-size: .7rem; }
    .timeline { display: grid; gap: 8px; }
    .chapter { width: 100%; display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 10px; padding: 13px 14px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: inherit; text-align: left; cursor: pointer; }
    .chapter:hover { border-color: #4e7259; background: #18221b; }
    .chapter.topic-match { border-color: #83cf98; background: #172b1d; box-shadow: inset 4px 0 #83cf98, 0 0 0 1px #83cf9830; }
    .chapter-time { color: var(--accent); font-variant-numeric: tabular-nums; font-size: .82rem; }
    .chapter-title { display: block; margin-bottom: 4px; font-weight: 650; }
    .chapter-desc { display: block; color: var(--muted); font-size: .85rem; line-height: 1.45; }
    .chapter-match-label { display: block; margin-top: 7px; color: #a8e3b9; font-size: .72rem; font-weight: 650; }
    .detail-inner details { max-width: 900px; margin-top: 27px; border-top: 1px solid var(--line); padding-top: 15px; color: var(--muted); font-size: .85rem; }
    .detail-inner summary { color: #b7c2ba; cursor: pointer; }
    .evidence { margin: 12px 0 0; padding-left: 19px; line-height: 1.55; }
    .placeholder { height: 100%; display: grid; place-items: center; padding: 40px; color: var(--muted); text-align: center; }
    [hidden] { display: none !important; }
    @media (max-width: 760px) {
      body { overflow: auto; }
      .app { height: auto; min-height: 100%; display: block; }
      .sidebar { height: 44vh; min-height: 300px; border-right: 0; border-bottom: 1px solid var(--line); }
      .splitter { display: none; }
      .detail { overflow: visible; }
      .detail-layout { height: auto; display: block; }
      .player-pane { position: sticky; top: 0; z-index: 5; height: min(56vw, 48vh); padding: 10px 16px; }
      .horizontal-splitter { display: none; }
      .detail-scroll { overflow: visible; }
      .detail-inner { padding: 18px 16px 55px; }
      .chapter { grid-template-columns: 65px minmax(0, 1fr); }
    }
  </style>
</head>
<body>
  <main class="app" id="app">
    <aside class="sidebar">
      <div class="sidebar-head">
        <div class="brand"><div class="brand-copy"><h1>Watchcraft</h1><div class="product-tagline">Learn a craft by watching</div><div class="collection-title" id="collection-title"></div></div><div class="brand-meta"><span class="count" id="count"></span><button class="clear-all-filters" id="clear-all-filters" type="button" aria-label="Clear all filters" title="Clear text and topic filters" hidden>×</button></div></div>
        <input class="search" id="search" type="search" placeholder="Search techniques, year, location…" autofocus>
      </div>
      <details class="filters" id="filters">
        <summary><span class="filter-label">Filter by topic</span><span class="filter-badge" id="filter-badge"></span></summary>
        <div class="filter-panel">
          <label class="threshold-row" for="topic-threshold">
            <span>Show topics used by at most</span><output id="threshold-value">40%</output>
            <input id="topic-threshold" type="range" min="1" max="100" value="40">
          </label>
          <input class="topic-filter-search" id="topic-filter-search" type="search" placeholder="Find a topic…">
          <div class="filter-note">Searching topics temporarily shows common and one-off topics.</div>
          <div class="facet-list">
            <div id="family-facet-section" hidden>
              <div class="facet-heading">Families</div>
              <div id="family-facets"></div>
            </div>
            <div class="facet-heading">Topics</div>
            <div id="topic-facets"></div>
          </div>
          <div class="filter-footer"><span id="facet-info"></span></div>
        </div>
      </details>
      <div class="video-list" id="video-list"></div>
    </aside>
    <div class="splitter" id="splitter" role="separator" aria-orientation="vertical" aria-label="Resize catalog and video panels"></div>
    <section class="detail" id="detail">
      <div class="placeholder" id="placeholder">Select a video to see its techniques and timeline.</div>
      <div class="detail-layout" id="detail-layout" hidden>
        <div class="player-pane">
          <div class="player-shell"><video id="player" controls preload="metadata" playsinline></video></div>
        </div>
        <div class="horizontal-splitter" id="horizontal-splitter" role="separator" aria-orientation="horizontal" aria-label="Resize video and timeline panes"></div>
        <div class="detail-scroll" id="detail-scroll">
          <div class="detail-inner">
            <div class="kicker" id="path"></div>
            <h2 id="title"></h2>
            <div class="fact-row" id="facts"></div>
            <div class="actions">
              <button class="action primary" id="native-open" type="button">Open in default player</button>
              <a class="action" id="video-link" target="_blank">Open video file</a>
              <a class="action" id="transcript-link" target="_blank">Read transcript</a>
            </div>
            <div class="detail-columns">
              <div class="detail-column detail-overview">
                <p class="summary" id="summary"></p>
                <h3>Concepts and techniques</h3>
                <div class="topics" id="topics"></div>
                <div class="related-topics" id="related-topics" hidden>
                  <span class="related-label">Related topics</span>
                  <p class="related-empty" id="related-empty">Select a topic above to see related topics.</p>
                  <div class="topics" id="related-topic-pills"></div>
                </div>
                <details id="evidence"><summary>Date and location evidence</summary><ul class="evidence" id="evidence-list"></ul></details>
              </div>
              <div class="detail-column detail-chapters">
                <h3>Technique timeline</h3>
                <div class="timeline" id="timeline"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </main>
  <script>
    const catalogData = __CATALOG_DATA__;
    const collection = catalogData.collection;
    const videos = catalogData.videos;

    function canonicalTopicKey(value) {
      return String(value || '').trim().replace(/\s+/g, ' ').toLocaleLowerCase();
    }
    function parseSearchGroups(value) {
      const groups = [];
      const pattern = /"([^"]+)"|(\S+)/g;
      for (const match of String(value || '').toLocaleLowerCase().matchAll(pattern)) {
        const quoted = match[1];
        const token = quoted || match[2];
        if (quoted) {
          groups.push(token.trim().replace(/\s+/g, ' '));
        } else if (/^\d+(?:\.\d+)?$/.test(token) && groups.length) {
          groups[groups.length - 1] += ` ${token}`;
        } else {
          groups.push(token);
        }
      }
      return groups.filter(Boolean);
    }
    function buildTopicStats() {
      return Object.values(collection.topics || {}).map(topic => ({
        id: topic.topic_id,
        key: topic.canonical_key,
        label: topic.label,
        count: topic.video_count,
        percentage: videos.length ? topic.video_count * 100 / videos.length : 0,
        familyIds: topic.family_ids || [],
        relatedTopicIds: topic.related_topic_ids || []
      })).sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));
    }
    function buildFamilyStats() {
      return Object.values(collection.topic_families || {}).map(family => ({
        id: family.family_id,
        key: family.canonical_key,
        label: family.label,
        description: family.description,
        count: family.video_count,
        percentage: videos.length ? family.video_count * 100 / videos.length : 0
      })).sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));
    }

    const topicStats = buildTopicStats();
    const familyStats = buildFamilyStats();
    const topicStatsById = new Map(topicStats.map(topic => [topic.id, topic]));
    const familyStatsById = new Map(familyStats.map(family => [family.id, family]));
    const validTopicIds = new Set(topicStatsById.keys());
    const validFamilyIds = new Set(familyStatsById.keys());
    const videosByItemId = new Map(videos.map(video => [video._itemId, video]));

    function readFilterRoute() {
      const params = new URLSearchParams(location.search);
      const routeMatch = location.protocol === 'file:'
        ? null
        : location.pathname.match(/^\/video\/([^/]+)\/?$/);
      const videoId = routeMatch
        ? decodeURIComponent(routeMatch[1])
        : null;
      return {
        query: params.get('q') || '',
        videoId: videosByItemId.has(videoId) ? videoId : null,
        topicIds: params.getAll('topic').filter(id => validTopicIds.has(id)),
        familyIds: params.getAll('family').filter(id => validFamilyIds.has(id))
      };
    }
    const initialFilter = readFilterRoute();
    const state = {
      filtered: videos,
      selected: null,
      selectedTopics: new Set(initialFilter.topicIds),
      selectedFamilies: new Set(initialFilter.familyIds),
      activeTopicId: null,
      activeTopicLabel: '',
      activeTopicSections: []
    };
    const app = document.querySelector('#app');
    const sidebar = document.querySelector('.sidebar');
    const list = document.querySelector('#video-list');
    const input = document.querySelector('#search');
    const clearAllFilters = document.querySelector('#clear-all-filters');
    const count = document.querySelector('#count');
    const collectionTitle = document.querySelector('#collection-title');
    const player = document.querySelector('#player');
    const nativeOpen = document.querySelector('#native-open');
    const topicThreshold = document.querySelector('#topic-threshold');
    const thresholdValue = document.querySelector('#threshold-value');
    const topicFilterSearch = document.querySelector('#topic-filter-search');
    const topicFacets = document.querySelector('#topic-facets');
    const familyFacetSection = document.querySelector('#family-facet-section');
    const familyFacets = document.querySelector('#family-facets');
    const facetInfo = document.querySelector('#facet-info');
    const filterBadge = document.querySelector('#filter-badge');
    const relatedTopics = document.querySelector('#related-topics');
    const relatedEmpty = document.querySelector('#related-empty');
    const relatedTopicPills = document.querySelector('#related-topic-pills');

    const savedThreshold = Number(localStorage.getItem('videoCatalogTopicThreshold'));
    if (savedThreshold >= 1 && savedThreshold <= 100) topicThreshold.value = savedThreshold;
    input.value = initialFilter.query;
    collectionTitle.textContent = collection.title || 'Video collection';
    document.title = `${collection.title || 'Video collection'} — Watchcraft`;

    function writeFilterRoute({ replace = false } = {}) {
      const params = new URLSearchParams();
      const query = input.value.trim();
      if (location.protocol === 'file:' && state.selected?._itemId) {
        params.set('video', state.selected._itemId);
      }
      if (query) params.set('q', query);
      for (const id of [...state.selectedTopics].sort()) params.append('topic', id);
      for (const id of [...state.selectedFamilies].sort()) params.append('family', id);
      const routePath = location.protocol === 'file:'
        ? location.pathname
        : state.selected?._itemId
          ? `/video/${encodeURIComponent(state.selected._itemId)}`
          : '/';
      const queryString = params.toString();
      history[replace ? 'replaceState' : 'pushState'](
        {}, '', `${routePath}${queryString ? `?${queryString}` : ''}`
      );
    }

    function commitFilterState(options = {}) {
      filterVideos();
      renderFacets();
      writeFilterRoute(options);
    }

    function setTopicFilter(topicId, selected) {
      if (selected) state.selectedTopics.add(topicId);
      else state.selectedTopics.delete(topicId);
      commitFilterState();
    }

    function setFamilyFilter(familyId, selected) {
      if (selected) state.selectedFamilies.add(familyId);
      else state.selectedFamilies.delete(familyId);
      commitFilterState();
    }

    function applyFilterRoute() {
      const route = readFilterRoute();
      input.value = route.query;
      state.selectedTopics = new Set(route.topicIds);
      state.selectedFamilies = new Set(route.familyIds);
      filterVideos({ preferredVideoId: route.videoId });
      renderFacets();
      if (!route.videoId || state.selected?._itemId !== route.videoId) {
        writeFilterRoute({ replace: true });
      }
    }

    function fileUrl(relativePath) {
      const encoded = relativePath.split('/').map(encodeURIComponent).join('/');
      return (location.protocol === 'file:' ? '../' : '/') + encoded;
    }
    function transcriptPath(videoPath) {
      return `Video Catalog/transcripts/${videoPath.replace(/\.[^.]+$/, '.transcript.txt')}`;
    }
    function clockSeconds(clock) { return String(clock || '0').split(':').reduce((total, part) => total * 60 + Number(part), 0); }
    function displayClock(clock) { return String(clock || '').replace(/\.\d+$/, ''); }
    function locationName(video) { return video.locations?.[0]?.name || 'Location unknown'; }
    function el(tag, className, text) {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    }

    function renderList() {
      list.replaceChildren();
      count.textContent = `${state.filtered.length} of ${videos.length}`;
      if (!state.filtered.length) {
        list.append(el('div', 'empty', 'No videos match the current search and filters.'));
        return;
      }
      for (const video of state.filtered) {
        const row = el('button', 'video-row');
        row.type = 'button';
        if (video === state.selected) row.classList.add('active');
        row.append(el('span', 'row-title', video.title || video.video));
        const meta = el('span', 'row-meta');
        meta.append(el('span', '', video.date?.display || 'Date unknown'));
        meta.append(el('span', '', locationName(video)));
        meta.append(el('span', '', `${video.sections?.length || 0} chapters`));
        row.append(meta);
        row.addEventListener('click', () => selectVideo(video));
        list.append(row);
      }
    }

    function addFact(text) { document.querySelector('#facts').append(el('span', 'fact', text)); }
    function addEvidence(label, value, basis, confidence) {
      const item = el('li');
      const score = Number.isFinite(confidence) ? ` (${Math.round(confidence * 100)}% confidence)` : '';
      item.append(el('strong', '', `${label}: ${value}${score}. `), document.createTextNode(basis || 'No supporting note recorded.'));
      document.querySelector('#evidence-list').append(item);
    }
    function seekTo(seconds) {
      const play = () => { player.currentTime = seconds; player.play().catch(() => {}); };
      if (player.readyState >= 1) play();
      else player.addEventListener('loadedmetadata', play, { once: true });
    }

    function selectVideo(video, { updateRoute = true, replaceRoute = false } = {}) {
      state.selected = video;
      state.activeTopicId = null;
      state.activeTopicLabel = '';
      state.activeTopicSections = [];
      document.querySelector('#placeholder').hidden = true;
      document.querySelector('#detail-layout').hidden = false;
      document.querySelector('#path').textContent = video.video;
      document.querySelector('#title').textContent = video.title || video.video;
      document.querySelector('#summary').textContent = video.summary || 'No summary yet.';
      player.src = fileUrl(video.video);
      document.querySelector('#video-link').href = fileUrl(video.video);
      document.querySelector('#transcript-link').href = fileUrl(
        video._transcriptPath || transcriptPath(video.video)
      );

      const facts = document.querySelector('#facts');
      facts.replaceChildren();
      addFact(video.date?.display || 'Date unknown');
      addFact(locationName(video));

      const timeline = document.querySelector('#timeline');
      timeline.replaceChildren();
      for (const [index, section] of (video.sections || []).entries()) {
        const button = el('button', 'chapter');
        button.type = 'button';
        button.dataset.sectionIndex = String(index);
        button.append(el('span', 'chapter-time', displayClock(section.start)));
        const copy = el('span', 'chapter-copy');
        copy.append(el('span', 'chapter-title', section.title || 'Untitled chapter'));
        copy.append(el('span', 'chapter-desc', section.description || ''));
        button.append(copy);
        button.addEventListener('click', () => seekTo(clockSeconds(section.start)));
        timeline.append(button);
      }
      renderDetailTopics();

      const evidence = document.querySelector('#evidence-list');
      evidence.replaceChildren();
      if (video.date) addEvidence('Date', video.date.display || 'Unknown', video.date.basis, video.date.confidence);
      for (const place of video.locations || []) addEvidence('Location', place.name, place.basis, place.confidence);
      document.querySelector('#evidence').hidden = !evidence.children.length;
      renderList();
      document.querySelector('#detail-scroll').scrollTop = 0;
      window.requestAnimationFrame(() => clampPlayerHeight());
      if (updateRoute) writeFilterRoute({ replace: replaceRoute });
    }

    function updateClearAllButton() {
      clearAllFilters.hidden = !(
        input.value || topicFilterSearch.value
        || state.selectedTopics.size || state.selectedFamilies.size
      );
    }

    function topicPassesDisplayThreshold(topic) {
      return topic.count > 1 && topic.percentage <= Number(topicThreshold.value);
    }

    function updateTopicPillStates() {
      document.querySelectorAll('.topic-pill.navigable').forEach(pill => {
        const active = pill.dataset.topicId === state.activeTopicId;
        pill.classList.toggle('active', active);
        pill.setAttribute('aria-pressed', String(active));
      });
    }

    function renderChapterHighlights() {
      const matchedSections = new Set(state.activeTopicSections);
      document.querySelectorAll('.chapter').forEach(chapter => {
        const matched = matchedSections.has(Number(chapter.dataset.sectionIndex));
        chapter.classList.toggle('topic-match', matched);
        chapter.querySelector('.chapter-match-label')?.remove();
        if (matched) {
          chapter.querySelector('.chapter-copy')?.append(
            el('span', 'chapter-match-label', `Matches “${state.activeTopicLabel}”`)
          );
        }
      });
    }

    function toggleTopicHighlight(topicId, label, sections) {
      const clearing = state.activeTopicId === topicId;
      state.activeTopicId = clearing ? null : topicId;
      state.activeTopicLabel = clearing ? '' : label;
      state.activeTopicSections = clearing ? [] : sections;
      updateTopicPillStates();
      renderChapterHighlights();
      renderRelatedTopics();
      if (!clearing && sections.length) {
        const firstMatch = document.querySelector(`.chapter[data-section-index="${sections[0]}"]`);
        firstMatch?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }

    function renderDetailTopics() {
      if (!state.selected) return;
      const visibleTopicIds = new Set();
      let navigableTopicCount = 0;
      const pills = [];
      for (const topicId of state.selected._topicIds || []) {
        const topic = topicStatsById.get(topicId);
        if (!topic || (!state.selectedTopics.has(topicId) && !topicPassesDisplayThreshold(topic))) continue;
        visibleTopicIds.add(topicId);
        const sections = state.selected._topicSections?.[topicId] || [];
        const pill = el(
          sections.length ? 'button' : 'span',
          sections.length ? 'topic-pill navigable' : 'topic-pill',
          topic.label
        );
        if (sections.length) {
          navigableTopicCount += 1;
          pill.type = 'button';
          pill.dataset.topicId = topicId;
          pill.title = sections.length === 1
            ? 'Highlight the matching chapter'
            : `Highlight ${sections.length} matching chapters`;
          pill.addEventListener('click', () => toggleTopicHighlight(topicId, topic.label, sections));
        }
        pills.push(pill);
      }
      if (state.activeTopicId && !visibleTopicIds.has(state.activeTopicId)) {
        state.activeTopicId = null;
        state.activeTopicLabel = '';
        state.activeTopicSections = [];
      }
      document.querySelector('#topics').replaceChildren(...pills);
      updateTopicPillStates();
      renderChapterHighlights();
      renderRelatedTopics(navigableTopicCount > 0);
    }

    function renderRelatedTopics(hasNavigableTopics = true) {
      const activeTopic = topicStatsById.get(state.activeTopicId);
      const related = (activeTopic?.relatedTopicIds || [])
        .map(topicId => topicStatsById.get(topicId))
        .filter(Boolean)
        .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label))
        .slice(0, 10);
      relatedTopics.hidden = !hasNavigableTopics;
      relatedEmpty.hidden = related.length > 0;
      relatedEmpty.textContent = activeTopic
        ? `No related topics recorded for ${activeTopic.label}.`
        : 'Select a topic above to highlight its chapters and see related topics.';
      relatedTopicPills.replaceChildren(...related.map(topic => {
        const button = el('button', 'topic-pill related-topic', `${topic.label} · ${topic.count}`);
        button.type = 'button';
        const selected = state.selectedTopics.has(topic.id);
        button.classList.toggle('selected', selected);
        button.setAttribute('aria-pressed', String(selected));
        button.title = selected ? `Remove ${topic.label} filter` : `Filter by ${topic.label}`;
        button.addEventListener('click', () => setTopicFilter(topic.id, !selected));
        return button;
      }));
    }

    function renderFacets() {
      const threshold = Number(topicThreshold.value);
      const query = canonicalTopicKey(topicFilterSearch.value);
      thresholdValue.textContent = `${threshold}%`;

      const visible = topicStats.filter(topic => {
        if (state.selectedTopics.has(topic.id)) return true;
        if (query) return topic.key.includes(query);
        return topicPassesDisplayThreshold(topic);
      }).sort((left, right) => {
        const selectedDifference = Number(state.selectedTopics.has(right.id)) - Number(state.selectedTopics.has(left.id));
        return selectedDifference || right.count - left.count || left.label.localeCompare(right.label);
      });

      const facets = visible.map(topic => {
        const label = el('label', 'facet');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = state.selectedTopics.has(topic.id);
        checkbox.addEventListener('change', () => {
          setTopicFilter(topic.id, checkbox.checked);
        });
        label.append(
          checkbox,
          el('span', 'facet-name', topic.label),
          el('span', 'facet-count', `${topic.count} · ${Math.round(topic.percentage)}%`)
        );
        return label;
      });
      topicFacets.replaceChildren(...facets);

      const visibleFamilies = familyStats.filter(family => {
        if (state.selectedFamilies.has(family.id)) return true;
        return !query || family.key.includes(query);
      }).sort((left, right) => {
        const selectedDifference = Number(state.selectedFamilies.has(right.id)) - Number(state.selectedFamilies.has(left.id));
        return selectedDifference || right.count - left.count || left.label.localeCompare(right.label);
      });
      familyFacetSection.hidden = !familyStats.length;
      familyFacets.replaceChildren(...visibleFamilies.map(family => {
        const label = el('label', 'facet');
        label.title = family.description || family.label;
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = state.selectedFamilies.has(family.id);
        checkbox.addEventListener('change', () => {
          setFamilyFilter(family.id, checkbox.checked);
        });
        label.append(
          checkbox,
          el('span', 'facet-name', family.label),
          el('span', 'facet-count', String(family.count))
        );
        return label;
      }));
      facetInfo.textContent = query
        ? `${visible.length} topics · ${visibleFamilies.length} families`
        : `${visible.length} of ${topicStats.length} topics`;
      const selectedCount = state.selectedTopics.size + state.selectedFamilies.size;
      filterBadge.textContent = selectedCount ? `${selectedCount} selected` : '';
      updateClearAllButton();
      renderDetailTopics();
    }

    function filterVideos({ preferredVideoId = null } = {}) {
      const searchGroups = parseSearchGroups(input.value);
      const selectedTopics = [...state.selectedTopics];
      const selectedFamilies = [...state.selectedFamilies];
      state.filtered = videos.filter(video => {
        const haystack = [
          video.video,
          video.title,
          video.summary,
          video.date?.display,
          video.date?.iso,
          ...(video.locations || []).map(location => location.name),
          ...(video.topics || []),
          ...(video._familyIds || []).map(id => familyStatsById.get(id)?.label),
          ...(video.sections || []).flatMap(section => [section.title, section.description]),
          ...(video.featured_techniques || []).flatMap(technique =>
            typeof technique === 'string'
              ? [technique]
              : [technique.name, technique.description]
          )
        ].filter(Boolean).join(' ').toLocaleLowerCase();
        return searchGroups.every(group => haystack.includes(group))
          && selectedTopics.every(id => video._topicIds.includes(id))
          && selectedFamilies.every(id => video._familyIds.includes(id));
      });
      const preferredVideo = videosByItemId.get(preferredVideoId);
      const nextVideo = preferredVideo && state.filtered.includes(preferredVideo)
        ? preferredVideo
        : state.selected && state.filtered.includes(state.selected)
          ? state.selected
          : state.filtered[0];
      if (nextVideo && nextVideo !== state.selected) {
        selectVideo(nextVideo, { updateRoute: false });
      } else {
        renderList();
      }
    }

    nativeOpen.addEventListener('click', async () => {
      if (!state.selected || location.protocol === 'file:') return;
      nativeOpen.disabled = true;
      nativeOpen.textContent = 'Opening…';
      try {
        const response = await fetch('/api/open-video', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ video: state.selected.video })
        });
        if (!response.ok) throw new Error('Could not open the video');
        nativeOpen.textContent = 'Opened in default player';
      } catch (error) {
        nativeOpen.textContent = 'Could not open video';
      } finally {
        window.setTimeout(() => {
          nativeOpen.disabled = false;
          nativeOpen.textContent = 'Open in default player';
        }, 1800);
      }
    });

    if (location.protocol === 'file:') {
      nativeOpen.disabled = true;
      nativeOpen.textContent = 'Use launcher for default player';
      nativeOpen.title = 'Double-click Launch Video Catalog.command to enable this button.';
    }
    input.addEventListener('input', () => {
      commitFilterState({ replace: true });
    });
    clearAllFilters.addEventListener('click', () => {
      input.value = '';
      topicFilterSearch.value = '';
      state.selectedTopics.clear();
      state.selectedFamilies.clear();
      input.focus();
      commitFilterState();
    });
    topicThreshold.addEventListener('input', () => {
      try { localStorage.setItem('videoCatalogTopicThreshold', topicThreshold.value); } catch (error) {}
      renderFacets();
    });
    topicFilterSearch.addEventListener('input', () => {
      updateClearAllButton();
      renderFacets();
    });
    window.addEventListener('popstate', applyFilterRoute);
    sidebar.addEventListener('wheel', event => {
      if (event.target.closest('.filters')) return;
      if (!event.deltaY) return;
      const before = list.scrollTop;
      list.scrollTop += event.deltaY;
      if (list.scrollTop !== before) event.preventDefault();
    }, { passive: false });

    const splitter = document.querySelector('#splitter');
    const savedWidth = Number(localStorage.getItem('videoCatalogSidebarWidth'));
    if (savedWidth) app.style.gridTemplateColumns = `${savedWidth}px 8px minmax(420px, 1fr)`;
    splitter.addEventListener('pointerdown', event => {
      splitter.setPointerCapture(event.pointerId);
      splitter.classList.add('dragging');
    });
    splitter.addEventListener('pointermove', event => {
      if (!splitter.hasPointerCapture(event.pointerId)) return;
      const width = Math.max(320, Math.min(event.clientX, window.innerWidth - 428));
      app.style.gridTemplateColumns = `${width}px 8px minmax(420px, 1fr)`;
      localStorage.setItem('videoCatalogSidebarWidth', width);
    });
    splitter.addEventListener('pointerup', event => {
      splitter.releasePointerCapture(event.pointerId);
      splitter.classList.remove('dragging');
    });

    const detailLayout = document.querySelector('#detail-layout');
    const horizontalSplitter = document.querySelector('#horizontal-splitter');
    const playerPane = document.querySelector('.player-pane');
    const detailScroll = document.querySelector('#detail-scroll');
    let savedPlayerHeight = Number(localStorage.getItem('videoCatalogPlayerHeight'));

    function playerHeightBounds() {
      const total = detailLayout.getBoundingClientRect().height;
      const minimumPlayer = Math.min(190, Math.max(120, total * .3));
      const minimumDetails = Math.min(280, Math.max(180, total * .3));
      return {
        minimum: minimumPlayer,
        maximum: Math.max(minimumPlayer, total - 8 - minimumDetails)
      };
    }
    function setPlayerHeight(requestedHeight, persist = false) {
      if (window.innerWidth <= 760 || detailLayout.hidden) return;
      const bounds = playerHeightBounds();
      const height = Math.max(bounds.minimum, Math.min(requestedHeight, bounds.maximum));
      detailLayout.style.gridTemplateRows = `${height}px 8px minmax(180px, 1fr)`;
      if (persist) {
        savedPlayerHeight = height;
        localStorage.setItem('videoCatalogPlayerHeight', height);
      }
    }
    function clampPlayerHeight() {
      const current = playerPane.getBoundingClientRect().height;
      setPlayerHeight(savedPlayerHeight || current);
    }
    horizontalSplitter.addEventListener('pointerdown', event => {
      horizontalSplitter.setPointerCapture(event.pointerId);
      horizontalSplitter.classList.add('dragging');
    });
    horizontalSplitter.addEventListener('pointermove', event => {
      if (!horizontalSplitter.hasPointerCapture(event.pointerId)) return;
      const bounds = detailLayout.getBoundingClientRect();
      setPlayerHeight(event.clientY - bounds.top, true);
    });
    horizontalSplitter.addEventListener('pointerup', event => {
      horizontalSplitter.releasePointerCapture(event.pointerId);
      horizontalSplitter.classList.remove('dragging');
    });
    playerPane.addEventListener('wheel', event => {
      if (!event.deltaY) return;
      detailScroll.scrollTop += event.deltaY;
      event.preventDefault();
    }, { passive: false });
    window.addEventListener('resize', () => {
      window.requestAnimationFrame(() => {
        const current = playerPane.getBoundingClientRect().height;
        setPlayerHeight(current);
      });
    });

    updateClearAllButton();
    renderFacets();
    filterVideos({ preferredVideoId: initialFilter.videoId });
    writeFilterRoute({ replace: true });
  </script>
</body>
</html>
"""


def render_html(
    analyses: list[dict],
    topic_chapter_maps: dict[str, dict[str, list[int]]] | None = None,
    collection_manifest: dict | None = None,
) -> str:
    topic_chapter_maps = topic_chapter_maps or {}
    collection_manifest = collection_manifest or build_collection_manifest(
        Path("Video Catalog"), analyses, topic_chapter_maps
    )
    items_by_video = {}
    for item in collection_manifest.get("items", {}).values():
        for media in item.get("media", []):
            if media.get("type") == "local-file" and media.get("relative_path"):
                items_by_video[media["relative_path"]] = item

    videos = []
    topic_registry = collection_manifest.get("topics", {})
    for analysis in analyses:
        item = dict(analysis)
        video = analysis.get("video", "")
        collection_item = items_by_video.get(video, {})
        item["_itemId"] = collection_item.get("item_id")
        item["_topicIds"] = collection_item.get("topic_ids", [])
        item["_familyIds"] = collection_item.get("family_ids", [])
        item["_topicSections"] = collection_item.get("topic_sections", {})
        item["topics"] = [
            topic_registry[topic_id]["label"]
            for topic_id in item["_topicIds"]
            if topic_id in topic_registry
        ]
        transcript_text = collection_item.get("transcript", {}).get("text")
        if transcript_text:
            item["_transcriptPath"] = (
                Path(CATALOG_DIR_NAME) / transcript_text
            ).as_posix()
        videos.append(item)
    payload = {"collection": collection_manifest, "videos": videos}
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return HTML_TEMPLATE.replace("__CATALOG_DATA__", data.replace("<", "\\u003c"))


def write_catalog(root: Path) -> dict:
    analyses = load_analyses(root)
    topic_chapter_maps = load_topic_chapter_maps(root, analyses)
    catalog_root = root / CATALOG_DIR_NAME
    previous_manifest = load_collection_manifest(catalog_root / "collection.json")
    normalization = load_topic_normalization(root)
    collection_manifest = build_collection_manifest(
        root, analyses, topic_chapter_maps, previous_manifest, normalization
    )
    atomic_write_text(
        catalog_root / "collection.json",
        json.dumps(collection_manifest, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write_text(
        catalog_root / "catalog.csv", render_csv(analyses, collection_manifest)
    )
    atomic_write_text(
        catalog_root / "catalog.html",
        render_html(analyses, topic_chapter_maps, collection_manifest),
    )
    print(
        f"built {collection_manifest['title']} revision "
        f"{collection_manifest['revision']} for {len(analyses)} videos"
    )
    return collection_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=validated_root)
    args = parser.parse_args()
    write_catalog(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
