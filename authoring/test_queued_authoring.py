import argparse
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import queued_authoring
from watchcraft_author import build_parser, main


class QueuedAuthoringTests(unittest.TestCase):
    def test_queue_parser_exposes_non_transcript_analysis_submission(self):
        args = build_parser().parse_args([
            "queue", "submit-analysis", "--title", "Color workflow",
            "--text", "Balance exposure and color before applying the final grade.",
        ])
        self.assertEqual(args.command, "queue")
        self.assertEqual(args.queue_command, "submit-analysis")
        self.assertEqual(args.max_topics, 8)
        self.assertEqual(args.operator_token_source, "auto")

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
            "configuration": {
                "title": "Color workflow",
                "text": "Color balance improves exposure balance.",
                "max_topics": 3,
            },
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


if __name__ == "__main__":
    unittest.main()
