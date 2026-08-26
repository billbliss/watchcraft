#!/usr/bin/env python3
"""Build a versioned collection manifest and CSV export from video analyses."""

from __future__ import annotations

import argparse
import hashlib
import csv
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from video_catalog import atomic_write_text, catalog_root, validated_root


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
    transcript_root = catalog_root(root) / "transcripts"
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
    analysis_root = catalog_root(root) / "analysis"
    analyses = []
    if not analysis_root.exists():
        return analyses
    for path in sorted(analysis_root.rglob("*.analysis.json")):
        with path.open(encoding="utf-8") as handle:
            analyses.append(json.load(handle))
    return analyses


COLLECTION_SCHEMA_VERSION = 4


def validate_collection_manifest(manifest: dict) -> None:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:
        raise RuntimeError(
            "jsonschema is not installed. Install authoring/prototype/requirements.txt."
        ) from error
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "catalog-schema"
        / "collection.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if errors:
        details = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in errors[:5]
        )
        raise RuntimeError(f"Collection manifest failed schema validation: {details}")


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
    path = catalog_root(root) / "topic-normalization.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read topic normalization: {path}") from error
    if not isinstance(payload, dict) or payload.get("status") != "complete":
        return None
    return payload


def load_authoring_config(root: Path) -> dict:
    path = root / "watchcraft-authoring.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read authoring configuration: {path}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"Authoring configuration is not an object: {path}")
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
    authoring = load_authoring_config(root)
    collection_config = authoring.get("collection", {})
    sources = authoring.get("sources", {})
    title = str(
        collection_config.get("title")
        or previous.get("title")
        or root.name
        or "Video Collection"
    )
    collection_id = str(
        collection_config.get("collection_id")
        or previous.get("collection_id")
        or re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
        or "video-collection"
    )

    previous_items_by_path = {}
    for item_id, item in previous.get("items", {}).items():
        for media in item.get("media", []):
            if media.get("type") == "local-file" and media.get("relative_path"):
                previous_items_by_path[media["relative_path"]] = item_id
            elif media.get("type") == "youtube" and media.get("video_id"):
                previous_items_by_path[f"{media['video_id']}.youtube"] = item_id

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
        source = sources.get(video, {}) if isinstance(sources, dict) else {}
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
        if source.get("type") == "youtube":
            media = [{
                "type": "youtube",
                "video_id": source["video_id"],
                "url": source.get("url")
                or f"https://www.youtube.com/watch?v={source['video_id']}",
            }]
            transcript = {}
        else:
            media = [{"type": "local-file", "relative_path": video}]
            transcript = {
                "subtitles": (
                    Path("transcripts") / relative.with_suffix(".srt")
                ).as_posix(),
                "text": (
                    Path("transcripts") / relative.with_suffix(".transcript.txt")
                ).as_posix(),
                "segments": (
                    Path("transcripts") / relative.with_suffix(".transcript.json")
                ).as_posix(),
            }
        items[item_id] = {
            "item_id": item_id,
            "title": analysis.get("title") or relative.stem,
            "media": media,
            "transcript": transcript,
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
        "kind": "watchcraft.collection",
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
    if any(
        media.get("type") == "local-file"
        for item in items.values()
        for media in item.get("media", [])
    ):
        manifest_body["media_root_hint"] = str(
            collection_config.get("media_root_hint") or ".."
        )
    for field in ("description", "publisher", "metadata_url", "license", "source"):
        if field in collection_config:
            manifest_body[field] = collection_config[field]
    for field in ("description", "publisher", "metadata_url", "license", "source"):
        if field not in manifest_body and field in previous:
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
            if media[0].get("type") == "youtube" and media[0].get("video_id"):
                video = f"{media[0]['video_id']}.youtube"
            item_topics_by_video[video] = [
                topic_registry[topic_id]["label"]
                for topic_id in item.get("topic_ids", [])
                if topic_id in topic_registry
            ]
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        lineterminator="\n",
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


def write_collection(root: Path) -> dict:
    analyses = load_analyses(root)
    topic_chapter_maps = load_topic_chapter_maps(root, analyses)
    metadata_root = catalog_root(root)
    previous_manifest = load_collection_manifest(metadata_root / "collection.json")
    normalization = load_topic_normalization(root)
    collection_manifest = build_collection_manifest(
        root, analyses, topic_chapter_maps, previous_manifest, normalization
    )
    validate_collection_manifest(collection_manifest)
    atomic_write_text(
        metadata_root / "collection.json",
        json.dumps(collection_manifest, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write_text(
        metadata_root / "catalog.csv", render_csv(analyses, collection_manifest)
    )
    (metadata_root / "catalog.html").unlink(missing_ok=True)
    print(
        f"built {collection_manifest['title']} revision "
        f"{collection_manifest['revision']} for {len(analyses)} videos"
    )
    return collection_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=validated_root)
    args = parser.parse_args()
    write_collection(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
