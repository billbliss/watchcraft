import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from jsonschema import Draft202012Validator

import queued_authoring
from watchcraft_author import build_parser, main


def registry_snapshot(*, transcription=False):
    if transcription:
        return {
            "registry_version": "2026-09-04.2",
            "registry_sha256": "c" * 64,
            "handler": queued_authoring.LOCAL_HANDLER_CONTRACTS[
                queued_authoring.TRANSCRIPTION_SMOKE_HANDLER
            ],
            "execution_profile": queued_authoring.LOCAL_EXECUTION_PROFILES[
                queued_authoring.MLX_EXECUTION_PROFILE
            ],
        }
    return {
        "registry_version": "2026-09-04.2",
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

    def test_queue_parser_exposes_one_command_smokes_and_guarded_cleanup(self):
        smoke = build_parser().parse_args([
            "queue", "smoke-transcription",
            "--operator-token-source", "keychain",
            "--r2-credentials-source", "keychain",
        ])
        self.assertEqual(smoke.timeout_seconds, 1800)
        self.assertEqual(smoke.retention_days, 7)

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
        self.assertEqual(run.call_args.args[0][3], "authoring-mlx-worker.yml")
        client.post.assert_not_called()

    def test_dispatch_rejects_an_unsafe_workflow_name(self):
        job = {"spec": {"registry_snapshot": registry_snapshot()}}
        job["spec"]["registry_snapshot"]["execution_profile"]["dispatcher"]["workflow"] = "../bad.yml"
        with self.assertRaisesRegex(RuntimeError, "unsafe"):
            queued_authoring.dispatch_workflow(job)

    def test_registry_commands_separate_operator_visibility_from_admin_changes(self):
        status = build_parser().parse_args(["queue", "registry-status"])
        self.assertEqual(status.operator_token_source, "auto")
        self.assertEqual(status.environment, "production")
        activate = build_parser().parse_args([
            "queue", "registry-activate", "--registry-admin-token-source", "keychain",
            "--expected-revision", "0",
        ])
        self.assertEqual(activate.registry_admin_token_source, "keychain")
        self.assertEqual(activate.registry_file, queued_authoring.DEFAULT_REGISTRY_PATH)

        client = Mock()
        client.post.return_value = {"registry_version": "2026-09-04.2"}
        with patch("queued_authoring.registry_admin_client", return_value=client):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(queued_authoring.run_queue_command(activate), 0)
        path, payload = client.post.call_args.args
        self.assertEqual(path, "/registry/activate")
        self.assertEqual(payload["expected_revision"], 0)
        self.assertRegex(payload["registry_sha256"], r"^[a-f0-9]{64}$")

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
