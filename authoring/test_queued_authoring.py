import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from jsonschema import Draft202012Validator

import queued_authoring
from watchcraft_author import build_parser, main


def registry_snapshot(
    *,
    educational_analysis=False,
    transcription=False,
    http_transcription=False,
    staged_transcription=False,
    staged_smoke=False,
    playlist_iterator=False,
    project_planner=False,
    terminology_resolution=False,
    topic_normalization=False,
    collection_compilation=False,
):
    if terminology_resolution:
        return {
            "registry_version": "2026-09-10.9",
            "registry_sha256": "c" * 64,
            "handler": queued_authoring.LOCAL_HANDLER_CONTRACTS[
                queued_authoring.TERMINOLOGY_RESOLUTION_HANDLER
            ],
            "execution_profile": queued_authoring.LOCAL_EXECUTION_PROFILES[
                queued_authoring.OPENAI_EXECUTION_PROFILE
            ],
        }
    if collection_compilation:
        return {
            "registry_version": "2026-09-10.9",
            "registry_sha256": "c" * 64,
            "handler": queued_authoring.LOCAL_HANDLER_CONTRACTS[
                queued_authoring.COLLECTION_COMPILATION_HANDLER
            ],
            "execution_profile": queued_authoring.LOCAL_EXECUTION_PROFILES[
                queued_authoring.PYTHON_EXECUTION_PROFILE
            ],
        }
    if topic_normalization:
        return {
            "registry_version": "2026-09-10.9",
            "registry_sha256": "c" * 64,
            "handler": queued_authoring.LOCAL_HANDLER_CONTRACTS[
                queued_authoring.TOPIC_NORMALIZATION_HANDLER
            ],
            "execution_profile": queued_authoring.LOCAL_EXECUTION_PROFILES[
                queued_authoring.OPENAI_EXECUTION_PROFILE
            ],
        }
    if project_planner:
        return {
            "registry_version": "2026-09-08.2",
            "registry_sha256": "c" * 64,
            "handler": queued_authoring.LOCAL_HANDLER_CONTRACTS[
                queued_authoring.PROJECT_PROCESSING_PLANNER_HANDLER
            ],
            "execution_profile": queued_authoring.LOCAL_EXECUTION_PROFILES[
                queued_authoring.PYTHON_EXECUTION_PROFILE
            ],
        }
    if playlist_iterator:
        return {
            "registry_version": "2026-09-08.2",
            "registry_sha256": "c" * 64,
            "handler": queued_authoring.LOCAL_HANDLER_CONTRACTS[
                queued_authoring.YOUTUBE_PLAYLIST_ITERATOR_HANDLER
            ],
            "execution_profile": queued_authoring.LOCAL_EXECUTION_PROFILES[
                queued_authoring.PYTHON_EXECUTION_PROFILE
            ],
        }
    if educational_analysis:
        return {
            "registry_version": "2026-09-08.2",
            "registry_sha256": "c" * 64,
            "handler": queued_authoring.LOCAL_HANDLER_CONTRACTS[
                queued_authoring.EDUCATIONAL_VIDEO_ANALYSIS_HANDLER
            ],
            "execution_profile": queued_authoring.LOCAL_EXECUTION_PROFILES[
                queued_authoring.OPENAI_EXECUTION_PROFILE
            ],
        }
    if transcription or http_transcription or staged_transcription or staged_smoke:
        handler = (
            queued_authoring.STAGED_TRANSCRIPTION_SMOKE_HANDLER
            if staged_smoke
            else (
                queued_authoring.PRODUCTION_TRANSCRIPTION_HANDLER
                if staged_transcription
                else (
                    queued_authoring.HTTP_TRANSCRIPTION_SMOKE_HANDLER
                    if http_transcription
                    else queued_authoring.TRANSCRIPTION_SMOKE_HANDLER
                )
            )
        )
        return {
            "registry_version": "2026-09-08.2",
            "registry_sha256": "c" * 64,
            "handler": queued_authoring.LOCAL_HANDLER_CONTRACTS[handler],
            "execution_profile": queued_authoring.LOCAL_EXECUTION_PROFILES[
                queued_authoring.MLX_EXECUTION_PROFILE
            ],
        }
    return {
        "registry_version": "2026-09-08.2",
        "registry_sha256": "c" * 64,
        "handler": {
            "id": "watchcraft.analysis.lexical",
            "version": "1",
            "operation": "generate",
            "inputs": [],
            "dependencies": [],
            "output": {
                "artifact_kind": "analysis",
                "schema": {"id": "watchcraft.analysis.lexical", "version": 1},
            },
            "execution_profile": {"id": "python-portable", "version": "1"},
            "lease_class": "short",
            "retry_policy": {
                "max_attempts": 3,
                "retryable_classifications": ["artifact_store_failed", "lease_expired"],
            },
        },
        "execution_profile": {
            "id": "python-portable",
            "version": "1",
            "dispatcher": {"kind": "github-actions", "workflow": "authoring-worker.yml"},
            "platform": {"os": "linux", "architecture": "x64"},
            "dependency_class": "python-authoring-worker",
            "cache_class": "pip",
            "timeout_minutes": 15,
            "lease_duration_ms": 300_000,
            "heartbeat_interval_ms": 60_000,
            "data_access": "public",
            "secret_capabilities": ["convex.worker", "r2.read-write"],
        },
    }


def staged_audio_reference(*, expires_at=2_000_000_000_000):
    digest = "b" * 64
    return {
        "store": "r2",
        "algorithm": "sha256",
        "digest": digest,
        "byte_length": 1_682_197,
        "media_type": "audio/webm",
        "artifact_kind": "source-audio",
        "schema": queued_authoring.SOURCE_AUDIO_SCHEMA,
        "key": (
            "staging/00000000-0000-4000-8000-000000000000/sha256/"
            f"{digest[:2]}/{digest[2:]}"
        ),
        "retention": {"class": "ephemeral", "expires_at": expires_at},
    }


def transcript_reference():
    digest = "d" * 64
    return {
        "store": "r2",
        "algorithm": "sha256",
        "digest": digest,
        "byte_length": 12_345,
        "media_type": "application/json",
        "artifact_kind": "transcript",
        "schema": {"id": "watchcraft.transcript", "version": 1},
        "key": f"objects/sha256/{digest[:2]}/{digest[2:]}",
    }


def youtube_metadata():
    return {
        "source_id": "youtube:WPtpUu3uIUI",
        "type": "youtube",
        "video_id": "WPtpUu3uIUI",
        "url": "https://www.youtube.com/watch?v=WPtpUu3uIUI",
        "title": "Three hotel-management techniques",
        "publisher": "Hospitality School",
        "publisher_url": "https://www.youtube.com/@hospitalityschool",
        "thumbnail_url": "https://i.ytimg.com/vi/WPtpUu3uIUI/hqdefault.jpg",
        "duration_seconds": 120,
        "published_at": "2026-08-19",
        "chapters": [],
    }


def staged_acquisition(reference=None):
    reference = reference or staged_audio_reference()
    return {
        "method": {"id": "watchcraft.youtube.yt-dlp-local", "version": "1"},
        "source": {
            "media_asset_id": "youtube:WPtpUu3uIUI",
            "provider": "youtube",
            "video_id": "WPtpUu3uIUI",
            "canonical_url": "https://www.youtube.com/watch?v=WPtpUu3uIUI",
        },
        "observed_at": 1_788_000_000_000,
        "tool": {"id": "yt-dlp", "version": "2026.08.19"},
        "media": {
            "algorithm": reference["algorithm"],
            "digest": reference["digest"],
            "byte_length": reference["byte_length"],
            "duration_seconds": 120.0,
            "format_id": "251",
            "language": "en",
            "container": "webm",
        },
    }


class QueuedAuthoringTests(unittest.TestCase):
    def test_default_capability_registry_conforms_to_its_language_neutral_schema(self):
        registry_directory = queued_authoring.DEFAULT_REGISTRY_PATH.parent
        schema = json.loads(
            (registry_directory / "authoring-capability-registry.schema.json").read_text()
        )
        registry = queued_authoring.load_registry_document(
            queued_authoring.DEFAULT_REGISTRY_PATH
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(registry)

    def test_queue_parser_exposes_non_transcript_analysis_submission(self):
        args = build_parser().parse_args([
            "queue", "submit-analysis", "--title", "Color workflow",
            "--text", "Balance exposure and color before applying the final grade.",
        ])
        self.assertEqual(args.command, "queue")
        self.assertEqual(args.queue_command, "submit-analysis")
        self.assertEqual(args.max_topics, 8)
        self.assertEqual(args.operator_token_source, "auto")

        queued = build_parser().parse_args([
            "queue",
            "analyze-transcript",
            "transcription-job-1",
            "--operator-token-source",
            "keychain",
            "--r2-credentials-source",
            "keychain",
        ])
        self.assertEqual(queued.queue_command, "analyze-transcript")
        self.assertEqual(queued.transcription_job_id, "transcription-job-1")
        self.assertEqual(queued.timeout_seconds, 3600)

    def test_queue_parser_exposes_one_command_smokes_and_guarded_cleanup(self):
        smoke = build_parser().parse_args([
            "queue", "smoke-transcription",
            "--operator-token-source", "keychain",
            "--r2-credentials-source", "keychain",
        ])
        self.assertEqual(smoke.timeout_seconds, 1800)
        self.assertEqual(smoke.retention_days, 7)
        http_smoke = build_parser().parse_args([
            "queue", "smoke-transcription-http",
            "--operator-token-source", "keychain",
            "--r2-credentials-source", "keychain",
        ])
        self.assertEqual(http_smoke.timeout_seconds, 1800)
        self.assertEqual(http_smoke.retention_days, 7)
        youtube_smoke = build_parser().parse_args([
            "queue", "smoke-transcription-youtube",
            "--operator-token-source", "keychain",
            "--r2-credentials-source", "keychain",
        ])
        self.assertEqual(
            youtube_smoke.youtube_url,
            queued_authoring.YOUTUBE_TRANSCRIPTION_SMOKE_URL,
        )
        self.assertEqual(youtube_smoke.r2_staging_credentials_source, "auto")
        production = build_parser().parse_args([
            "queue", "transcribe-youtube", "WPtpUu3uIUI",
        ])
        self.assertEqual(production.youtube_url, "WPtpUu3uIUI")
        self.assertEqual(production.timeout_seconds, 3600)
        self.assertEqual(production.r2_staging_credentials_source, "auto")
        pipeline = build_parser().parse_args([
            "queue", "process-youtube", "WPtpUu3uIUI",
        ])
        self.assertEqual(pipeline.youtube_url, "WPtpUu3uIUI")
        self.assertEqual(pipeline.transcription_timeout_seconds, 3600)
        self.assertEqual(pipeline.analysis_timeout_seconds, 3600)
        self.assertEqual(pipeline.r2_staging_credentials_source, "auto")
        iterator = build_parser().parse_args([
            "queue", "iterate-project", "project.json",
            "--operator-token-source", "keychain",
            "--r2-credentials-source", "keychain",
        ])
        self.assertEqual(iterator.project, "project.json")
        self.assertEqual(iterator.timeout_seconds, 1800)
        planner = build_parser().parse_args([
            "queue", "plan-project", "essence-of-linear-algebra",
            "--operator-token-source", "keychain",
            "--r2-credentials-source", "keychain",
        ])
        self.assertEqual(planner.project_id, "essence-of-linear-algebra")
        self.assertEqual(planner.timeout_seconds, 900)
        project_processing = build_parser().parse_args([
            "queue", "process-project",
            "--plan-job-id", "plan-job-1",
            "--limit", "1",
            "--operator-token-source", "keychain",
            "--r2-staging-credentials-source", "keychain",
            "--r2-credentials-source", "keychain",
        ])
        self.assertEqual(project_processing.plan_job_id, "plan-job-1")
        self.assertEqual(project_processing.limit, 1)
        self.assertIsNone(project_processing.item_id)
        self.assertFalse(project_processing.process_all)
        self.assertEqual(project_processing.concurrency, 2)
        all_project_processing = build_parser().parse_args([
            "queue", "process-project",
            "--plan-job-id", "plan-job-1",
            "--all",
            "--concurrency", "3",
        ])
        self.assertTrue(all_project_processing.process_all)
        self.assertEqual(all_project_processing.concurrency, 3)
        terminology = build_parser().parse_args([
            "queue", "resolve-project-terminology",
            "--plan-job-id", "plan-job-1",
            "--operator-token-source", "keychain",
            "--r2-credentials-source", "keychain",
        ])
        self.assertEqual(terminology.plan_job_id, "plan-job-1")
        self.assertEqual(terminology.timeout_seconds, 3600)
        normalization = build_parser().parse_args([
            "queue", "normalize-project-topics",
            "--plan-job-id", "plan-job-1",
            "--operator-token-source", "keychain",
            "--r2-credentials-source", "keychain",
        ])
        self.assertEqual(normalization.plan_job_id, "plan-job-1")
        self.assertEqual(normalization.timeout_seconds, 3600)
        project_import = build_parser().parse_args([
            "queue", "project-import", "project.json",
        ])
        self.assertEqual(project_import.project_file, Path("project.json"))
        self.assertIsNone(project_import.accepted_snapshot_file)
        project_accept = build_parser().parse_args([
            "queue", "project-accept-snapshot", "project-1", "job-1",
            "--r2-credentials-source", "keychain",
        ])
        self.assertEqual(project_accept.project_id, "project-1")
        self.assertEqual(project_accept.job_id, "job-1")
        self.assertIsNone(project_accept.expected_revision)

        cleanup = build_parser().parse_args([
            "queue", "cleanup-run", "run-1", "--confirm", "run-1",
            "--allow-unmarked",
        ])
        self.assertEqual(cleanup.run_id, "run-1")
        self.assertEqual(cleanup.confirm, "run-1")
        self.assertTrue(cleanup.allow_unmarked)
        orphan = build_parser().parse_args([
            "queue", "cleanup-orphan-job", "job-1", "--confirm", "job-1",
        ])
        self.assertEqual(orphan.job_id, "job-1")
        self.assertEqual(orphan.confirm, "job-1")

    def test_project_import_verifies_and_sends_the_bound_snapshot(self):
        examples = queued_authoring.CATALOG_PROJECT_SCHEMA_PATH.parent / "examples"
        project_path = examples / "current-playlist.project.json"
        snapshot_path = examples / "current-playlist.snapshot.json"
        expected_snapshot = snapshot_path.read_text(encoding="utf-8")
        control = Mock()
        control.post.return_value = {
            "created": True,
            "project": {"project_id": "essence-of-linear-algebra", "revision": 1},
        }
        args = build_parser().parse_args([
            "queue", "project-import", str(project_path),
            "--operator-token-source", "keychain",
        ])
        with patch("queued_authoring.operator_client", return_value=control):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(queued_authoring.run_queue_command(args), 0)
        path, payload = control.post.call_args.args
        self.assertEqual(path, "/projects/import")
        self.assertEqual(payload["project"]["revision"], 1)
        self.assertEqual(payload["accepted_snapshot_json"], expected_snapshot)

    def test_project_accept_snapshot_uses_observed_revision_and_exact_bytes(self):
        examples = queued_authoring.CATALOG_PROJECT_SCHEMA_PATH.parent / "examples"
        project = json.loads(
            (examples / "current-playlist.project.json").read_text(encoding="utf-8")
        )
        snapshot_bytes = (
            examples / "current-playlist.snapshot.json"
        ).read_bytes()
        snapshot = json.loads(snapshot_bytes)
        job = {
            "job_id": "iterator-job-1",
            "state": "succeeded",
            "result": project["iterator"]["accepted_snapshot"],
        }
        control = Mock()

        def post(path, payload):
            if path == "/projects/get":
                return {"project": project, "updated_at": 1}
            if path == "/submissions/get":
                return {"job": job, "run": {"run_id": "run-1"}}
            if path == "/projects/accept-snapshot":
                self.assertEqual(payload["expected_revision"], 1)
                self.assertEqual(payload["snapshot_json"], snapshot_bytes.decode("utf-8"))
                return {
                    "project": {**project, "revision": 2},
                    "previous_revision": 1,
                }
            raise AssertionError(path)

        control.post.side_effect = post
        args = build_parser().parse_args([
            "queue", "project-accept-snapshot",
            "essence-of-linear-algebra", "iterator-job-1",
            "--operator-token-source", "keychain",
            "--r2-credentials-source", "keychain",
        ])
        with patch("queued_authoring.operator_client", return_value=control), patch(
            "queued_authoring.verified_json_result_bytes",
            return_value=(snapshot, snapshot_bytes),
        ):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(queued_authoring.run_queue_command(args), 0)

    def test_plan_project_uses_the_authoritative_project_and_only_dispatches_planner(self):
        examples = queued_authoring.CATALOG_PROJECT_SCHEMA_PATH.parent / "examples"
        project = json.loads(
            (examples / "current-playlist.project.json").read_text(encoding="utf-8")
        )
        captured = {}
        submitted_job = {
            "job_id": "plan-job-1",
            "run_id": "plan-run-1",
            "revision": 2,
            "state": "awaiting_approval",
            "spec_sha256": "a" * 64,
            "spec": {
                **queued_authoring.project_processing_plan_spec(
                    project,
                    planned_at="2026-09-08T20:00:00Z",
                ),
                "registry_snapshot": registry_snapshot(project_planner=True),
            },
        }
        control = Mock()

        def post(path, payload):
            if path == "/projects/get":
                self.assertEqual(payload, {"project_id": project["project_id"]})
                return {"project": project}
            if path == "/submissions/approve":
                return {"job": {**submitted_job, "revision": 3, "state": "ready"}}
            raise AssertionError(path)

        control.post.side_effect = post

        def submit(_control, *, request, spec):
            captured.update(request=request, spec=spec)
            return {"job": submitted_job, "run": {"run_id": "plan-run-1"}}

        pending = {
            **submitted_job,
            "revision": 4,
            "state": "dispatch_pending",
            "dispatch": {"generation": 1},
        }
        completed = {
            "job": {
                **pending,
                "state": "succeeded",
                "result": {"digest": "d" * 64},
            },
            "run": {"run_id": "plan-run-1", "state": "complete"},
        }
        plan = {
            "project": {
                "project_id": project["project_id"],
                "revision": project["revision"],
            },
            "source_snapshot": project["iterator"]["accepted_snapshot"],
            "plan_hash": "e" * 64,
            "summary": {"unique_items": 16},
            "estimate": {"status": "duration-informed"},
        }
        args = build_parser().parse_args([
            "queue", "plan-project", project["project_id"],
            "--operator-token-source", "keychain",
            "--r2-credentials-source", "keychain",
        ])
        output = io.StringIO()
        with patch("queued_authoring.operator_client", return_value=control), patch(
            "queued_authoring.submit_spec", side_effect=submit
        ), patch(
            "queued_authoring.dispatch_submission", return_value=pending
        ), patch(
            "queued_authoring.wait_for_terminal_job", return_value=completed
        ), patch(
            "queued_authoring.verified_json_result", return_value=plan
        ), patch(
            "queued_authoring.validate_project_processing_plan"
        ):
            with redirect_stdout(output):
                self.assertEqual(queued_authoring.run_queue_command(args), 0)
        self.assertEqual(captured["request"]["kind"], "project-processing-plan")
        self.assertEqual(captured["spec"]["inputs"], [project["iterator"]["accepted_snapshot"]])
        self.assertEqual(
            captured["spec"]["handler"]["id"],
            queued_authoring.PROJECT_PROCESSING_PLANNER_HANDLER[0],
        )
        self.assertIn("Full plan:", output.getvalue())

    def test_process_project_executes_one_plan_item_with_deterministic_context(self):
        snapshot = {
            "store": "r2",
            "algorithm": "sha256",
            "digest": "b" * 64,
            "byte_length": 100,
            "media_type": "application/json",
            "artifact_kind": "collection-iterator-snapshot",
            "schema": queued_authoring.COLLECTION_ITERATOR_SNAPSHOT_SCHEMA,
            "key": "objects/sha256/bb/" + "b" * 62,
        }
        project = json.loads((
            queued_authoring.CATALOG_PROJECT_SCHEMA_PATH.parent
            / "examples/current-playlist.project.json"
        ).read_text(encoding="utf-8"))
        project["iterator"]["accepted_snapshot"] = snapshot
        item = {
            "item_id": "youtube:fNk_zzaMoSs",
            "title": "Vectors",
            "source": {
                "media_asset_id": "youtube:fNk_zzaMoSs",
                "media_type": "youtube",
                "media_id": "fNk_zzaMoSs",
                "canonical_url": "https://www.youtube.com/watch?v=fNk_zzaMoSs",
            },
            "stages": [
                {
                    "stage": "metadata-enrichment",
                    "task_id": "metadata-task",
                    "handler": {"id": "watchcraft.metadata.youtube", "version": "1"},
                    "executor": "operator-local",
                    "disposition": "required",
                },
                {
                    "stage": "source-acquisition",
                    "task_id": "acquisition-task",
                    "handler": {"id": "watchcraft.acquire.youtube-audio", "version": "1"},
                    "executor": "operator-local",
                    "disposition": "required",
                },
                {
                    "stage": "transcription",
                    "task_id": "transcription-task",
                    "handler": {
                        "id": queued_authoring.PRODUCTION_TRANSCRIPTION_HANDLER[0],
                        "version": "1",
                    },
                    "executor": "registered-worker",
                    "disposition": "required",
                },
                {
                    "stage": "analysis",
                    "task_id": "analysis-task",
                    "handler": {
                        "id": queued_authoring.EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0],
                        "version": "1",
                    },
                    "executor": "registered-worker",
                    "disposition": "required",
                },
            ],
        }
        plan = {
            "project": {
                "project_id": project["project_id"],
                "revision": project["revision"],
            },
            "source_snapshot": snapshot,
            "plan_hash": "c" * 64,
            "items": [item],
        }
        plan_job = {
            "job_id": "plan-job-1",
            "state": "succeeded",
            "spec": {"handler": {
                "id": queued_authoring.PROJECT_PROCESSING_PLANNER_HANDLER[0],
                "version": "1",
            }},
            "result": {
                "store": "r2",
                "algorithm": "sha256",
                "digest": "d" * 64,
                "byte_length": 1_000,
                "media_type": "application/json",
                "artifact_kind": "project-processing-plan",
                "schema": queued_authoring.PROJECT_PROCESSING_PLAN_SCHEMA,
                "key": "objects/sha256/dd/" + "d" * 62,
            },
        }
        control = Mock()

        def post(path, payload):
            if path == "/submissions/get":
                return {"job": plan_job, "run": {"run_id": "plan-run-1"}}
            if path == "/projects/get":
                return {"project": project}
            raise AssertionError(path)

        control.post.side_effect = post
        args = build_parser().parse_args([
            "queue", "process-project",
            "--plan-job-id", "plan-job-1",
            "--limit", "1",
        ])
        captured = {}

        def execute(pipeline_args, *, project_execution, emit_result):
            captured.update(
                youtube_url=pipeline_args.youtube_url,
                project_execution=project_execution,
                emit_result=emit_result,
            )
            return {
                "run_id": "item-run-1",
                "state": "complete",
                "jobs": {
                    "transcription": {"job_id": "transcription-job-1"},
                    "analysis": {"job_id": "analysis-job-1"},
                },
                "timing": {"local": {"command_total_ms": 1_000}},
                "plan_execution": {"disposition": "executed"},
            }

        with patch("queued_authoring.operator_client", return_value=control), patch(
            "queued_authoring.verified_json_result", return_value=plan
        ), patch(
            "queued_authoring.validate_project_processing_plan"
        ), patch(
            "queued_authoring.run_youtube_video_pipeline", side_effect=execute
        ):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(queued_authoring.run_process_project(args), 0)
        self.assertEqual(
            captured["youtube_url"],
            "https://www.youtube.com/watch?v=fNk_zzaMoSs",
        )
        self.assertFalse(captured["emit_result"])
        self.assertEqual(captured["project_execution"], {
            "plan_job_id": "plan-job-1",
            "plan_artifact_sha256": "d" * 64,
            "plan_hash": "c" * 64,
            "project_id": project["project_id"],
            "project_revision": project["revision"],
            "item_id": item["item_id"],
            "logical_tasks": {
                "metadata-enrichment": "metadata-task",
                "source-acquisition": "acquisition-task",
                "transcription": "transcription-task",
                "analysis": "analysis-task",
            },
        })
        first = queued_authoring.stable_project_execution_id(
            "d" * 64, item["item_id"], "run"
        )
        second = queued_authoring.stable_project_execution_id(
            "d" * 64, item["item_id"], "run"
        )
        self.assertEqual(first, second)

    def test_process_project_executes_all_items_and_reports_resumed_work(self):
        snapshot = {
            "store": "r2",
            "algorithm": "sha256",
            "digest": "b" * 64,
            "byte_length": 100,
            "media_type": "application/json",
            "artifact_kind": "collection-iterator-snapshot",
            "schema": queued_authoring.COLLECTION_ITERATOR_SNAPSHOT_SCHEMA,
            "key": "objects/sha256/bb/" + "b" * 62,
        }
        project = json.loads((
            queued_authoring.CATALOG_PROJECT_SCHEMA_PATH.parent
            / "examples/current-playlist.project.json"
        ).read_text(encoding="utf-8"))
        project["iterator"]["accepted_snapshot"] = snapshot

        def item(video_id, title):
            return {
                "item_id": f"youtube:{video_id}",
                "title": title,
                "source": {
                    "media_asset_id": f"youtube:{video_id}",
                    "media_type": "youtube",
                    "media_id": video_id,
                    "canonical_url": f"https://www.youtube.com/watch?v={video_id}",
                },
                "stages": [
                    {
                        "stage": stage,
                        "task_id": f"{video_id}:{stage}",
                        "handler": {"id": handler, "version": "1"},
                        "executor": executor,
                        "disposition": "required",
                    }
                    for stage, handler, executor in [
                        ("metadata-enrichment", "watchcraft.metadata.youtube", "operator-local"),
                        ("source-acquisition", "watchcraft.acquire.youtube-audio", "operator-local"),
                        ("transcription", queued_authoring.PRODUCTION_TRANSCRIPTION_HANDLER[0], "registered-worker"),
                        ("analysis", queued_authoring.EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0], "registered-worker"),
                    ]
                ],
            }

        items = [
            item("fNk_zzaMoSs", "Vectors"),
            item("k7RM-ot2NWY", "Linear combinations"),
        ]
        plan = {
            "project": {
                "project_id": project["project_id"],
                "revision": project["revision"],
            },
            "source_snapshot": snapshot,
            "plan_hash": "c" * 64,
            "items": items,
        }
        plan_job = {
            "job_id": "plan-job-1",
            "state": "succeeded",
            "spec": {"handler": {
                "id": queued_authoring.PROJECT_PROCESSING_PLANNER_HANDLER[0],
                "version": "1",
            }},
            "result": {
                "store": "r2",
                "algorithm": "sha256",
                "digest": "d" * 64,
                "byte_length": 1_000,
                "media_type": "application/json",
                "artifact_kind": "project-processing-plan",
                "schema": queued_authoring.PROJECT_PROCESSING_PLAN_SCHEMA,
                "key": "objects/sha256/dd/" + "d" * 62,
            },
        }
        control = Mock()

        def post(path, payload):
            if path == "/submissions/get":
                return {"job": plan_job, "run": {"run_id": "plan-run-1"}}
            if path == "/projects/get":
                return {"project": project}
            raise AssertionError(path)

        control.post.side_effect = post
        args = build_parser().parse_args([
            "queue", "process-project",
            "--plan-job-id", "plan-job-1",
            "--all",
            "--concurrency", "2",
        ])

        def execute(pipeline_args, *, project_execution, emit_result):
            video_id = queued_authoring.youtube_video_id(pipeline_args.youtube_url)
            return {
                "run_id": f"run-{video_id}",
                "state": "complete",
                "jobs": {
                    "transcription": {"job_id": f"transcription-{video_id}"},
                    "analysis": {"job_id": f"analysis-{video_id}"},
                },
                "timing": {"local": {"command_total_ms": 1_000}},
                "plan_execution": {
                    "disposition": (
                        "already-complete" if video_id == "fNk_zzaMoSs" else "executed"
                    )
                },
            }

        output = io.StringIO()
        with patch("queued_authoring.operator_client", return_value=control), patch(
            "queued_authoring.verified_json_result", return_value=plan
        ), patch(
            "queued_authoring.validate_project_processing_plan"
        ), patch(
            "queued_authoring.run_youtube_video_pipeline", side_effect=execute
        ):
            with redirect_stdout(output):
                self.assertEqual(queued_authoring.run_process_project(args), 0)
        result = output.getvalue()
        self.assertIn('"selected_items": 2', result)
        self.assertIn('"succeeded": 2', result)
        self.assertIn('"already_complete": 1', result)
        self.assertIn('"concurrency": 2', result)

    def test_result_parser_exposes_separate_control_and_artifact_credentials(self):
        args = build_parser().parse_args([
            "queue", "result",
            "--operator-token-source", "keychain",
            "--r2-credentials-source", "environment",
            "job-1",
        ])
        self.assertEqual(args.queue_command, "result")
        self.assertEqual(args.operator_token_source, "keychain")
        self.assertEqual(args.r2_credentials_source, "environment")
        self.assertIsNone(args.output)

    def test_empty_command_prints_help_instead_of_an_argument_error(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main([]), 0)
        self.assertIn("queue", output.getvalue())
        self.assertIn("watchcraft-author queue --help", output.getvalue())

    def test_operator_token_prefers_environment_without_reading_keychain(self):
        with patch.dict(os.environ, {"WATCHCRAFT_AUTHORING_OPERATOR_TOKEN": "a" * 64}):
            with patch("queued_authoring.subprocess.run") as run:
                self.assertEqual(queued_authoring.operator_token(), "a" * 64)
                run.assert_not_called()

    def test_operator_token_source_can_require_the_environment(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "WATCHCRAFT_AUTHORING_OPERATOR_TOKEN"):
                queued_authoring.operator_token("environment")

    def test_operator_token_is_retrieved_from_the_stable_keychain_item(self):
        with patch.dict(
            os.environ,
            {"WATCHCRAFT_AUTHORING_OPERATOR_TOKEN": "a" * 64},
            clear=True,
        ):
            with patch("queued_authoring.subprocess.run") as run:
                run.return_value = Mock(stdout="b" * 64 + "\n")
                token = queued_authoring.operator_token("keychain")
        self.assertEqual(token, "b" * 64)
        self.assertIn("Watchcraft authoring operator token", run.call_args.args[0])

    def test_registry_admin_token_uses_a_separate_keychain_item(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("queued_authoring.subprocess.run") as run:
                run.return_value = Mock(stdout="d" * 64 + "\n")
                token = queued_authoring.registry_admin_token("keychain")
        self.assertEqual(token, "d" * 64)
        self.assertIn("Watchcraft authoring registry admin token", run.call_args.args[0])

    def test_r2_reader_credentials_support_environment_and_keychain_sources(self):
        environment = {
            "WATCHCRAFT_R2_READER_ACCESS_KEY_ID": "environment-access",
            "WATCHCRAFT_R2_READER_SECRET_ACCESS_KEY": "environment-secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(
                queued_authoring.r2_reader_credentials("environment"),
                ("environment-access", "environment-secret"),
            )
            with patch(
                "queued_authoring.keychain_password",
                side_effect=("keychain-access", "keychain-secret"),
            ):
                self.assertEqual(
                    queued_authoring.r2_reader_credentials("keychain"),
                    ("keychain-access", "keychain-secret"),
                )

        staging_environment = {
            "WATCHCRAFT_R2_STAGING_ACCESS_KEY_ID": "staging-access",
            "WATCHCRAFT_R2_STAGING_SECRET_ACCESS_KEY": "staging-secret",
        }
        with patch.dict(os.environ, staging_environment, clear=True):
            self.assertEqual(
                queued_authoring.r2_staging_credentials("environment"),
                ("staging-access", "staging-secret"),
            )

    def test_lexical_analysis_is_deterministic_and_not_a_transcript_artifact(self):
        job = {
            "job_id": "job-1",
            "spec_sha256": "a" * 64,
            "spec": {
                "source": {"media_asset_id": "lesson-1"},
                "configuration": {
                    "title": "Color workflow",
                    "text": "Color balance improves color. Exposure balance follows.",
                    "max_topics": 3,
                },
            },
        }
        result = queued_authoring.lexical_analysis(job)
        self.assertEqual(result["kind"], "watchcraft.analysis.lexical")
        self.assertEqual(result["topics"], ["balance", "color", "exposure"])
        self.assertNotIn("segments", result)

    def test_queued_educational_analysis_uses_the_existing_analysis_core(self):
        reference = transcript_reference()
        metadata = youtube_metadata()
        spec = queued_authoring.educational_video_analysis_spec(
            source={"media_asset_id": metadata["source_id"]},
            transcript=reference,
            source_metadata=metadata,
            video="WPtpUu3uIUI.youtube",
        )
        job = {
            "job_id": "analysis-job-1",
            "spec_sha256": "a" * 64,
            "spec": spec,
        }
        transcript = {
            "kind": "watchcraft.transcript",
            "schema_version": 1,
            "source": {"media_asset_id": metadata["source_id"]},
            "text": "Use a pinch grip and keep fingertips tucked.",
            "segments": [{
                "start": 0.0,
                "end": 4.0,
                "text": "Use a pinch grip and keep fingertips tucked.",
            }],
        }
        generated = {
            "schema_version": 2,
            "video": "WPtpUu3uIUI.youtube",
            "title": "Safe knife grip",
            "date": {
                "display": "August 19, 2026",
                "iso": "2026-08-19",
                "precision": "day",
                "confidence": 1.0,
                "basis": "YouTube publication date",
            },
            "locations": [],
            "summary": "A concise knife-safety lesson.",
            "topics": ["Pinch grip"],
            "sections": [{
                "start": "00:00:00",
                "end": "00:00:04",
                "title": "Grip and safety",
                "concepts": ["Pinch grip"],
                "description": "Demonstrates a safe grip.",
            }],
            "featured_techniques": [],
            "analysis_model": queued_authoring.EDUCATIONAL_VIDEO_ANALYSIS_MODEL,
            "analysis_prompt_version": 3,
            "analysis_created_at": "2026-09-05T00:00:00+00:00",
        }
        store = Mock()
        store.get_bytes.return_value = json.dumps(transcript).encode()
        client = Mock()
        with patch.object(
            queued_authoring.R2ArtifactStore,
            "from_environment",
            return_value=store,
        ):
            with patch("analyze_catalog.create_openai_client", return_value=client):
                with patch(
                    "analyze_catalog.generate_analysis",
                    return_value=generated,
                ) as analyze:
                    with patch(
                        "queued_authoring.time.monotonic",
                        side_effect=(0.0, 0.1, 0.2, 1.0, 1.2, 1.3, 3.8, 4.0),
                    ):
                        result = queued_authoring.educational_video_analysis(job)
        store.get_bytes.assert_called_once_with(reference)
        analyze.assert_called_once()
        self.assertEqual(analyze.call_args.kwargs["client"], client)
        self.assertEqual(analyze.call_args.kwargs["source_metadata"], metadata)
        self.assertEqual(analyze.call_args.args[0], transcript)
        self.assertEqual(result["title"], generated["title"])
        self.assertEqual(result["sections"], generated["sections"])
        self.assertEqual(result["provenance"]["transcript"], reference)
        self.assertEqual(result["provenance"]["timing"], {
            "dependency_resolution_ms": 100,
            "input_fetch_ms": 200,
            "analysis_ms": 2500,
            "handler_ms": 4000,
        })

    def test_queued_educational_analysis_resolves_a_job_output_dependency(self):
        reference = transcript_reference()
        metadata = youtube_metadata()
        dependency = {
            "kind": "job-output",
            "job_id": "transcription-job-1",
            "artifact_kind": "transcript",
            "schema": {"id": "watchcraft.transcript", "version": 1},
        }
        spec = queued_authoring.educational_video_analysis_spec(
            source={"media_asset_id": metadata["source_id"]},
            transcript=dependency,
            source_metadata=metadata,
            video="WPtpUu3uIUI.youtube",
        )
        job = {
            "job_id": "analysis-job-1",
            "run_id": "pipeline-run-1",
            "spec_sha256": "a" * 64,
            "spec": spec,
        }
        transcript = {
            "kind": "watchcraft.transcript",
            "schema_version": 1,
            "source": {"media_asset_id": metadata["source_id"]},
            "text": "Use a pinch grip.",
            "segments": [{"start": 0.0, "end": 1.0, "text": "Use a pinch grip."}],
        }
        generated = {
            "schema_version": 2,
            "video": "WPtpUu3uIUI.youtube",
            "title": "Safe knife grip",
            "summary": "A concise lesson.",
            "topics": ["Pinch grip"],
            "sections": [{"title": "Grip"}],
            "featured_techniques": [],
        }
        control = Mock()
        control.post.return_value = {
            "job": {
                "job_id": dependency["job_id"],
                "run_id": job["run_id"],
                "state": "succeeded",
                "result": reference,
            }
        }
        store = Mock()
        store.get_bytes.return_value = json.dumps(transcript).encode()
        with patch("queued_authoring.worker_client", return_value=control):
            with patch.object(
                queued_authoring.R2ArtifactStore,
                "from_environment",
                return_value=store,
            ):
                with patch("analyze_catalog.create_openai_client"):
                    with patch("analyze_catalog.generate_analysis", return_value=generated):
                        result = queued_authoring.educational_video_analysis(job)
        control.post.assert_called_once_with(
            "/jobs/get", {"job_id": dependency["job_id"]}
        )
        store.get_bytes.assert_called_once_with(reference)
        self.assertEqual(
            result["provenance"]["transcription_job_id"],
            dependency["job_id"],
        )
        self.assertEqual(result["provenance"]["transcript"], reference)

    def test_collection_terminology_resolution_binds_raw_and_draft_evidence(self):
        transcript_artifact = transcript_reference()
        analysis_artifact = {
            **transcript_artifact,
            "digest": "e" * 64,
            "artifact_kind": "analysis",
            "schema": queued_authoring.VIDEO_ANALYSIS_SCHEMA,
            "key": "objects/sha256/ee/" + "e" * 62,
        }
        project = {
            "project_id": "linear-algebra",
            "revision": 2,
            "metadata": {"title": "Essence of linear algebra"},
        }
        plan_reference = {
            **transcript_artifact,
            "digest": "f" * 64,
            "artifact_kind": "project-processing-plan",
            "schema": queued_authoring.PROJECT_PROCESSING_PLAN_SCHEMA,
            "key": "objects/sha256/ff/" + "f" * 62,
        }
        binding = {
            "item_id": "youtube:lesson",
            "source_title": "Linear combinations and basis vectors",
            "video": "lesson.youtube",
            "transcript_digest": transcript_artifact["digest"],
            "analysis_digest": analysis_artifact["digest"],
        }
        checkpoint_artifact = {
            **transcript_artifact,
            "digest": "9" * 64,
            "artifact_kind": "terminology-resolution-checkpoint",
            "schema": queued_authoring.TERMINOLOGY_RESOLUTION_CHECKPOINT_SCHEMA,
            "key": "objects/sha256/99/" + "9" * 62,
        }
        spec = queued_authoring.project_terminology_resolution_spec(
            project=project,
            plan_job_id="plan-job",
            plan_reference=plan_reference,
            plan={"plan_hash": "a" * 64},
            transcript_references=[transcript_artifact],
            analysis_references=[analysis_artifact],
            bindings=[binding],
            resume_checkpoint=checkpoint_artifact,
        )
        transcript = {
            "kind": "watchcraft.transcript",
            "schema_version": 1,
            "source": {"media_asset_id": "youtube:lesson"},
            "text": "The basis vectors are i hat and j hat.",
            "segments": [{"start": 0.0, "end": 2.0, "text": "The basis vectors."}],
        }
        analysis = {
            "schema_version": 2,
            "video": "lesson.youtube",
            "title": "Basis vectors",
            "summary": "The basis vectors are i_hat and j_hat.",
            "topics": ["i_hat", "j_hat"],
            "sections": [{"concepts": ["basis vectors"]}],
            "provenance": {"transcript": transcript_artifact},
        }
        payloads = {
            transcript_artifact["key"]: json.dumps(transcript).encode(),
            analysis_artifact["key"]: json.dumps(analysis).encode(),
            checkpoint_artifact["key"]: json.dumps({
                "kind": "watchcraft.terminology-resolution-checkpoint"
            }).encode(),
        }
        store = Mock()
        store.get_bytes.side_effect = lambda reference: payloads[reference["key"]]
        context = Mock()
        context.artifact_store.return_value = store
        context.latest_checkpoint.return_value = None
        inferred = {
            "source_hash": "b" * 64,
            "observed_terms": 3,
            "resolutions": [{
                "resolution_id": "term-123456789abc",
                "observed_forms": ["i_hat"],
                "canonical_term": "i-hat",
                "display_label": "i-hat",
                "classification": "orthographic-normalization",
                "confidence": 0.99,
                "rationale": "Normalize mathematical notation.",
                "affected_items": ["youtube:lesson"],
                "evidence": ["topic:i_hat"],
                "alternatives": [],
                "disposition": "automatic-safe",
            }],
        }
        job = {
            "job_id": "terminology-job",
            "spec_sha256": "c" * 64,
            "spec": spec,
        }
        def infer_with_progress(**kwargs):
            kwargs["report_progress"](0, 1, "batch 1")
            kwargs["report_progress"](1, 1, "complete")
            return inferred

        with patch("analyze_catalog.create_openai_client", return_value=Mock()), patch(
            "resolve_terminology.infer_terminology_resolution",
            side_effect=infer_with_progress,
        ) as resolve:
            result = queued_authoring.collection_terminology_resolution(job, context)

        resolve.assert_called_once()
        self.assertEqual(
            resolve.call_args.kwargs["resume_checkpoint"],
            {"kind": "watchcraft.terminology-resolution-checkpoint"},
        )
        self.assertEqual(result["kind"], "watchcraft.terminology-resolution")
        self.assertEqual(result["stats"], {
            "observed_terms": 3,
            "proposed_changes": 1,
            "automatic_safe": 1,
            "needs_review": 0,
        })
        self.assertEqual(
            result["provenance"]["items"][0]["transcript"], transcript_artifact
        )
        self.assertEqual(context.report_progress.call_count, 3)

    def test_new_terminology_handler_imports_the_previous_completed_checkpoint(self):
        plan_reference = {
            **transcript_reference(),
            "digest": "f" * 64,
            "artifact_kind": "project-processing-plan",
            "schema": queued_authoring.PROJECT_PROCESSING_PLAN_SCHEMA,
            "key": "objects/sha256/ff/" + "f" * 62,
        }
        checkpoint_reference = {
            **transcript_reference(),
            "digest": "9" * 64,
            "artifact_kind": "terminology-resolution-checkpoint",
            "schema": queued_authoring.TERMINOLOGY_RESOLUTION_CHECKPOINT_SCHEMA,
            "key": "objects/sha256/99/" + "9" * 62,
        }
        control = Mock()
        control.post.return_value = {
            "jobs": [{
                "spec": {
                    "handler": {
                        "id": queued_authoring.PREVIOUS_TERMINOLOGY_RESOLUTION_HANDLER[0],
                        "version": queued_authoring.PREVIOUS_TERMINOLOGY_RESOLUTION_HANDLER[1],
                    }
                },
                "spec_sha256": "a" * 64,
                "attempts": [{
                    "checkpoint": {
                        "sequence": 27,
                        "spec_sha256": "a" * 64,
                        "artifact": checkpoint_reference,
                    }
                }],
            }]
        }

        checkpoint = queued_authoring.previous_terminology_checkpoint(
            control,
            plan_reference=plan_reference,
            project_id="linear-algebra",
        )

        self.assertEqual(checkpoint, (27, checkpoint_reference))
        self.assertEqual(control.post.call_args.args[0], "/pipelines/get")

    def test_terminology_resolution_summary_includes_local_ledger_and_worker_timing(self):
        artifact = transcript_reference()
        completed = {
            "job": {
                "job_id": "terminology-job",
                "state": "succeeded",
                "created_at": 1_000,
                "updated_at": 6_000,
                "result": artifact,
                "dispatch": {"requested_at": 2_000},
                "attempts": [{
                    "state": "succeeded",
                    "started_at": 3_000,
                    "updated_at": 5_500,
                }],
            },
            "run": {"run_id": "terminology-run"},
        }
        resolution = {
            "project": {"project_id": "linear-algebra", "revision": 2},
            "stats": {"observed_terms": 2, "proposed_changes": 2},
            "resolutions": [
                {
                    "observed_forms": ["i_hat"],
                    "canonical_term": "i-hat",
                    "display_label": "i-hat",
                    "confidence": 0.99,
                    "disposition": "automatic-safe",
                },
                {
                    "observed_forms": ["j_hat"],
                    "canonical_term": "j-hat",
                    "display_label": "j-hat",
                    "confidence": 0.75,
                    "disposition": "needs-review",
                    "alternatives": ["y-hat"],
                    "affected_items": ["youtube:lesson"],
                    "rationale": "The audio is ambiguous.",
                },
            ],
            "provenance": {
                "timing": {
                    "dependency_fetch_ms": 100,
                    "resolution_ms": 4_000,
                    "handler_ms": 4_200,
                }
            },
        }

        summary = queued_authoring.compact_terminology_resolution_result(
            completed,
            resolution,
            local_timing={"command_total_ms": 5_500},
        )

        self.assertEqual(summary["job_id"], "terminology-job")
        self.assertEqual(summary["run_id"], "terminology-run")
        self.assertEqual(summary["automatic_safe"][0]["canonical_term"], "i-hat")
        self.assertEqual(summary["needs_review"][0]["alternatives"], ["y-hat"])
        self.assertEqual(summary["timing"]["local"]["command_total_ms"], 5_500)
        self.assertEqual(summary["timing"]["ledger"]["worker_attempt_ms"], 2_500)
        self.assertEqual(summary["timing"]["worker"]["resolution_ms"], 4_000)

    def test_mlx_smoke_transcribes_a_temporary_generated_audio_fixture(self):
        transcription_smoke_spec = queued_authoring.transcription_smoke_spec(
            "Watchcraft verifies audio."
        )
        job = {
            "job_id": "job-mlx",
            "spec_sha256": "a" * 64,
            "spec": transcription_smoke_spec,
        }
        mlx_whisper = Mock()
        mlx_whisper.transcribe.return_value = {
            "language": "en",
            "segments": [{"start": 0.0, "end": 1.0, "text": " Watchcraft verifies audio."}],
        }
        with patch.dict(sys.modules, {"mlx_whisper": mlx_whisper}):
            with patch("queued_authoring.subprocess.run") as run:
                result = queued_authoring.mlx_transcription_smoke(job)
        run.assert_called_once()
        generated_path = Path(run.call_args.args[0][4])
        self.assertEqual(run.call_args.args[0][:5], ["say", "-r", "155", "-o", str(generated_path)])
        self.assertFalse(generated_path.exists())
        mlx_whisper.transcribe.assert_called_once()
        self.assertEqual(result["kind"], "watchcraft.transcript")
        self.assertEqual(result["text"], "Watchcraft verifies audio.")
        self.assertFalse(result["provenance"]["audio_retained"])
        self.assertEqual(transcription_smoke_spec["artifact_kind"], "transcript")

    def test_https_audio_download_is_bounded_and_verified_before_use(self):
        payload = b"verified remote audio"

        class Response(io.BytesIO):
            def __init__(self, value):
                super().__init__(value)
                self.headers = {"Content-Length": str(len(value))}

            def geturl(self):
                return "https://fixtures.example/audio.flac"

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "audio.flac"
            with patch(
                "queued_authoring.urllib.request.urlopen",
                return_value=Response(payload),
            ):
                result = queued_authoring.download_verified_https(
                    "https://fixtures.example/audio.flac",
                    destination,
                    expected_sha256=queued_authoring.sha256_hex(payload),
                    expected_bytes=len(payload),
                    maximum_bytes=100,
                    timeout_seconds=30,
                )
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(result["digest"], queued_authoring.sha256_hex(payload))
            self.assertEqual(result["byte_length"], len(payload))

            bad_destination = Path(directory) / "bad.flac"
            with patch(
                "queued_authoring.urllib.request.urlopen",
                return_value=Response(payload),
            ):
                with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                    queued_authoring.download_verified_https(
                        "https://fixtures.example/audio.flac",
                        bad_destination,
                        expected_sha256="a" * 64,
                        expected_bytes=len(payload),
                        maximum_bytes=100,
                        timeout_seconds=30,
                    )
            self.assertFalse(bad_destination.exists())

            oversized_destination = Path(directory) / "oversized.flac"
            with patch(
                "queued_authoring.urllib.request.urlopen",
                return_value=Response(payload),
            ):
                with self.assertRaisesRegex(RuntimeError, "declares 21 bytes"):
                    queued_authoring.download_verified_https(
                        "https://fixtures.example/audio.flac",
                        oversized_destination,
                        expected_sha256=queued_authoring.sha256_hex(payload),
                        expected_bytes=20,
                        maximum_bytes=20,
                        timeout_seconds=30,
                    )
            self.assertFalse(oversized_destination.exists())

    def test_http_mlx_smoke_downloads_transcribes_and_discards_pinned_audio(self):
        job = {
            "job_id": "job-http-mlx",
            "spec_sha256": "a" * 64,
            "spec": queued_authoring.http_transcription_smoke_spec(),
        }
        acquisition = {
            "url": queued_authoring.HTTP_TRANSCRIPTION_SMOKE_URL,
            "algorithm": "sha256",
            "digest": queued_authoring.HTTP_TRANSCRIPTION_SMOKE_SHA256,
            "byte_length": queued_authoring.HTTP_TRANSCRIPTION_SMOKE_BYTES,
        }
        with patch(
            "queued_authoring.download_verified_https",
            return_value=acquisition,
        ) as download:
            with patch(
                "queued_authoring.mlx_transcribe_file",
                return_value={
                    "language": "en",
                    "text": "And so my fellow Americans.",
                    "segments": [{"start": 0.0, "end": 2.0, "text": "And so."}],
                },
            ) as transcribe:
                result = queued_authoring.mlx_http_transcription_smoke(job)
        audio_path = download.call_args.args[1]
        self.assertFalse(audio_path.exists())
        self.assertEqual(transcribe.call_args.args[0], audio_path)
        self.assertEqual(result["kind"], "watchcraft.transcript")
        self.assertEqual(result["provenance"]["acquisition"], acquisition)
        self.assertFalse(result["provenance"]["audio_retained"])

    def test_staged_mlx_handler_verifies_input_then_transcribes_temporary_audio(self):
        reference = staged_audio_reference()
        acquisition = staged_acquisition(reference)
        spec = queued_authoring.staged_transcription_spec(
            source={"media_asset_id": "youtube:WPtpUu3uIUI"},
            source_audio=reference,
            acquisition=acquisition,
        )
        job = {
            "job_id": "job-staged-mlx",
            "spec_sha256": "a" * 64,
            "spec": spec,
        }
        store = Mock()
        store.get_bytes.return_value = b"verified staged audio"
        with patch.object(
            queued_authoring.R2ArtifactStore,
            "from_environment",
            return_value=store,
        ):
            with patch(
                "queued_authoring.mlx_transcribe_file",
                return_value={
                    "language": "en",
                    "text": "Welcome to the hotel.",
                    "segments": [{"start": 0.0, "end": 2.0, "text": "Welcome."}],
                },
            ) as transcribe:
                with patch("queued_authoring.time.time", return_value=1_788_000_000):
                    with patch(
                        "queued_authoring.time.monotonic",
                        side_effect=(0.0, 1.0, 1.25, 1.5, 4.0, 4.1),
                    ):
                        result = queued_authoring.mlx_staged_transcription(job)
        audio_path = transcribe.call_args.args[0]
        self.assertFalse(audio_path.exists())
        self.assertEqual(
            transcribe.call_args.kwargs["model"],
            queued_authoring.PRODUCTION_TRANSCRIPTION_MODEL,
        )
        store.get_bytes.assert_called_once_with(reference)
        self.assertEqual(spec["source"], {"media_asset_id": "youtube:WPtpUu3uIUI"})
        self.assertEqual(
            spec["configuration"]["acquisition"]["source"]["canonical_url"],
            "https://www.youtube.com/watch?v=WPtpUu3uIUI",
        )
        self.assertEqual(result["provenance"]["acquisition"], acquisition)
        self.assertEqual(result["provenance"]["source_audio"], reference)
        self.assertFalse(result["provenance"]["worker_audio_retained"])
        self.assertEqual(result["provenance"]["timing"], {
            "input_fetch_ms": 250,
            "transcription_ms": 2500,
            "handler_ms": 4100,
        })

        wrong_model_job = {
            **job,
            "spec": {
                **spec,
                "configuration": {
                    **spec["configuration"],
                    "model": queued_authoring.TRANSCRIPTION_SMOKE_MODEL,
                },
            },
        }
        with self.assertRaisesRegex(ValueError, "requires.*large-v3-turbo-q4"):
            queued_authoring.mlx_staged_transcription(wrong_model_job)

    def test_staged_mlx_handler_rejects_expired_input_without_reading_r2(self):
        reference = staged_audio_reference(expires_at=1_788_000_000_000)
        job = {
            "job_id": "job-expired-staged-mlx",
            "spec_sha256": "a" * 64,
            "spec": queued_authoring.staged_transcription_spec(
                source={"media_asset_id": "youtube:WPtpUu3uIUI"},
                source_audio=reference,
                acquisition=staged_acquisition(reference),
            ),
        }
        store = Mock()
        with patch.object(
            queued_authoring.R2ArtifactStore,
            "from_environment",
            return_value=store,
        ):
            with patch("queued_authoring.time.time", return_value=1_788_000_001):
                with self.assertRaises(queued_authoring.StagedSourceError) as failure:
                    queued_authoring.mlx_staged_transcription(job)
        self.assertEqual(failure.exception.classification, "source_input_expired")
        self.assertFalse(failure.exception.retryable)
        store.get_bytes.assert_not_called()

    def test_python_r2_store_is_content_addressed_and_create_once(self):
        class MissingObject(Exception):
            response = {
                "ResponseMetadata": {"HTTPStatusCode": 404},
                "Error": {"Code": "NoSuchKey"},
            }

        class Body:
            def __init__(self, value):
                self.value = value

            def read(self):
                return self.value

        class S3:
            def __init__(self):
                self.objects = {}
                self.put_count = 0

            def head_object(self, *, Bucket, Key):
                if Key not in self.objects:
                    raise MissingObject()

            def put_object(self, *, Bucket, Key, Body, **kwargs):
                self.put_count += 1
                self.objects[Key] = Body

            def get_object(self, *, Bucket, Key):
                return {"Body": Body(self.objects[Key])}

            def delete_object(self, *, Bucket, Key):
                self.objects.pop(Key, None)

        s3 = S3()
        store = queued_authoring.R2ArtifactStore(s3, "test-bucket")
        description = {
            "artifact_kind": "analysis",
            "schema": {"id": "watchcraft.analysis.lexical", "version": 1},
        }
        first = store.put_json({"topics": ["color"]}, description)
        second = store.put_json({"topics": ["color"]}, description)
        self.assertEqual(second, first)
        self.assertEqual(s3.put_count, 1)
        self.assertRegex(first["key"], r"^objects/sha256/[a-f0-9]{2}/[a-f0-9]{62}$")
        s3.objects[first["key"]] = b"corrupt"
        with self.assertRaisesRegex(RuntimeError, "content verification"):
            store.get_bytes(first)

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.webm"
            source.write_bytes(b"temporary source audio")
            staged = store.put_staged_file(
                source,
                {
                    "artifact_kind": "source-audio",
                    "media_type": "audio/webm",
                    "schema": queued_authoring.SOURCE_AUDIO_SCHEMA,
                },
                acquisition_id="00000000-0000-4000-8000-000000000000",
                expires_at=2_000_000_000_000,
            )
        self.assertRegex(
            staged["key"],
            r"^staging/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}/sha256/[a-f0-9]{2}/[a-f0-9]{62}$",
        )
        self.assertEqual(staged["retention"]["class"], "ephemeral")
        self.assertEqual(store.get_bytes(staged), b"temporary source audio")
        store.delete(staged)
        self.assertNotIn(staged["key"], s3.objects)

    def test_dispatch_uses_the_approved_job_identifiers(self):
        job = {
            "job_id": "job-1",
            "revision": 3,
            "state": "ready",
            "spec_sha256": "a" * 64,
            "spec": {"registry_snapshot": registry_snapshot()},
        }
        pending = {
            **job,
            "revision": 4,
            "dispatch": {"generation": 1},
        }
        client = Mock()
        client.post.side_effect = [{"job": job, "run": {}}, pending]
        args = argparse.Namespace(
            queue_command="dispatch",
            job_id="job-1",
            operator_token_source="auto",
        )
        with patch("queued_authoring.operator_client", return_value=client):
            with patch("queued_authoring.subprocess.run") as run:
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(queued_authoring.run_queue_command(args), 0)
        command = run.call_args.args[0]
        self.assertIn("job_id=job-1", command)
        self.assertIn("spec_sha256=" + "a" * 64, command)
        self.assertIn("dispatch_generation=1", command)
        self.assertIn("expected_revision=4", command)
        self.assertEqual(command[3], "authoring-worker.yml")

    def test_dispatch_routes_mlx_transcription_to_the_macos_workflow(self):
        job = {
            "job_id": "job-mlx",
            "revision": 4,
            "state": "dispatch_pending",
            "spec_sha256": "a" * 64,
            "dispatch": {"generation": 1},
            "spec": {
                **queued_authoring.transcription_smoke_spec(),
                "registry_snapshot": registry_snapshot(transcription=True),
            },
        }
        client = Mock()
        with patch("queued_authoring.subprocess.run") as run:
            queued_authoring.dispatch_submission(client, job)
        command = run.call_args.args[0]
        self.assertEqual(command[3], "authoring-mlx-worker.yml")
        self.assertIn("model_cache_key=whisper-tiny-mlx", command)
        client.post.assert_not_called()

        reference = staged_audio_reference()
        production_job = {
            **job,
            "job_id": "job-production-mlx",
            "spec": {
                **queued_authoring.staged_transcription_spec(
                    source={"media_asset_id": "youtube:WPtpUu3uIUI"},
                    source_audio=reference,
                    acquisition=staged_acquisition(reference),
                ),
                "registry_snapshot": registry_snapshot(staged_transcription=True),
            },
        }
        with patch("queued_authoring.subprocess.run") as production_run:
            queued_authoring.dispatch_submission(client, production_job)
        self.assertIn(
            "model_cache_key=whisper-large-v3-turbo-q4",
            production_run.call_args.args[0],
        )

    def test_dispatch_rejects_an_unsafe_workflow_name(self):
        job = {"spec": {"registry_snapshot": registry_snapshot()}}
        job["spec"]["registry_snapshot"]["execution_profile"]["dispatcher"]["workflow"] = "../bad.yml"
        with self.assertRaisesRegex(RuntimeError, "unsafe"):
            queued_authoring.dispatch_workflow(job)

    def test_registry_commands_separate_operator_visibility_from_admin_changes(self):
        status = build_parser().parse_args(["queue", "registry-status"])
        self.assertEqual(status.operator_token_source, "auto")
        self.assertEqual(status.environment, "production")
        explicit = build_parser().parse_args([
            "queue", "registry-activate", "--registry-admin-token-source", "keychain",
            "--expected-revision", "0",
        ])
        self.assertEqual(explicit.expected_revision, 0)
        activate = build_parser().parse_args([
            "queue", "registry-activate", "--registry-admin-token-source", "keychain",
        ])
        self.assertIsNone(activate.expected_revision)
        self.assertEqual(activate.registry_admin_token_source, "keychain")
        self.assertEqual(activate.registry_file, queued_authoring.DEFAULT_REGISTRY_PATH)

        client = Mock()
        client.post.side_effect = [
            {
                "active": {
                    "environment": "production",
                    "revision": 2,
                },
                "registry": {},
            },
            {
                "registry_version": "2026-09-05.1",
                "revision": 3,
            },
        ]
        with patch("queued_authoring.registry_admin_client", return_value=client):
            activation_message = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(activation_message):
                self.assertEqual(queued_authoring.run_queue_command(activate), 0)
        self.assertIn("observed active-pointer revision 2", activation_message.getvalue())
        self.assertEqual(
            client.post.call_args_list[0].args,
            ("/registry/get-active", {"environment": "production"}),
        )
        path, payload = client.post.call_args_list[1].args
        self.assertEqual(path, "/registry/activate")
        self.assertEqual(payload["expected_revision"], 2)
        self.assertRegex(payload["registry_sha256"], r"^[a-f0-9]{64}$")

        override_client = Mock()
        override_client.post.return_value = {"registry_version": "2026-09-05.1"}
        with patch("queued_authoring.registry_admin_client", return_value=override_client):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(queued_authoring.run_queue_command(explicit), 0)
        self.assertEqual(override_client.post.call_count, 1)
        self.assertEqual(
            override_client.post.call_args.args[1]["expected_revision"],
            0,
        )

        no_active_registry = Mock()
        no_active_registry.post.return_value = {"active": None, "registry": None}
        self.assertEqual(
            queued_authoring.active_registry_revision(no_active_registry, "development"),
            0,
        )

    def test_cleanup_command_uses_admin_authority_and_exact_confirmation(self):
        client = Mock()
        client.post.return_value = {"run_id": "run-1", "deleted_jobs": 1}
        args = build_parser().parse_args([
            "queue", "cleanup-run", "run-1", "--confirm", "run-1",
        ])
        with patch("queued_authoring.registry_admin_client", return_value=client):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(queued_authoring.run_queue_command(args), 0)
        path, payload = client.post.call_args.args
        self.assertEqual(path, "/cleanup/purge-run")
        self.assertEqual(payload["confirmation"], "run-1")
        self.assertFalse(payload["allow_unmarked"])
        self.assertRegex(payload["command_id"], r"^[a-f0-9-]{36}$")

        orphan_client = Mock()
        orphan_client.post.return_value = {"job_id": "job-1", "deleted_job_events": 8}
        orphan_args = build_parser().parse_args([
            "queue", "cleanup-orphan-job", "job-1", "--confirm", "job-1",
        ])
        with patch("queued_authoring.registry_admin_client", return_value=orphan_client):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(queued_authoring.run_queue_command(orphan_args), 0)
        orphan_path, orphan_payload = orphan_client.post.call_args.args
        self.assertEqual(orphan_path, "/cleanup/purge-orphan-job")
        self.assertEqual(orphan_payload["confirmation"], "job-1")

    def test_one_command_analysis_smoke_runs_the_full_remote_ritual(self):
        result_document = {
            "kind": "watchcraft.analysis.lexical",
            "topics": ["color", "exposure"],
        }
        payload = queued_authoring.canonical_json(result_document).encode("utf-8")
        digest = queued_authoring.sha256_hex(payload)
        reference = {
            "store": "r2",
            "algorithm": "sha256",
            "digest": digest,
            "byte_length": len(payload),
            "media_type": "application/json",
            "artifact_kind": "analysis",
            "schema": {"id": "watchcraft.analysis.lexical", "version": 1},
            "key": f"objects/sha256/{digest[:2]}/{digest[2:]}",
        }
        submitted_job = {
            "job_id": "job-smoke",
            "run_id": "run-smoke",
            "revision": 2,
            "state": "awaiting_approval",
            "spec_sha256": "a" * 64,
            "spec": {
                **queued_authoring.analysis_spec(argparse.Namespace(
                    source_id="synthetic:lexical-analysis-smoke",
                    title="Watchcraft lexical smoke",
                    text="Balance exposure and color.",
                    max_topics=8,
                )),
                "registry_snapshot": registry_snapshot(),
            },
        }
        ready_job = {**submitted_job, "revision": 3, "state": "ready"}
        pending_job = {
            **ready_job,
            "revision": 4,
            "state": "dispatch_pending",
            "dispatch": {"generation": 1},
        }
        succeeded_job = {
            **pending_job,
            "revision": 8,
            "state": "succeeded",
            "result": reference,
        }
        client = Mock()

        def post(path, body):
            if path == "/submissions/submit":
                self.assertEqual(body["request"]["purpose"], "smoke")
                self.assertEqual(body["request"]["retention"]["class"], "ephemeral")
                return {"job": submitted_job, "run": {"run_id": "run-smoke"}}
            if path == "/submissions/approve":
                return {"job": ready_job, "run": {"run_id": "run-smoke"}}
            if path == "/submissions/request-dispatch":
                return pending_job
            if path == "/submissions/get":
                return {
                    "job": succeeded_job,
                    "run": {"run_id": "run-smoke", "state": "complete"},
                }
            raise AssertionError(path)

        client.post.side_effect = post
        reader = Mock()
        reader.get_bytes.return_value = payload
        args = build_parser().parse_args([
            "queue", "smoke-analysis", "--operator-token-source", "keychain",
            "--r2-credentials-source", "keychain",
        ])
        output = io.StringIO()
        with patch("queued_authoring.operator_client", return_value=client):
            with patch("queued_authoring.r2_artifact_reader", return_value=reader):
                with patch("queued_authoring.subprocess.run") as run:
                    with redirect_stdout(output):
                        self.assertEqual(queued_authoring.run_queue_command(args), 0)
        self.assertEqual(run.call_args.args[0][3], "authoring-worker.yml")
        self.assertIn('"state": "succeeded"', output.getvalue())
        reader.get_bytes.assert_called_once_with(reference)

    def test_one_command_http_transcription_smoke_binds_verified_remote_media(self):
        spec = {
            **queued_authoring.http_transcription_smoke_spec(),
            "registry_snapshot": registry_snapshot(http_transcription=True),
        }
        submitted_job = {
            "job_id": "job-http-smoke",
            "run_id": "run-http-smoke",
            "revision": 2,
            "state": "awaiting_approval",
            "spec_sha256": "a" * 64,
            "spec": spec,
        }
        ready_job = {**submitted_job, "revision": 3, "state": "ready"}
        pending_job = {
            **ready_job,
            "revision": 4,
            "state": "dispatch_pending",
            "dispatch": {"generation": 1},
        }
        completed_job = {
            **pending_job,
            "revision": 8,
            "state": "succeeded",
            "result": {"digest": "b" * 64},
        }
        completed = {
            "job": completed_job,
            "run": {"run_id": "run-http-smoke", "state": "complete"},
        }
        verified_result = {
            "kind": "watchcraft.transcript",
            "text": "And so my fellow Americans.",
            "segments": [{"text": "And so my fellow Americans."}],
            "provenance": {
                "handler_id": queued_authoring.HTTP_TRANSCRIPTION_SMOKE_HANDLER[0],
                "acquisition": {
                    "digest": queued_authoring.HTTP_TRANSCRIPTION_SMOKE_SHA256,
                    "byte_length": queued_authoring.HTTP_TRANSCRIPTION_SMOKE_BYTES,
                },
            },
        }
        control = Mock()
        control.post.return_value = {
            "job": ready_job,
            "run": {"run_id": "run-http-smoke"},
        }
        args = build_parser().parse_args([
            "queue", "smoke-transcription-http",
            "--operator-token-source", "keychain",
            "--r2-credentials-source", "keychain",
        ])
        with patch("queued_authoring.operator_client", return_value=control):
            with patch(
                "queued_authoring.submit_spec",
                return_value={
                    "job": submitted_job,
                    "run": {"run_id": "run-http-smoke"},
                },
            ) as submit:
                with patch(
                    "queued_authoring.dispatch_submission",
                    return_value=pending_job,
                ):
                    with patch(
                        "queued_authoring.wait_for_terminal_job",
                        return_value=completed,
                    ):
                        with patch(
                            "queued_authoring.verified_json_result",
                            return_value=verified_result,
                        ):
                            with redirect_stdout(io.StringIO()):
                                self.assertEqual(
                                    queued_authoring.run_queue_command(args),
                                    0,
                                )
        submitted_request = submit.call_args.kwargs["request"]
        submitted_spec = submit.call_args.kwargs["spec"]
        self.assertEqual(submitted_request["purpose"], "smoke")
        self.assertEqual(
            submitted_spec["configuration"]["expected_sha256"],
            queued_authoring.HTTP_TRANSCRIPTION_SMOKE_SHA256,
        )
        self.assertEqual(
            submitted_spec["handler"]["id"],
            queued_authoring.HTTP_TRANSCRIPTION_SMOKE_HANDLER[0],
        )

    def test_youtube_smoke_and_production_commands_bind_distinct_handlers(self):
        cases = (
            (
                "smoke-transcription-youtube",
                queued_authoring.STAGED_TRANSCRIPTION_SMOKE_HANDLER,
                queued_authoring.TRANSCRIPTION_SMOKE_MODEL,
                True,
            ),
            (
                "transcribe-youtube",
                queued_authoring.PRODUCTION_TRANSCRIPTION_HANDLER,
                queued_authoring.PRODUCTION_TRANSCRIPTION_MODEL,
                False,
            ),
        )
        for command, expected_handler, expected_model, smoke in cases:
            with self.subTest(command=command):
                reference = staged_audio_reference()
                staging = Mock()
                staging.put_staged_file.return_value = reference
                captured = {}

                def submit(_control, *, request, spec):
                    resolved_spec = {
                        **spec,
                        "registry_snapshot": registry_snapshot(
                            staged_smoke=smoke,
                            staged_transcription=not smoke,
                        ),
                    }
                    job = {
                        "job_id": f"job-{command}",
                        "run_id": f"run-{command}",
                        "revision": 2,
                        "state": "awaiting_approval",
                        "spec_sha256": "a" * 64,
                        "spec": resolved_spec,
                    }
                    captured.update(request=request, spec=resolved_spec, job=job)
                    return {"job": job, "run": {"run_id": job["run_id"]}}

                control = Mock()

                def control_post(path, payload):
                    if path != "/submissions/approve":
                        raise AssertionError(path)
                    self.assertEqual(
                        payload["actor"],
                        "watchcraft-author-cli:smoke"
                        if smoke
                        else "watchcraft-author-cli",
                    )
                    ready = {**captured["job"], "revision": 3, "state": "ready"}
                    captured["ready"] = ready
                    return {"job": ready}

                def dispatch(_control, ready):
                    pending = {
                        **ready,
                        "revision": 4,
                        "state": "dispatch_pending",
                        "dispatch": {"generation": 1},
                    }
                    captured["pending"] = pending
                    return pending

                def wait(_control, job_id, timeout_seconds):
                    self.assertEqual(job_id, captured["job"]["job_id"])
                    self.assertGreater(timeout_seconds, 0)
                    return {
                        "job": {
                            **captured["pending"],
                            "revision": 8,
                            "state": "succeeded",
                            "result": {"digest": "c" * 64},
                            "created_at": 1_000,
                            "updated_at": 5_500,
                            "dispatch": {
                                "generation": 1,
                                "requested_at": 2_000,
                            },
                            "attempts": [{
                                "state": "succeeded",
                                "started_at": 2_750,
                                "updated_at": 5_250,
                            }],
                        },
                        "run": {
                            "run_id": captured["job"]["run_id"],
                            "state": "complete",
                        },
                    }

                verified_result = {
                    "kind": "watchcraft.transcript",
                    "source": {"media_asset_id": "youtube:WPtpUu3uIUI"},
                    "model": expected_model,
                    "language": "en",
                    "text": "Welcome to the hotel.",
                    "segments": [{"text": "Welcome to the hotel."}],
                    "provenance": {
                        "handler_id": expected_handler[0],
                        "source_audio": reference,
                        "acquisition": {
                            "media": {"duration_seconds": 120.0},
                        },
                        "timing": {
                            "input_fetch_ms": 100,
                            "transcription_ms": 2_000,
                            "handler_ms": 2_200,
                        },
                    },
                }
                args = build_parser().parse_args([
                    "queue", command,
                    "--operator-token-source", "keychain",
                    "--r2-credentials-source", "keychain",
                    "--r2-staging-credentials-source", "keychain",
                    "https://www.youtube.com/shorts/WPtpUu3uIUI",
                ])
                acquisition_result = {
                    "provider": "youtube",
                    "video_id": "WPtpUu3uIUI",
                    "canonical_url": "https://www.youtube.com/watch?v=WPtpUu3uIUI",
                    "yt_dlp_version": "2026.08.19",
                    "format_id": "251",
                    "audio_language": "en",
                    "container": "webm",
                    "duration_seconds": 120.0,
                    "algorithm": "sha256",
                    "digest": reference["digest"],
                    "byte_length": reference["byte_length"],
                }
                control.post.side_effect = control_post
                with patch("queued_authoring.operator_client", return_value=control):
                    with patch("queued_authoring.r2_staging_writer", return_value=staging):
                        with patch(
                            "queued_authoring.download_youtube_audio",
                            return_value=acquisition_result,
                        ) as download:
                            with patch("queued_authoring.submit_spec", side_effect=submit):
                                with patch(
                                    "queued_authoring.dispatch_submission",
                                    side_effect=dispatch,
                                ):
                                    with patch(
                                        "queued_authoring.wait_for_terminal_job",
                                        side_effect=wait,
                                    ):
                                        with patch(
                                            "queued_authoring.verified_json_result",
                                            return_value=verified_result,
                                        ):
                                            output = io.StringIO()
                                            with redirect_stdout(output):
                                                self.assertEqual(
                                                    queued_authoring.run_queue_command(args),
                                                    0,
                                                )
                download.assert_called_once()
                self.assertEqual(
                    download.call_args.kwargs["maximum_bytes"],
                    queued_authoring.YOUTUBE_TRANSCRIPTION_SMOKE_MAX_BYTES
                    if smoke
                    else queued_authoring.YOUTUBE_TRANSCRIPTION_MAX_BYTES,
                )
                staging.put_staged_file.assert_called_once()
                staging.delete.assert_called_once_with(reference)
                self.assertEqual(
                    captured["spec"]["source"],
                    {"media_asset_id": "youtube:WPtpUu3uIUI"},
                )
                self.assertEqual(captured["spec"]["inputs"], [reference])
                self.assertEqual(captured["spec"]["handler"]["id"], expected_handler[0])
                self.assertEqual(captured["spec"]["configuration"]["model"], expected_model)
                self.assertGreaterEqual(
                    captured["spec"]["configuration"]["acquisition"]["timing"]["acquisition_ms"],
                    0,
                )
                self.assertIn('"submitted_to_completed_ms": 4500', output.getvalue())
                self.assertIn('"transcription_ms": 2000', output.getvalue())
                self.assertIn("(worker transcription 2s)", output.getvalue())
                self.assertIn("Full transcript:", output.getvalue())
                self.assertNotIn('"segments": [', output.getvalue())
                if smoke:
                    self.assertEqual(captured["request"]["purpose"], "smoke")
                else:
                    self.assertNotIn("purpose", captured["request"])
                    self.assertNotIn("retention", captured["request"])

    def test_process_youtube_runs_dependent_transcription_and_analysis_jobs(self):
        reference = staged_audio_reference()
        transcript_artifact = transcript_reference()
        analysis_digest = "e" * 64
        analysis_artifact = {
            **transcript_artifact,
            "digest": analysis_digest,
            "artifact_kind": "analysis",
            "schema": queued_authoring.VIDEO_ANALYSIS_SCHEMA,
            "key": f"objects/sha256/{analysis_digest[:2]}/{analysis_digest[2:]}",
        }
        staging = Mock()
        staging.put_staged_file.return_value = reference
        control = Mock()
        captured = {}

        def submit(_control, *, request, jobs):
            captured.update(request=request, jobs=jobs)
            submitted_jobs = [{
                "job_id": candidate["job_id"],
                "run_id": "pipeline-run-1",
                "revision": 2,
                "state": "awaiting_approval",
                "spec_sha256": ("a" if index else "b") * 64,
                "spec": candidate["spec"],
            } for index, candidate in enumerate(jobs)]
            captured["submitted_jobs"] = submitted_jobs
            return {
                "jobs": submitted_jobs,
                "run": {
                    "run_id": "pipeline-run-1",
                    "revision": 2,
                    "state": "planned",
                    "approval_sha256": "c" * 64,
                },
            }

        def control_post(path, payload):
            self.assertEqual(path, "/pipelines/approve")
            return {
                "jobs": [
                    {**job, "revision": 3, "state": "ready"}
                    for job in captured["submitted_jobs"]
                ],
                "run": {"run_id": payload["run_id"], "state": "approved"},
            }

        def dispatch(_control, job):
            return {
                **job,
                "revision": 4,
                "state": "dispatch_pending",
                "dispatch": {"generation": 1},
            }

        def wait(_control, job_id, _timeout_seconds):
            transcription = job_id == captured["jobs"][0]["job_id"]
            return {
                "job": {
                    "job_id": job_id,
                    "run_id": "pipeline-run-1",
                    "state": "succeeded",
                    "result": transcript_artifact if transcription else analysis_artifact,
                    "created_at": 1_000,
                    "updated_at": 5_000 if transcription else 9_000,
                    "dispatch": {"requested_at": 2_000 if transcription else 6_000},
                    "attempts": [{
                        "state": "succeeded",
                        "started_at": 2_500 if transcription else 6_500,
                        "updated_at": 4_500 if transcription else 8_500,
                    }],
                },
                "run": {
                    "run_id": "pipeline-run-1",
                    "state": "running" if transcription else "complete",
                    "created_at": 1_000,
                    "updated_at": 9_000,
                },
            }

        def verified(job, _credential_source):
            if job["job_id"] == captured["jobs"][0]["job_id"]:
                return {
                    "kind": "watchcraft.transcript",
                    "source": {"media_asset_id": "youtube:WPtpUu3uIUI"},
                    "text": "Use a pinch grip.",
                    "segments": [{"text": "Use a pinch grip."}],
                    "model": queued_authoring.PRODUCTION_TRANSCRIPTION_MODEL,
                    "language": "en",
                    "provenance": {
                        "handler_id": queued_authoring.PRODUCTION_TRANSCRIPTION_HANDLER[0],
                        "timing": {"transcription_ms": 2_000},
                    },
                }
            return {
                "schema_version": 2,
                "video": "WPtpUu3uIUI.youtube",
                "title": "Knife skills",
                "summary": "A knife-skills lesson.",
                "topics": ["Pinch grip"],
                "sections": [{"title": "Grip"}],
                "featured_techniques": [],
                "analysis_model": queued_authoring.EDUCATIONAL_VIDEO_ANALYSIS_MODEL,
                "provenance": {
                    "handler_id": queued_authoring.EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0],
                    "transcription_job_id": captured["jobs"][0]["job_id"],
                    "transcript": transcript_artifact,
                    "timing": {"analysis_ms": 1_000},
                },
            }

        acquisition_result = {
            "provider": "youtube",
            "video_id": "WPtpUu3uIUI",
            "canonical_url": "https://www.youtube.com/watch?v=WPtpUu3uIUI",
            "yt_dlp_version": "2026.08.19",
            "format_id": "251",
            "audio_language": "en",
            "container": "webm",
            "duration_seconds": 120.0,
            "algorithm": "sha256",
            "digest": reference["digest"],
            "byte_length": reference["byte_length"],
        }
        args = build_parser().parse_args([
            "queue", "process-youtube",
            "--operator-token-source", "keychain",
            "--r2-credentials-source", "keychain",
            "--r2-staging-credentials-source", "keychain",
            "WPtpUu3uIUI",
        ])
        control.post.side_effect = control_post
        output = io.StringIO()
        with patch("queued_authoring.operator_client", return_value=control), patch(
            "queued_authoring.r2_staging_writer", return_value=staging
        ), patch(
            "queued_authoring.download_youtube_audio", return_value=acquisition_result
        ), patch(
            "queued_authoring.youtube_source_metadata", return_value=youtube_metadata()
        ), patch(
            "queued_authoring.submit_pipeline", side_effect=submit
        ), patch(
            "queued_authoring.dispatch_submission", side_effect=dispatch
        ), patch(
            "queued_authoring.wait_for_terminal_job", side_effect=wait
        ), patch(
            "queued_authoring.verified_json_result", side_effect=verified
        ):
            with redirect_stdout(output):
                self.assertEqual(queued_authoring.run_queue_command(args), 0)
        self.assertEqual(captured["request"]["stages"], [
            "transcription",
            "educational-video-analysis",
        ])
        dependency = captured["jobs"][1]["spec"]["dependencies"][0]
        self.assertEqual(dependency["kind"], "job-output")
        self.assertEqual(dependency["job_id"], captured["jobs"][0]["job_id"])
        staging.delete.assert_called_once_with(reference)
        self.assertIn("completed run pipeline-run-1", output.getvalue())
        self.assertIn('"run_created_to_completed_ms": 8000', output.getvalue())
        self.assertIn('"submission_to_dispatch_ms": 1000', output.getvalue())
        self.assertIn('"dispatch_to_worker_ms": 500', output.getvalue())
        self.assertIn('"worker_attempt_ms": 2000', output.getvalue())
        self.assertIn("Full transcript:", output.getvalue())
        self.assertIn("Full analysis:", output.getvalue())

    def test_project_item_execution_resumes_the_same_completed_pipeline(self):
        plan_hash = "c" * 64
        item_id = "youtube:WPtpUu3uIUI"
        execution = {
            "plan_job_id": "plan-job-1",
            "plan_artifact_sha256": "d" * 64,
            "plan_hash": plan_hash,
            "project_id": "project-1",
            "project_revision": 2,
            "item_id": item_id,
            "logical_tasks": {
                "metadata-enrichment": "metadata-task",
                "source-acquisition": "acquisition-task",
                "transcription": "transcription-task",
                "analysis": "analysis-task",
            },
        }
        run_id = queued_authoring.stable_project_execution_id(
            execution["plan_artifact_sha256"], item_id, "run"
        )
        transcription_job_id = queued_authoring.stable_project_execution_id(
            execution["plan_artifact_sha256"], item_id, "transcription"
        )
        analysis_job_id = queued_authoring.stable_project_execution_id(
            execution["plan_artifact_sha256"], item_id, "analysis"
        )
        source = {"media_asset_id": item_id}
        reference = staged_audio_reference()
        acquisition = staged_acquisition(reference)
        transcription_spec = queued_authoring.staged_transcription_spec(
            source=source,
            source_audio=reference,
            acquisition=acquisition,
            handler=queued_authoring.PRODUCTION_TRANSCRIPTION_HANDLER,
        )
        analysis_spec = queued_authoring.educational_video_analysis_spec(
            source=source,
            transcript={
                "kind": "job-output",
                "job_id": transcription_job_id,
                "artifact_kind": "transcript",
                "schema": {"id": "watchcraft.transcript", "version": 1},
            },
            source_metadata=youtube_metadata(),
            video="WPtpUu3uIUI.youtube",
        )
        transcript_artifact = transcript_reference()
        analysis_artifact = {
            **transcript_artifact,
            "digest": "e" * 64,
            "artifact_kind": "analysis",
            "schema": queued_authoring.VIDEO_ANALYSIS_SCHEMA,
            "key": "objects/sha256/ee/" + "e" * 62,
        }
        request = {
            "kind": "project-item-processing",
            "plan_job_id": execution["plan_job_id"],
            "plan_artifact_sha256": execution["plan_artifact_sha256"],
            "plan_hash": plan_hash,
            "project_id": execution["project_id"],
            "project_revision": 2,
            "item_id": item_id,
            "logical_tasks": execution["logical_tasks"],
            "source_id": item_id,
            "stages": ["transcription", "educational-video-analysis"],
        }
        run = {
            "run_id": run_id,
            "request": request,
            "state": "complete",
            "created_at": 1_000,
            "updated_at": 9_000,
        }
        jobs = [
            {
                "job_id": transcription_job_id,
                "state": "succeeded",
                "spec": transcription_spec,
                "result": transcript_artifact,
            },
            {
                "job_id": analysis_job_id,
                "state": "succeeded",
                "spec": analysis_spec,
                "result": analysis_artifact,
            },
        ]
        control = Mock()
        control.post.return_value = {"run": run, "jobs": jobs}
        staging = Mock()

        def wait(_control, job_id, _timeout):
            job = next(candidate for candidate in jobs if candidate["job_id"] == job_id)
            return {"job": job, "run": run}

        def verified(job, _source):
            if job["job_id"] == transcription_job_id:
                return {
                    "kind": "watchcraft.transcript",
                    "text": "Use a pinch grip.",
                    "segments": [{"text": "Use a pinch grip."}],
                    "provenance": {
                        "handler_id": queued_authoring.PRODUCTION_TRANSCRIPTION_HANDLER[0],
                    },
                }
            return {
                "schema_version": 2,
                "video": "WPtpUu3uIUI.youtube",
                "summary": "A knife-skills lesson.",
                "provenance": {
                    "handler_id": queued_authoring.EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0],
                    "transcription_job_id": transcription_job_id,
                    "transcript": transcript_artifact,
                },
            }

        args = build_parser().parse_args([
            "queue", "process-youtube", "WPtpUu3uIUI",
            "--r2-staging-credentials-source", "keychain",
            "--r2-credentials-source", "keychain",
        ])
        with patch("queued_authoring.operator_client", return_value=control), patch(
            "queued_authoring.r2_staging_writer", return_value=staging
        ), patch(
            "queued_authoring.download_youtube_audio"
        ) as download, patch(
            "queued_authoring.youtube_source_metadata"
        ) as metadata, patch(
            "queued_authoring.submit_pipeline"
        ) as submit, patch(
            "queued_authoring.wait_for_terminal_job", side_effect=wait
        ), patch(
            "queued_authoring.verified_json_result", side_effect=verified
        ):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    queued_authoring.run_youtube_video_pipeline(
                        args, project_execution=execution
                    ),
                    0,
                )
        control.post.assert_called_once_with("/pipelines/get", {"run_id": run_id})
        download.assert_not_called()
        metadata.assert_not_called()
        submit.assert_not_called()
        staging.delete.assert_called_once_with(reference)

    def test_analyze_transcript_runs_existing_analysis_as_a_dependent_job(self):
        transcript = transcript_reference()
        metadata = youtube_metadata()
        transcription_job = {
            "job_id": "transcription-job-1",
            "state": "succeeded",
            "result": transcript,
            "spec": {"source": {"media_asset_id": metadata["source_id"]}},
        }
        captured = {}

        def submit(_control, *, request, spec):
            resolved_spec = {
                **spec,
                "registry_snapshot": registry_snapshot(educational_analysis=True),
            }
            job = {
                "job_id": "analysis-job-1",
                "run_id": "analysis-run-1",
                "revision": 2,
                "state": "awaiting_approval",
                "spec_sha256": "a" * 64,
                "spec": resolved_spec,
            }
            captured.update(request=request, spec=resolved_spec, job=job)
            return {"job": job, "run": {"run_id": job["run_id"]}}

        control = Mock()

        def control_post(path, payload):
            if path == "/submissions/get":
                self.assertEqual(payload["job_id"], transcription_job["job_id"])
                return {"job": transcription_job, "run": {"run_id": "source-run"}}
            if path == "/submissions/approve":
                return {"job": {**captured["job"], "revision": 3, "state": "ready"}}
            raise AssertionError(path)

        def dispatch(_control, ready):
            return {
                **ready,
                "revision": 4,
                "state": "dispatch_pending",
                "dispatch": {"generation": 1, "requested_at": 2_000},
            }

        result_reference = {
            **transcript,
            "digest": "e" * 64,
            "byte_length": 9_876,
            "artifact_kind": "analysis",
            "schema": queued_authoring.VIDEO_ANALYSIS_SCHEMA,
            "key": "objects/sha256/ee/" + "e" * 62,
        }

        def wait(_control, job_id, timeout_seconds):
            self.assertEqual(job_id, "analysis-job-1")
            self.assertEqual(timeout_seconds, 3600)
            return {
                "job": {
                    **captured["job"],
                    "state": "succeeded",
                    "result": result_reference,
                    "created_at": 1_000,
                    "updated_at": 5_500,
                    "dispatch": {"generation": 1, "requested_at": 2_000},
                    "attempts": [{
                        "state": "succeeded",
                        "started_at": 2_500,
                        "updated_at": 5_250,
                    }],
                },
                "run": {"run_id": "analysis-run-1", "state": "complete"},
            }

        analysis = {
            "schema_version": 2,
            "video": "WPtpUu3uIUI.youtube",
            "title": "Three hotel-management techniques",
            "summary": "Three practical techniques are demonstrated.",
            "topics": ["Hospitality"],
            "sections": [{"title": "Introduction"}],
            "featured_techniques": [{"technique": "Welcome guests"}],
            "analysis_model": queued_authoring.EDUCATIONAL_VIDEO_ANALYSIS_MODEL,
            "provenance": {
                "handler_id": queued_authoring.EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0],
                "transcript": transcript,
                "timing": {
                    "input_fetch_ms": 100,
                    "analysis_ms": 2_000,
                    "handler_ms": 2_200,
                },
            },
        }
        args = build_parser().parse_args([
            "queue",
            "analyze-transcript",
            "--operator-token-source",
            "keychain",
            "--r2-credentials-source",
            "keychain",
            transcription_job["job_id"],
        ])
        control.post.side_effect = control_post
        output = io.StringIO()
        with patch("queued_authoring.operator_client", return_value=control):
            with patch("queued_authoring.youtube_source_metadata", return_value=metadata):
                with patch("queued_authoring.submit_spec", side_effect=submit):
                    with patch("queued_authoring.dispatch_submission", side_effect=dispatch):
                        with patch("queued_authoring.wait_for_terminal_job", side_effect=wait):
                            with patch(
                                "queued_authoring.verified_json_result",
                                return_value=analysis,
                            ):
                                with redirect_stdout(output):
                                    self.assertEqual(
                                        queued_authoring.run_queue_command(args),
                                        0,
                                    )
        self.assertEqual(captured["spec"]["inputs"], [])
        self.assertEqual(captured["spec"]["dependencies"], [transcript])
        self.assertEqual(
            captured["spec"]["configuration"]["source_metadata"],
            metadata,
        )
        self.assertEqual(
            captured["spec"]["handler"]["id"],
            queued_authoring.EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0],
        )
        self.assertEqual(
            captured["request"]["transcription_job_id"],
            transcription_job["job_id"],
        )
        self.assertIn("authoring-openai-worker.yml", output.getvalue())
        self.assertIn('"analysis_ms": 2000', output.getvalue())
        self.assertIn("Full analysis:", output.getvalue())

    def test_automatic_terminology_changes_only_derived_human_facing_content(self):
        analysis = {
            "schema_version": 2,
            "video": "lesson.youtube",
            "title": "Source title containing i_hat",
            "summary": "Compare i_hat and j_hat basis vectors.",
            "topics": ["basis vectors i_hat and j_hat", "matrix"],
            "sections": [{
                "title": "Using i_hat",
                "description": "The i_hat direction.",
                "concepts": ["i_hat", "j_hat"],
            }],
            "featured_techniques": [{"technique": "Draw i_hat"}],
            "provenance": {"handler_id": "source-handler"},
        }
        resolution = {
            "source_hash": "a" * 64,
            "resolutions": [
                {
                    "resolution_id": "term-i-hat",
                    "observed_forms": ["i_hat"],
                    "display_label": "i-hat",
                    "disposition": "automatic-safe",
                },
                {
                    "resolution_id": "term-j-hat",
                    "observed_forms": ["j_hat"],
                    "display_label": "j-hat",
                    "disposition": "needs-review",
                },
                {
                    "resolution_id": "term-no-cascade",
                    "observed_forms": ["i-hat"],
                    "display_label": "should-not-cascade",
                    "disposition": "automatic-safe",
                },
            ],
            "provenance": {"job_id": "terminology-job-1"},
        }

        derived, applied = queued_authoring.apply_automatic_terminology(
            analysis, resolution
        )

        self.assertEqual(analysis["summary"], "Compare i_hat and j_hat basis vectors.")
        self.assertEqual(derived["title"], "Source title containing i_hat")
        self.assertEqual(derived["summary"], "Compare i-hat and j_hat basis vectors.")
        self.assertEqual(derived["topics"][0], "basis vectors i-hat and j_hat")
        self.assertEqual(derived["sections"][0]["title"], "Using i-hat")
        self.assertEqual(derived["featured_techniques"][0]["technique"], "Draw i-hat")
        self.assertEqual(applied, ["term-i-hat"])
        self.assertEqual(
            derived["provenance"]["terminology_resolution"],
            {
                "job_id": "terminology-job-1",
                "source_hash": "a" * 64,
                "resolution_ids": ["term-i-hat"],
            },
        )

    def test_automatic_terminology_repairs_normalized_display_labels(self):
        normalization = {
            "assignments": {
                "basis vectors i-hat and j-hat": {
                    "canonical_key": "basis vectors i-hat and j-hat",
                    "canonical_label": "basis vectors i-hat and j-hat",
                },
                "i-hat": {
                    "canonical_key": "i-hat",
                    "canonical_label": "i-hat",
                },
                "i-hat and j-hat": {
                    "canonical_key": "i-hat and j-hat",
                    "canonical_label": "i-hat and j-hat",
                },
                "basis vectors i-hat, j-hat, k-hat": {
                    "canonical_key": "basis vectors i-hat, j-hat, k-hat",
                    "canonical_label": "basis vectors i-hat, j-hat, k-hat",
                },
                "columns as images of basis vectors (i-hat, j-hat)": {
                    "canonical_key": "columns as images of basis vectors (i-hat, j-hat)",
                    "canonical_label": "columns as images of basis vectors (i-hat, j-hat)",
                },
                "i-hat, j-hat, k-hat": {
                    "canonical_key": "i-hat, j-hat, k-hat",
                    "canonical_label": "i-hat, j-hat, k-hat",
                },
                "matrix encoding of linear transformations": {
                    "canonical_key": "matrix encoding of linear transformations",
                    "canonical_label": "matrix encoding of linear transformations",
                },
                "right-hand rule for cross-product direction": {
                    "canonical_key": "right-hand rule for cross-product direction",
                    "canonical_label": "right-hand rule for cross-product direction",
                },
            },
            "display_labels": {
                "basis vectors i-hat and j-hat": "basis vectors i Hat & j Hat",
                "i-hat": "I Hat Vector",
                "i-hat and j-hat": "Jennifer Coordinates",
                "basis vectors i-hat, j-hat, k-hat": "i j k Basis",
                "columns as images of basis vectors (i-hat, j-hat)": (
                    "columns images of basis vectors"
                ),
                "i-hat, j-hat, k-hat": "ijk Basis Vectors",
                "matrix encoding of linear transformations": (
                    "Linear Transformation Encoding"
                ),
                "right-hand rule for cross-product direction": "Cross-Product Direction",
            },
        }
        terminology = {
            "resolutions": [
                {
                    "observed_forms": ["i_hat"],
                    "display_label": "i-hat",
                    "disposition": "automatic-safe",
                },
                {
                    "observed_forms": [
                        "right-hand rule for cross product direction",
                    ],
                    "display_label": "right-hand rule for cross-product direction",
                    "disposition": "automatic-safe",
                },
                {
                    "observed_forms": [
                        "matrix encoding of linear transformations",
                        "Matrix encoding of linear transformations",
                    ],
                    "display_label": "matrix encoding of linear transformations",
                    "disposition": "automatic-safe",
                },
                {
                    "observed_forms": ["j_hat"],
                    "display_label": "j-hat",
                    "disposition": "automatic-safe",
                },
            ],
        }

        labels = queued_authoring.apply_automatic_terminology_to_display_labels(
            normalization, terminology
        )

        self.assertEqual(
            labels["basis vectors i-hat and j-hat"],
            "basis vectors i-hat & j-hat",
        )
        self.assertEqual(labels["i-hat"], "i-hat")
        self.assertEqual(labels["i-hat and j-hat"], "i-hat and j-hat")
        self.assertEqual(
            labels["basis vectors i-hat, j-hat, k-hat"],
            "Basis i-hat j-hat k-hat",
        )
        self.assertEqual(
            labels["columns as images of basis vectors (i-hat, j-hat)"],
            "Columns i-hat j-hat",
        )
        self.assertEqual(
            labels["i-hat, j-hat, k-hat"],
            "i-hat j-hat k-hat",
        )
        self.assertEqual(
            labels["matrix encoding of linear transformations"],
            "Linear Transformation Encoding",
        )
        self.assertEqual(
            labels["right-hand rule for cross-product direction"],
            "Cross-Product Direction",
        )

    def test_collection_topic_normalizer_uses_the_existing_normalization_core(self):
        references = []
        analyses = []
        for index, video_id in enumerate(("fNk_zzaMoSs", "k7RM-ot2NWY")):
            digest = str(index + 1) * 64
            references.append({
                "store": "r2",
                "algorithm": "sha256",
                "digest": digest,
                "byte_length": 1_000,
                "media_type": "application/json",
                "artifact_kind": "analysis",
                "schema": queued_authoring.VIDEO_ANALYSIS_SCHEMA,
                "key": f"objects/sha256/{digest[:2]}/{digest[2:]}",
            })
            analyses.append({
                "schema_version": 2,
                "video": f"{video_id}.youtube",
                "title": f"Lesson {index + 1}",
                "summary": "The i_hat basis vector.",
                "topics": ["i_hat", "linear algebra"],
                "sections": [{
                    "start": "00:00:00",
                    "end": "00:01:00",
                    "title": "Vectors",
                    "concepts": ["vectors"],
                    "description": "Introduces vectors.",
                }],
                "provenance": {
                    "handler_id": queued_authoring.EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0],
                },
            })
        bindings = [
            {
                "item_id": f"youtube:{Path(analysis['video']).stem}",
                "video": analysis["video"],
                "digest": reference["digest"],
            }
            for analysis, reference in zip(analyses, references)
        ]
        terminology_reference = {
            **references[0],
            "digest": "f" * 64,
            "artifact_kind": "terminology-resolution",
            "schema": queued_authoring.TERMINOLOGY_RESOLUTION_SCHEMA,
            "key": "objects/sha256/ff/" + "f" * 62,
        }
        terminology = {
            "project": {"project_id": "linear-algebra", "revision": 2},
            "source_hash": "b" * 64,
            "resolutions": [{
                "resolution_id": "term-i-hat",
                "observed_forms": ["i_hat"],
                "display_label": "i-hat",
                "disposition": "automatic-safe",
            }],
            "provenance": {
                "job_id": "terminology-job-1",
                "plan_artifact_sha256": "d" * 64,
            },
        }
        baseline_reference = {
            **references[0],
            "digest": "6" * 64,
            "artifact_kind": "topic-normalization",
            "schema": queued_authoring.TOPIC_NORMALIZATION_SCHEMA,
            "key": "objects/sha256/66/" + "6" * 62,
        }
        baseline = {
            "kind": "watchcraft.topic-normalization",
            "status": "complete",
            "collection_id": "linear-algebra",
            "model": queued_authoring.TOPIC_NORMALIZATION_MODEL,
            "prompt_version": queued_authoring.TOPIC_NORMALIZATION_PROMPT_VERSION,
            "families": {"family-stable": {"label": "Stable family"}},
            "provenance": {"plan_artifact_sha256": "d" * 64},
        }
        spec = queued_authoring.project_topic_normalization_spec(
            plan_job_id="plan-job-1",
            plan_reference={"digest": "d" * 64},
            plan={
                "project": {"project_id": "linear-algebra", "revision": 2},
                "plan_hash": "c" * 64,
                "collection_tasks": [{"task_id": "project:linear-algebra:topics"}],
            },
            dependencies=references,
            bindings=bindings,
            terminology_reference=terminology_reference,
            baseline_reference=baseline_reference,
        )
        job = {"job_id": "normalization-job-1", "spec_sha256": "a" * 64, "spec": spec}
        store = Mock()
        store.get_bytes.side_effect = [
            json.dumps(baseline).encode("utf-8"),
            json.dumps(terminology).encode("utf-8"),
            *[
            json.dumps(analysis).encode("utf-8") for analysis in analyses
            ],
        ]
        context = Mock()
        context.artifact_store.return_value = store
        normalized_analyses = []
        observed_baselines = []

        def normalize(args):
            observed_baselines.append(json.loads(
                (args.root / "Video Catalog" / "topic-normalization.json").read_text(
                    encoding="utf-8"
                )
            ))
            normalized_analyses.extend(
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(
                    (args.root / "Video Catalog" / "analysis").glob("*.json")
                )
            )
            output = args.root / "Video Catalog" / "topic-normalization.json"
            output.write_text(json.dumps({
                "schema_version": 1,
                "prompt_version": queued_authoring.TOPIC_NORMALIZATION_PROMPT_VERSION,
                "display_label_prompt_version": (
                    queued_authoring.TOPIC_DISPLAY_LABEL_PROMPT_VERSION
                ),
                "collection_id": "linear-algebra",
                "status": "complete",
                "model": queued_authoring.TOPIC_NORMALIZATION_MODEL,
                "source_hash": "e" * 64,
                "stats": {
                    "raw_topic_count": 2,
                    "canonical_topic_count": 2,
                    "family_count": 8,
                    "display_label_count": 2,
                    "related_edge_count": 1,
                },
            }), encoding="utf-8")
            return 0

        with patch("normalize_topics.run", side_effect=normalize), patch(
            "queued_authoring.validate_json_schema"
        ):
            result = queued_authoring.collection_topic_normalization(job, context)
        self.assertEqual(result["kind"], "watchcraft.topic-normalization")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["provenance"]["plan_job_id"], "plan-job-1")
        self.assertEqual(result["provenance"]["baseline"], baseline_reference)
        self.assertEqual(result["provenance"]["terminology"], terminology_reference)
        self.assertEqual(len(result["provenance"]["analyses"]), 2)
        self.assertEqual(store.get_bytes.call_count, 4)
        self.assertEqual(context.report_progress.call_count, 4)
        self.assertEqual(observed_baselines[0]["families"], baseline["families"])
        self.assertTrue(all(
            analysis["summary"] == "The i-hat basis vector."
            and analysis["topics"][0] == "i-hat"
            for analysis in normalized_analyses
        ))

    def test_previous_topic_normalization_is_an_explicit_plan_bound_baseline(self):
        reference = {
            "store": "r2",
            "algorithm": "sha256",
            "digest": "6" * 64,
            "byte_length": 1_000,
            "media_type": "application/json",
            "artifact_kind": "topic-normalization",
            "schema": queued_authoring.TOPIC_NORMALIZATION_SCHEMA,
            "key": "objects/sha256/66/" + "6" * 62,
        }
        control = Mock()
        control.post.return_value = {
            "run": {"request": {
                "plan_job_id": "plan-job-1",
                "plan_artifact_sha256": "d" * 64,
                "project_id": "linear-algebra",
            }},
            "jobs": [{
                "state": "succeeded",
                "spec": {"handler": {
                    "id": queued_authoring.PRE_TERMINOLOGY_TOPIC_NORMALIZATION_HANDLER[0],
                    "version": queued_authoring.PRE_TERMINOLOGY_TOPIC_NORMALIZATION_HANDLER[1],
                }},
                "result": reference,
            }],
        }

        self.assertEqual(
            queued_authoring.previous_project_topic_normalization(
                control,
                plan_job_id="plan-job-1",
                plan={"project": {"project_id": "linear-algebra"}},
                plan_reference={"digest": "d" * 64},
            ),
            reference,
        )
        control.post.assert_called_once()

    def test_normalize_project_submits_the_complete_analysis_set_deterministically(self):
        snapshot = {
            "store": "r2",
            "algorithm": "sha256",
            "digest": "b" * 64,
            "byte_length": 100,
            "media_type": "application/json",
            "artifact_kind": "collection-iterator-snapshot",
            "schema": queued_authoring.COLLECTION_ITERATOR_SNAPSHOT_SCHEMA,
            "key": "objects/sha256/bb/" + "b" * 62,
        }
        project = json.loads((
            queued_authoring.CATALOG_PROJECT_SCHEMA_PATH.parent
            / "examples/current-playlist.project.json"
        ).read_text(encoding="utf-8"))
        project["iterator"]["accepted_snapshot"] = snapshot
        plan = {
            "project": {
                "project_id": project["project_id"],
                "revision": project["revision"],
            },
            "source_snapshot": snapshot,
            "plan_hash": "c" * 64,
            "items": [],
            "collection_tasks": [{"task_id": "project:linear-algebra:topics"}],
        }
        plan_reference = {
            "store": "r2",
            "algorithm": "sha256",
            "digest": "d" * 64,
            "byte_length": 1_000,
            "media_type": "application/json",
            "artifact_kind": "project-processing-plan",
            "schema": queued_authoring.PROJECT_PROCESSING_PLAN_SCHEMA,
            "key": "objects/sha256/dd/" + "d" * 62,
        }
        analysis_reference = {
            **plan_reference,
            "digest": "e" * 64,
            "artifact_kind": "analysis",
            "schema": queued_authoring.VIDEO_ANALYSIS_SCHEMA,
            "key": "objects/sha256/ee/" + "e" * 62,
        }
        terminology_reference = {
            **plan_reference,
            "digest": "7" * 64,
            "artifact_kind": "terminology-resolution",
            "schema": queued_authoring.TERMINOLOGY_RESOLUTION_SCHEMA,
            "key": "objects/sha256/77/" + "7" * 62,
        }
        baseline_reference = {
            **plan_reference,
            "digest": "6" * 64,
            "artifact_kind": "topic-normalization",
            "schema": queued_authoring.TOPIC_NORMALIZATION_SCHEMA,
            "key": "objects/sha256/66/" + "6" * 62,
        }
        plan_job = {
            "job_id": "plan-job-1",
            "state": "succeeded",
            "spec": {"handler": {
                "id": queued_authoring.PROJECT_PROCESSING_PLANNER_HANDLER[0],
                "version": queued_authoring.PROJECT_PROCESSING_PLANNER_HANDLER[1],
            }},
            "result": plan_reference,
        }
        control = Mock()

        def post(path, payload):
            if path == "/submissions/get":
                return {"job": plan_job}
            if path == "/projects/get":
                return {"project": project}
            if path == "/pipelines/get":
                return {"run": None, "jobs": []}
            if path == "/submissions/approve":
                return {"job": {
                    "job_id": captured["job_id"],
                    "state": "ready",
                }}
            raise AssertionError(path)

        control.post.side_effect = post
        captured = {}

        def submit(
            _control, *, job_id, run_id, command_prefix, request, spec
        ):
            captured.update(
                run_id=run_id,
                command_prefix=command_prefix,
                request=request,
                job_id=job_id,
                spec=spec,
            )
            return {
                "run": {
                    "run_id": run_id,
                    "state": "planned",
                    "revision": 1,
                    "approval_sha256": "f" * 64,
                },
                "job": {
                    "job_id": job_id,
                    "state": "awaiting_approval",
                    "revision": 1,
                    "spec_sha256": "f" * 64,
                },
            }

        completed_job = {
            "job_id": "unused",
            "state": "succeeded",
            "result": {
                **analysis_reference,
                "digest": "9" * 64,
                "artifact_kind": "topic-normalization",
                "schema": queued_authoring.TOPIC_NORMALIZATION_SCHEMA,
                "key": "objects/sha256/99/" + "9" * 62,
            },
        }
        result = {
            "kind": "watchcraft.topic-normalization",
            "status": "complete",
            "collection_id": project["project_id"],
            "model": queued_authoring.TOPIC_NORMALIZATION_MODEL,
            "source_hash": "8" * 64,
            "stats": {"raw_topic_count": 10},
            "provenance": {
                "handler_id": queued_authoring.TOPIC_NORMALIZATION_HANDLER[0],
                "plan_artifact_sha256": plan_reference["digest"],
                "baseline": baseline_reference,
                "terminology": terminology_reference,
                "analyses": [{"artifact": analysis_reference}],
                "timing": {"normalization_ms": 1_000},
            },
        }
        args = build_parser().parse_args([
            "queue", "normalize-project-topics",
            "--plan-job-id", "plan-job-1",
        ])
        output = io.StringIO()
        with patch("queued_authoring.operator_client", return_value=control), patch(
            "queued_authoring.verified_json_result", side_effect=[plan, result]
        ), patch(
            "queued_authoring.validate_project_processing_plan"
        ), patch(
            "queued_authoring.completed_project_analysis_set",
            return_value=([analysis_reference], [{
                "item_id": "youtube:fNk_zzaMoSs",
                "video": "fNk_zzaMoSs.youtube",
                "digest": analysis_reference["digest"],
            }], ["analysis-job-1"]),
        ), patch(
            "queued_authoring.completed_project_terminology_resolution",
            return_value=terminology_reference,
        ), patch(
            "queued_authoring.previous_project_topic_normalization",
            return_value=baseline_reference,
        ), patch(
            "queued_authoring.submit_spec", side_effect=submit
        ), patch(
            "queued_authoring._resume_pipeline_job"
        ), patch(
            "queued_authoring.wait_for_terminal_job",
            return_value={"job": completed_job, "run": {"run_id": "normalization-run"}},
        ):
            with redirect_stdout(output):
                self.assertEqual(queued_authoring.run_normalize_project(args), 0)
        self.assertEqual(captured["request"]["analysis_job_ids"], ["analysis-job-1"])
        self.assertEqual(captured["spec"]["dependencies"], [
            analysis_reference,
            terminology_reference,
        ])
        self.assertEqual(captured["spec"]["inputs"], [baseline_reference])
        self.assertEqual(
            captured["request"]["baseline_sha256"], baseline_reference["digest"]
        )
        self.assertEqual(captured["spec"]["handler"]["id"], (
            queued_authoring.TOPIC_NORMALIZATION_HANDLER[0]
        ))
        self.assertIn("Full normalization:", output.getvalue())
        self.assertNotIn('"sections": [', output.getvalue())

    def test_collection_compiler_builds_a_portable_manifest_from_bound_resources(self):
        examples = queued_authoring.CATALOG_PROJECT_SCHEMA_PATH.parent / "examples"
        project = json.loads(
            (examples / "current-playlist.project.json").read_text(encoding="utf-8")
        )
        snapshot = json.loads(
            (examples / "current-playlist.snapshot.json").read_text(encoding="utf-8")
        )

        def reference(value, artifact_kind, schema):
            payload = queued_authoring.canonical_json(value).encode("utf-8")
            digest = queued_authoring.sha256_hex(payload)
            return ({
                "store": "r2",
                "algorithm": "sha256",
                "digest": digest,
                "byte_length": len(payload),
                "media_type": "application/json",
                "artifact_kind": artifact_kind,
                "schema": schema,
                "key": f"objects/sha256/{digest[:2]}/{digest[2:]}",
            }, payload)

        snapshot_reference, snapshot_payload = reference(
            snapshot,
            "collection-iterator-snapshot",
            queued_authoring.COLLECTION_ITERATOR_SNAPSHOT_SCHEMA,
        )
        project["iterator"]["accepted_snapshot"] = snapshot_reference
        project["revision"] = snapshot["project"]["revision"] + 1
        planner_context = Mock()
        planner_store = Mock()
        planner_store.get_bytes.return_value = snapshot_payload
        planner_context.artifact_store.return_value = planner_store
        plan = queued_authoring.project_processing_planner({
            "job_id": "plan-job-1",
            "spec_sha256": "a" * 64,
            "spec": queued_authoring.project_processing_plan_spec(
                project, planned_at="2026-09-08T20:00:00Z"
            ),
        }, planner_context)
        plan_reference, plan_payload = reference(
            plan,
            "project-processing-plan",
            queued_authoring.PROJECT_PROCESSING_PLAN_SCHEMA,
        )
        transcripts = []
        analyses = []
        transcript_references = []
        analysis_references = []
        bindings = []
        payloads = {
            plan_reference["key"]: plan_payload,
            snapshot_reference["key"]: snapshot_payload,
        }
        for item in plan["items"]:
            video = f"{item['source']['media_id']}.youtube"
            transcript = {
                "kind": "watchcraft.transcript",
                "schema_version": 1,
                "source": {"media_asset_id": item["item_id"]},
                "text": "Vectors transform through matrices.",
                "segments": [],
            }
            transcript_reference, transcript_payload = reference(
                transcript,
                "transcript",
                {"id": "watchcraft.transcript", "version": 1},
            )
            analysis = {
                "schema_version": 2,
                "video": video,
                "title": f"Generated rewrite of {item['title']}",
                "summary": "A visual linear algebra lesson.",
                "topics": ["vectors"],
                "sections": [],
                "locations": [],
                "analysis_model": "gpt-5-nano",
                "provenance": {
                    "handler_id": queued_authoring.EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0],
                    "transcript": transcript_reference,
                },
            }
            analysis_reference, analysis_payload = reference(
                analysis, "analysis", queued_authoring.VIDEO_ANALYSIS_SCHEMA
            )
            transcripts.append(transcript)
            analyses.append(analysis)
            transcript_references.append(transcript_reference)
            analysis_references.append(analysis_reference)
            payloads[transcript_reference["key"]] = transcript_payload
            payloads[analysis_reference["key"]] = analysis_payload
            bindings.append({
                "item_id": item["item_id"],
                "video": video,
                "transcript_digest": transcript_reference["digest"],
                "analysis_digest": analysis_reference["digest"],
            })
        normalization = {
            "kind": "watchcraft.topic-normalization",
            "schema_version": 1,
            "collection_id": project["project_id"],
            "status": "complete",
            "prompt_version": 2,
            "display_label_prompt_version": 1,
            "model": "gpt-5.4-mini",
            "source_hash": "b" * 64,
            "assignments": {
                "vectors": {
                    "canonical_key": "vectors",
                    "canonical_label": "Vectors",
                    "family_ids": ["family-vectors"],
                },
            },
            "families": {
                "family-vectors": {
                    "canonical_key": "vectors",
                    "label": "Vectors",
                    "description": "Vector concepts.",
                },
            },
            "display_labels": {"vectors": "Vectors"},
            "related": {"vectors": []},
            "provenance": {"plan_artifact_sha256": plan_reference["digest"]},
        }
        terminology = {
            "project": {
                "project_id": project["project_id"],
                "revision": project["revision"],
                "metadata": project.get("metadata", {}),
            },
            "source_hash": "7" * 64,
            "resolutions": [{
                "resolution_id": "term-vectors-display",
                "observed_forms": ["vectors"],
                "display_label": "Vectors",
                "disposition": "automatic-safe",
            }],
            "provenance": {
                "job_id": "terminology-job-1",
                "plan_artifact_sha256": plan_reference["digest"],
            },
        }
        terminology_reference, terminology_payload = reference(
            terminology,
            "terminology-resolution",
            queued_authoring.TERMINOLOGY_RESOLUTION_SCHEMA,
        )
        normalization["provenance"]["terminology"] = terminology_reference
        normalization_reference, normalization_payload = reference(
            normalization,
            "topic-normalization",
            queued_authoring.TOPIC_NORMALIZATION_SCHEMA,
        )
        payloads[normalization_reference["key"]] = normalization_payload
        payloads[terminology_reference["key"]] = terminology_payload
        spec = {
            **queued_authoring.project_collection_compilation_spec(
                project=project,
                plan_job_id="plan-job-1",
                plan_reference=plan_reference,
                plan=plan,
                transcript_references=transcript_references,
                analysis_references=analysis_references,
                bindings=bindings,
                terminology_reference=terminology_reference,
                normalization_reference=normalization_reference,
            ),
            "registry_snapshot": registry_snapshot(collection_compilation=True),
        }
        store = Mock()
        store.get_bytes.side_effect = lambda value: payloads[value["key"]]
        derived_analyses = []

        def put_derived(value, description):
            derived_analyses.append(value)
            return reference(
                value, description["artifact_kind"], description["schema"]
            )[0]

        store.put_json.side_effect = put_derived
        context = Mock()
        context.artifact_store.return_value = store
        with patch("queued_authoring.validate_json_schema"):
            result = queued_authoring.compile_video_collection({
                "job_id": "compile-job-1",
                "spec_sha256": "c" * 64,
                "spec": spec,
            }, context)

        self.assertEqual(result["kind"], "watchcraft.collection-compilation")
        self.assertEqual(result["manifest"]["kind"], "watchcraft.collection")
        self.assertEqual(result["manifest"]["collection_id"], project["project_id"])
        self.assertEqual(len(result["manifest"]["items"]), len(plan["items"]))
        self.assertEqual(len(result["resources"]), len(plan["items"]))
        self.assertEqual(len(derived_analyses), len(plan["items"]))
        self.assertTrue(all(
            analysis["topics"] == ["Vectors"] for analysis in derived_analyses
        ))
        self.assertTrue(all(
            resource["source_artifact"] == source
            and resource["applied_resolution_ids"] == ["term-vectors-display"]
            for resource, source in zip(result["resources"], analysis_references)
        ))
        self.assertEqual(result["provenance"]["terminology"], terminology_reference)
        self.assertEqual(result["manifest"]["stats"]["topic_family_count"], 1)
        self.assertEqual(
            {item["title"] for item in result["manifest"]["items"].values()},
            {item["title"] for item in snapshot["items"]},
        )
        self.assertEqual(context.report_progress.call_count, len(plan["items"]) + 1)

    def test_collection_comparison_reports_revision_and_identity_drift(self):
        published = {
            "revision": 3,
            "content_hash": "a" * 64,
            "items": {"video-1": {}},
            "topics": {"topic-1": {"canonical_key": "vectors"}},
            "topic_families": {},
        }
        candidate = {
            "revision": 1,
            "content_hash": "b" * 64,
            "items": {"video-1": {}, "video-2": {}},
            "topics": {
                "topic-2": {"canonical_key": "vectors"},
                "topic-3": {"canonical_key": "matrices"},
            },
            "topic_families": {"family-1": {}},
        }
        comparison = queued_authoring.collection_comparison(candidate, published)
        self.assertTrue(comparison["content_changed"])
        self.assertEqual(comparison["proposed_revision"], 4)
        self.assertEqual(comparison["items"]["shared_ids"], 1)
        self.assertEqual(comparison["topics"]["shared_canonical_keys"], 1)

    def test_compile_project_submits_one_deterministic_collection_job(self):
        examples = queued_authoring.CATALOG_PROJECT_SCHEMA_PATH.parent / "examples"
        project = json.loads(
            (examples / "current-playlist.project.json").read_text(encoding="utf-8")
        )
        snapshot_reference = project["iterator"]["accepted_snapshot"]
        plan_reference = {
            **snapshot_reference,
            "digest": "d" * 64,
            "artifact_kind": "project-processing-plan",
            "schema": queued_authoring.PROJECT_PROCESSING_PLAN_SCHEMA,
            "key": "objects/sha256/dd/" + "d" * 62,
        }
        plan = {
            "project": {
                "project_id": project["project_id"],
                "revision": project["revision"],
            },
            "source_snapshot": snapshot_reference,
            "plan_hash": "c" * 64,
            "collection_tasks": [
                {"task_id": "topics-task"},
                {"task_id": "compile-task"},
            ],
        }
        transcript_artifact = transcript_reference()
        analysis_reference = {
            **transcript_artifact,
            "digest": "e" * 64,
            "artifact_kind": "analysis",
            "schema": queued_authoring.VIDEO_ANALYSIS_SCHEMA,
            "key": "objects/sha256/ee/" + "e" * 62,
        }
        normalization_reference = {
            **transcript_artifact,
            "digest": "f" * 64,
            "artifact_kind": "topic-normalization",
            "schema": queued_authoring.TOPIC_NORMALIZATION_SCHEMA,
            "key": "objects/sha256/ff/" + "f" * 62,
        }
        terminology_reference = {
            **transcript_artifact,
            "digest": "7" * 64,
            "artifact_kind": "terminology-resolution",
            "schema": queued_authoring.TERMINOLOGY_RESOLUTION_SCHEMA,
            "key": "objects/sha256/77/" + "7" * 62,
        }
        bindings = [{
            "item_id": "youtube:fNk_zzaMoSs",
            "video": "fNk_zzaMoSs.youtube",
            "transcript_digest": transcript_artifact["digest"],
            "analysis_digest": analysis_reference["digest"],
        }]
        plan_job = {
            "job_id": "plan-job-1",
            "state": "succeeded",
            "spec": {"handler": {
                "id": queued_authoring.PROJECT_PROCESSING_PLANNER_HANDLER[0],
                "version": queued_authoring.PROJECT_PROCESSING_PLANNER_HANDLER[1],
            }},
            "result": plan_reference,
        }
        captured = {}
        control = Mock()

        def post(path, payload):
            if path == "/submissions/get":
                return {"job": plan_job}
            if path == "/projects/get":
                return {"project": project}
            if path == "/pipelines/get":
                return {"run": None, "jobs": []}
            if path == "/submissions/approve":
                return {"job": {"job_id": captured["job_id"], "state": "ready"}}
            raise AssertionError(path)

        control.post.side_effect = post

        def submit(_control, *, job_id, run_id, command_prefix, request, spec):
            captured.update(
                job_id=job_id,
                run_id=run_id,
                command_prefix=command_prefix,
                request=request,
                spec=spec,
            )
            return {
                "run": {"run_id": run_id, "state": "planned"},
                "job": {
                    "job_id": job_id,
                    "state": "awaiting_approval",
                    "revision": 1,
                    "spec_sha256": "a" * 64,
                },
            }

        completed_job = {
            "job_id": "compile-job",
            "state": "succeeded",
            "result": {
                **normalization_reference,
                "digest": "9" * 64,
                "artifact_kind": "collection-compilation",
                "schema": queued_authoring.COLLECTION_COMPILATION_SCHEMA,
                "key": "objects/sha256/99/" + "9" * 62,
            },
        }
        result = {
            "kind": "watchcraft.collection-compilation",
            "schema_version": 1,
            "project": plan["project"],
            "manifest": {
                "collection_id": project["publication"]["collection_id"],
                "revision": 1,
                "content_hash": "8" * 64,
                "items": {"video-1": {}},
                "topics": {},
                "topic_families": {},
                "stats": {
                    "video_count": 1,
                    "topic_count": 0,
                    "topic_family_count": 0,
                },
            },
            "resources": [{"path": "analysis/video.analysis.json"}],
            "provenance": {
                "handler_id": queued_authoring.COLLECTION_COMPILATION_HANDLER[0],
                "plan": plan_reference,
                "terminology": terminology_reference,
                "normalization": normalization_reference,
                "timing": {},
            },
        }
        args = build_parser().parse_args([
            "queue", "compile-project", "--plan-job-id", "plan-job-1",
        ])
        with patch("queued_authoring.operator_client", return_value=control), patch(
            "queued_authoring.verified_json_result", side_effect=[plan, result]
        ), patch(
            "queued_authoring.validate_project_processing_plan"
        ), patch(
            "queued_authoring.completed_project_compilation_inputs",
            return_value=(
                [transcript_artifact],
                [analysis_reference],
                bindings,
                terminology_reference,
                normalization_reference,
            ),
        ), patch(
            "queued_authoring.submit_spec", side_effect=submit
        ), patch(
            "queued_authoring._resume_pipeline_job"
        ), patch(
            "queued_authoring.wait_for_terminal_job",
            return_value={"job": completed_job, "run": {}},
        ), patch(
            "build_collection.validate_collection_manifest"
        ):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(queued_authoring.run_compile_project(args), 0)
        self.assertEqual(captured["spec"]["operation"], "compile")
        self.assertEqual(captured["spec"]["inputs"], [plan_reference, snapshot_reference])
        self.assertEqual(captured["spec"]["dependencies"], [
            transcript_artifact,
            analysis_reference,
            terminology_reference,
            normalization_reference,
        ])
        self.assertEqual(captured["request"]["handler"], {
            "id": queued_authoring.COLLECTION_COMPILATION_HANDLER[0],
            "version": queued_authoring.COLLECTION_COMPILATION_HANDLER[1],
        })
        project_item_id = f"catalog-project:{project['project_id']}"
        current_role = queued_authoring.versioned_handler_execution_role(
            "collection-compilation", queued_authoring.COLLECTION_COMPILATION_HANDLER
        )
        prior_role = queued_authoring.versioned_handler_execution_role(
            "collection-compilation",
            (queued_authoring.COLLECTION_COMPILATION_HANDLER[0], "1"),
        )
        self.assertEqual(
            captured["job_id"],
            queued_authoring.stable_project_execution_id(
                plan_reference["digest"], project_item_id, current_role
            ),
        )
        self.assertNotEqual(
            captured["job_id"],
            queued_authoring.stable_project_execution_id(
                plan_reference["digest"], project_item_id, prior_role
            ),
        )

    def test_materialize_project_creates_a_new_revision_package_and_diff(self):
        from build_collection import build_collection_manifest, render_csv

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authoring_root = root / "authoring-source"
            published_root = root / "published"
            authoring_root.mkdir()
            published_root.mkdir()
            (authoring_root / "watchcraft-authoring.json").write_text(
                json.dumps({"collection": {
                    "collection_id": "example-collection",
                    "title": "Example Collection",
                }}),
                encoding="utf-8",
            )
            old_analysis = {
                "schema_version": 2,
                "video": "lesson.mp4",
                "title": "Old lesson title",
                "summary": "Old summary.",
                "topics": ["vectors"],
                "sections": [],
                "locations": [],
                "analysis_model": "gpt-5-nano",
            }
            new_analysis = {
                **old_analysis,
                "title": "New lesson title",
                "summary": "New summary.",
            }
            published = build_collection_manifest(
                authoring_root, [old_analysis], {}, previous=None, normalization=None
            )
            candidate = build_collection_manifest(
                authoring_root, [new_analysis], {}, previous=None, normalization=None
            )
            (published_root / "collection.json").write_text(
                json.dumps(published, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (published_root / "catalog.csv").write_text(
                render_csv([old_analysis], published), encoding="utf-8"
            )
            (published_root / "analysis").mkdir()
            (published_root / "analysis/lesson.analysis.json").write_text(
                json.dumps(old_analysis), encoding="utf-8"
            )
            analysis_payload = queued_authoring.canonical_json(new_analysis).encode("utf-8")
            digest = queued_authoring.sha256_hex(analysis_payload)
            analysis_reference = {
                "store": "r2",
                "algorithm": "sha256",
                "digest": digest,
                "byte_length": len(analysis_payload),
                "media_type": "application/json",
                "artifact_kind": "analysis",
                "schema": queued_authoring.VIDEO_ANALYSIS_SCHEMA,
                "key": f"objects/sha256/{digest[:2]}/{digest[2:]}",
            }
            job = {
                "job_id": "compile-job-1",
                "state": "succeeded",
                "spec": {"handler": {
                    "id": queued_authoring.COLLECTION_COMPILATION_HANDLER[0],
                    "version": queued_authoring.COLLECTION_COMPILATION_HANDLER[1],
                }},
            }
            bundle = {
                "kind": "watchcraft.collection-compilation",
                "schema_version": 1,
                "manifest": candidate,
                "resources": [{
                    "path": "analysis/lesson.analysis.json",
                    "artifact": analysis_reference,
                }],
                "provenance": {
                    "handler_id": queued_authoring.COLLECTION_COMPILATION_HANDLER[0],
                    "job_id": job["job_id"],
                },
            }
            control = Mock()
            control.post.return_value = {"job": job}
            store = Mock()
            store.get_bytes.return_value = analysis_payload
            destination = root / "review"
            args = build_parser().parse_args([
                "queue", "materialize-project", job["job_id"],
                "--published-collection", str(published_root / "collection.json"),
                "--output-directory", str(destination),
            ])
            with patch("queued_authoring.operator_client", return_value=control), patch(
                "queued_authoring.verified_json_result", return_value=bundle
            ), patch(
                "queued_authoring.r2_artifact_reader", return_value=store
            ):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(queued_authoring.run_materialize_project(args), 0)

            materialized = json.loads(
                (destination / "collection.json").read_text(encoding="utf-8")
            )
            self.assertEqual(materialized["revision"], 2)
            self.assertEqual(materialized["content_hash"], candidate["content_hash"])
            self.assertEqual(
                (destination / "analysis/lesson.analysis.json").read_bytes(),
                (
                    json.dumps(
                        json.loads(analysis_payload.decode("utf-8")),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                ).encode("utf-8"),
            )
            self.assertTrue((destination / "catalog.csv").is_file())
            self.assertIn(
                "New lesson title",
                Path(f"{destination}.diff").read_text(encoding="utf-8"),
            )
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                queued_authoring.run_materialize_project(args)

    def test_waiting_for_a_remote_job_reports_periodic_progress(self):
        client = Mock()
        client.post.side_effect = [
            {"job": {"job_id": "job-1", "state": "dispatch_pending"}},
            {"job": {"job_id": "job-1", "state": "dispatch_pending"}},
            {"job": {"job_id": "job-1", "state": "succeeded"}},
        ]
        output = io.StringIO()
        with patch("queued_authoring.time.monotonic", side_effect=[0.0, 0.0, 31.0, 32.0]):
            with patch("queued_authoring.time.sleep") as sleep:
                with redirect_stdout(output):
                    result = queued_authoring.wait_for_terminal_job(
                        client,
                        "job-1",
                        timeout_seconds=60,
                        poll_seconds=5,
                        progress_seconds=30,
                    )
        self.assertEqual(result["job"]["state"], "succeeded")
        self.assertIn("job-1: dispatch_pending", output.getvalue())
        self.assertIn(
            "job-1: still waiting (dispatch_pending, 31s elapsed)",
            output.getvalue(),
        )
        self.assertIn("job-1: succeeded", output.getvalue())
        self.assertEqual(sleep.call_count, 2)

    def test_waiting_for_a_remote_job_reports_structured_progress_changes(self):
        client = Mock()
        client.post.side_effect = [
            {"job": {"job_id": "job-1", "state": "running", "attempts": [{
                "progress": {
                    "phase": "enumerating",
                    "completed": 1,
                    "total": 3,
                    "unit": "placements",
                    "current": "Lesson one",
                },
            }]}},
            {"job": {"job_id": "job-1", "state": "running", "attempts": [{
                "progress": {
                    "phase": "enumerating",
                    "completed": 2,
                    "total": 3,
                    "unit": "placements",
                    "current": "Lesson two",
                },
            }]}},
            {"job": {"job_id": "job-1", "state": "succeeded", "attempts": [{
                "progress": {
                    "phase": "storing",
                    "completed": 1,
                    "total": 1,
                    "unit": "snapshot",
                },
            }]}},
        ]
        output = io.StringIO()
        with patch("queued_authoring.time.monotonic", side_effect=[0.0, 0.0, 1.0, 2.0]):
            with patch("queued_authoring.time.sleep"):
                with redirect_stdout(output):
                    queued_authoring.wait_for_terminal_job(
                        client,
                        "job-1",
                        timeout_seconds=60,
                    )
        self.assertIn(
            "job-1: enumerating: 1 of 3 placements — Lesson one",
            output.getvalue(),
        )
        self.assertIn(
            "job-1: enumerating: 2 of 3 placements — Lesson two",
            output.getvalue(),
        )
        self.assertLess(
            output.getvalue().index("job-1: storing: 1 of 1 snapshot"),
            output.getvalue().index("job-1: succeeded"),
        )

    def test_mlx_registry_snapshot_is_accepted_only_by_the_macos_profile(self):
        job = {
            "job_id": "job-mlx",
            "spec": {
                **queued_authoring.transcription_smoke_spec(),
                "registry_snapshot": registry_snapshot(transcription=True),
            },
        }
        environment = {
            "WATCHCRAFT_EXECUTION_PROFILE_ID": "macos-mlx",
            "WATCHCRAFT_EXECUTION_PROFILE_VERSION": "1",
        }
        with patch.dict(os.environ, environment, clear=True):
            profile = queued_authoring.validate_registry_snapshot(job)
        self.assertEqual(profile["dispatcher"]["workflow"], "authoring-mlx-worker.yml")

        http_job = {
            "job_id": "job-http-mlx",
            "spec": {
                **queued_authoring.http_transcription_smoke_spec(),
                "registry_snapshot": registry_snapshot(http_transcription=True),
            },
        }
        with patch.dict(os.environ, environment, clear=True):
            http_profile = queued_authoring.validate_registry_snapshot(http_job)
        self.assertEqual(http_profile["id"], "macos-mlx")

        reference = staged_audio_reference()
        staged_job = {
            "job_id": "job-staged-mlx",
            "spec": {
                **queued_authoring.staged_transcription_spec(
                    source={"media_asset_id": "youtube:WPtpUu3uIUI"},
                    source_audio=reference,
                    acquisition=staged_acquisition(reference),
                ),
                "registry_snapshot": registry_snapshot(staged_transcription=True),
            },
        }
        with patch.dict(os.environ, environment, clear=True):
            staged_profile = queued_authoring.validate_registry_snapshot(staged_job)
        self.assertEqual(staged_profile["id"], "macos-mlx")

        transcript = transcript_reference()
        analysis_job = {
            "job_id": "job-educational-analysis",
            "spec": {
                **queued_authoring.educational_video_analysis_spec(
                    source={"media_asset_id": "youtube:WPtpUu3uIUI"},
                    transcript=transcript,
                    source_metadata=youtube_metadata(),
                    video="WPtpUu3uIUI.youtube",
                ),
                "registry_snapshot": registry_snapshot(educational_analysis=True),
            },
        }
        analysis_environment = {
            "WATCHCRAFT_EXECUTION_PROFILE_ID": "python-openai",
            "WATCHCRAFT_EXECUTION_PROFILE_VERSION": "1",
        }
        with patch.dict(os.environ, analysis_environment, clear=True):
            analysis_profile = queued_authoring.validate_registry_snapshot(analysis_job)
        self.assertEqual(analysis_profile["id"], "python-openai")
        self.assertEqual(
            analysis_profile["dispatcher"]["workflow"],
            "authoring-openai-worker.yml",
        )

        normalization_job = {
            "job_id": "job-topic-normalization",
            "spec": {
                "operation": "generate",
                "artifact_kind": "topic-normalization",
                "output_schema": queued_authoring.TOPIC_NORMALIZATION_SCHEMA,
                "handler": {
                    "id": queued_authoring.TOPIC_NORMALIZATION_HANDLER[0],
                    "version": queued_authoring.TOPIC_NORMALIZATION_HANDLER[1],
                },
                "source": {"media_asset_id": "catalog-project:example"},
                "inputs": [],
                "dependencies": [
                    transcript_reference(),
                    transcript_reference(),
                    {
                        **transcript_reference(),
                        "artifact_kind": "terminology-resolution",
                        "schema": queued_authoring.TERMINOLOGY_RESOLUTION_SCHEMA,
                    },
                ],
                "configuration": {},
                "registry_snapshot": registry_snapshot(topic_normalization=True),
            },
        }
        for dependency in normalization_job["spec"]["dependencies"][:-1]:
            dependency["artifact_kind"] = "analysis"
            dependency["schema"] = queued_authoring.VIDEO_ANALYSIS_SCHEMA
        with patch.dict(os.environ, analysis_environment, clear=True):
            normalization_profile = queued_authoring.validate_registry_snapshot(
                normalization_job
            )
        self.assertEqual(normalization_profile["id"], "python-openai")

    def test_result_displays_verified_json_from_the_authoritative_reference(self):
        payload = queued_authoring.canonical_json({
            "kind": "watchcraft.analysis.lexical",
            "topics": ["color", "exposure"],
        }).encode("utf-8")
        digest = queued_authoring.sha256_hex(payload)
        reference = {
            "store": "r2",
            "algorithm": "sha256",
            "digest": digest,
            "byte_length": len(payload),
            "media_type": "application/json",
            "artifact_kind": "analysis",
            "schema": {"id": "watchcraft.analysis.lexical", "version": 1},
            "key": f"objects/sha256/{digest[:2]}/{digest[2:]}",
        }
        client = Mock()
        client.post.return_value = {
            "job": {"job_id": "job-1", "state": "succeeded", "result": reference},
            "run": {"state": "complete"},
        }
        reader = Mock()
        reader.get_bytes.return_value = payload
        args = build_parser().parse_args([
            "queue", "result", "--operator-token-source", "keychain", "job-1",
        ])
        output = io.StringIO()
        with patch("queued_authoring.operator_client", return_value=client):
            with patch("queued_authoring.r2_artifact_reader", return_value=reader):
                with redirect_stdout(output):
                    self.assertEqual(queued_authoring.run_queue_command(args), 0)
        displayed = json.loads(output.getvalue())
        self.assertEqual(displayed["topics"], ["color", "exposure"])
        reader.get_bytes.assert_called_once_with(reference)

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "analysis.json"
            file_args = build_parser().parse_args([
                "queue", "result", "job-1", "--output", str(target),
            ])
            with patch("queued_authoring.operator_client", return_value=client):
                with patch("queued_authoring.r2_artifact_reader", return_value=reader):
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(queued_authoring.run_queue_command(file_args), 0)
                    self.assertEqual(target.read_bytes(), payload)
                    with self.assertRaisesRegex(RuntimeError, "Refusing to overwrite"):
                        queued_authoring.run_queue_command(file_args)

    def test_result_rejects_an_artifact_key_that_does_not_match_its_digest(self):
        digest = "a" * 64
        with self.assertRaisesRegex(RuntimeError, "artifact key"):
            queued_authoring.validated_artifact_reference({
                "store": "r2",
                "algorithm": "sha256",
                "digest": digest,
                "byte_length": 1,
                "media_type": "application/json",
                "key": "objects/sha256/not-the-digest",
            })

    def test_python_worker_dispatches_analysis_by_handler_identity(self):
        spec = {
            "operation": "generate",
            "artifact_kind": "analysis",
            "output_schema": {"id": "watchcraft.analysis.lexical", "version": 1},
            "handler": {"id": "watchcraft.analysis.lexical", "version": "1"},
            "source": {"media_asset_id": "lesson-1"},
            "inputs": [],
            "dependencies": [],
            "configuration": {
                "title": "Color workflow",
                "text": "Color balance improves exposure balance.",
                "max_topics": 3,
            },
            "registry_snapshot": registry_snapshot(),
        }
        job = {
            "job_id": "job-1",
            "run_id": "run-1",
            "revision": 4,
            "state": "dispatch_pending",
            "spec_sha256": "a" * 64,
            "spec": spec,
            "dispatch": {"generation": 1},
        }

        class Control:
            def __init__(self):
                self.paths = []

            def post(self, path, payload):
                self.paths.append(path)
                if path == "/jobs/dispatch/record":
                    return {**job, "revision": 5, "state": "dispatched"}
                if path == "/jobs/claim":
                    return {**job, "revision": 6, "state": "claimed"}
                if path == "/jobs/start":
                    return {**job, "revision": 7, "state": "running"}
                if path == "/jobs/succeed":
                    return {
                        **job,
                        "revision": 8,
                        "state": "succeeded",
                        "result": payload["artifact"],
                    }
                raise AssertionError(path)

        class Artifacts:
            def put_json(self, value, description):
                self.value = value
                self.description = description
                return {
                    "store": "r2",
                    "algorithm": "sha256",
                    "digest": "b" * 64,
                    "byte_length": 100,
                    "media_type": "application/json",
                    "artifact_kind": description["artifact_kind"],
                    "schema": description["schema"],
                    "key": "objects/sha256/bb/" + "b" * 62,
                }

        control = Control()
        artifacts = Artifacts()
        with patch("queued_authoring.worker_client", return_value=control):
            with patch.object(
                queued_authoring.R2ArtifactStore,
                "from_environment",
                return_value=artifacts,
            ):
                result = queued_authoring.run_worker(
                    job_id="job-1",
                    spec_sha256="a" * 64,
                    dispatch_generation=1,
                    expected_revision=4,
                )
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(artifacts.value["kind"], "watchcraft.analysis.lexical")
        self.assertEqual(artifacts.description["artifact_kind"], "analysis")
        self.assertEqual(control.paths, [
            "/jobs/dispatch/record",
            "/jobs/claim",
            "/jobs/start",
            "/jobs/succeed",
        ])

    def test_playlist_iterator_reports_progress_and_completes_at_latest_revision(self):
        project_path = (
            queued_authoring.CATALOG_PROJECT_SCHEMA_PATH.parent
            / "examples"
            / "current-playlist.project.json"
        )
        project = json.loads(project_path.read_text(encoding="utf-8"))
        spec = {
            **queued_authoring.youtube_playlist_iterator_spec(
                project,
                observed_at="2026-09-08T12:00:00Z",
            ),
            "registry_snapshot": registry_snapshot(playlist_iterator=True),
        }
        base_job = {
            "job_id": "job-playlist",
            "run_id": "run-playlist",
            "revision": 4,
            "state": "dispatch_pending",
            "spec_sha256": "a" * 64,
            "spec": spec,
            "dispatch": {"generation": 1},
            "attempts": [],
        }

        class Control:
            def __init__(self):
                self.job = dict(base_job)
                self.progress = []
                self.success_revision = None

            def transition(self, state, **changes):
                self.job = {
                    **self.job,
                    **changes,
                    "revision": self.job["revision"] + 1,
                    "state": state,
                }
                return self.job

            def post(self, path, payload):
                self.assert_revision(payload)
                if path == "/jobs/dispatch/record":
                    return self.transition("dispatched")
                if path == "/jobs/claim":
                    attempt = {
                        "attempt_id": payload["attempt_id"],
                        "state": "claimed",
                    }
                    return self.transition("claimed", attempts=[attempt])
                if path == "/jobs/start":
                    self.job["attempts"][-1]["state"] = "running"
                    return self.transition("running")
                if path == "/jobs/heartbeat":
                    self.progress.append(payload["progress"])
                    self.job["attempts"][-1]["progress"] = payload["progress"]
                    if "checkpoint" in payload:
                        self.job["attempts"][-1]["checkpoint"] = payload["checkpoint"]
                    return self.transition("running")
                if path == "/jobs/succeed":
                    self.success_revision = payload["expected_revision"]
                    return self.transition("succeeded", result=payload["artifact"])
                raise AssertionError(path)

            def assert_revision(self, payload):
                self_case.assertEqual(payload["expected_revision"], self.job["revision"])

        class Artifacts:
            def __init__(self):
                self.objects = {}

            def put_json(self, value, description):
                payload = queued_authoring.canonical_json(value).encode("utf-8")
                digest = queued_authoring.sha256_hex(payload)
                reference = {
                    "store": "r2",
                    "algorithm": "sha256",
                    "digest": digest,
                    "byte_length": len(payload),
                    "media_type": "application/json",
                    "artifact_kind": description["artifact_kind"],
                    "schema": description["schema"],
                    "key": f"objects/sha256/{digest[:2]}/{digest[2:]}",
                }
                self.objects[reference["key"]] = payload
                return reference

            def get_bytes(self, reference):
                return self.objects[reference["key"]]

        self_case = self
        control = Control()
        artifacts = Artifacts()
        video_ids = [f"video{index:06d}" for index in range(1, 11)] + ["video000001"]
        playlist = {
            "playlist_id": project["iterator"]["configuration"]["playlist_id"],
            "url": project["iterator"]["configuration"]["canonical_url"],
            "title": "Editing lessons",
            "description": "Editing and color lessons.",
            "entries": video_ids,
            "video_ids": video_ids,
            "duplicate_count": 1,
        }

        def metadata(video_id):
            return {
                "source_id": f"youtube:{video_id}",
                "type": "youtube",
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": f"Lesson {video_id}",
                "publisher": "Editing School",
                "publisher_url": "https://www.youtube.com/@editingschool",
                "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "duration_seconds": 120,
                "published_at": "2026-09-08",
                "chapters": [],
            }

        with patch("queued_authoring.worker_client", return_value=control):
            with patch.object(
                queued_authoring.R2ArtifactStore,
                "from_environment",
                return_value=artifacts,
            ):
                with patch(
                    "queued_authoring.discover_youtube_playlist",
                    return_value=playlist,
                ):
                    with patch(
                        "queued_authoring.discover_youtube_video",
                        side_effect=metadata,
                    ):
                        result = queued_authoring.run_worker(
                            job_id=base_job["job_id"],
                            spec_sha256=base_job["spec_sha256"],
                            dispatch_generation=1,
                            expected_revision=4,
                        )

        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["result"]["artifact_kind"], "collection-iterator-snapshot")
        self.assertGreater(control.success_revision, 7)
        self.assertIn(
            {
                "phase": "enumerating",
                "completed": 11,
                "unit": "placements",
                "total": 11,
                "current": "Lesson video000001",
            },
            control.progress,
        )
        snapshot = json.loads(artifacts.get_bytes(result["result"]))
        self.assertEqual(snapshot["coverage"], {
            "basis": "source-entries",
            "expected": 11,
            "resolved": 11,
            "unresolved": [],
        })
        self.assertEqual(len(snapshot["items"]), 10)
        self.assertEqual(len(snapshot["placements"]), 11)
        self.assertEqual(snapshot["placements"][-1]["item_id"], "youtube:video000001")
        checkpoint = result["attempts"][-1]["checkpoint"]
        self.assertEqual(checkpoint["sequence"], 1)
        checkpoint_payload = json.loads(artifacts.get_bytes(checkpoint["artifact"]))
        self.assertEqual(checkpoint_payload["next_index"], 10)
        resumed = queued_authoring._playlist_checkpoint_state(
            queued_authoring.WorkerContext(
                control=control,
                job=result,
                attempt_id="replacement-attempt",
                lease_duration_ms=300_000,
                artifacts=artifacts,
            ),
            project=project,
            playlist=playlist,
            entries=video_ids,
        )
        self.assertEqual(resumed[0], 10)
        self.assertEqual(len(resumed[1]), 10)

    def test_project_planner_plans_unique_items_from_the_accepted_snapshot(self):
        examples = queued_authoring.CATALOG_PROJECT_SCHEMA_PATH.parent / "examples"
        project = json.loads(
            (examples / "current-playlist.project.json").read_text(encoding="utf-8")
        )
        snapshot = json.loads(
            (examples / "current-playlist.snapshot.json").read_text(encoding="utf-8")
        )
        duplicate = {
            **snapshot["placements"][0],
            "placement_id": "youtube-playlist:duplicate-placement",
            "position": len(snapshot["placements"]) + 1,
        }
        snapshot["placements"].append(duplicate)
        snapshot["coverage"]["expected"] += 1
        snapshot["coverage"]["resolved"] += 1
        snapshot["structure_hash"] = queued_authoring.iterator_structure_sha256(snapshot)
        payload = queued_authoring.canonical_json(snapshot).encode("utf-8")
        digest = queued_authoring.sha256_hex(payload)
        accepted = {
            "store": "r2",
            "algorithm": "sha256",
            "digest": digest,
            "byte_length": len(payload),
            "media_type": "application/json",
            "artifact_kind": "collection-iterator-snapshot",
            "schema": queued_authoring.COLLECTION_ITERATOR_SNAPSHOT_SCHEMA,
            "key": f"objects/sha256/{digest[:2]}/{digest[2:]}",
        }
        project["iterator"]["accepted_snapshot"] = accepted
        spec = {
            **queued_authoring.project_processing_plan_spec(
                project,
                planned_at="2026-09-08T20:00:00Z",
            ),
            "registry_snapshot": registry_snapshot(project_planner=True),
        }
        artifacts = Mock()
        artifacts.get_bytes.return_value = payload
        context = Mock()
        context.artifact_store.return_value = artifacts
        job = {
            "job_id": "job-project-plan",
            "spec_sha256": "a" * 64,
            "spec": spec,
        }

        plan = queued_authoring.project_processing_planner(job, context)

        queued_authoring.validate_project_processing_plan(plan)
        self.assertEqual(plan["source_snapshot"], accepted)
        item_count = len(snapshot["items"])
        self.assertEqual(plan["summary"], {
            "unique_items": item_count,
            "placements": len(snapshot["placements"]),
            "operator_local_tasks": item_count * 2,
            "registered_worker_jobs": item_count * 2,
            "deferred_collection_jobs": 2,
        })
        self.assertEqual(len(plan["items"]), item_count)
        self.assertEqual(len(plan["items"][0]["placement_ids"]), 2)
        self.assertEqual(
            [stage["stage"] for stage in plan["items"][0]["stages"]],
            [
                "metadata-enrichment",
                "source-acquisition",
                "transcription",
                "analysis",
            ],
        )
        self.assertEqual(
            plan["items"][0]["stages"][2]["reuse"]["status"],
            "deferred",
        )
        self.assertEqual(plan["estimate"]["status"], "duration-informed")
        self.assertEqual(plan["estimate"]["unknown_duration_items"], 0)
        self.assertEqual(
            plan["estimate"]["sequential_worker_upper_bound_minutes"],
            item_count * 90,
        )
        self.assertEqual(context.report_progress.call_count, item_count)
        self.assertEqual(
            context.report_progress.call_args.kwargs,
            {
                "phase": "planning",
                "completed": item_count,
                "total": item_count,
                "unit": "items",
                "current": snapshot["items"][-1]["title"],
            },
        )

        plan["summary"]["unique_items"] = 15
        with self.assertRaisesRegex(ValueError, "summary"):
            queued_authoring.validate_project_processing_plan(plan)

    def test_python_worker_preserves_classified_staged_input_failures(self):
        reference = staged_audio_reference()
        spec = {
            **queued_authoring.staged_transcription_spec(
                source={"media_asset_id": "youtube:WPtpUu3uIUI"},
                source_audio=reference,
                acquisition=staged_acquisition(reference),
            ),
            "registry_snapshot": registry_snapshot(staged_transcription=True),
        }
        job = {
            "job_id": "job-staged-failure",
            "run_id": "run-staged-failure",
            "revision": 4,
            "state": "dispatch_pending",
            "spec_sha256": "a" * 64,
            "spec": spec,
            "dispatch": {"generation": 1},
        }

        class Control:
            def __init__(self):
                self.failure = None

            def post(self, path, payload):
                if path == "/jobs/dispatch/record":
                    return {**job, "revision": 5, "state": "dispatched"}
                if path == "/jobs/claim":
                    return {**job, "revision": 6, "state": "claimed"}
                if path == "/jobs/start":
                    return {**job, "revision": 7, "state": "running"}
                if path == "/jobs/fail":
                    self.failure = payload["failure"]
                    return {**job, "revision": 8, "state": "retryable_failed"}
                raise AssertionError(path)

        def fail_input(_job, _context):
            raise queued_authoring.StagedSourceError(
                "Staged source is temporarily unavailable",
                "source_input_unavailable",
                True,
            )

        control = Control()
        environment = {
            "WATCHCRAFT_EXECUTION_PROFILE_ID": "macos-mlx",
            "WATCHCRAFT_EXECUTION_PROFILE_VERSION": "1",
        }
        with patch.dict(os.environ, environment, clear=True):
            with patch("queued_authoring.worker_client", return_value=control):
                with patch.dict(
                    queued_authoring.HANDLERS,
                    {queued_authoring.PRODUCTION_TRANSCRIPTION_HANDLER: fail_input},
                ):
                    with self.assertRaisesRegex(
                        queued_authoring.StagedSourceError,
                        "temporarily unavailable",
                    ):
                        queued_authoring.run_worker(
                            job_id=job["job_id"],
                            spec_sha256=job["spec_sha256"],
                            dispatch_generation=1,
                            expected_revision=4,
                        )
        self.assertEqual(control.failure["classification"], "source_input_unavailable")
        self.assertTrue(control.failure["retryable"])

    def test_python_worker_rejects_a_job_routed_to_another_execution_profile(self):
        spec = {
            "operation": "generate",
            "artifact_kind": "analysis",
            "output_schema": {"id": "watchcraft.analysis.lexical", "version": 1},
            "handler": {"id": "watchcraft.analysis.lexical", "version": "1"},
            "source": {"media_asset_id": "lesson-1"},
            "inputs": [],
            "dependencies": [],
            "configuration": {},
            "registry_snapshot": registry_snapshot(),
        }
        spec["registry_snapshot"]["execution_profile"]["id"] = "macos-mlx"
        job = {
            "job_id": "job-1",
            "revision": 4,
            "spec_sha256": "a" * 64,
            "spec": spec,
        }

        class Control:
            def __init__(self):
                self.failure = None

            def post(self, path, payload):
                if path == "/jobs/dispatch/record":
                    return {**job, "revision": 5, "state": "dispatched"}
                if path == "/jobs/claim":
                    return {**job, "revision": 6, "state": "claimed"}
                if path == "/jobs/fail":
                    self.failure = payload["failure"]
                    return {**job, "revision": 7, "state": "terminal_failed"}
                raise AssertionError(path)

        control = Control()
        with patch("queued_authoring.worker_client", return_value=control):
            with self.assertRaisesRegex(queued_authoring.RegistrySupportError, "cannot execute"):
                queued_authoring.run_worker(
                    job_id="job-1",
                    spec_sha256="a" * 64,
                    dispatch_generation=1,
                    expected_revision=4,
                )
        self.assertEqual(control.failure["classification"], "unsupported_execution_profile")
        self.assertFalse(control.failure["retryable"])


if __name__ == "__main__":
    unittest.main()
