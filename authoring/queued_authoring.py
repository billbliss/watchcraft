"""Operator and worker primitives for queued Watchcraft authoring."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


OPERATOR_KEYCHAIN_ACCOUNT = "watchcraft-operator-cli"
OPERATOR_KEYCHAIN_SERVICE = "Watchcraft authoring operator token"
REGISTRY_ADMIN_KEYCHAIN_ACCOUNT = "watchcraft-registry-admin-cli"
REGISTRY_ADMIN_KEYCHAIN_SERVICE = "Watchcraft authoring registry admin token"
R2_READER_KEYCHAIN_SERVICE = "Watchcraft R2 artifact reader"
R2_READER_ACCESS_KEY_ACCOUNT = "access-key-id"
R2_READER_SECRET_KEY_ACCOUNT = "secret-access-key"
R2_READER_ACCESS_KEY_ENV = "WATCHCRAFT_R2_READER_ACCESS_KEY_ID"
R2_READER_SECRET_KEY_ENV = "WATCHCRAFT_R2_READER_SECRET_ACCESS_KEY"
DEFAULT_GITHUB_REPOSITORY = "billbliss/watchcraft"
DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages" / "authoring-pipeline" / "registry" / "default-registry.json"
)
ANALYSIS_HANDLER = ("watchcraft.analysis.lexical", "1")
PYTHON_EXECUTION_PROFILE = ("python-portable", "1")
PYTHON_EXECUTION_WORKFLOW = "authoring-worker.yml"
WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9'-]{2,}")
STOP_WORDS = {
    "and", "are", "but", "for", "from", "has", "have", "into", "its", "not",
    "that", "the", "their", "then", "this", "through", "was", "were", "will",
    "with", "you", "your",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256_hex(value: bytes | str) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def convex_http_url(deployment_url: str) -> str:
    match = re.fullmatch(r"https://([a-z0-9-]+)\.convex\.cloud/?", deployment_url)
    if not match:
        raise ValueError("Convex URL must be an https://*.convex.cloud deployment URL")
    return f"https://{match.group(1)}.convex.site"


def keychain_password(service: str, account: str) -> str:
    if os.name != "posix":
        raise RuntimeError("macOS Keychain access is unavailable on this platform")
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", service, "-w"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            f"Could not retrieve Keychain item {service!r}, account {account!r}"
        ) from error
    value = result.stdout.rstrip("\n")
    if not value:
        raise RuntimeError(f"Keychain item {service!r}, account {account!r} is empty")
    return value


def operator_token(token_source: str = "auto") -> str:
    if token_source not in {"auto", "keychain", "environment"}:
        raise ValueError(f"Unsupported operator token source {token_source!r}")
    explicit = os.environ.get("WATCHCRAFT_AUTHORING_OPERATOR_TOKEN")
    if token_source in {"auto", "environment"} and explicit:
        if len(explicit) != 64:
            raise RuntimeError("WATCHCRAFT_AUTHORING_OPERATOR_TOKEN must contain 64 characters")
        return explicit
    if token_source == "environment":
        raise RuntimeError(
            "WATCHCRAFT_AUTHORING_OPERATOR_TOKEN is required when "
            "--operator-token-source environment is selected"
        )
    try:
        token = keychain_password(OPERATOR_KEYCHAIN_SERVICE, OPERATOR_KEYCHAIN_ACCOUNT)
    except RuntimeError as error:
        raise RuntimeError(
            f"Could not retrieve {OPERATOR_KEYCHAIN_SERVICE!r} from Keychain. "
            "Set WATCHCRAFT_AUTHORING_OPERATOR_TOKEN and select "
            "--operator-token-source environment to use an explicit override"
        ) from error
    if len(token) != 64:
        raise RuntimeError("The Keychain operator token is not a 64-character token")
    return token


def registry_admin_token(token_source: str = "auto") -> str:
    if token_source not in {"auto", "keychain", "environment"}:
        raise ValueError(f"Unsupported registry admin token source {token_source!r}")
    environment_name = "WATCHCRAFT_AUTHORING_REGISTRY_ADMIN_TOKEN"
    explicit = os.environ.get(environment_name)
    if token_source in {"auto", "environment"} and explicit:
        if len(explicit) != 64:
            raise RuntimeError(f"{environment_name} must contain 64 characters")
        return explicit
    if token_source == "environment":
        raise RuntimeError(
            f"{environment_name} is required when --registry-admin-token-source "
            "environment is selected"
        )
    try:
        token = keychain_password(
            REGISTRY_ADMIN_KEYCHAIN_SERVICE,
            REGISTRY_ADMIN_KEYCHAIN_ACCOUNT,
        )
    except RuntimeError as error:
        raise RuntimeError(
            f"Could not retrieve {REGISTRY_ADMIN_KEYCHAIN_SERVICE!r} from Keychain. "
            f"Set {environment_name} and select --registry-admin-token-source "
            "environment to use an explicit override"
        ) from error
    if len(token) != 64:
        raise RuntimeError("The Keychain registry admin token is not a 64-character token")
    return token


def production_configuration(name: str) -> str:
    explicit = os.environ.get(name)
    if explicit:
        return explicit
    try:
        result = subprocess.run(
            [
                "gh", "variable", "get", name,
                "--env", "authoring-production", "--repo", DEFAULT_GITHUB_REPOSITORY,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            f"Set {name} or authenticate the GitHub CLI"
        ) from error
    value = result.stdout.strip()
    if not value:
        raise RuntimeError(f"GitHub returned an empty {name}")
    return value


def production_convex_url() -> str:
    return production_configuration("WATCHCRAFT_CONVEX_URL")


def r2_reader_credentials(credential_source: str = "auto") -> tuple[str, str]:
    if credential_source not in {"auto", "keychain", "environment"}:
        raise ValueError(f"Unsupported R2 credential source {credential_source!r}")
    access_key = os.environ.get(R2_READER_ACCESS_KEY_ENV, "")
    secret_key = os.environ.get(R2_READER_SECRET_KEY_ENV, "")
    if credential_source in {"auto", "environment"} and (access_key or secret_key):
        if not access_key or not secret_key:
            raise RuntimeError(
                f"{R2_READER_ACCESS_KEY_ENV} and {R2_READER_SECRET_KEY_ENV} "
                "must be set together"
            )
        return access_key, secret_key
    if credential_source == "environment":
        raise RuntimeError(
            f"{R2_READER_ACCESS_KEY_ENV} and {R2_READER_SECRET_KEY_ENV} are "
            "required when --r2-credentials-source environment is selected"
        )
    try:
        return (
            keychain_password(R2_READER_KEYCHAIN_SERVICE, R2_READER_ACCESS_KEY_ACCOUNT),
            keychain_password(R2_READER_KEYCHAIN_SERVICE, R2_READER_SECRET_KEY_ACCOUNT),
        )
    except RuntimeError as error:
        raise RuntimeError(
            f"Could not retrieve read-only R2 credentials from "
            f"{R2_READER_KEYCHAIN_SERVICE!r}. Set both {R2_READER_ACCESS_KEY_ENV} "
            f"and {R2_READER_SECRET_KEY_ENV} and select "
            "--r2-credentials-source environment to use an explicit override"
        ) from error


@dataclass
class AuthoringHttpClient:
    deployment_url: str
    token: str
    prefix: str

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{convex_http_url(self.deployment_url)}{self.prefix}{path}",
            data=canonical_json(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "WatchcraftAuthor/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read().decode("utf-8")).get("error")
            except (json.JSONDecodeError, AttributeError):
                detail = None
            raise RuntimeError(detail or f"Authoring control request failed with HTTP {error.code}") from error
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Authoring control request failed: {error}") from error
        if not isinstance(result, dict):
            raise RuntimeError("Authoring control returned an invalid response")
        return result


def operator_client(token_source: str = "auto") -> AuthoringHttpClient:
    return AuthoringHttpClient(
        production_convex_url(),
        operator_token(token_source),
        "/authoring/operator",
    )


def registry_admin_client(token_source: str = "auto") -> AuthoringHttpClient:
    return AuthoringHttpClient(
        production_convex_url(),
        registry_admin_token(token_source),
        "/authoring/admin",
    )


def worker_client() -> AuthoringHttpClient:
    deployment_url = os.environ.get("WATCHCRAFT_CONVEX_URL", "")
    token = os.environ.get("WATCHCRAFT_AUTHORING_WORKER_TOKEN", "")
    if not deployment_url or not token:
        raise RuntimeError("WATCHCRAFT_CONVEX_URL and WATCHCRAFT_AUTHORING_WORKER_TOKEN are required")
    return AuthoringHttpClient(deployment_url, token, "/authoring")


def lexical_analysis(job: dict[str, Any]) -> dict[str, Any]:
    configuration = job["spec"]["configuration"]
    text = configuration.get("text")
    title = configuration.get("title")
    maximum = configuration.get("max_topics", 8)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("analysis text must be non-empty")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("analysis title must be non-empty")
    if not isinstance(maximum, int) or not 1 <= maximum <= 20:
        raise ValueError("max_topics must be between 1 and 20")
    normalized = " ".join(text.split())
    counts = Counter(
        word.casefold()
        for word in WORD_PATTERN.findall(normalized)
        if word.casefold() not in STOP_WORDS
    )
    topics = [word for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:maximum]]
    return {
        "kind": "watchcraft.analysis.lexical",
        "schema_version": 1,
        "source": job["spec"]["source"],
        "title": title.strip(),
        "summary": normalized[:240],
        "topics": topics,
        "metrics": {
            "characters": len(text),
            "words": len(WORD_PATTERN.findall(normalized)),
            "unique_terms": len(counts),
        },
        "provenance": {
            "handler_id": ANALYSIS_HANDLER[0],
            "handler_version": ANALYSIS_HANDLER[1],
            "job_id": job["job_id"],
            "spec_sha256": job["spec_sha256"],
        },
    }


HANDLERS: dict[tuple[str, str], Callable[[dict[str, Any]], dict[str, Any]]] = {
    ANALYSIS_HANDLER: lexical_analysis,
}
LOCAL_HANDLER_CONTRACTS: dict[tuple[str, str], dict[str, Any]] = {
    ANALYSIS_HANDLER: {
        "id": ANALYSIS_HANDLER[0],
        "version": ANALYSIS_HANDLER[1],
        "operation": "generate",
        "inputs": [],
        "dependencies": [],
        "output": {
            "artifact_kind": "analysis",
            "schema": {"id": "watchcraft.analysis.lexical", "version": 1},
        },
        "execution_profile": {
            "id": PYTHON_EXECUTION_PROFILE[0],
            "version": PYTHON_EXECUTION_PROFILE[1],
        },
        "lease_class": "short",
        "retry_policy": {
            "max_attempts": 3,
            "retryable_classifications": ["artifact_store_failed", "lease_expired"],
        },
    },
}
LOCAL_EXECUTION_PROFILE = {
    "id": PYTHON_EXECUTION_PROFILE[0],
    "version": PYTHON_EXECUTION_PROFILE[1],
    "dispatcher": {"kind": "github-actions", "workflow": PYTHON_EXECUTION_WORKFLOW},
    "platform": {"os": "linux", "architecture": "x64"},
    "dependency_class": "python-authoring-worker",
    "cache_class": "pip",
    "timeout_minutes": 15,
    "lease_duration_ms": 300_000,
    "heartbeat_interval_ms": 60_000,
    "data_access": "public",
    "secret_capabilities": ["convex.worker", "r2.read-write"],
}


class RegistrySupportError(RuntimeError):
    """An approved registry resolution cannot be executed by this worker."""

    def __init__(self, message: str, classification: str = "invalid_registry_snapshot"):
        super().__init__(message)
        self.classification = classification


def validate_registry_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    spec = job.get("spec")
    if not isinstance(spec, dict):
        raise RegistrySupportError("Job specification is missing")
    snapshot = spec.get("registry_snapshot")
    if not isinstance(snapshot, dict):
        raise RegistrySupportError("Job specification has no capability registry snapshot")
    registry_digest = snapshot.get("registry_sha256")
    if not isinstance(registry_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", registry_digest):
        raise RegistrySupportError("Job registry snapshot has an invalid digest")
    handler = snapshot.get("handler")
    profile = snapshot.get("execution_profile")
    if not isinstance(handler, dict) or not isinstance(profile, dict):
        raise RegistrySupportError("Job registry snapshot is incomplete")

    handler_key = (spec.get("handler", {}).get("id"), spec.get("handler", {}).get("version"))
    if handler_key not in HANDLERS:
        raise RegistrySupportError(
            f"Unsupported authoring handler {handler_key[0]}@{handler_key[1]}",
            "unsupported_handler",
        )
    if handler != LOCAL_HANDLER_CONTRACTS[handler_key]:
        raise RegistrySupportError(
            "Resolved handler contract is unsupported by this worker",
            "unsupported_handler",
        )
    if handler.get("operation") != spec.get("operation") or handler.get("output") != {
        "artifact_kind": spec.get("artifact_kind"), "schema": spec.get("output_schema")
    }:
        raise RegistrySupportError("Resolved handler contract does not match the job specification")
    for field in ("inputs", "dependencies"):
        references = spec.get(field)
        contracts = handler.get(field)
        if not isinstance(references, list) or len(references) != len(contracts):
            raise RegistrySupportError(
                f"Resolved handler {field} do not match the job specification"
            )
        for reference, contract in zip(references, contracts):
            if not isinstance(reference, dict) or {
                "artifact_kind": reference.get("artifact_kind"),
                "schema": reference.get("schema"),
            } != contract:
                raise RegistrySupportError(
                    f"Resolved handler {field} do not match the job specification"
                )

    expected_profile = (
        os.environ.get("WATCHCRAFT_EXECUTION_PROFILE_ID", PYTHON_EXECUTION_PROFILE[0]),
        os.environ.get("WATCHCRAFT_EXECUTION_PROFILE_VERSION", PYTHON_EXECUTION_PROFILE[1]),
    )
    profile_key = (profile.get("id"), profile.get("version"))
    if profile_key != expected_profile:
        raise RegistrySupportError(
            f"Worker profile {expected_profile[0]}@{expected_profile[1]} cannot execute "
            f"{profile_key[0]}@{profile_key[1]}",
            "unsupported_execution_profile",
        )
    if handler.get("execution_profile") != {
        "id": profile_key[0], "version": profile_key[1]
    }:
        raise RegistrySupportError("Resolved handler references a different execution profile")
    if profile != LOCAL_EXECUTION_PROFILE:
        raise RegistrySupportError(
            "Execution profile contract is unsupported by this worker",
            "unsupported_execution_profile",
        )
    return profile


def dispatch_workflow(job: dict[str, Any]) -> str:
    snapshot = job.get("spec", {}).get("registry_snapshot")
    if snapshot is None:
        return PYTHON_EXECUTION_WORKFLOW
    try:
        dispatcher = snapshot["execution_profile"]["dispatcher"]
        kind = dispatcher["kind"]
        workflow = dispatcher["workflow"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("Approved job has an invalid execution dispatcher") from error
    if kind != "github-actions" or not isinstance(workflow, str):
        raise RuntimeError("Approved job has an unsupported execution dispatcher")
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.ya?ml", workflow):
        raise RuntimeError("Approved job has an unsafe GitHub Actions workflow name")
    return workflow


class R2ArtifactStore:
    def __init__(self, client: Any, bucket: str):
        self.client = client
        self.bucket = bucket

    @classmethod
    def from_configuration(
        cls,
        *,
        endpoint: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> "R2ArtifactStore":
        try:
            import boto3
        except ImportError as error:
            raise RuntimeError("Install the authoring requirements to use R2") from error
        client = boto3.client(
            "s3",
            region_name="auto",
            endpoint_url=endpoint.rstrip("/"),
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )
        return cls(client, bucket)

    @classmethod
    def from_environment(cls) -> "R2ArtifactStore":
        names = (
            "WATCHCRAFT_R2_ENDPOINT", "WATCHCRAFT_R2_BUCKET",
            "WATCHCRAFT_R2_ACCESS_KEY_ID", "WATCHCRAFT_R2_SECRET_ACCESS_KEY",
        )
        required = {name: os.environ.get(name, "") for name in names}
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Missing R2 configuration: {', '.join(missing)}")
        return cls.from_configuration(
            endpoint=required["WATCHCRAFT_R2_ENDPOINT"],
            bucket=required["WATCHCRAFT_R2_BUCKET"],
            access_key_id=required["WATCHCRAFT_R2_ACCESS_KEY_ID"],
            secret_access_key=required["WATCHCRAFT_R2_SECRET_ACCESS_KEY"],
        )

    def put_json(self, value: dict[str, Any], description: dict[str, Any]) -> dict[str, Any]:
        payload = canonical_json(value).encode("utf-8")
        digest = sha256_hex(payload)
        key = f"objects/sha256/{digest[:2]}/{digest[2:]}"
        reference = {
            "store": "r2",
            "algorithm": "sha256",
            "digest": digest,
            "byte_length": len(payload),
            "media_type": "application/json",
            "artifact_kind": description["artifact_kind"],
            "schema": description["schema"],
            "key": key,
        }
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            status = getattr(error, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = getattr(error, "response", {}).get("Error", {}).get("Code")
            if status != 404 and code not in {"404", "NoSuchKey", "NotFound"}:
                raise
            try:
                self.client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=payload,
                    ContentLength=len(payload),
                    ContentType="application/json",
                    IfNoneMatch="*",
                    Metadata={"sha256": digest, "artifact_kind": description["artifact_kind"]},
                )
            except Exception as put_error:
                put_status = getattr(put_error, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
                if put_status != 412:
                    raise
        if self.get_bytes(reference) != payload:
            raise RuntimeError("R2 artifact did not round-trip exactly")
        return reference

    def get_bytes(self, reference: dict[str, Any]) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=reference["key"])
        except Exception as error:
            raise RuntimeError(f"Could not read R2 artifact {reference['key']}") from error
        payload = response["Body"].read()
        if len(payload) != reference["byte_length"] or sha256_hex(payload) != reference["digest"]:
            raise RuntimeError("R2 artifact failed content verification")
        return payload


def validated_artifact_reference(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("The completed job has an invalid artifact reference")
    digest = value.get("digest")
    byte_length = value.get("byte_length")
    media_type = value.get("media_type")
    if value.get("store") != "r2" or value.get("algorithm") != "sha256":
        raise RuntimeError("The completed job does not reference a SHA-256 R2 artifact")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise RuntimeError("The completed job has an invalid artifact digest")
    expected_key = f"objects/sha256/{digest[:2]}/{digest[2:]}"
    if value.get("key") != expected_key:
        raise RuntimeError("The artifact key does not match its content digest")
    if (
        isinstance(byte_length, bool)
        or not isinstance(byte_length, int)
        or byte_length < 0
    ):
        raise RuntimeError("The completed job has an invalid artifact byte length")
    if not isinstance(media_type, str) or not media_type:
        raise RuntimeError("The completed job has an invalid artifact media type")
    return dict(value)


def r2_artifact_reader(credential_source: str = "auto") -> R2ArtifactStore:
    access_key, secret_key = r2_reader_credentials(credential_source)
    return R2ArtifactStore.from_configuration(
        endpoint=production_configuration("WATCHCRAFT_R2_ENDPOINT"),
        bucket=production_configuration("WATCHCRAFT_R2_BUCKET"),
        access_key_id=access_key,
        secret_access_key=secret_key,
    )


def run_worker(*, job_id: str, spec_sha256: str, dispatch_generation: int, expected_revision: int) -> dict[str, Any]:
    control = worker_client()
    run_id = os.environ.get("GITHUB_RUN_ID", "local-worker")
    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repository = os.environ.get("GITHUB_REPOSITORY", DEFAULT_GITHUB_REPOSITORY)
    run_url = f"{server_url}/{repository}/actions/runs/{run_id}"
    job = control.post("/jobs/dispatch/record", {
        "job_id": job_id,
        "command_id": f"dispatch:{dispatch_generation}:record",
        "expected_revision": expected_revision,
        "generation": dispatch_generation,
        "github_run_id": run_id,
        "github_run_url": run_url,
    })
    snapshot = job.get("spec", {}).get("registry_snapshot", {})
    configured_lease = snapshot.get("execution_profile", {}).get("lease_duration_ms")
    lease_duration_ms = (
        configured_lease
        if isinstance(configured_lease, int) and 1_000 <= configured_lease <= 3_600_000
        else 300_000
    )
    attempt_id = str(uuid.uuid4())
    job = control.post("/jobs/claim", {
        "job_id": job_id,
        "command_id": f"{attempt_id}:claim",
        "expected_revision": job["revision"],
        "attempt_id": attempt_id,
        "owner": f"github-actions:{run_id}",
        "spec_sha256": spec_sha256,
        "dispatch_generation": dispatch_generation,
        "lease_duration_ms": lease_duration_ms,
        "github_run_id": run_id,
    })
    try:
        validate_registry_snapshot(job)
    except RegistrySupportError as error:
        control.post("/jobs/fail", {
            "job_id": job_id,
            "command_id": f"{attempt_id}:registry-reject",
            "expected_revision": job["revision"],
            "attempt_id": attempt_id,
            "failure": {
                "classification": error.classification,
                "message": str(error)[:500],
                "retryable": False,
            },
        })
        raise
    job = control.post("/jobs/start", {
        "job_id": job_id,
        "command_id": f"{attempt_id}:start",
        "expected_revision": job["revision"],
        "attempt_id": attempt_id,
    })
    handler_key = (job["spec"]["handler"]["id"], job["spec"]["handler"]["version"])
    handler = HANDLERS[handler_key]
    try:
        output = handler(job)
    except Exception as error:
        control.post("/jobs/fail", {
            "job_id": job_id,
            "command_id": f"{attempt_id}:handler-fail",
            "expected_revision": job["revision"],
            "attempt_id": attempt_id,
            "failure": {
                "classification": "handler_failed",
                "message": str(error)[:500],
                "retryable": False,
            },
        })
        raise
    try:
        artifact = R2ArtifactStore.from_environment().put_json(output, {
            "artifact_kind": job["spec"]["artifact_kind"],
            "schema": job["spec"]["output_schema"],
        })
    except Exception as error:
        control.post("/jobs/fail", {
            "job_id": job_id,
            "command_id": f"{attempt_id}:storage-fail",
            "expected_revision": job["revision"],
            "attempt_id": attempt_id,
            "failure": {
                "classification": "artifact_store_failed",
                "message": str(error)[:500],
                "retryable": True,
            },
        })
        raise
    return control.post("/jobs/succeed", {
        "job_id": job_id,
        "command_id": f"{attempt_id}:succeed",
        "expected_revision": job["revision"],
        "attempt_id": attempt_id,
        "artifact": artifact,
    })


def analysis_spec(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "operation": "generate",
        "artifact_kind": "analysis",
        "output_schema": {"id": "watchcraft.analysis.lexical", "version": 1},
        "handler": {"id": ANALYSIS_HANDLER[0], "version": ANALYSIS_HANDLER[1]},
        "source": {"media_asset_id": args.source_id},
        "inputs": [],
        "dependencies": [],
        "configuration": {
            "title": args.title,
            "text": args.text,
            "max_topics": args.max_topics,
        },
    }


def add_queue_parsers(parent: argparse.ArgumentParser) -> None:
    parent.description = (
        "Submit, approve, dispatch, and inspect durable remote authoring jobs."
    )
    parent.epilog = (
        "Operator authentication defaults to WATCHCRAFT_AUTHORING_OPERATOR_TOKEN "
        "when set, then the macOS login Keychain. Raw tokens are intentionally not "
        "accepted as command-line values."
    )
    commands = parent.add_subparsers(dest="queue_command", required=True)
    credentials = argparse.ArgumentParser(add_help=False)
    credentials.add_argument(
        "--operator-token-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help=(
            "Credential source: environment requires "
            "WATCHCRAFT_AUTHORING_OPERATOR_TOKEN; auto uses it when set and otherwise "
            "reads the macOS Keychain (default: auto)"
        ),
    )
    admin_credentials = argparse.ArgumentParser(add_help=False)
    admin_credentials.add_argument(
        "--registry-admin-token-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help=(
            "Registry administrator credential source: environment requires "
            "WATCHCRAFT_AUTHORING_REGISTRY_ADMIN_TOKEN; auto uses it when set and "
            "otherwise reads the macOS Keychain (default: auto)"
        ),
    )
    submit = commands.add_parser(
        "submit-analysis",
        parents=[credentials],
        help="Submit a deterministic analysis job",
        description="Submit a deterministic, non-transcript lexical-analysis job.",
    )
    submit.add_argument("--title", required=True)
    submit.add_argument("--text", required=True)
    submit.add_argument("--source-id", default="operator:lexical-analysis")
    submit.add_argument("--max-topics", type=int, default=8)
    command_help = {
        "status": "Show the authoritative job and run aggregates",
        "approve": "Approve the immutable job specification",
        "dispatch": "Request and launch the GitHub worker",
        "cancel": "Cancel an unfinished job",
        "retry": "Return a retryable failed job to the ready state",
    }
    for name, help_text in command_help.items():
        command = commands.add_parser(
            name,
            parents=[credentials],
            help=help_text,
            description=help_text + ".",
        )
        command.add_argument("job_id")
    result = commands.add_parser(
        "result",
        parents=[credentials],
        help="Retrieve and verify a completed job artifact",
        description=(
            "Retrieve the authoritative artifact from private R2 and verify its "
            "content digest before displaying or writing it."
        ),
    )
    result.add_argument("job_id")
    result.add_argument(
        "--r2-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help=(
            f"Read-only R2 credential source: environment uses {R2_READER_ACCESS_KEY_ENV} "
            f"and {R2_READER_SECRET_KEY_ENV}; auto uses them when set and otherwise "
            "reads the macOS Keychain (default: auto)"
        ),
    )
    result.add_argument(
        "--output",
        type=Path,
        metavar="PATH",
        help="Write the exact verified bytes to a new file instead of displaying JSON",
    )
    registry_status = commands.add_parser(
        "registry-status",
        parents=[credentials],
        help="Show the active capability registry",
        description="Show the active immutable capability registry for an environment.",
    )
    registry_status.add_argument("--environment", default="production")
    for name, help_text in {
        "registry-publish": "Publish an immutable capability registry version",
        "registry-activate": "Activate a published capability registry version",
    }.items():
        command = commands.add_parser(
            name,
            parents=[admin_credentials],
            help=help_text,
            description=help_text + ".",
        )
        command.add_argument(
            "registry_file",
            nargs="?",
            type=Path,
            default=DEFAULT_REGISTRY_PATH,
            help=f"Registry JSON document (default: {DEFAULT_REGISTRY_PATH})",
        )
        if name == "registry-activate":
            command.add_argument("--environment", default="production")
            command.add_argument("--expected-revision", required=True, type=int)


def load_registry_document(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read capability registry {path}: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError("Capability registry must be a JSON object")
    if (
        value.get("kind") != "watchcraft.authoring-capability-registry"
        or value.get("schema_version") != 1
        or not isinstance(value.get("registry_version"), str)
    ):
        raise RuntimeError("Capability registry has an unsupported schema")
    return value


def run_queue_command(args: argparse.Namespace) -> int:
    if args.queue_command in {"registry-publish", "registry-activate"}:
        registry = load_registry_document(args.registry_file)
        control = registry_admin_client(args.registry_admin_token_source)
        if args.queue_command == "registry-publish":
            result = control.post("/registry/publish", {
                "command_id": str(uuid.uuid4()),
                "actor": "watchcraft-author-cli",
                "registry": registry,
            })
        else:
            result = control.post("/registry/activate", {
                "environment": args.environment,
                "command_id": str(uuid.uuid4()),
                "actor": "watchcraft-author-cli",
                "registry_version": registry["registry_version"],
                "registry_sha256": sha256_hex(canonical_json(registry)),
                "expected_revision": args.expected_revision,
            })
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    control = operator_client(args.operator_token_source)
    if args.queue_command == "registry-status":
        result = control.post("/registry/get-active", {"environment": args.environment})
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.queue_command == "submit-analysis":
        if not 1 <= args.max_topics <= 20:
            raise ValueError("--max-topics must be between 1 and 20")
        job_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        result = control.post("/submissions/submit", {
            "job_id": job_id,
            "run_id": run_id,
            "command_prefix": str(uuid.uuid4()),
            "request": {"kind": "lexical-analysis", "source_id": args.source_id},
            "spec": analysis_spec(args),
        })
        print(canonical_json({"job": result["job"], "run": result["run"]}))
        return 0

    submission = control.post("/submissions/get", {"job_id": args.job_id})
    job = submission["job"]
    if args.queue_command == "status":
        print(json.dumps(submission, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.queue_command == "result":
        if job.get("state") != "succeeded" or job.get("result") is None:
            raise RuntimeError(
                f"Job {job['job_id']} is {job.get('state', 'unknown')}; "
                "a result is available only after it succeeds"
            )
        reference = validated_artifact_reference(job["result"])
        payload = r2_artifact_reader(args.r2_credentials_source).get_bytes(reference)
        if args.output is not None:
            try:
                with args.output.open("xb") as destination:
                    destination.write(payload)
            except FileExistsError as error:
                raise RuntimeError(
                    f"Refusing to overwrite existing output file {args.output}"
                ) from error
            except OSError as error:
                raise RuntimeError(f"Could not write artifact to {args.output}: {error}") from error
            print(
                f"wrote {len(payload)} verified bytes for {job['job_id']} to {args.output}"
            )
            return 0
        if reference["media_type"] != "application/json":
            raise RuntimeError(
                f"Artifact media type is {reference['media_type']}; use --output PATH"
            )
        try:
            result = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("The verified artifact is not valid UTF-8 JSON") from error
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.queue_command == "approve":
        result = control.post("/submissions/approve", {
            "job_id": job["job_id"],
            "command_id": str(uuid.uuid4()),
            "expected_revision": job["revision"],
            "actor": "watchcraft-author-cli",
            "spec_sha256": job["spec_sha256"],
        })
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.queue_command == "dispatch":
        if job["state"] == "ready":
            pending = control.post("/submissions/request-dispatch", {
                "job_id": job["job_id"],
                "command_id": str(uuid.uuid4()),
                "expected_revision": job["revision"],
            })
        elif job["state"] == "dispatch_pending":
            pending = job
        else:
            raise RuntimeError(
                f"Job {job['job_id']} is {job['state']}; expected ready or dispatch_pending"
            )
        workflow = dispatch_workflow(pending)
        subprocess.run([
            "gh", "workflow", "run", workflow, "--ref", "main",
            "--repo", DEFAULT_GITHUB_REPOSITORY,
            "-f", f"job_id={pending['job_id']}",
            "-f", f"spec_sha256={pending['spec_sha256']}",
            "-f", f"dispatch_generation={pending['dispatch']['generation']}",
            "-f", f"expected_revision={pending['revision']}",
        ], check=True)
        print(f"dispatched {pending['job_id']} generation {pending['dispatch']['generation']}")
        return 0
    endpoint = "/submissions/cancel" if args.queue_command == "cancel" else "/submissions/retry"
    result = control.post(endpoint, {
        "job_id": job["job_id"],
        "command_id": str(uuid.uuid4()),
        "expected_revision": job["revision"],
    })
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
