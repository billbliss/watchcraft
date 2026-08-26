import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import video_catalog
from analyze_catalog import (
    ApproximateDate,
    FeaturedTechnique,
    GeneratedAnalysis,
    GeneratedTimeline,
    Location,
    Section,
    analysis_path,
    analyze_state,
    request_timeline_repair,
)
from build_collection import (
    build_collection_manifest,
    build_topic_chapter_map,
    render_csv,
    write_collection,
)
from chunked_download import chunk_plan
from normalize_topics import (
    alias_candidates,
    build_parser as build_normalization_parser,
    finalize_canonical_assignments,
    load_state,
    make_related_symmetric,
    mechanically_equivalent,
    topic_inventory,
)
from process_catalog import select_work


class FormattingTests(unittest.TestCase):
    def test_srt_timestamp(self):
        self.assertEqual(video_catalog.format_clock(3661.234, srt=True), "01:01:01,234")

    def test_srt_rendering(self):
        rendered = video_catalog.render_srt(
            [{"start": 1.2, "end": 3.4, "text": "  Puppet   Warp  "}]
        )
        self.assertEqual(
            rendered, "1\n00:00:01,200 --> 00:00:03,400\nPuppet Warp\n"
        )

    def test_repetition_filter_rejects_stuck_decoder(self):
        text = "monitor " * 80
        accepted, rejected = video_catalog.clean_segments(
            [{"start": 1.0, "end": 2.0, "text": text}]
        )
        self.assertEqual(accepted, [])
        self.assertEqual(len(rejected), 1)

    def test_repetition_filter_keeps_normal_instruction(self):
        text = (
            "Use the perspective warp to straighten the horizon without cropping "
            "the edges, then blend the sky with a soft clone stamp brush."
        )
        accepted, rejected = video_catalog.clean_segments(
            [{"start": 1.0, "end": 2.0, "text": text}]
        )
        self.assertEqual(len(accepted), 1)
        self.assertEqual(rejected, [])

    def test_output_paths_preserve_collection_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "Part 3" / "Lesson.mp4"
            video.parent.mkdir()
            video.touch()
            srt, text, state = video_catalog.output_paths(root, video)
            self.assertEqual(
                srt,
                root / "Video Catalog" / "transcripts" / "Part 3" / "Lesson.srt",
            )
            self.assertEqual(
                text,
                root
                / "Video Catalog"
                / "transcripts"
                / "Part 3"
                / "Lesson.transcript.txt",
            )
            self.assertEqual(
                state,
                root
                / "Video Catalog"
                / "transcripts"
                / "Part 3"
                / "Lesson.transcript.json",
            )

    def test_migrate_transcript_sidecars_preserves_relative_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "Course" / "Lesson.mp4"
            video.parent.mkdir()
            video.touch()
            legacy_srt = video.with_suffix(".srt")
            legacy_text = video.with_suffix(".transcript.txt")
            legacy_srt.write_text("subtitle", encoding="utf-8")
            legacy_text.write_text("transcript", encoding="utf-8")

            planned, central = video_catalog.migrate_transcript_sidecars(
                root, dry_run=True
            )
            self.assertEqual((planned, central), (2, 0))
            self.assertTrue(legacy_srt.exists())

            moved, central = video_catalog.migrate_transcript_sidecars(root)
            self.assertEqual((moved, central), (2, 0))
            srt, text, _ = video_catalog.output_paths(root, video)
            self.assertEqual(srt.read_text(encoding="utf-8"), "subtitle")
            self.assertEqual(text.read_text(encoding="utf-8"), "transcript")
            self.assertFalse(legacy_srt.exists())
            self.assertFalse(legacy_text.exists())

    def test_chunk_plan_covers_file_exactly(self):
        chunks = chunk_plan(21, 8)
        self.assertEqual([(c.start, c.end, c.size) for c in chunks], [
            (0, 7, 8),
            (8, 15, 8),
            (16, 20, 5),
        ])

    def test_analysis_and_normalization_models_have_independent_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                "os.environ",
                {
                    "VIDEO_CATALOG_ANALYSIS_MODEL": "analysis-test-model",
                    "VIDEO_CATALOG_NORMALIZATION_MODEL": "normalization-test-model",
                },
            ):
                analysis_args = video_catalog.build_parser().parse_args(
                    ["analyze", "--root", directory, "--all", "--dry-run"]
                )
                normalization_args = build_normalization_parser().parse_args(
                    ["--root", directory, "--dry-run"]
                )
            self.assertEqual(analysis_args.analysis_model, "analysis-test-model")
            self.assertEqual(
                normalization_args.normalization_model,
                "normalization-test-model",
            )


    def test_collection_manifest_models_groups_stable_ids_and_scoped_topics(self):
        analyses = [
            {
                "video": "Course A/Module 1/Lesson One.mp4",
                "title": "Lesson One",
                "summary": "First lesson.",
                "schema_version": 2,
                "analysis_model": "test-model",
                "topics": ["Camera Raw", "Dodge and Burn"],
                "sections": [{"title": "Raw adjustments"}, {"title": "Dodging"}],
                "date": {"display": "2022 (approx.)"},
                "locations": [],
            },
            {
                "video": "Course A/Lesson Two.mp4",
                "title": "Lesson Two",
                "summary": "Second lesson.",
                "topics": ["camera raw"],
                "sections": [{"title": "Raw adjustments"}],
                "locations": [{"name": "Oregon Coast (probable)"}],
            },
        ]
        mappings = {
            "Course A/Module 1/Lesson One.mp4": {
                "camera raw": [0],
                "dodge and burn": [1],
            },
            "Course A/Lesson Two.mp4": {"camera raw": [0]},
        }

        manifest = build_collection_manifest(
            Path("/library/Landscape Classes"), analyses, mappings
        )

        self.assertEqual(manifest["kind"], "watchcraft.collection")
        self.assertEqual(manifest["schema_version"], 4)
        self.assertEqual(manifest["media_root_hint"], "..")
        self.assertEqual(manifest["collection_id"], "landscape-classes")
        self.assertEqual(manifest["topic_scope"], "collection")
        self.assertEqual(
            manifest["stats"],
            {"video_count": 2, "topic_count": 2, "topic_family_count": 0},
        )
        self.assertEqual(manifest["revision"], 1)

        course = manifest["root"]["children"][0]
        self.assertEqual((course["type"], course["title"]), ("group", "Course A"))
        self.assertEqual(course["children"][0]["title"], "Module 1")
        self.assertEqual(course["children"][0]["children"][0]["type"], "video")
        self.assertEqual(course["children"][1]["type"], "video")

        camera_raw = next(
            topic
            for topic in manifest["topics"].values()
            if topic["canonical_key"] == "camera raw"
        )
        self.assertEqual(camera_raw["label"], "Camera Raw")
        self.assertEqual(camera_raw["aliases"], ["camera raw"])
        self.assertEqual(camera_raw["video_count"], 2)

        lesson_one_id = next(
            item_id
            for item_id, item in manifest["items"].items()
            if item["media"][0]["relative_path"]
            == "Course A/Module 1/Lesson One.mp4"
        )
        lesson_one = manifest["items"][lesson_one_id]
        self.assertEqual(
            lesson_one["transcript"]["text"],
            "transcripts/Course A/Module 1/Lesson One.transcript.txt",
        )
        self.assertEqual(
            lesson_one["analysis"]["path"],
            "analysis/Course A/Module 1/Lesson One.analysis.json",
        )
        self.assertEqual(lesson_one["topic_sections"][camera_raw["topic_id"]], [0])

        unchanged = build_collection_manifest(
            Path("/moved/Landscape Classes"), analyses, mappings, manifest
        )
        self.assertEqual(unchanged["revision"], 1)
        self.assertEqual(unchanged["content_hash"], manifest["content_hash"])
        self.assertEqual(set(unchanged["items"]), set(manifest["items"]))

        changed_analyses = json.loads(json.dumps(analyses))
        changed_analyses[0]["summary"] = "Updated first lesson."
        changed = build_collection_manifest(
            Path("/moved/Landscape Classes"), changed_analyses, mappings, unchanged
        )
        self.assertEqual(changed["revision"], 2)
        self.assertEqual(set(changed["items"]), set(manifest["items"]))

    def test_collection_manifest_applies_canonical_families_and_related_topics(self):
        family_id = "family-retouching-test"
        normalization = {
            "schema_version": 1,
            "prompt_version": 1,
            "model": "test-model",
            "source_hash": "test-source",
            "families": {
                family_id: {
                    "family_id": family_id,
                    "canonical_key": "retouching",
                    "label": "Retouching",
                    "description": "Localized cleanup and repair.",
                }
            },
            "assignments": {
                "clone stamp": {
                    "canonical_label": "Clone Stamp",
                    "family_ids": [family_id],
                },
                "clone stamp tool": {
                    "canonical_label": "Clone Stamp",
                    "family_ids": [family_id],
                },
                "content-aware fill": {
                    "canonical_label": "Content-Aware Fill",
                    "family_ids": [family_id],
                },
            },
            "related": {
                "clone stamp": ["content-aware fill"],
                "content-aware fill": ["clone stamp"],
            },
        }
        analyses = [
            {
                "video": "Course/A.mp4",
                "topics": ["Clone Stamp Tool", "Content-Aware Fill"],
                "sections": [{"title": "Cleanup"}, {"title": "Fill"}],
            },
            {
                "video": "Course/B.mp4",
                "topics": ["Clone Stamp"],
                "sections": [{"title": "Cleanup"}],
            },
        ]
        mappings = {
            "Course/A.mp4": {
                "clone stamp tool": [0],
                "content-aware fill": [1],
            },
            "Course/B.mp4": {"clone stamp": [0]},
        }
        manifest = build_collection_manifest(
            Path("/library/Classes"), analyses, mappings, normalization=normalization
        )
        self.assertEqual(manifest["stats"]["topic_count"], 2)
        self.assertEqual(manifest["stats"]["topic_family_count"], 1)
        clone = next(
            topic
            for topic in manifest["topics"].values()
            if topic["canonical_key"] == "clone stamp"
        )
        fill = next(
            topic
            for topic in manifest["topics"].values()
            if topic["canonical_key"] == "content-aware fill"
        )
        self.assertEqual(clone["video_count"], 2)
        self.assertEqual(clone["aliases"], ["Clone Stamp Tool"])
        self.assertEqual(clone["family_ids"], [family_id])
        self.assertEqual(clone["related_topic_ids"], [fill["topic_id"]])
        self.assertEqual(
            manifest["topic_families"][family_id]["video_count"], 2
        )
        self.assertTrue(
            all(family_id in item["family_ids"] for item in manifest["items"].values())
        )

    def test_topic_chapter_mapping_combines_structured_and_transcript_evidence(self):
        analysis = {
            "video": "Course/Lesson.mp4",
            "topics": ["Dodge and Burn", "Camera Raw", "Unmapped"],
            "sections": [
                {
                    "start": "00:00:00",
                    "end": "00:01:00",
                    "title": "Introduction",
                    "concepts": ["dodge and burn"],
                    "description": "Overview.",
                },
                {
                    "start": "00:01:00",
                    "end": "00:03:00",
                    "title": "Sculpting light with dodging and burning",
                    "concepts": [],
                    "description": "Practical work.",
                },
            ],
            "featured_techniques": [
                {
                    "technique": "Dodge and burn to sculpt light",
                    "timestamp": "00:01:00",
                }
            ],
        }
        transcript = [
            {
                "start": 120,
                "end": 125,
                "text": "Now open Camera Raw and adjust the exposure.",
            }
        ]
        mapping = build_topic_chapter_map(analysis, transcript)
        self.assertEqual(mapping["dodge and burn"], [0, 1])
        self.assertEqual(mapping["camera raw"], [1])
        self.assertNotIn("unmapped", mapping)

    def test_collection_csv_export_remains_available(self):
        analysis = {
            "video": "Course/Lesson.mp4",
            "title": "Lesson",
            "date": {"display": "2024"},
            "locations": [{"name": "Oregon Coast"}],
            "summary": "A useful lesson.",
            "topics": ["Dodge and Burn"],
            "sections": [],
        }
        rows = render_csv([analysis]).splitlines()
        self.assertEqual(
            rows[0],
            "video,title,date,location,summary,topics,featured_techniques,section_count",
        )
        self.assertIn("Course/Lesson.mp4,Lesson,2024,Oregon Coast", rows[1])

    def test_collection_build_removes_the_legacy_html_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / video_catalog.CATALOG_DIR_NAME
            analysis_path = catalog / "analysis" / "Course" / "Lesson.analysis.json"
            analysis_path.parent.mkdir(parents=True)
            analysis_path.write_text(
                json.dumps(
                    {
                        "video": "Course/Lesson.mp4",
                        "title": "Lesson",
                        "summary": "A useful lesson.",
                        "topics": [],
                        "sections": [],
                        "locations": [],
                    }
                ),
                encoding="utf-8",
            )
            legacy_html = catalog / "catalog.html"
            legacy_html.write_text("legacy UI", encoding="utf-8")

            manifest = write_collection(root)

            self.assertEqual(manifest["kind"], "watchcraft.collection")
            self.assertTrue((catalog / "collection.json").is_file())
            self.assertTrue((catalog / "catalog.csv").is_file())
            self.assertFalse(legacy_html.exists())

    def test_structured_analysis_is_atomic_normalized_and_resumable(self):
        class FakeResponses:
            def __init__(self, generated):
                self.generated = generated
                self.calls = 0

            def parse(self, **kwargs):
                self.calls += 1
                self.kwargs = kwargs
                return type("Response", (), {"output_parsed": self.generated})()

        class FakeClient:
            def __init__(self, generated):
                self.responses = FakeResponses(generated)

        generated = GeneratedAnalysis(
            title="A useful lesson",
            date=ApproximateDate(
                display="2022 (approx.)",
                iso="2022",
                precision="year",
                confidence=1.4,
                basis="Folder name",
            ),
            locations=[
                Location(name="Oregon Coast (probable)", confidence=-0.2, basis="Context")
            ],
            summary="A practical Photoshop workflow.",
            topics=["Puppet Warp", "puppet warp", "History Brush"],
            sections=[
                Section(
                    start="00:10:00",
                    end="00:12:00",
                    title="Warp",
                    concepts=["Puppet Warp"],
                    description="Reshapes the frame.",
                ),
                Section(
                    start="00:02:00",
                    end="00:05:00",
                    title="Blend",
                    concepts=["History Brush"],
                    description="Blends local changes.",
                ),
            ],
            featured_techniques=[
                FeaturedTechnique(
                    technique="Puppet Warp", timestamp="00:10:00", confidence=0.9
                )
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "Part 3" / "Lesson.mp4"
            video.parent.mkdir()
            video.touch()
            state_path = (
                root
                / video_catalog.CATALOG_DIR_NAME
                / "transcripts"
                / "Part 3"
                / "Lesson.transcript.json"
            )
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                json.dumps(
                    {
                        "video": "Part 3/Lesson.mp4",
                        "segments": [
                            {"start": 2, "end": 5, "text": "Use the History Brush."}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            client = FakeClient(generated)
            with patch("analyze_catalog.probe_creation_time", return_value="2022-01-01"):
                result = analyze_state(
                    root,
                    state_path,
                    client=client,
                    model="test-model",
                    force=False,
                    retries=0,
                    max_transcript_chars=10_000,
                )
            self.assertEqual(result, "completed")
            output = analysis_path(root, "Part 3/Lesson.mp4")
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["date"]["confidence"], 1.0)
            self.assertEqual(payload["locations"][0]["confidence"], 0.0)
            self.assertEqual(payload["topics"], ["Puppet Warp", "History Brush"])
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(payload["sections"][0]["title"], "Blend")
            self.assertEqual(payload["analysis_model"], "test-model")
            self.assertEqual(client.responses.kwargs["text_format"], GeneratedAnalysis)
            self.assertEqual(
                analyze_state(
                    root,
                    state_path,
                    client=client,
                    model="test-model",
                    force=False,
                    retries=0,
                    max_transcript_chars=10_000,
                ),
                "skipped",
            )
            self.assertEqual(client.responses.calls, 1)

    def test_topic_normalization_inventory_candidates_and_symmetric_relations(self):
        analyses = [
            {
                "video": "Course/A.mp4",
                "title": "Retouching",
                "topics": ["Clone Stamp Tool", "Masking"],
                "sections": [{"title": "Clone cleanup"}],
            },
            {
                "video": "Course/B.mp4",
                "title": "Cleanup",
                "topics": ["Clone Stamp", "Layer Masks"],
                "sections": [{"title": "Clone stamp"}],
            },
        ]
        maps = {
            "Course/A.mp4": {"clone stamp tool": [0]},
            "Course/B.mp4": {"clone stamp": [0]},
        }
        records = topic_inventory(analyses, maps)
        candidates = alias_candidates(records)
        self.assertIn("clone stamp", candidates["clone stamp tool"])
        self.assertIn("Retouching — Clone cleanup", records["clone stamp tool"]["contexts"])
        self.assertEqual(
            make_related_symmetric({"clone stamp": ["masking"], "masking": []}),
            {"clone stamp": ["masking"], "masking": ["clone stamp"]},
        )
        assignments = {
            "clone stamp": {"alias_source_keys": ["clone stamp tool"]},
            "clone stamp tool": {"alias_source_keys": ["clone stamp"]},
            "masking": {"alias_source_keys": ["layer masks"]},
            "layer masks": {"alias_source_keys": []},
        }
        finalize_canonical_assignments(records, assignments)
        self.assertEqual(
            assignments["clone stamp tool"]["canonical_key"], "clone stamp"
        )
        self.assertEqual(assignments["masking"]["canonical_key"], "masking")
        self.assertEqual(assignments["layer masks"]["canonical_key"], "layer masks")

    def test_timeline_repair_requires_and_returns_valid_sections(self):
        class FakeResponses:
            def __init__(self, generated):
                self.generated = generated

            def parse(self, **kwargs):
                self.kwargs = kwargs
                return type("Response", (), {"output_parsed": self.generated})()

        class FakeClient:
            def __init__(self, generated):
                self.responses = FakeResponses(generated)

        sections = [
            Section(
                start=f"00:0{index}:00",
                end=f"00:0{index + 1}:00",
                title=f"Chapter {index}",
                concepts=["Technique"],
                description="Demonstrates a technique.",
            )
            for index in range(3)
        ]
        client = FakeClient(GeneratedTimeline(sections=sections))
        repaired = request_timeline_repair(
            client,
            model="timeline-model",
            context={"filename": "Lesson.mp4"},
            existing_analysis={"title": "Lesson"},
            transcript="[00:00:00] Instruction",
            transcript_duration="00:10:00",
            retries=0,
        )
        self.assertEqual(len(repaired.sections), 3)
        self.assertEqual(client.responses.kwargs["text_format"], GeneratedTimeline)

        empty_client = FakeClient(GeneratedTimeline(sections=[]))
        with self.assertRaisesRegex(RuntimeError, "only 0 sections"):
            request_timeline_repair(
                empty_client,
                model="timeline-model",
                context={},
                existing_analysis={},
                transcript="[00:00:00] Instruction",
                transcript_duration="00:10:00",
                retries=0,
            )

    def test_canonical_aliases_are_conservative_and_mechanical(self):
        self.assertTrue(mechanically_equivalent("4x5 crop", "4x5 Cropping"))
        self.assertTrue(mechanically_equivalent("ACR", "Adobe Camera Raw"))
        self.assertTrue(mechanically_equivalent("Clone Stamp", "Clone Stamp Tool"))
        self.assertFalse(
            mechanically_equivalent("Local adjustments", "Tonal adjustments")
        )
        self.assertFalse(mechanically_equivalent("Luminosity", "Luminosity masks"))
        self.assertFalse(mechanically_equivalent("Camera Raw", "Camera Raw Filter"))
        self.assertFalse(mechanically_equivalent("Field technique", "Field workflow"))

    def test_normalization_resume_rejects_a_different_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "topic-normalization.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_version": 2,
                        "collection_id": "collection",
                        "model": "first-model",
                        "families": {"one": {}},
                        "assignments": {},
                        "related": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "first-model"):
                load_state(path, "collection", "hash", "second-model", False)

    def test_process_limit_selects_next_unfinished_video_for_both_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            videos = [root / f"Course/{name}.mp4" for name in ("A", "B", "C")]
            videos[0].parent.mkdir()
            for video in videos:
                video.touch()

            # A is fully complete. B has only its transcript. C has neither.
            for video in videos[:2]:
                srt_path, text_path, state_path = video_catalog.output_paths(root, video)
                state_path.parent.mkdir(parents=True, exist_ok=True)
                srt_path.write_text("subtitle", encoding="utf-8")
                text_path.write_text("transcript", encoding="utf-8")
                state_path.write_text(
                    json.dumps(
                        {
                            "video": video.relative_to(root).as_posix(),
                            "segments": [
                                {"start": 0, "end": 1, "text": "Instruction"}
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
            completed_analysis = analysis_path(
                root, videos[0].relative_to(root).as_posix()
            )
            completed_analysis.parent.mkdir(parents=True)
            completed_analysis.write_text("{}", encoding="utf-8")

            selected, total_pending = select_work(
                root, requested_video=None, limit=1
            )
            self.assertEqual(total_pending, 2)
            self.assertEqual(selected[0].video, videos[1])
            self.assertFalse(selected[0].transcribe)
            self.assertTrue(selected[0].analyze)

            selected, total_pending = select_work(
                root, requested_video=None, limit=2
            )
            self.assertEqual([item.video for item in selected], videos[1:])
            self.assertTrue(selected[1].transcribe)
            self.assertTrue(selected[1].analyze)


if __name__ == "__main__":
    unittest.main()
