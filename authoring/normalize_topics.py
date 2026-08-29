#!/usr/bin/env python3
"""Create a resumable, AI-assisted topic normalization artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from analyze_catalog import create_openai_client
from build_collection import (
    analysis_topics,
    canonical_topic_key,
    load_analyses,
    load_collection_manifest,
    load_topic_chapter_maps,
    stable_id,
)
from video_catalog import atomic_write_text, catalog_root, validated_root


NORMALIZATION_MODEL_ENV = "VIDEO_CATALOG_NORMALIZATION_MODEL"
BUILTIN_NORMALIZATION_MODEL = "gpt-5.4-mini"
NORMALIZATION_SCHEMA_VERSION = 1
NORMALIZATION_PROMPT_VERSION = 2
DISPLAY_LABEL_PROMPT_VERSION = 1
DEFAULT_BATCH_SIZE = 40
MAX_DISPLAY_LABEL_CHARS = 32
MIN_DISPLAY_LABEL_WORDS = 2
MAX_DISPLAY_LABEL_WORDS = 5


def default_normalization_model() -> str:
    return os.environ.get(
        NORMALIZATION_MODEL_ENV, BUILTIN_NORMALIZATION_MODEL
    )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FamilyProposal(StrictModel):
    label: str
    description: str


class GeneratedTaxonomy(StrictModel):
    families: list[FamilyProposal]


class TopicAssignment(StrictModel):
    source_id: str
    alias_ids: list[str]
    family_labels: list[str]
    confidence: float
    rationale: str


class GeneratedAssignments(StrictModel):
    assignments: list[TopicAssignment]


class RelatedDecision(StrictModel):
    source_id: str
    related_ids: list[str]


class GeneratedRelatedTopics(StrictModel):
    decisions: list[RelatedDecision]


class DisplayLabelDecision(StrictModel):
    source_id: str
    label: str


class GeneratedDisplayLabels(StrictModel):
    labels: list[DisplayLabelDecision]


class DisplayLabelBatchError(RuntimeError):
    def __init__(
        self,
        *,
        completed: dict[str, str],
        remaining: list[str],
        rejected: dict[str, str],
    ) -> None:
        self.completed = completed
        self.remaining = remaining
        self.rejected = rejected
        details = "; ".join(
            f"{key}: {rejected.get(key, 'model omitted topic')}"
            for key in remaining
        )
        super().__init__(f"Display-label batch remained invalid: {details}")


TAXONOMY_PROMPT = """You organize topics within one educational-video collection.
Create 12-24 useful, broad topic families that help people browse this corpus.

Rules:
- A family is a synthetic aggregation, not an alias or a topic copied from one video.
- Prefer durable workflow or subject-area families over narrow tool names.
- Use distinct families; avoid overlapping color-management or workflow catch-alls.
- Use concise one-to-four-word title-case labels, not long lists joined by commas.
- Interpret product-specific terms from their supplied chapter context rather than their
  ordinary-language meaning (for example, an editing History Brush is not version history).
- Write one-sentence descriptions.
- Base the taxonomy only on the supplied corpus topics.
"""


ASSIGNMENT_PROMPT = """Normalize educational-video topics using the supplied fixed family taxonomy.

For every source_id, return exactly one assignment and copy source_id exactly.
- alias_ids: zero or more IDs copied from possible_aliases. Select only true aliases,
  spelling variants, acronyms, or wording variants; do not select merely related concepts.
- family_labels: zero to two labels copied exactly from the allowed family list.
- confidence: 0.0-1.0 for the alias/normalization decision.
- rationale: one short sentence.
- Preserve useful technical specificity.
- Never replace or equate a topic with a family label.
"""


RELATED_PROMPT = """Select genuinely related topics for browsing an educational-video catalog.

For every source_id, return exactly one decision and copy source_id exactly. Choose zero to five related_ids only
from that topic's supplied candidates. Related means a person studying one would reasonably
want to discover the other. Copy candidate_id values exactly. Do not choose aliases, parent
families, generic associations, or every topic that happens to share a family.
"""


DISPLAY_LABEL_PROMPT = """Create compact UI labels for educational-video topics.

For every source_id, return exactly one label and copy source_id exactly.
Rules:
- Use two to five words and no more than 32 characters, including spaces.
- Preserve the distinctive technique, tool, panel, or workflow name.
- Remove parenthetical examples, keyboard-shortcut lists, settings, and enumerations.
- Do not use commas, colons, semicolons, parentheses, or square brackets.
- Labels must be unique within this batch and must not duplicate reserved_labels.
- Prefer natural title-style labels such as "Multi-Camera Editing", "Essential Sound",
  "Lumetri Scopes", "Transcript-Based Editing", or "Video Transitions".
- Do not broaden a specific topic into only its family name.
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalization_path(root: Path) -> Path:
    return catalog_root(root) / "topic-normalization.json"


def preferred_label(forms: Counter) -> str:
    return sorted(
        forms.items(), key=lambda item: (-item[1], item[0].casefold(), item[0])
    )[0][0]


def topic_inventory(
    analyses: list[dict], topic_chapter_maps: dict[str, dict[str, list[int]]]
) -> dict[str, dict]:
    forms: dict[str, Counter] = defaultdict(Counter)
    videos: dict[str, set[str]] = defaultdict(set)
    contexts: dict[str, set[str]] = defaultdict(set)
    for analysis in analyses:
        video = analysis.get("video", "")
        title = str(analysis.get("title") or Path(video).stem)
        sections = analysis.get("sections", [])
        for raw_topic in analysis_topics(analysis):
            label = " ".join(str(raw_topic).split())
            key = canonical_topic_key(label)
            if not key:
                continue
            forms[key][label] += 1
            videos[key].add(video)
            indexes = topic_chapter_maps.get(video, {}).get(key, [])
            chapter_titles = [
                str(sections[index].get("title", "")).strip()
                for index in indexes
                if 0 <= index < len(sections)
            ]
            context = title
            if chapter_titles:
                context += " — " + "; ".join(chapter_titles[:3])
            contexts[key].add(context)
    return {
        key: {
            "source_key": key,
            "label": preferred_label(forms[key]),
            "forms": sorted(forms[key]),
            "video_count": len(videos[key]),
            "videos": sorted(videos[key]),
            "contexts": sorted(contexts[key])[:4],
        }
        for key in sorted(forms)
    }


def inventory_hash(records: dict[str, dict]) -> str:
    portable = {
        key: {
            "forms": record["forms"],
            "videos": record["videos"],
            "contexts": record["contexts"],
        }
        for key, record in records.items()
    }
    return hashlib.sha256(
        json.dumps(portable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def comparison_tokens(value: str) -> set[str]:
    ignored = {
        "adobe", "and", "for", "in", "of", "the", "to", "tool", "tools",
    }
    normalized_forms = {
        "blending": "blend",
        "burning": "burn",
        "cloning": "clone",
        "cropping": "crop",
        "dodging": "dodge",
        "editing": "edit",
        "grading": "grade",
        "masking": "mask",
        "processing": "process",
        "stitching": "stitch",
        "warping": "warp",
    }
    return {
        normalized_forms.get(
            token,
            token[:-1] if len(token) > 4 and token.endswith("s") else token,
        )
        for token in re.findall(
            r"[a-z0-9]+", canonical_topic_key(value).replace("&", " and ")
        )
        if token not in ignored
    }


def label_acronym(value: str) -> str:
    ignored = {"and", "for", "in", "of", "the", "to"}
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", canonical_topic_key(value))
        if token not in ignored
    ]
    return "".join(token[0] for token in tokens if token)


def mechanically_equivalent(left: str, right: str) -> bool:
    left_tokens = comparison_tokens(left)
    right_tokens = comparison_tokens(right)
    if left_tokens and left_tokens == right_tokens:
        return True
    left_compact = "".join(re.findall(r"[a-z0-9]+", canonical_topic_key(left)))
    right_compact = "".join(re.findall(r"[a-z0-9]+", canonical_topic_key(right)))
    return (
        2 <= len(left_compact) <= 6 and left_compact == label_acronym(right)
    ) or (
        2 <= len(right_compact) <= 6 and right_compact == label_acronym(left)
    )


def alias_candidates(records: dict[str, dict]) -> dict[str, list[str]]:
    token_index: dict[str, set[str]] = defaultdict(set)
    tokens_by_key = {}
    for key, record in records.items():
        tokens = comparison_tokens(record["label"])
        tokens_by_key[key] = tokens
        for token in tokens:
            token_index[token].add(key)
    result = {}
    for key, record in records.items():
        candidates = set()
        for token in tokens_by_key[key]:
            candidates.update(token_index[token])
        candidates.discard(key)
        scored = []
        for other in candidates:
            left = tokens_by_key[key]
            right = tokens_by_key[other]
            overlap = len(left & right) / max(1, len(left | right))
            sequence = SequenceMatcher(
                None, canonical_topic_key(record["label"]), canonical_topic_key(records[other]["label"])
            ).ratio()
            score = max(overlap, sequence)
            if score >= 0.62:
                scored.append((score, records[other]["video_count"], other))
        result[key] = [
            other
            for _, _, other in sorted(scored, reverse=True)[:6]
        ]
    return result


def compact_record(
    source_id: str,
    record: dict,
    candidate_map: dict[str, str],
    records: dict[str, dict],
) -> dict:
    return {
        "source_id": source_id,
        "label": record["label"],
        "forms": record["forms"],
        "video_count": record["video_count"],
        "chapter_context": record["contexts"],
        "possible_aliases": [
            {"alias_id": alias_id, "label": records[key]["label"]}
            for alias_id, key in candidate_map.items()
        ],
    }


def request_structured(
    client: Any,
    *,
    model: str,
    system_prompt: str,
    payload: dict,
    output_type: type[BaseModel],
    retries: int,
) -> BaseModel:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = client.responses.parse(
                model=model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                text_format=output_type,
            )
            if response.output_parsed is None:
                raise RuntimeError("The normalization model returned no structured output")
            return response.output_parsed
        except Exception as error:  # SDK error classes vary between releases.
            last_error = error
            if attempt >= retries:
                break
            delay = min(30, 2**attempt)
            print(f"  API attempt {attempt + 1} failed; retrying in {delay}s", flush=True)
            time.sleep(delay)
    raise RuntimeError(
        f"Topic-normalization request failed after {retries + 1} attempts: {last_error}"
    )


def save_state(path: Path, state: dict) -> None:
    state["updated_at"] = now_iso()
    atomic_write_text(
        path, json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


def initial_state(collection_id: str, source_hash: str, model: str) -> dict:
    timestamp = now_iso()
    return {
        "schema_version": NORMALIZATION_SCHEMA_VERSION,
        "prompt_version": NORMALIZATION_PROMPT_VERSION,
        "collection_id": collection_id,
        "status": "new",
        "model": model,
        "source_hash": source_hash,
        "created_at": timestamp,
        "updated_at": timestamp,
        "families": {},
        "assignments": {},
        "related": {},
        "display_label_prompt_version": DISPLAY_LABEL_PROMPT_VERSION,
        "display_labels": {},
    }


def load_state(
    path: Path,
    collection_id: str,
    source_hash: str,
    model: str,
    force: bool,
) -> dict:
    if force or not path.exists():
        return initial_state(collection_id, source_hash, model)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != NORMALIZATION_SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported topic-normalization schema: {path}")
    if payload.get("prompt_version") != NORMALIZATION_PROMPT_VERSION:
        raise RuntimeError("Topic-normalization prompt changed; rerun with --force")
    if payload.get("collection_id") != collection_id:
        raise RuntimeError("Topic normalization belongs to a different collection")
    previous_model = payload.get("model")
    has_model_output = bool(
        payload.get("families")
        or payload.get("assignments")
        or payload.get("related")
        or payload.get("display_labels")
    )
    if has_model_output and previous_model != model:
        raise RuntimeError(
            "Topic normalization was started with "
            f"{previous_model!r}; use that model or rerun with --force"
        )
    payload["source_hash"] = source_hash
    payload["model"] = model
    payload.setdefault("display_label_prompt_version", DISPLAY_LABEL_PROMPT_VERSION)
    payload.setdefault("display_labels", {})
    return payload


def create_taxonomy(client: Any, model: str, records: dict[str, dict], retries: int) -> dict:
    topics = [
        {
            "label": record["label"],
            "video_count": record["video_count"],
            "chapter_context": record["contexts"][:2],
        }
        for record in sorted(
            records.values(), key=lambda item: (-item["video_count"], item["label"].casefold())
        )
    ]
    generated = request_structured(
        client,
        model=model,
        system_prompt=TAXONOMY_PROMPT,
        payload={"corpus_topics": topics},
        output_type=GeneratedTaxonomy,
        retries=retries,
    )
    families = {}
    seen = set()
    for proposal in generated.families:
        label = " ".join(proposal.label.split())
        key = canonical_topic_key(label)
        if not key or key in seen:
            continue
        seen.add(key)
        family_id = stable_id("family", key)
        families[family_id] = {
            "family_id": family_id,
            "canonical_key": key,
            "label": label,
            "description": " ".join(proposal.description.split()),
        }
    if not 8 <= len(families) <= 40:
        raise RuntimeError(f"Model returned an implausible family count: {len(families)}")
    return families


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def assign_batch(
    client: Any,
    *,
    model: str,
    keys: list[str],
    records: dict[str, dict],
    candidates: dict[str, list[str]],
    families: dict[str, dict],
    retries: int,
) -> dict[str, dict]:
    family_by_key = {family["canonical_key"]: family for family in families.values()}
    allowed_families = [
        {"label": family["label"], "description": family["description"]}
        for family in families.values()
    ]
    decisions = {}
    decision_aliases = {}
    remaining = list(keys)
    for repair_attempt in range(3):
        source_ids = {f"T{index + 1:03d}": key for index, key in enumerate(remaining)}
        candidate_maps = {
            source_id: {
                f"A{index + 1:02d}": candidate
                for index, candidate in enumerate(candidates[key])
            }
            for source_id, key in source_ids.items()
        }
        payload = {
            "allowed_families": allowed_families,
            "topics": [
                compact_record(source_id, records[key], candidate_maps[source_id], records)
                for source_id, key in source_ids.items()
            ],
        }
        generated = request_structured(
            client,
            model=model,
            system_prompt=ASSIGNMENT_PROMPT,
            payload=payload,
            output_type=GeneratedAssignments,
            retries=retries,
        )
        for decision in generated.assignments:
            key = source_ids.get(decision.source_id)
            if key:
                decisions[key] = decision
                decision_aliases[key] = [
                    candidate_maps[decision.source_id][alias_id]
                    for alias_id in decision.alias_ids
                    if alias_id in candidate_maps[decision.source_id]
                ]
        remaining = [key for key in remaining if key not in decisions]
        if not remaining:
            break
        print(
            f"  repairing {len(remaining)} omitted assignment(s), attempt {repair_attempt + 1}/3",
            flush=True,
        )
    if remaining:
        raise RuntimeError(f"Assignment batch omitted topics after repairs: {remaining}")
    result = {}
    for key in keys:
        decision = decisions[key]
        family_ids = []
        for label in decision.family_labels[:2]:
            family = family_by_key.get(canonical_topic_key(label))
            if family and family["family_id"] not in family_ids:
                family_ids.append(family["family_id"])
        result[key] = {
            "source_key": key,
            "source_label": records[key]["label"],
            "alias_source_keys": sorted(set(decision_aliases[key])),
            "family_ids": family_ids,
            "confidence": round(max(0.0, min(1.0, decision.confidence)), 3),
            "rationale": " ".join(decision.rationale.split()),
        }
    return result


def finalize_canonical_assignments(records: dict[str, dict], assignments: dict[str, dict]) -> None:
    parent = {key: key for key in assignments}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for key, assignment in assignments.items():
        for other in assignment.get("alias_source_keys", []):
            if other not in assignments:
                continue
            if mechanically_equivalent(
                records[key]["label"], records[other]["label"]
            ):
                union(key, other)

    components: dict[str, list[str]] = defaultdict(list)
    for key in assignments:
        components[find(key)].append(key)
    for members in components.values():
        canonical_source = sorted(
            members,
            key=lambda key: (
                -records[key]["video_count"],
                len(records[key]["label"]),
                records[key]["label"].casefold(),
            ),
        )[0]
        canonical_label = records[canonical_source]["label"]
        canonical_key = canonical_topic_key(canonical_label)
        family_scores: Counter = Counter()
        for key in members:
            weight = records[key]["video_count"] * assignments[key].get(
                "confidence", 0.5
            )
            for family_id in assignments[key].get("family_ids", []):
                family_scores[family_id] += weight
        component_families = [
            family_id for family_id, _ in family_scores.most_common(2)
        ]
        for key in members:
            assignments[key]["canonical_key"] = canonical_key
            assignments[key]["canonical_label"] = canonical_label
            assignments[key]["family_ids"] = component_families


def canonical_inventory(records: dict[str, dict], assignments: dict[str, dict]) -> dict[str, dict]:
    result = {}
    for source_key, record in records.items():
        assignment = assignments[source_key]
        key = assignment["canonical_key"]
        target = result.setdefault(
            key,
            {
                "canonical_key": key,
                "label": assignment["canonical_label"],
                "source_keys": [],
                "family_ids": set(),
                "videos": set(),
                "contexts": set(),
            },
        )
        target["source_keys"].append(source_key)
        target["family_ids"].update(assignment["family_ids"])
        target["videos"].update(record["videos"])
        target["contexts"].update(record["contexts"])
    return result


def display_label_error(label: str, reserved_keys: set[str]) -> str | None:
    if not label:
        return "label is empty"
    if len(label) > MAX_DISPLAY_LABEL_CHARS:
        return f"label exceeds {MAX_DISPLAY_LABEL_CHARS} characters"
    if any(character in label for character in ",:;()[]{}"):
        return "label contains list or parenthetical punctuation"
    words = re.findall(r"[A-Za-z0-9]+(?:[&+./-][A-Za-z0-9]+)*", label)
    if not MIN_DISPLAY_LABEL_WORDS <= len(words) <= MAX_DISPLAY_LABEL_WORDS:
        return (
            f"label must contain {MIN_DISPLAY_LABEL_WORDS} to "
            f"{MAX_DISPLAY_LABEL_WORDS} words"
        )
    if canonical_topic_key(label) in reserved_keys:
        return "label duplicates another display label"
    return None


def deterministic_display_label(
    label: str,
    reserved_keys: set[str],
    *,
    preferred_label: str | None = None,
) -> str | None:
    normalized = " ".join(label.split())
    if ":" in normalized:
        prefix = normalized.split(":", 1)[0].strip()
        if display_label_error(prefix, reserved_keys) is None:
            return prefix
    candidate = re.sub(r"\([^)]*\)|\[[^]]*\]|\{[^}]*\}", " ", label)
    candidate = re.sub(r"[,;:]", " ", candidate)
    candidate = re.sub(r"\s+and\s+", " & ", " ".join(candidate.split()), flags=re.I)
    if display_label_error(candidate, reserved_keys) is None:
        return candidate
    words = candidate.split()
    if len(words) > MIN_DISPLAY_LABEL_WORDS:
        removable = range(1, max(1, len(words) - 1))
        index = min(removable, key=lambda value: (len(words[value]), value))
        shortened = " ".join(
            word for word_index, word in enumerate(words) if word_index != index
        )
        if display_label_error(shortened, reserved_keys) is None:
            return shortened

    # A model-generated label can be perfectly valid except that an earlier topic
    # already claimed it. Preserve the model's natural wording and add a distinctive
    # word from the canonical topic before falling back to a generic qualifier.
    preferred = " ".join((preferred_label or "").split())
    if preferred:
        word_pattern = r"[A-Za-z0-9]+(?:[&+./-][A-Za-z0-9]+)*"
        preferred_words = re.findall(word_pattern, preferred)
        preferred_tokens = {
            canonical_topic_key(word).rstrip("s")
            for word in preferred_words
        }
        filler_words = {
            "a",
            "an",
            "and",
            "by",
            "for",
            "in",
            "of",
            "on",
            "or",
            "running",
            "the",
            "through",
            "to",
            "using",
            "with",
        }
        distinctive_words = []
        for word in re.findall(word_pattern, label):
            token = canonical_topic_key(word).rstrip("s")
            if token in filler_words or token in preferred_tokens:
                continue
            distinctive_words.append(word)

        preferred_tails = [
            preferred_words,
            preferred_words[-3:],
            preferred_words[-2:],
        ]
        for word in distinctive_words:
            for tail in preferred_tails:
                title_word = word[:1].upper() + word[1:]
                disambiguated = " ".join([title_word, *tail])
                if display_label_error(disambiguated, reserved_keys) is None:
                    return disambiguated

        for qualifier in ("Overview", "Guidance", "Methods", "Concepts"):
            disambiguated = f"{preferred} {qualifier}"
            if display_label_error(disambiguated, reserved_keys) is None:
                return disambiguated

        # This should be extremely rare, but a stable suffix guarantees that a large
        # collection cannot be left unfinished solely because every natural fallback
        # is already reserved.
        digest = hashlib.sha256(canonical_topic_key(label).encode()).hexdigest()[:4].upper()
        for tail in (preferred_words[:4], preferred_words[:3], preferred_words[:2]):
            disambiguated = " ".join([*tail, digest])
            if display_label_error(disambiguated, reserved_keys) is None:
                return disambiguated
    return None


def label_batch(
    client: Any,
    *,
    model: str,
    keys: list[str],
    canonical: dict[str, dict],
    families: dict[str, dict],
    reserved_labels: list[str],
    retries: int,
) -> dict[str, str]:
    results: dict[str, str] = {}
    remaining = list(keys)
    reserved_keys = {
        canonical_topic_key(label) for label in reserved_labels if label.strip()
    }
    rejected: dict[str, str] = {}
    rejected_labels: dict[str, str] = {}
    for repair_attempt in range(4):
        source_ids = {f"D{index + 1:03d}": key for index, key in enumerate(remaining)}
        payload = {
            "reserved_labels": sorted(
                [*reserved_labels, *results.values()], key=str.casefold
            ),
            "topics": [
                {
                    "source_id": source_id,
                    "current_label": canonical[key]["label"],
                    "families": [
                        families[family_id]["label"]
                        for family_id in canonical[key]["family_ids"]
                        if family_id in families
                    ],
                    "chapter_context": sorted(canonical[key]["contexts"])[:2],
                    "previous_rejection": rejected.get(key),
                }
                for source_id, key in source_ids.items()
            ],
        }
        generated = request_structured(
            client,
            model=model,
            system_prompt=DISPLAY_LABEL_PROMPT,
            payload=payload,
            output_type=GeneratedDisplayLabels,
            retries=retries,
        )
        rejected = {}
        for decision in generated.labels:
            key = source_ids.get(decision.source_id)
            if not key or key in results:
                continue
            label = " ".join(decision.label.split())
            error = display_label_error(label, reserved_keys)
            if error:
                rejected[key] = f"{label!r}: {error}"
                rejected_labels[key] = label
                continue
            results[key] = label
            reserved_keys.add(canonical_topic_key(label))
        remaining = [key for key in remaining if key not in results]
        for key in remaining:
            rejected.setdefault(key, "model omitted topic")
        if not remaining:
            return results
        print(
            f"  repairing {len(remaining)} display label(s), attempt "
            f"{repair_attempt + 1}/4",
            flush=True,
        )
    unresolved = []
    for key in remaining:
        fallback = deterministic_display_label(
            canonical[key]["label"],
            reserved_keys,
            preferred_label=rejected_labels.get(key),
        )
        if fallback is None:
            unresolved.append(key)
            continue
        results[key] = fallback
        reserved_keys.add(canonical_topic_key(fallback))
        print(f"  using deterministic display label for {key}: {fallback}", flush=True)
    if unresolved:
        raise DisplayLabelBatchError(
            completed=results,
            remaining=unresolved,
            rejected=rejected,
        )
    return results


def related_candidates(canonical: dict[str, dict]) -> dict[str, list[str]]:
    family_members: dict[str, set[str]] = defaultdict(set)
    for key, record in canonical.items():
        for family_id in record["family_ids"]:
            family_members[family_id].add(key)
    result = {}
    for key, record in canonical.items():
        candidates = set()
        for family_id in record["family_ids"]:
            candidates.update(family_members[family_id])
        candidates.discard(key)
        scored = []
        left_videos = record["videos"]
        left_tokens = comparison_tokens(record["label"])
        for other in candidates:
            right = canonical[other]
            cooccurrence = len(left_videos & right["videos"]) / max(
                1, len(left_videos | right["videos"])
            )
            right_tokens = comparison_tokens(right["label"])
            lexical = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
            shared_families = len(record["family_ids"] & right["family_ids"])
            if not cooccurrence and not lexical:
                continue
            score = cooccurrence * 2 + lexical + shared_families * 0.25
            scored.append((score, len(right["videos"]), other))
        result[key] = [other for _, _, other in sorted(scored, reverse=True)[:10]]
    return result


def relate_batch(
    client: Any,
    *,
    model: str,
    keys: list[str],
    canonical: dict[str, dict],
    candidates: dict[str, list[str]],
    families: dict[str, dict],
    retries: int,
) -> dict[str, list[str]]:
    results = {}
    remaining = list(keys)
    for repair_attempt in range(3):
        source_ids = {f"T{index + 1:03d}": key for index, key in enumerate(remaining)}
        candidate_maps = {}
        payload_topics = []
        for source_id, key in source_ids.items():
            record = canonical[key]
            candidate_map = {
                f"C{index + 1:02d}": other
                for index, other in enumerate(candidates[key])
            }
            candidate_maps[source_id] = candidate_map
            payload_topics.append(
                {
                    "source_id": source_id,
                    "label": record["label"],
                    "families": [families[family_id]["label"] for family_id in record["family_ids"]],
                    "chapter_context": sorted(record["contexts"])[:4],
                    "candidates": [
                        {"candidate_id": candidate_id, "label": canonical[other]["label"]}
                        for candidate_id, other in candidate_map.items()
                    ],
                }
            )
        generated = request_structured(
            client,
            model=model,
            system_prompt=RELATED_PROMPT,
            payload={"topics": payload_topics},
            output_type=GeneratedRelatedTopics,
            retries=retries,
        )
        for decision in generated.decisions:
            key = source_ids.get(decision.source_id)
            if not key:
                continue
            candidate_map = candidate_maps[decision.source_id]
            results[key] = [
                candidate_map[candidate_id]
                for candidate_id in decision.related_ids
                if candidate_id in candidate_map
            ][:5]
        remaining = [key for key in remaining if key not in results]
        if not remaining:
            break
        print(
            f"  repairing {len(remaining)} omitted relation decision(s), attempt {repair_attempt + 1}/3",
            flush=True,
        )
    if remaining:
        raise RuntimeError(f"Related-topic batch omitted topics after repairs: {remaining}")
    return results


def make_related_symmetric(related: dict[str, list[str]]) -> dict[str, list[str]]:
    graph: dict[str, set[str]] = {
        source: set() for source in related
    }
    for source, targets in related.items():
        for target in targets:
            if source == target:
                continue
            graph.setdefault(source, set()).add(target)
            graph.setdefault(target, set()).add(source)
    return {key: sorted(values) for key, values in sorted(graph.items())}


def run(args: argparse.Namespace) -> int:
    analyses = load_analyses(args.root)
    topic_maps = load_topic_chapter_maps(args.root, analyses)
    records = topic_inventory(analyses, topic_maps)
    source_hash = inventory_hash(records)
    path = normalization_path(args.root)
    previous_manifest = load_collection_manifest(
        catalog_root(args.root) / "collection.json"
    ) or {}
    collection_id = (
        previous_manifest.get("collection_id")
        or canonical_topic_key(args.root.name).replace(" ", "-")
        or "video-collection"
    )
    state = load_state(
        path, collection_id, source_hash, args.normalization_model, args.force
    )
    if args.rebuild_related:
        state["related"] = {}
        state.pop("stats", None)
        if state.get("assignments"):
            state["status"] = "assigning"
    if (
        args.rebuild_display_labels
        or state.get("display_label_prompt_version") != DISPLAY_LABEL_PROMPT_VERSION
    ):
        state["display_label_prompt_version"] = DISPLAY_LABEL_PROMPT_VERSION
        state["display_labels"] = {}
        state.pop("stats", None)
    known_keys = set(records)
    state["assignments"] = {
        key: value for key, value in state.get("assignments", {}).items() if key in known_keys
    }
    pending = sorted(known_keys - set(state["assignments"]))
    selected = pending[: args.limit] if args.limit is not None else pending
    print(
        f"{len(records)} raw topics | {len(state['assignments'])} assigned | "
        f"{len(pending)} pending | {len(selected)} selected",
        flush=True,
    )
    if args.dry_run:
        print("family taxonomy: " + ("present" if state.get("families") else "pending"))
        print(f"related topics: {len(state.get('related', {}))} completed")
        canonical_keys = {
            assignment.get("canonical_key")
            for assignment in state["assignments"].values()
            if assignment.get("canonical_key")
        }
        completed_labels = canonical_keys & set(state.get("display_labels", {}))
        print(
            f"display labels: {len(completed_labels)} completed | "
            f"{len(canonical_keys - completed_labels)} pending"
        )
        return 0

    client = create_openai_client(args.timeout)
    if not state.get("families"):
        print("Creating collection topic families…", flush=True)
        state["families"] = create_taxonomy(
            client, args.normalization_model, records, args.retries
        )
        state["status"] = "assigning"
        save_state(path, state)
        print(f"  {len(state['families'])} families", flush=True)

    candidates = alias_candidates(records)
    for batch_number, keys in enumerate(chunks(selected, args.batch_size), start=1):
        print(
            f"Assigning batch {batch_number}/{max(1, len(chunks(selected, args.batch_size)))} "
            f"({len(keys)} topics)…",
            flush=True,
        )
        state["assignments"].update(
            assign_batch(
                client,
                model=args.normalization_model,
                keys=keys,
                records=records,
                candidates=candidates,
                families=state["families"],
                retries=args.retries,
            )
        )
        save_state(path, state)

    remaining = known_keys - set(state["assignments"])
    if remaining:
        state["status"] = "assigning"
        save_state(path, state)
        print(f"{len(remaining)} topics remain; rerun to continue.", flush=True)
        return 0

    finalize_canonical_assignments(records, state["assignments"])
    save_state(path, state)
    canonical = canonical_inventory(records, state["assignments"])
    state["display_labels"] = {
        key: label
        for key, label in state.get("display_labels", {}).items()
        if key in canonical
    }
    pending_labels = sorted(set(canonical) - set(state["display_labels"]))
    for batch_number, keys in enumerate(chunks(pending_labels, args.batch_size), start=1):
        print(
            f"Labeling batch {batch_number}/{max(1, len(chunks(pending_labels, args.batch_size)))} "
            f"({len(keys)} canonical topics)…",
            flush=True,
        )
        try:
            labels = label_batch(
                client,
                model=args.normalization_model,
                keys=keys,
                canonical=canonical,
                families=state["families"],
                reserved_labels=list(state["display_labels"].values()),
                retries=args.retries,
            )
        except DisplayLabelBatchError as error:
            state["display_labels"].update(error.completed)
            state["status"] = "labeling"
            state["last_error"] = {
                "phase": "display-labels",
                "topics": error.remaining,
                "rejections": error.rejected,
            }
            save_state(path, state)
            raise
        state["display_labels"].update(labels)
        state.pop("last_error", None)
        state["status"] = "labeling"
        save_state(path, state)
    relation_candidates = related_candidates(canonical)
    pending_related = sorted(set(canonical) - set(state.get("related", {})))
    for batch_number, keys in enumerate(chunks(pending_related, args.batch_size), start=1):
        print(
            f"Relating batch {batch_number}/{max(1, len(chunks(pending_related, args.batch_size)))} "
            f"({len(keys)} canonical topics)…",
            flush=True,
        )
        state["related"].update(
            relate_batch(
                client,
                model=args.normalization_model,
                keys=keys,
                canonical=canonical,
                candidates=relation_candidates,
                families=state["families"],
                retries=args.retries,
            )
        )
        save_state(path, state)

    state["related"] = make_related_symmetric(state["related"])
    state["status"] = "complete"
    state["stats"] = {
        "raw_topic_count": len(records),
        "canonical_topic_count": len(canonical),
        "family_count": len(state["families"]),
        "display_label_count": len(state["display_labels"]),
        "related_edge_count": sum(len(values) for values in state["related"].values()) // 2,
    }
    save_state(path, state)
    print(
        f"complete: {len(records)} raw → {len(canonical)} canonical topics | "
        f"{len(state['display_labels'])} compact labels | "
        f"{len(state['families'])} families | {state['stats']['related_edge_count']} related pairs",
        flush=True,
    )
    if not args.no_rebuild:
        from build_collection import write_collection

        write_collection(args.root)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=validated_root)
    parser.add_argument(
        "--normalization-model",
        default=default_normalization_model(),
        help=f"Topic clustering/normalization model (env: {NORMALIZATION_MODEL_ENV})",
    )
    parser.add_argument("--limit", type=int, help="Assign at most this many pending raw topics")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--force", action="store_true", help="Discard prior generated normalization")
    parser.add_argument(
        "--rebuild-related",
        action="store_true",
        help="Preserve families and assignments but regenerate related-topic links",
    )
    parser.add_argument(
        "--rebuild-display-labels",
        action="store_true",
        help="Preserve normalization and regenerate compact UI topic labels",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report work without API calls")
    parser.add_argument("--no-rebuild", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    if args.batch_size < 1 or args.batch_size > 100:
        raise SystemExit("--batch-size must be between 1 and 100")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
