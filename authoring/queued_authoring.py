"""Operator and worker primitives for queued Watchcraft authoring."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from youtube_audio import (
    canonical_youtube_url,
    download_youtube_audio,
    youtube_video_id,
)
from youtube_discovery import (
    discover_youtube_playlist,
    discover_youtube_video,
    youtube_playlist_id,
)


OPERATOR_KEYCHAIN_ACCOUNT = "watchcraft-operator-cli"
OPERATOR_KEYCHAIN_SERVICE = "Watchcraft authoring operator token"
REGISTRY_ADMIN_KEYCHAIN_ACCOUNT = "watchcraft-registry-admin-cli"
REGISTRY_ADMIN_KEYCHAIN_SERVICE = "Watchcraft authoring registry admin token"
R2_READER_KEYCHAIN_SERVICE = "Watchcraft R2 artifact reader"
R2_READER_ACCESS_KEY_ACCOUNT = "access-key-id"
R2_READER_SECRET_KEY_ACCOUNT = "secret-access-key"
R2_READER_ACCESS_KEY_ENV = "WATCHCRAFT_R2_READER_ACCESS_KEY_ID"
R2_READER_SECRET_KEY_ENV = "WATCHCRAFT_R2_READER_SECRET_ACCESS_KEY"
R2_STAGING_KEYCHAIN_SERVICE = "Watchcraft R2 staging uploader"
R2_STAGING_ACCESS_KEY_ACCOUNT = "access-key-id"
R2_STAGING_SECRET_KEY_ACCOUNT = "secret-access-key"
R2_STAGING_ACCESS_KEY_ENV = "WATCHCRAFT_R2_STAGING_ACCESS_KEY_ID"
R2_STAGING_SECRET_KEY_ENV = "WATCHCRAFT_R2_STAGING_SECRET_ACCESS_KEY"
DEFAULT_GITHUB_REPOSITORY = "billbliss/watchcraft"
DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages" / "authoring-pipeline" / "registry" / "default-registry.json"
)
ANALYSIS_HANDLER = ("watchcraft.analysis.lexical", "1")
EDUCATIONAL_VIDEO_ANALYSIS_HANDLER = (
    "watchcraft.analysis.educational-video",
    "1",
)
TERMINOLOGY_RESOLUTION_HANDLER = (
    "watchcraft.resolve.collection-terminology",
    "7",
)
PREVIOUS_TERMINOLOGY_RESOLUTION_HANDLER = (
    "watchcraft.resolve.collection-terminology",
    "6",
)
TRANSCRIPTION_SMOKE_HANDLER = ("watchcraft.transcript.mlx-whisper-smoke", "1")
HTTP_TRANSCRIPTION_SMOKE_HANDLER = (
    "watchcraft.transcript.mlx-whisper-http-smoke",
    "1",
)
STAGED_TRANSCRIPTION_SMOKE_HANDLER = (
    "watchcraft.transcript.mlx-whisper-staged-smoke",
    "1",
)
PRODUCTION_TRANSCRIPTION_HANDLER = (
    "watchcraft.transcript.mlx-whisper-large-v3-turbo-q4",
    "1",
)
YOUTUBE_PLAYLIST_ITERATOR_HANDLER = (
    "watchcraft.iterator.youtube-playlist",
    "1",
)
PROJECT_PROCESSING_PLANNER_HANDLER = (
    "watchcraft.planner.video-collection",
    "1",
)
TOPIC_NORMALIZATION_HANDLER = (
    "watchcraft.normalize.collection-topics",
    "1",
)
COLLECTION_COMPILATION_HANDLER = (
    "watchcraft.compile.video-collection",
    "2",
)
PYTHON_EXECUTION_PROFILE = ("python-portable", "1")
PYTHON_EXECUTION_WORKFLOW = "authoring-worker.yml"
OPENAI_EXECUTION_PROFILE = ("python-openai", "1")
OPENAI_EXECUTION_WORKFLOW = "authoring-openai-worker.yml"
MLX_EXECUTION_PROFILE = ("macos-mlx", "1")
MLX_EXECUTION_WORKFLOW = "authoring-mlx-worker.yml"
TRANSCRIPTION_SMOKE_MODEL = "mlx-community/whisper-tiny-mlx"
PRODUCTION_TRANSCRIPTION_MODEL = "mlx-community/whisper-large-v3-turbo-q4"
EDUCATIONAL_VIDEO_ANALYSIS_MODEL = "gpt-5-nano"
EDUCATIONAL_VIDEO_ANALYSIS_PROMPT_VERSION = 3
EDUCATIONAL_VIDEO_ANALYSIS_MAX_TRANSCRIPT_CHARS = 1_500_000
EDUCATIONAL_VIDEO_ANALYSIS_RETRIES = 5
EDUCATIONAL_VIDEO_ANALYSIS_TIMEOUT_SECONDS = 300
TOPIC_NORMALIZATION_MODEL = "gpt-5.4-mini"
TOPIC_NORMALIZATION_PROMPT_VERSION = 2
TOPIC_DISPLAY_LABEL_PROMPT_VERSION = 1
TOPIC_NORMALIZATION_BATCH_SIZE = 40
TOPIC_NORMALIZATION_RETRIES = 5
TOPIC_NORMALIZATION_TIMEOUT_SECONDS = 300
TERMINOLOGY_RESOLUTION_MODEL = "gpt-5.4-mini"
TERMINOLOGY_RESOLUTION_PROMPT_VERSION = 2
TERMINOLOGY_RESOLUTION_RETRIES = 5
TERMINOLOGY_RESOLUTION_TIMEOUT_SECONDS = 300
TERMINOLOGY_RESOLUTION_BATCH_MAX_TERMS = 24
TERMINOLOGY_RESOLUTION_BATCH_MAX_CHARS = 60_000
VIDEO_ANALYSIS_SCHEMA = {"id": "watchcraft.video-analysis", "version": 2}
TERMINOLOGY_RESOLUTION_SCHEMA = {
    "id": "watchcraft.terminology-resolution",
    "version": 1,
}
TERMINOLOGY_RESOLUTION_CHECKPOINT_SCHEMA = {
    "id": "watchcraft.terminology-resolution-checkpoint",
    "version": 1,
}
TOPIC_NORMALIZATION_SCHEMA = {"id": "watchcraft.topic-normalization", "version": 1}
COLLECTION_COMPILATION_SCHEMA = {
    "id": "watchcraft.collection-compilation",
    "version": 1,
}
TRANSCRIPTION_SMOKE_TEXT = (
    "Watchcraft verifies real audio transcription on an Apple silicon worker."
)
HTTP_TRANSCRIPTION_SMOKE_URL = (
    "https://raw.githubusercontent.com/openai/whisper/"
    "86098128c0b4f24f0e2aa2994de830614b474227/tests/jfk.flac"
)
HTTP_TRANSCRIPTION_SMOKE_SHA256 = (
    "63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715"
)
HTTP_TRANSCRIPTION_SMOKE_BYTES = 1_152_693
HTTP_TRANSCRIPTION_SMOKE_MAX_BYTES = 2_000_000
HTTP_TRANSCRIPTION_SMOKE_TIMEOUT_SECONDS = 60
YOUTUBE_TRANSCRIPTION_SMOKE_URL = "https://www.youtube.com/watch?v=D_jOvlB_D7A"
YOUTUBE_TRANSCRIPTION_SMOKE_MAX_BYTES = 10_000_000
YOUTUBE_TRANSCRIPTION_SMOKE_MAX_DURATION_SECONDS = 300
YOUTUBE_TRANSCRIPTION_SMOKE_TIMEOUT_SECONDS = 180
YOUTUBE_TRANSCRIPTION_MAX_BYTES = 100_000_000
YOUTUBE_TRANSCRIPTION_MAX_DURATION_SECONDS = 7_200
YOUTUBE_TRANSCRIPTION_TIMEOUT_SECONDS = 900
SOURCE_AUDIO_RETENTION_MILLISECONDS = 86_400_000
SOURCE_AUDIO_SCHEMA = {"id": "watchcraft.source-audio", "version": 1}
COLLECTION_ITERATOR_SNAPSHOT_SCHEMA = {
    "id": "watchcraft.collection-iterator-snapshot",
    "version": 1,
}
COLLECTION_ITERATOR_CHECKPOINT_SCHEMA = {
    "id": "watchcraft.collection-iterator-checkpoint",
    "version": 1,
}
PROJECT_PROCESSING_PLAN_SCHEMA = {
    "id": "watchcraft.project-processing-plan",
    "version": 1,
}
CATALOG_PROJECT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "authoring-pipeline"
    / "project"
    / "catalog-project.schema.json"
)
ITERATOR_SNAPSHOT_SCHEMA_PATH = CATALOG_PROJECT_SCHEMA_PATH.with_name(
    "collection-iterator-snapshot.schema.json"
)
PROJECT_PROCESSING_PLAN_SCHEMA_PATH = CATALOG_PROJECT_SCHEMA_PATH.with_name(
    "project-processing-plan.schema.json"
)
TERMINOLOGY_RESOLUTION_SCHEMA_PATH = CATALOG_PROJECT_SCHEMA_PATH.with_name(
    "terminology-resolution.schema.json"
)
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


def r2_staging_credentials(credential_source: str = "auto") -> tuple[str, str]:
    if credential_source not in {"auto", "keychain", "environment"}:
        raise ValueError(f"Unsupported R2 staging credential source {credential_source!r}")
    access_key = os.environ.get(R2_STAGING_ACCESS_KEY_ENV, "")
    secret_key = os.environ.get(R2_STAGING_SECRET_KEY_ENV, "")
    if credential_source in {"auto", "environment"} and (access_key or secret_key):
        if not access_key or not secret_key:
            raise RuntimeError(
                f"{R2_STAGING_ACCESS_KEY_ENV} and {R2_STAGING_SECRET_KEY_ENV} "
                "must be set together"
            )
        return access_key, secret_key
    if credential_source == "environment":
        raise RuntimeError(
            f"{R2_STAGING_ACCESS_KEY_ENV} and {R2_STAGING_SECRET_KEY_ENV} are "
            "required when --r2-staging-credentials-source environment is selected"
        )
    try:
        return (
            keychain_password(
                R2_STAGING_KEYCHAIN_SERVICE,
                R2_STAGING_ACCESS_KEY_ACCOUNT,
            ),
            keychain_password(
                R2_STAGING_KEYCHAIN_SERVICE,
                R2_STAGING_SECRET_KEY_ACCOUNT,
            ),
        )
    except RuntimeError as error:
        raise RuntimeError(
            f"Could not retrieve R2 staging credentials from "
            f"{R2_STAGING_KEYCHAIN_SERVICE!r}. Set both {R2_STAGING_ACCESS_KEY_ENV} "
            f"and {R2_STAGING_SECRET_KEY_ENV} and select "
            "--r2-staging-credentials-source environment to use an explicit override"
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


def lexical_analysis(
    job: dict[str, Any], context: WorkerContext | None = None
) -> dict[str, Any]:
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


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(child) for child in value]
    if hasattr(value, "item"):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def mlx_transcribe_file(audio_path: Path, *, language: str, model: str) -> dict[str, Any]:
    try:
        import mlx_whisper
    except ImportError as error:
        raise RuntimeError("mlx-whisper is required by the macos-mlx worker") from error
    result = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=model,
        language=language,
        task="transcribe",
        word_timestamps=True,
        temperature=0.0,
        condition_on_previous_text=False,
        verbose=None,
    )
    safe_result = json_safe(result)
    if not isinstance(safe_result, dict):
        raise RuntimeError("MLX Whisper returned an invalid transcript result")
    segments = safe_result.get("segments", [])
    if not isinstance(segments, list):
        raise RuntimeError("MLX Whisper returned invalid transcript segments")
    text = " ".join(
        " ".join(str(segment.get("text", "")).split())
        for segment in segments
        if isinstance(segment, dict) and str(segment.get("text", "")).strip()
    ).strip()
    if not text:
        raise RuntimeError("MLX Whisper returned an empty transcript")
    return {
        "language": safe_result.get("language") or language,
        "text": text,
        "segments": segments,
    }


def download_verified_https(
    url: str,
    destination: Path,
    *,
    expected_sha256: str,
    expected_bytes: int,
    maximum_bytes: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("remote audio must use an HTTPS URL without embedded credentials")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ValueError("remote audio expected_sha256 must be a lowercase SHA-256 digest")
    if not 0 < expected_bytes <= maximum_bytes:
        raise ValueError("remote audio byte limits are invalid")
    if not 1 <= timeout_seconds <= 300:
        raise ValueError("remote audio timeout must be between 1 and 300 seconds")

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "audio/*,application/octet-stream;q=0.9",
            "User-Agent": "WatchcraftAuthor/0.1",
        },
    )
    digest = hashlib.sha256()
    byte_length = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            resolved = urllib.parse.urlsplit(response.geturl())
            if resolved.scheme != "https":
                raise RuntimeError("remote audio redirected away from HTTPS")
            declared_length = response.headers.get("Content-Length")
            if declared_length is not None:
                try:
                    declared_bytes = int(declared_length)
                except ValueError as error:
                    raise RuntimeError("remote audio returned an invalid Content-Length") from error
                if declared_bytes > maximum_bytes:
                    raise RuntimeError(
                        f"remote audio declares {declared_bytes} bytes; limit is {maximum_bytes}"
                    )
            with destination.open("xb") as output:
                while chunk := response.read(64 * 1024):
                    byte_length += len(chunk)
                    if byte_length > maximum_bytes:
                        raise RuntimeError(
                            f"remote audio exceeded the {maximum_bytes}-byte limit"
                        )
                    digest.update(chunk)
                    output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    actual_sha256 = digest.hexdigest()
    if byte_length != expected_bytes:
        destination.unlink(missing_ok=True)
        raise RuntimeError(
            f"remote audio has {byte_length} bytes; expected {expected_bytes}"
        )
    if actual_sha256 != expected_sha256:
        destination.unlink(missing_ok=True)
        raise RuntimeError(
            f"remote audio SHA-256 is {actual_sha256}; expected {expected_sha256}"
        )
    return {
        "url": url,
        "algorithm": "sha256",
        "digest": actual_sha256,
        "byte_length": byte_length,
    }


def mlx_transcription_smoke(
    job: dict[str, Any], context: WorkerContext | None = None
) -> dict[str, Any]:
    configuration = job["spec"]["configuration"]
    phrase = configuration.get("fixture_text")
    language = configuration.get("language", "en")
    model = configuration.get("model", TRANSCRIPTION_SMOKE_MODEL)
    if not isinstance(phrase, str) or not phrase.strip() or len(phrase) > 500:
        raise ValueError("fixture_text must contain between 1 and 500 characters")
    if language != "en":
        raise ValueError("the initial MLX transcription smoke supports only English")
    if model != TRANSCRIPTION_SMOKE_MODEL:
        raise ValueError(f"the initial MLX transcription smoke requires {TRANSCRIPTION_SMOKE_MODEL}")

    with tempfile.TemporaryDirectory(prefix="watchcraft-mlx-smoke-") as directory:
        audio_path = Path(directory) / "fixture.aiff"
        try:
            subprocess.run(
                ["say", "-r", "155", "-o", str(audio_path), phrase],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise RuntimeError("macOS could not synthesize the transcription fixture") from error
        transcript = mlx_transcribe_file(audio_path, language=language, model=model)

    return {
        "kind": "watchcraft.transcript",
        "schema_version": 1,
        "source": job["spec"]["source"],
        "model": model,
        **transcript,
        "provenance": {
            "handler_id": TRANSCRIPTION_SMOKE_HANDLER[0],
            "handler_version": TRANSCRIPTION_SMOKE_HANDLER[1],
            "job_id": job["job_id"],
            "spec_sha256": job["spec_sha256"],
            "fixture_generator": "macos-say",
            "fixture_text_sha256": sha256_hex(phrase),
            "audio_retained": False,
        },
    }


def mlx_http_transcription_smoke(
    job: dict[str, Any], context: WorkerContext | None = None
) -> dict[str, Any]:
    configuration = job["spec"]["configuration"]
    expected_configuration = {
        "url": HTTP_TRANSCRIPTION_SMOKE_URL,
        "expected_sha256": HTTP_TRANSCRIPTION_SMOKE_SHA256,
        "expected_bytes": HTTP_TRANSCRIPTION_SMOKE_BYTES,
        "maximum_bytes": HTTP_TRANSCRIPTION_SMOKE_MAX_BYTES,
        "timeout_seconds": HTTP_TRANSCRIPTION_SMOKE_TIMEOUT_SECONDS,
        "language": "en",
        "model": TRANSCRIPTION_SMOKE_MODEL,
    }
    if configuration != expected_configuration:
        raise ValueError("the HTTP transcription smoke requires its pinned fixture configuration")

    with tempfile.TemporaryDirectory(prefix="watchcraft-mlx-http-smoke-") as directory:
        audio_path = Path(directory) / "fixture.flac"
        acquisition = download_verified_https(
            configuration["url"],
            audio_path,
            expected_sha256=configuration["expected_sha256"],
            expected_bytes=configuration["expected_bytes"],
            maximum_bytes=configuration["maximum_bytes"],
            timeout_seconds=configuration["timeout_seconds"],
        )
        transcript = mlx_transcribe_file(
            audio_path,
            language=configuration["language"],
            model=configuration["model"],
        )

    return {
        "kind": "watchcraft.transcript",
        "schema_version": 1,
        "source": job["spec"]["source"],
        "model": configuration["model"],
        **transcript,
        "provenance": {
            "handler_id": HTTP_TRANSCRIPTION_SMOKE_HANDLER[0],
            "handler_version": HTTP_TRANSCRIPTION_SMOKE_HANDLER[1],
            "job_id": job["job_id"],
            "spec_sha256": job["spec_sha256"],
            "fixture_source": "openai/whisper tests/jfk.flac",
            "acquisition": acquisition,
            "audio_retained": False,
        },
    }


class StagedSourceError(RuntimeError):
    """An approved staged source-media input cannot be consumed."""

    def __init__(self, message: str, classification: str, retryable: bool):
        super().__init__(message)
        self.classification = classification
        self.retryable = retryable


STAGED_TRANSCRIPTION_SETTINGS = {
    STAGED_TRANSCRIPTION_SMOKE_HANDLER: {
        "model": TRANSCRIPTION_SMOKE_MODEL,
        "maximum_bytes": YOUTUBE_TRANSCRIPTION_SMOKE_MAX_BYTES,
        "maximum_duration_seconds": YOUTUBE_TRANSCRIPTION_SMOKE_MAX_DURATION_SECONDS,
    },
    PRODUCTION_TRANSCRIPTION_HANDLER: {
        "model": PRODUCTION_TRANSCRIPTION_MODEL,
        "maximum_bytes": YOUTUBE_TRANSCRIPTION_MAX_BYTES,
        "maximum_duration_seconds": YOUTUBE_TRANSCRIPTION_MAX_DURATION_SECONDS,
    },
}
MLX_MODEL_CACHE_KEYS = {
    TRANSCRIPTION_SMOKE_HANDLER: "whisper-tiny-mlx",
    HTTP_TRANSCRIPTION_SMOKE_HANDLER: "whisper-tiny-mlx",
    STAGED_TRANSCRIPTION_SMOKE_HANDLER: "whisper-tiny-mlx",
    PRODUCTION_TRANSCRIPTION_HANDLER: "whisper-large-v3-turbo-q4",
}


def elapsed_milliseconds(started_at: float) -> int:
    return max(0, round((time.monotonic() - started_at) * 1000))


def format_elapsed(milliseconds: int) -> str:
    total_seconds = round(milliseconds / 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


class AnalysisDependencyError(RuntimeError):
    """An authoritative transcript dependency cannot be analyzed."""

    classification = "analysis_dependency_invalid"
    retryable = False


class AnalysisProviderError(RuntimeError):
    """The registered analysis provider did not produce a result."""

    classification = "analysis_provider_failed"
    retryable = True


class TerminologyDependencyError(RuntimeError):
    """A bound draft corpus cannot be resolved."""

    classification = "terminology_dependency_invalid"
    retryable = False


class TerminologyProviderError(RuntimeError):
    """The terminology model did not produce a resolution."""

    classification = "terminology_provider_failed"
    retryable = True


class WorkerDependencyError(RuntimeError):
    """A worker deployment is missing a declared runtime dependency."""

    classification = "worker_dependency_unavailable"
    retryable = True


class NormalizationDependencyError(RuntimeError):
    """An authoritative analysis set cannot be normalized."""

    classification = "analysis_dependency_invalid"
    retryable = False


class NormalizationProviderError(RuntimeError):
    """The registered normalization provider did not produce a result."""

    classification = "normalization_provider_failed"
    retryable = True


class CompilationDependencyError(RuntimeError):
    """An approved collection input set cannot be compiled."""

    classification = "compilation_dependency_invalid"
    retryable = False


def educational_video_analysis(
    job: dict[str, Any], context: WorkerContext | None = None
) -> dict[str, Any]:
    handler_started_at = time.monotonic()
    spec = job["spec"]
    configuration = spec.get("configuration")
    expected_keys = {
        "max_transcript_chars",
        "model",
        "prompt_version",
        "retries",
        "source_metadata",
        "timeout_seconds",
        "video",
    }
    if not isinstance(configuration, dict) or set(configuration) != expected_keys:
        raise ValueError("the educational-video analysis configuration is invalid")
    if (
        configuration["model"] != EDUCATIONAL_VIDEO_ANALYSIS_MODEL
        or configuration["prompt_version"] != EDUCATIONAL_VIDEO_ANALYSIS_PROMPT_VERSION
        or configuration["max_transcript_chars"]
        != EDUCATIONAL_VIDEO_ANALYSIS_MAX_TRANSCRIPT_CHARS
        or configuration["retries"] != EDUCATIONAL_VIDEO_ANALYSIS_RETRIES
        or configuration["timeout_seconds"]
        != EDUCATIONAL_VIDEO_ANALYSIS_TIMEOUT_SECONDS
    ):
        raise ValueError("the educational-video analysis policy is unsupported")
    source_metadata = configuration["source_metadata"]
    video = configuration["video"]
    source_id = spec.get("source", {}).get("media_asset_id")
    if (
        not isinstance(source_metadata, dict)
        or source_metadata.get("source_id") != source_id
        or not isinstance(source_metadata.get("type"), str)
        or not isinstance(video, str)
        or not video
        or Path(video).is_absolute()
        or ".." in Path(video).parts
    ):
        raise ValueError("the educational-video source metadata is invalid")
    if spec.get("inputs") != [] or len(spec.get("dependencies", [])) != 1:
        raise AnalysisDependencyError(
            "Educational-video analysis requires exactly one transcript dependency"
        )
    dependency = spec["dependencies"][0]
    dependency_resolution_started_at = time.monotonic()
    dependency_job_id = None
    if isinstance(dependency, dict) and dependency.get("kind") == "job-output":
        dependency_job_id = dependency.get("job_id")
        if not isinstance(dependency_job_id, str) or not dependency_job_id:
            raise AnalysisDependencyError("Transcript job-output dependency is invalid")
        try:
            upstream = worker_client().post("/jobs/get", {"job_id": dependency_job_id})
            upstream_job = upstream.get("job")
            if (
                not isinstance(upstream_job, dict)
                or upstream_job.get("run_id") != job.get("run_id")
                or upstream_job.get("state") != "succeeded"
                or upstream_job.get("result") is None
            ):
                raise AnalysisDependencyError(
                    f"Transcript dependency job {dependency_job_id} is not a successful job in this run"
                )
            reference = validated_artifact_reference(upstream_job["result"])
        except AnalysisDependencyError:
            raise
        except Exception as error:
            failure = AnalysisDependencyError(
                f"Could not resolve transcript dependency job {dependency_job_id}"
            )
            failure.classification = "analysis_dependency_unavailable"
            failure.retryable = True
            raise failure from error
    else:
        reference = validated_artifact_reference(dependency)
    dependency_resolution_ms = elapsed_milliseconds(dependency_resolution_started_at)
    if (
        reference.get("artifact_kind") != "transcript"
        or reference.get("schema")
        != {"id": "watchcraft.transcript", "version": 1}
        or reference.get("media_type") != "application/json"
    ):
        raise AnalysisDependencyError(
            "Educational-video analysis requires a transcript@1 JSON dependency"
        )

    input_fetch_started_at = time.monotonic()
    try:
        payload = R2ArtifactStore.from_environment().get_bytes(reference)
        transcript_state = json.loads(payload.decode("utf-8"))
    except Exception as error:
        failure = AnalysisDependencyError(
            "Could not retrieve and decode the transcript dependency"
        )
        failure.classification = "analysis_dependency_unavailable"
        failure.retryable = True
        raise failure from error
    input_fetch_ms = elapsed_milliseconds(input_fetch_started_at)
    transcript_source = (
        transcript_state.get("source") if isinstance(transcript_state, dict) else None
    )
    if (
        not isinstance(transcript_state, dict)
        or transcript_state.get("kind") != "watchcraft.transcript"
        or transcript_state.get("schema_version") != 1
        or not isinstance(transcript_source, dict)
        or transcript_source.get("media_asset_id") != source_id
        or not transcript_state.get("text")
        or not transcript_state.get("segments")
    ):
        raise AnalysisDependencyError(
            "The transcript dependency does not match the analysis source"
        )

    try:
        from analyze_catalog import (
            create_openai_client,
            generate_analysis,
            source_metadata_context,
        )

        analysis_started_at = time.monotonic()
        result = generate_analysis(
            transcript_state,
            relative_video=video,
            source_metadata=source_metadata,
            context=source_metadata_context(source_metadata),
            client=create_openai_client(configuration["timeout_seconds"]),
            model=configuration["model"],
            retries=configuration["retries"],
            max_transcript_chars=configuration["max_transcript_chars"],
        )
        analysis_ms = elapsed_milliseconds(analysis_started_at)
    except (AnalysisDependencyError, ValueError):
        raise
    except Exception as error:
        raise AnalysisProviderError(str(error)) from error

    result["provenance"] = {
        "handler_id": EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0],
        "handler_version": EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[1],
        "job_id": job["job_id"],
        "spec_sha256": job["spec_sha256"],
        "transcript": reference,
        **(
            {"transcription_job_id": dependency_job_id}
            if dependency_job_id is not None
            else {}
        ),
        "timing": {
            "dependency_resolution_ms": dependency_resolution_ms,
            "input_fetch_ms": input_fetch_ms,
            "analysis_ms": analysis_ms,
            "handler_ms": elapsed_milliseconds(handler_started_at),
        },
    }
    return result


def collection_terminology_resolution(
    job: dict[str, Any], context: WorkerContext | None = None
) -> dict[str, Any]:
    handler_started_at = time.monotonic()
    if context is None:
        raise RuntimeError("Collection terminology resolution requires a worker context")
    spec = job["spec"]
    configuration = spec.get("configuration")
    expected_keys = {
        "batch_max_chars",
        "batch_max_terms",
        "items",
        "logical_task_id",
        "model",
        "plan_artifact_sha256",
        "plan_hash",
        "plan_job_id",
        "project",
        "prompt_version",
        "retries",
        "timeout_seconds",
    }
    if not isinstance(configuration, dict) or set(configuration) != expected_keys:
        raise ValueError("the collection terminology-resolution configuration is invalid")
    project = configuration["project"]
    bindings = configuration["items"]
    dependencies = spec.get("dependencies")
    if (
        configuration["model"] != TERMINOLOGY_RESOLUTION_MODEL
        or configuration["prompt_version"] != TERMINOLOGY_RESOLUTION_PROMPT_VERSION
        or configuration["retries"] != TERMINOLOGY_RESOLUTION_RETRIES
        or configuration["timeout_seconds"] != TERMINOLOGY_RESOLUTION_TIMEOUT_SECONDS
        or configuration["batch_max_terms"]
        != TERMINOLOGY_RESOLUTION_BATCH_MAX_TERMS
        or configuration["batch_max_chars"]
        != TERMINOLOGY_RESOLUTION_BATCH_MAX_CHARS
        or not isinstance(project, dict)
        or not isinstance(project.get("project_id"), str)
        or type(project.get("revision")) is not int
        or spec.get("source", {}).get("media_asset_id")
        != f"catalog-project:{project['project_id']}"
        or not isinstance(spec.get("inputs"), list)
        or len(spec["inputs"]) > 1
        or not isinstance(bindings, list)
        or not bindings
        or not isinstance(dependencies, list)
        or len(dependencies) != len(bindings) * 2
    ):
        raise ValueError("the collection terminology-resolution policy is unsupported")

    transcript_references = dependencies[:len(bindings)]
    analysis_references = dependencies[len(bindings):]
    store = context.artifact_store()
    records = []
    fetch_started_at = time.monotonic()
    for index, binding in enumerate(bindings):
        transcript_reference = validated_artifact_reference(transcript_references[index])
        analysis_reference = validated_artifact_reference(analysis_references[index])
        if (
            not isinstance(binding, dict)
            or set(binding) != {
                "analysis_digest",
                "item_id",
                "source_title",
                "transcript_digest",
                "video",
            }
            or binding["transcript_digest"] != transcript_reference.get("digest")
            or binding["analysis_digest"] != analysis_reference.get("digest")
            or transcript_reference.get("artifact_kind") != "transcript"
            or transcript_reference.get("schema")
            != {"id": "watchcraft.transcript", "version": 1}
            or analysis_reference.get("artifact_kind") != "analysis"
            or analysis_reference.get("schema") != VIDEO_ANALYSIS_SCHEMA
        ):
            raise TerminologyDependencyError(
                f"Terminology binding {index + 1} is invalid"
            )
        context.report_progress(
            phase="fetching-corpus",
            completed=index,
            total=len(bindings),
            unit="items",
            current=binding["item_id"],
        )
        try:
            transcript = json.loads(store.get_bytes(transcript_reference).decode("utf-8"))
            analysis = json.loads(store.get_bytes(analysis_reference).decode("utf-8"))
        except Exception as error:
            failure = TerminologyDependencyError(
                f"Could not retrieve terminology evidence for {binding['item_id']}"
            )
            failure.classification = "terminology_dependency_unavailable"
            failure.retryable = True
            raise failure from error
        if (
            transcript.get("kind") != "watchcraft.transcript"
            or transcript.get("source", {}).get("media_asset_id") != binding["item_id"]
            or analysis.get("schema_version") != VIDEO_ANALYSIS_SCHEMA["version"]
            or analysis.get("video") != binding["video"]
            or analysis.get("provenance", {}).get("transcript") != transcript_reference
        ):
            raise TerminologyDependencyError(
                f"Terminology evidence for {binding['item_id']} is inconsistent"
            )
        records.append({
            "item_id": binding["item_id"],
            "source_title": binding["source_title"],
            "transcript": transcript,
            "analysis": analysis,
        })
    dependency_fetch_ms = elapsed_milliseconds(fetch_started_at)
    latest_checkpoint = context.latest_checkpoint(
        artifact_kind="terminology-resolution-checkpoint",
        schema=TERMINOLOGY_RESOLUTION_CHECKPOINT_SCHEMA,
    )
    resume_checkpoint = latest_checkpoint[1] if latest_checkpoint is not None else None
    if resume_checkpoint is None and spec["inputs"]:
        checkpoint_reference = validated_artifact_reference(spec["inputs"][0])
        if (
            checkpoint_reference.get("artifact_kind")
            != "terminology-resolution-checkpoint"
            or checkpoint_reference.get("schema")
            != TERMINOLOGY_RESOLUTION_CHECKPOINT_SCHEMA
        ):
            raise TerminologyDependencyError(
                "The imported terminology checkpoint has the wrong artifact contract"
            )
        try:
            resume_checkpoint = json.loads(
                store.get_bytes(checkpoint_reference).decode("utf-8")
            )
        except Exception as error:
            failure = TerminologyDependencyError(
                "Could not retrieve the imported terminology checkpoint"
            )
            failure.classification = "terminology_dependency_unavailable"
            failure.retryable = True
            raise failure from error
        if not isinstance(resume_checkpoint, dict):
            raise TerminologyDependencyError(
                "The imported terminology checkpoint is not an object"
            )
    try:
        from analyze_catalog import create_openai_client
        from resolve_terminology import infer_terminology_resolution

        resolution_started_at = time.monotonic()
        inferred = infer_terminology_resolution(
            project=project,
            records=records,
            client=create_openai_client(configuration["timeout_seconds"]),
            model=configuration["model"],
            retries=configuration["retries"],
            batch_max_terms=configuration["batch_max_terms"],
            batch_max_chars=configuration["batch_max_chars"],
            resume_checkpoint=resume_checkpoint,
            report_progress=lambda completed, total, current: context.report_progress(
                phase="resolving-terminology",
                completed=completed,
                total=total,
                unit="batches",
                current=current,
            ),
            save_checkpoint=lambda value, sequence, completed, total, current: (
                context.save_checkpoint(
                    value,
                    sequence=sequence,
                    phase="resolving-terminology",
                    completed=completed,
                    total=total,
                    unit="batches",
                    current=current,
                    artifact_kind="terminology-resolution-checkpoint",
                    schema=TERMINOLOGY_RESOLUTION_CHECKPOINT_SCHEMA,
                )
            ),
        )
        resolution_ms = elapsed_milliseconds(resolution_started_at)
    except (TerminologyDependencyError, ValueError):
        raise
    except Exception as error:
        failure = TerminologyProviderError(str(error))
        if getattr(error, "retryable", True) is False:
            failure.classification = "terminology_request_invalid"
            failure.retryable = False
        raise failure from error

    resolutions = inferred["resolutions"]
    result = {
        "kind": "watchcraft.terminology-resolution",
        "schema_version": TERMINOLOGY_RESOLUTION_SCHEMA["version"],
        "project": project,
        "model": configuration["model"],
        "prompt_version": configuration["prompt_version"],
        "source_hash": inferred["source_hash"],
        "resolutions": resolutions,
        "stats": {
            "observed_terms": inferred["observed_terms"],
            "proposed_changes": len(resolutions),
            "automatic_safe": sum(
                item["disposition"] == "automatic-safe" for item in resolutions
            ),
            "needs_review": sum(
                item["disposition"] == "needs-review" for item in resolutions
            ),
        },
        "provenance": {
            "handler_id": TERMINOLOGY_RESOLUTION_HANDLER[0],
            "handler_version": TERMINOLOGY_RESOLUTION_HANDLER[1],
            "job_id": job["job_id"],
            "spec_sha256": job["spec_sha256"],
            "plan_job_id": configuration["plan_job_id"],
            "plan_artifact_sha256": configuration["plan_artifact_sha256"],
            "plan_hash": configuration["plan_hash"],
            "logical_task_id": configuration["logical_task_id"],
            "items": [
                {
                    **binding,
                    "transcript": transcript_reference,
                    "analysis": analysis_reference,
                }
                for binding, transcript_reference, analysis_reference in zip(
                    bindings, transcript_references, analysis_references
                )
            ],
            "timing": {
                "dependency_fetch_ms": dependency_fetch_ms,
                "resolution_ms": resolution_ms,
                "handler_ms": elapsed_milliseconds(handler_started_at),
            },
        },
    }
    validate_json_schema(
        result, TERMINOLOGY_RESOLUTION_SCHEMA_PATH, "Terminology resolution"
    )
    return result


def collection_topic_normalization(
    job: dict[str, Any], context: WorkerContext | None = None
) -> dict[str, Any]:
    handler_started_at = time.monotonic()
    if context is None:
        raise RuntimeError("Collection topic normalization requires a worker context")
    spec = job["spec"]
    configuration = spec.get("configuration")
    expected_keys = {
        "analyses",
        "batch_size",
        "display_label_prompt_version",
        "logical_task_id",
        "model",
        "plan_artifact_sha256",
        "plan_hash",
        "plan_job_id",
        "project_id",
        "project_revision",
        "prompt_version",
        "retries",
        "timeout_seconds",
    }
    if not isinstance(configuration, dict) or set(configuration) != expected_keys:
        raise ValueError("the collection topic-normalization configuration is invalid")
    if (
        configuration["model"] != TOPIC_NORMALIZATION_MODEL
        or configuration["prompt_version"] != TOPIC_NORMALIZATION_PROMPT_VERSION
        or configuration["display_label_prompt_version"]
        != TOPIC_DISPLAY_LABEL_PROMPT_VERSION
        or configuration["batch_size"] != TOPIC_NORMALIZATION_BATCH_SIZE
        or configuration["retries"] != TOPIC_NORMALIZATION_RETRIES
        or configuration["timeout_seconds"] != TOPIC_NORMALIZATION_TIMEOUT_SECONDS
        or spec.get("source", {}).get("media_asset_id")
        != f"catalog-project:{configuration['project_id']}"
        or spec.get("inputs") != []
    ):
        raise ValueError("the collection topic-normalization policy is unsupported")
    analysis_bindings = configuration["analyses"]
    dependencies = spec.get("dependencies")
    if (
        not isinstance(analysis_bindings, list)
        or not analysis_bindings
        or not isinstance(dependencies, list)
        or len(dependencies) != len(analysis_bindings)
    ):
        raise NormalizationDependencyError(
            "Collection topic normalization requires one analysis for every planned item"
        )

    store = context.artifact_store()
    analyses = []
    dependency_started_at = time.monotonic()
    for index, (binding, dependency) in enumerate(
        zip(analysis_bindings, dependencies), start=1
    ):
        reference = validated_artifact_reference(dependency)
        if (
            not isinstance(binding, dict)
            or set(binding) != {"digest", "item_id", "video"}
            or binding.get("digest") != reference.get("digest")
            or reference.get("artifact_kind") != "analysis"
            or reference.get("schema") != VIDEO_ANALYSIS_SCHEMA
            or reference.get("media_type") != "application/json"
        ):
            raise NormalizationDependencyError(
                "A topic-normalization analysis binding is invalid"
            )
        context.report_progress(
            phase="fetching-analyses",
            completed=index - 1,
            total=len(dependencies),
            unit="analyses",
            current=binding["item_id"],
        )
        try:
            analysis = json.loads(store.get_bytes(reference).decode("utf-8"))
        except Exception as error:
            failure = NormalizationDependencyError(
                f"Could not retrieve analysis dependency for {binding['item_id']}"
            )
            failure.classification = "analysis_dependency_unavailable"
            failure.retryable = True
            raise failure from error
        provenance = analysis.get("provenance") if isinstance(analysis, dict) else None
        if (
            not isinstance(analysis, dict)
            or analysis.get("schema_version") != VIDEO_ANALYSIS_SCHEMA["version"]
            or analysis.get("video") != binding["video"]
            or not analysis.get("topics")
            or not analysis.get("sections")
            or not isinstance(provenance, dict)
            or provenance.get("handler_id") != EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0]
        ):
            raise NormalizationDependencyError(
                f"Analysis dependency for {binding['item_id']} is invalid"
            )
        analyses.append(analysis)
    dependency_ms = elapsed_milliseconds(dependency_started_at)
    context.report_progress(
        phase="normalizing-topics",
        completed=0,
        total=1,
        unit="collection",
        current=configuration["project_id"],
    )

    try:
        import normalize_topics

        normalization_started_at = time.monotonic()
        with tempfile.TemporaryDirectory(
            prefix="watchcraft-topic-normalization-"
        ) as directory:
            root = Path(directory)
            catalog = root / "Video Catalog"
            analysis_root = catalog / "analysis"
            analysis_root.mkdir(parents=True)
            (catalog / "collection.json").write_text(
                json.dumps({"collection_id": configuration["project_id"]}),
                encoding="utf-8",
            )
            for analysis in analyses:
                (analysis_root / f"{Path(analysis['video']).stem}.analysis.json").write_text(
                    json.dumps(analysis, ensure_ascii=False),
                    encoding="utf-8",
                )
            normalize_topics.run(argparse.Namespace(
                root=root,
                normalization_model=configuration["model"],
                limit=None,
                batch_size=configuration["batch_size"],
                retries=configuration["retries"],
                timeout=configuration["timeout_seconds"],
                force=False,
                rebuild_related=False,
                rebuild_display_labels=False,
                dry_run=False,
                no_rebuild=True,
            ))
            result = json.loads(
                (catalog / "topic-normalization.json").read_text(encoding="utf-8")
            )
        normalization_ms = elapsed_milliseconds(normalization_started_at)
    except (NormalizationDependencyError, ValueError):
        raise
    except Exception as error:
        raise NormalizationProviderError(str(error)) from error

    if (
        not isinstance(result, dict)
        or result.get("schema_version") != TOPIC_NORMALIZATION_SCHEMA["version"]
        or result.get("prompt_version") != TOPIC_NORMALIZATION_PROMPT_VERSION
        or result.get("display_label_prompt_version")
        != TOPIC_DISPLAY_LABEL_PROMPT_VERSION
        or result.get("collection_id") != configuration["project_id"]
        or result.get("model") != TOPIC_NORMALIZATION_MODEL
        or result.get("status") != "complete"
        or not isinstance(result.get("stats"), dict)
    ):
        raise RuntimeError("Collection topic normalization returned an invalid result")
    result["kind"] = "watchcraft.topic-normalization"
    result["provenance"] = {
        "handler_id": TOPIC_NORMALIZATION_HANDLER[0],
        "handler_version": TOPIC_NORMALIZATION_HANDLER[1],
        "job_id": job["job_id"],
        "spec_sha256": job["spec_sha256"],
        "plan_job_id": configuration["plan_job_id"],
        "plan_artifact_sha256": configuration["plan_artifact_sha256"],
        "plan_hash": configuration["plan_hash"],
        "logical_task_id": configuration["logical_task_id"],
        "project_revision": configuration["project_revision"],
        "analyses": [
            {**binding, "artifact": dependency}
            for binding, dependency in zip(analysis_bindings, dependencies)
        ],
        "timing": {
            "dependency_fetch_ms": dependency_ms,
            "normalization_ms": normalization_ms,
            "handler_ms": elapsed_milliseconds(handler_started_at),
        },
    }
    context.report_progress(
        phase="normalizing-topics",
        completed=1,
        total=1,
        unit="collection",
        current=configuration["project_id"],
    )
    return result


def compile_video_collection(
    job: dict[str, Any], context: WorkerContext | None = None
) -> dict[str, Any]:
    handler_started_at = time.monotonic()
    if context is None:
        raise RuntimeError("Collection compilation requires a worker context")
    spec = job["spec"]
    configuration = spec.get("configuration")
    expected_keys = {
        "items",
        "logical_task_id",
        "plan_artifact_sha256",
        "plan_hash",
        "plan_job_id",
        "project",
    }
    if not isinstance(configuration, dict) or set(configuration) != expected_keys:
        raise ValueError("the collection-compilation configuration is invalid")
    project = configuration["project"]
    validate_json_schema(project, CATALOG_PROJECT_SCHEMA_PATH, "Catalog project")
    if (
        project.get("collection_type") != {
            "id": "watchcraft.video-collection",
            "version": "1",
            "configuration": {"structure": "ordered-list"},
        }
        or spec.get("source", {}).get("media_asset_id")
        != f"catalog-project:{project['project_id']}"
    ):
        raise ValueError("the collection type is unsupported by this compiler")

    inputs = spec.get("inputs")
    dependencies = spec.get("dependencies")
    bindings = configuration["items"]
    if (
        not isinstance(inputs, list)
        or len(inputs) != 2
        or not isinstance(dependencies, list)
        or not isinstance(bindings, list)
        or not bindings
        or len(dependencies) != len(bindings) * 2 + 1
    ):
        raise CompilationDependencyError(
            "Collection compilation requires its plan, snapshot, transcripts, analyses, and normalization"
        )
    plan_reference = validated_artifact_reference(inputs[0])
    snapshot_reference = validated_artifact_reference(inputs[1])
    if (
        plan_reference.get("artifact_kind") != "project-processing-plan"
        or plan_reference.get("schema") != PROJECT_PROCESSING_PLAN_SCHEMA
        or plan_reference.get("digest") != configuration["plan_artifact_sha256"]
        or snapshot_reference != project["iterator"].get("accepted_snapshot")
    ):
        raise CompilationDependencyError("Compilation inputs do not match the project plan")

    transcript_references = dependencies[:len(bindings)]
    analysis_references = dependencies[len(bindings):len(bindings) * 2]
    normalization_reference = validated_artifact_reference(dependencies[-1])
    if (
        normalization_reference.get("artifact_kind") != "topic-normalization"
        or normalization_reference.get("schema") != TOPIC_NORMALIZATION_SCHEMA
    ):
        raise CompilationDependencyError("Collection compilation has invalid normalization")

    store = context.artifact_store()
    try:
        plan = json.loads(store.get_bytes(plan_reference).decode("utf-8"))
        snapshot = json.loads(store.get_bytes(snapshot_reference).decode("utf-8"))
        normalization = json.loads(
            store.get_bytes(normalization_reference).decode("utf-8")
        )
    except Exception as error:
        raise CompilationDependencyError(
            "Could not retrieve and decode collection-level compilation inputs"
        ) from error
    validate_project_processing_plan(plan)
    validate_json_schema(
        snapshot, ITERATOR_SNAPSHOT_SCHEMA_PATH, "Collection iterator snapshot"
    )
    if (
        plan.get("project") != {
            "project_id": project["project_id"],
            "revision": project["revision"],
        }
        or plan.get("source_snapshot") != snapshot_reference
        or plan.get("plan_hash") != configuration["plan_hash"]
        or snapshot.get("project", {}).get("project_id") != project["project_id"]
        or snapshot.get("project", {}).get("revision", project["revision"])
        > project["revision"]
        or normalization.get("kind") != "watchcraft.topic-normalization"
        or normalization.get("status") != "complete"
        or normalization.get("collection_id") != project["project_id"]
        or normalization.get("provenance", {}).get("plan_artifact_sha256")
        != plan_reference["digest"]
    ):
        raise CompilationDependencyError(
            "Compilation inputs do not describe the same authoritative project revision"
        )

    analyses = []
    transcripts = []
    resources = []
    for index, binding in enumerate(bindings):
        transcript_reference = validated_artifact_reference(transcript_references[index])
        analysis_reference = validated_artifact_reference(analysis_references[index])
        if (
            not isinstance(binding, dict)
            or set(binding) != {
                "analysis_digest", "item_id", "transcript_digest", "video"
            }
            or transcript_reference.get("artifact_kind") != "transcript"
            or transcript_reference.get("schema")
            != {"id": "watchcraft.transcript", "version": 1}
            or transcript_reference.get("digest") != binding["transcript_digest"]
            or analysis_reference.get("artifact_kind") != "analysis"
            or analysis_reference.get("schema") != VIDEO_ANALYSIS_SCHEMA
            or analysis_reference.get("digest") != binding["analysis_digest"]
        ):
            raise CompilationDependencyError(
                f"Compilation binding {index + 1} is invalid"
            )
        context.report_progress(
            phase="fetching-resources",
            completed=index,
            total=len(bindings),
            unit="items",
            current=binding["item_id"],
        )
        try:
            transcript = json.loads(store.get_bytes(transcript_reference).decode("utf-8"))
            analysis = json.loads(store.get_bytes(analysis_reference).decode("utf-8"))
        except Exception as error:
            raise CompilationDependencyError(
                f"Could not retrieve compilation resources for {binding['item_id']}"
            ) from error
        if (
            transcript.get("kind") != "watchcraft.transcript"
            or analysis.get("video") != binding["video"]
            or analysis.get("provenance", {}).get("transcript") != transcript_reference
        ):
            raise CompilationDependencyError(
                f"Compilation resources for {binding['item_id']} do not match"
            )
        transcripts.append(transcript)
        analyses.append(analysis)
        resources.append({
            "path": f"analysis/{Path(binding['video']).stem}.analysis.json",
            "artifact": analysis_reference,
        })

    snapshot_items = {item["item_id"]: item for item in snapshot["items"]}
    positions = {}
    for placement in snapshot["placements"]:
        positions.setdefault(placement["item_id"], placement["position"])
    sources = {}
    for binding in bindings:
        item = snapshot_items.get(binding["item_id"])
        if not isinstance(item, dict):
            raise CompilationDependencyError(
                f"Snapshot is missing compilation item {binding['item_id']}"
            )
        media = next(
            (value for value in item["media"] if value.get("type") == "youtube"),
            None,
        )
        if not isinstance(media, dict):
            raise CompilationDependencyError(
                f"Compilation item {binding['item_id']} has no YouTube media"
            )
        sources[binding["video"]] = {
            "type": "youtube",
            "video_id": media["media_id"],
            "url": media["canonical_url"],
            "title": item["title"],
            "position": positions.get(binding["item_id"]),
        }

    try:
        from build_collection import (
            build_collection_manifest,
            build_topic_chapter_map,
            validate_collection_manifest,
        )

        compile_started_at = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="watchcraft-collection-compilation-") as directory:
            root = Path(directory)
            collection_metadata = {
                "collection_id": project["publication"]["collection_id"],
                **project["metadata"],
                "source": snapshot["source"],
                "listed": project["publication"].get("listed", True),
            }
            (root / "watchcraft-authoring.json").write_text(
                json.dumps({"collection": collection_metadata, "sources": sources}),
                encoding="utf-8",
            )
            chapter_maps = {
                analysis["video"]: build_topic_chapter_map(
                    analysis, transcript.get("segments", [])
                )
                for analysis, transcript in zip(analyses, transcripts)
            }
            manifest = build_collection_manifest(
                root,
                analyses,
                chapter_maps,
                previous=None,
                normalization=normalization,
            )
            validate_collection_manifest(manifest)
        compilation_ms = elapsed_milliseconds(compile_started_at)
    except CompilationDependencyError:
        raise
    except Exception as error:
        raise RuntimeError(f"Collection compilation failed: {error}") from error

    context.report_progress(
        phase="compiling",
        completed=1,
        total=1,
        unit="collection",
        current=project["project_id"],
    )
    return {
        "kind": "watchcraft.collection-compilation",
        "schema_version": 1,
        "project": {
            "project_id": project["project_id"],
            "revision": project["revision"],
        },
        "manifest": manifest,
        "resources": resources,
        "provenance": {
            "handler_id": COLLECTION_COMPILATION_HANDLER[0],
            "handler_version": COLLECTION_COMPILATION_HANDLER[1],
            "job_id": job["job_id"],
            "spec_sha256": job["spec_sha256"],
            "plan_job_id": configuration["plan_job_id"],
            "plan": plan_reference,
            "snapshot": snapshot_reference,
            "normalization": normalization_reference,
            "items": [
                {
                    **binding,
                    "transcript": transcript_reference,
                    "analysis": analysis_reference,
                }
                for binding, transcript_reference, analysis_reference in zip(
                    bindings, transcript_references, analysis_references
                )
            ],
            "timing": {
                "compilation_ms": compilation_ms,
                "handler_ms": elapsed_milliseconds(handler_started_at),
            },
        },
    }


def mlx_staged_transcription(
    job: dict[str, Any], context: WorkerContext | None = None
) -> dict[str, Any]:
    handler_started_at = time.monotonic()
    spec = job["spec"]
    handler_identity = (
        spec.get("handler", {}).get("id"),
        spec.get("handler", {}).get("version"),
    )
    settings = STAGED_TRANSCRIPTION_SETTINGS.get(handler_identity)
    if settings is None:
        raise ValueError("the staged transcription handler identity is unsupported")
    configuration = spec["configuration"]
    if not isinstance(configuration, dict) or set(configuration) != {
        "acquisition",
        "language",
        "maximum_bytes",
        "maximum_duration_seconds",
        "model",
    }:
        raise ValueError("the staged transcription configuration is invalid")
    if configuration["language"] != "en":
        raise ValueError("the initial staged transcription handler supports only English")
    if configuration["model"] != settings["model"]:
        raise ValueError(
            f"the staged transcription handler requires {settings['model']}"
        )
    maximum_bytes = configuration["maximum_bytes"]
    maximum_duration_seconds = configuration["maximum_duration_seconds"]
    if (
        type(maximum_bytes) is not int
        or not 1 <= maximum_bytes <= settings["maximum_bytes"]
        or type(maximum_duration_seconds) is not int
        or maximum_duration_seconds < 1
        or maximum_duration_seconds > settings["maximum_duration_seconds"]
    ):
        raise ValueError("the staged transcription media limits are invalid")
    if not isinstance(spec.get("inputs"), list) or len(spec["inputs"]) != 1:
        raise ValueError("the staged transcription handler requires one source-audio input")
    reference = validated_artifact_reference(spec["inputs"][0], allow_staged=True)
    if (
        reference.get("artifact_kind") != "source-audio"
        or reference.get("schema") != SOURCE_AUDIO_SCHEMA
        or not reference.get("media_type", "").startswith("audio/")
        or reference["byte_length"] < 1
        or reference["byte_length"] > maximum_bytes
    ):
        raise ValueError("the staged source-audio reference is invalid")
    retention = reference["retention"]
    if retention["expires_at"] <= int(time.time() * 1000):
        raise StagedSourceError(
            "The staged source-audio input has expired",
            "source_input_expired",
            False,
        )
    acquisition = configuration["acquisition"]
    if not isinstance(acquisition, dict):
        raise ValueError("the staged source-audio acquisition provenance is invalid")
    acquisition_source = acquisition.get("source")
    acquisition_media = acquisition.get("media")
    method = acquisition.get("method")
    if (
        not isinstance(acquisition_source, dict)
        or acquisition_source.get("media_asset_id")
        != spec.get("source", {}).get("media_asset_id")
        or not isinstance(acquisition_media, dict)
        or acquisition_media.get("algorithm") != reference["algorithm"]
        or acquisition_media.get("digest") != reference["digest"]
        or acquisition_media.get("byte_length") != reference["byte_length"]
        or isinstance(acquisition_media.get("duration_seconds"), bool)
        or not isinstance(acquisition_media.get("duration_seconds"), (int, float))
        or acquisition_media["duration_seconds"] <= 0
        or acquisition_media["duration_seconds"] > maximum_duration_seconds
        or not isinstance(method, dict)
        or not isinstance(method.get("id"), str)
        or not isinstance(method.get("version"), str)
    ):
        raise ValueError("the staged source-audio provenance does not match its input")

    input_fetch_started_at = time.monotonic()
    try:
        payload = R2ArtifactStore.from_environment().get_bytes(reference)
    except Exception as error:
        raise StagedSourceError(
            "Could not retrieve and verify the staged source-audio input",
            "source_input_unavailable",
            True,
        ) from error
    input_fetch_ms = elapsed_milliseconds(input_fetch_started_at)
    with tempfile.TemporaryDirectory(prefix="watchcraft-mlx-staged-") as directory:
        audio_path = Path(directory) / "source-audio"
        audio_path.write_bytes(payload)
        transcription_started_at = time.monotonic()
        transcript = mlx_transcribe_file(
            audio_path,
            language=configuration["language"],
            model=configuration["model"],
        )
        transcription_ms = elapsed_milliseconds(transcription_started_at)

    return {
        "kind": "watchcraft.transcript",
        "schema_version": 1,
        "source": spec["source"],
        "model": configuration["model"],
        **transcript,
        "provenance": {
            "handler_id": handler_identity[0],
            "handler_version": handler_identity[1],
            "job_id": job["job_id"],
            "spec_sha256": job["spec_sha256"],
            "acquisition": acquisition,
            "source_audio": reference,
            "worker_audio_retained": False,
            "timing": {
                "input_fetch_ms": input_fetch_ms,
                "transcription_ms": transcription_ms,
                "handler_ms": elapsed_milliseconds(handler_started_at),
            },
        },
    }


HANDLERS: dict[
    tuple[str, str],
    Callable[[dict[str, Any], WorkerContext | None], dict[str, Any]],
] = {
    ANALYSIS_HANDLER: lexical_analysis,
    EDUCATIONAL_VIDEO_ANALYSIS_HANDLER: educational_video_analysis,
    TERMINOLOGY_RESOLUTION_HANDLER: collection_terminology_resolution,
    TOPIC_NORMALIZATION_HANDLER: collection_topic_normalization,
    COLLECTION_COMPILATION_HANDLER: compile_video_collection,
    TRANSCRIPTION_SMOKE_HANDLER: mlx_transcription_smoke,
    HTTP_TRANSCRIPTION_SMOKE_HANDLER: mlx_http_transcription_smoke,
    STAGED_TRANSCRIPTION_SMOKE_HANDLER: mlx_staged_transcription,
    PRODUCTION_TRANSCRIPTION_HANDLER: mlx_staged_transcription,
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
    EDUCATIONAL_VIDEO_ANALYSIS_HANDLER: {
        "id": EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0],
        "version": EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[1],
        "operation": "generate",
        "inputs": [],
        "dependencies": [
            {
                "artifact_kind": "transcript",
                "schema": {"id": "watchcraft.transcript", "version": 1},
            },
        ],
        "output": {
            "artifact_kind": "analysis",
            "schema": VIDEO_ANALYSIS_SCHEMA,
        },
        "execution_profile": {
            "id": OPENAI_EXECUTION_PROFILE[0],
            "version": OPENAI_EXECUTION_PROFILE[1],
        },
        "lease_class": "model-api",
        "retry_policy": {
            "max_attempts": 2,
            "retryable_classifications": [
                "analysis_dependency_unavailable",
                "analysis_provider_failed",
                "artifact_store_failed",
                "lease_expired",
            ],
        },
    },
    TERMINOLOGY_RESOLUTION_HANDLER: {
        "id": TERMINOLOGY_RESOLUTION_HANDLER[0],
        "version": TERMINOLOGY_RESOLUTION_HANDLER[1],
        "operation": "generate",
        "inputs": [
            {
                "artifact_kind": "terminology-resolution-checkpoint",
                "schema": TERMINOLOGY_RESOLUTION_CHECKPOINT_SCHEMA,
                "cardinality": {"minimum": 0, "maximum": 1},
            },
        ],
        "dependencies": [
            {
                "artifact_kind": "transcript",
                "schema": {"id": "watchcraft.transcript", "version": 1},
                "cardinality": {"minimum": 1, "maximum": 10_000},
            },
            {
                "artifact_kind": "analysis",
                "schema": VIDEO_ANALYSIS_SCHEMA,
                "cardinality": {"minimum": 1, "maximum": 10_000},
            },
        ],
        "output": {
            "artifact_kind": "terminology-resolution",
            "schema": TERMINOLOGY_RESOLUTION_SCHEMA,
        },
        "execution_profile": {
            "id": OPENAI_EXECUTION_PROFILE[0],
            "version": OPENAI_EXECUTION_PROFILE[1],
        },
        "lease_class": "model-api",
        "retry_policy": {
            "max_attempts": 2,
            "retryable_classifications": [
                "terminology_dependency_unavailable",
                "terminology_provider_failed",
                "worker_dependency_unavailable",
                "artifact_store_failed",
                "lease_expired",
            ],
        },
    },
    TOPIC_NORMALIZATION_HANDLER: {
        "id": TOPIC_NORMALIZATION_HANDLER[0],
        "version": TOPIC_NORMALIZATION_HANDLER[1],
        "operation": "generate",
        "inputs": [],
        "dependencies": [
            {
                "artifact_kind": "analysis",
                "schema": VIDEO_ANALYSIS_SCHEMA,
                "cardinality": {"minimum": 1, "maximum": 10_000},
            },
        ],
        "output": {
            "artifact_kind": "topic-normalization",
            "schema": TOPIC_NORMALIZATION_SCHEMA,
        },
        "execution_profile": {
            "id": OPENAI_EXECUTION_PROFILE[0],
            "version": OPENAI_EXECUTION_PROFILE[1],
        },
        "lease_class": "model-api",
        "retry_policy": {
            "max_attempts": 2,
            "retryable_classifications": [
                "analysis_dependency_unavailable",
                "normalization_provider_failed",
                "artifact_store_failed",
                "lease_expired",
            ],
        },
    },
    COLLECTION_COMPILATION_HANDLER: {
        "id": COLLECTION_COMPILATION_HANDLER[0],
        "version": COLLECTION_COMPILATION_HANDLER[1],
        "operation": "compile",
        "inputs": [
            {
                "artifact_kind": "project-processing-plan",
                "schema": PROJECT_PROCESSING_PLAN_SCHEMA,
            },
            {
                "artifact_kind": "collection-iterator-snapshot",
                "schema": COLLECTION_ITERATOR_SNAPSHOT_SCHEMA,
            },
        ],
        "dependencies": [
            {
                "artifact_kind": "transcript",
                "schema": {"id": "watchcraft.transcript", "version": 1},
                "cardinality": {"minimum": 1, "maximum": 10_000},
            },
            {
                "artifact_kind": "analysis",
                "schema": VIDEO_ANALYSIS_SCHEMA,
                "cardinality": {"minimum": 1, "maximum": 10_000},
            },
            {
                "artifact_kind": "topic-normalization",
                "schema": TOPIC_NORMALIZATION_SCHEMA,
            },
        ],
        "output": {
            "artifact_kind": "collection-compilation",
            "schema": COLLECTION_COMPILATION_SCHEMA,
        },
        "execution_profile": {
            "id": PYTHON_EXECUTION_PROFILE[0],
            "version": PYTHON_EXECUTION_PROFILE[1],
        },
        "lease_class": "short",
        "retry_policy": {
            "max_attempts": 3,
            "retryable_classifications": [
                "artifact_store_failed",
                "lease_expired",
            ],
        },
    },
    TRANSCRIPTION_SMOKE_HANDLER: {
        "id": TRANSCRIPTION_SMOKE_HANDLER[0],
        "version": TRANSCRIPTION_SMOKE_HANDLER[1],
        "operation": "generate",
        "inputs": [],
        "dependencies": [],
        "output": {
            "artifact_kind": "transcript",
            "schema": {"id": "watchcraft.transcript", "version": 1},
        },
        "execution_profile": {
            "id": MLX_EXECUTION_PROFILE[0],
            "version": MLX_EXECUTION_PROFILE[1],
        },
        "lease_class": "accelerated",
        "retry_policy": {
            "max_attempts": 2,
            "retryable_classifications": [
                "artifact_store_failed", "lease_expired",
            ],
        },
    },
    HTTP_TRANSCRIPTION_SMOKE_HANDLER: {
        "id": HTTP_TRANSCRIPTION_SMOKE_HANDLER[0],
        "version": HTTP_TRANSCRIPTION_SMOKE_HANDLER[1],
        "operation": "generate",
        "inputs": [],
        "dependencies": [],
        "output": {
            "artifact_kind": "transcript",
            "schema": {"id": "watchcraft.transcript", "version": 1},
        },
        "execution_profile": {
            "id": MLX_EXECUTION_PROFILE[0],
            "version": MLX_EXECUTION_PROFILE[1],
        },
        "lease_class": "accelerated",
        "retry_policy": {
            "max_attempts": 2,
            "retryable_classifications": [
                "artifact_store_failed", "lease_expired",
            ],
        },
    },
    STAGED_TRANSCRIPTION_SMOKE_HANDLER: {
        "id": STAGED_TRANSCRIPTION_SMOKE_HANDLER[0],
        "version": STAGED_TRANSCRIPTION_SMOKE_HANDLER[1],
        "operation": "generate",
        "inputs": [
            {
                "artifact_kind": "source-audio",
                "schema": SOURCE_AUDIO_SCHEMA,
            },
        ],
        "dependencies": [],
        "output": {
            "artifact_kind": "transcript",
            "schema": {"id": "watchcraft.transcript", "version": 1},
        },
        "execution_profile": {
            "id": MLX_EXECUTION_PROFILE[0],
            "version": MLX_EXECUTION_PROFILE[1],
        },
        "lease_class": "accelerated",
        "retry_policy": {
            "max_attempts": 2,
            "retryable_classifications": [
                "artifact_store_failed",
                "lease_expired",
                "source_input_unavailable",
            ],
        },
    },
    PRODUCTION_TRANSCRIPTION_HANDLER: {
        "id": PRODUCTION_TRANSCRIPTION_HANDLER[0],
        "version": PRODUCTION_TRANSCRIPTION_HANDLER[1],
        "operation": "generate",
        "inputs": [
            {
                "artifact_kind": "source-audio",
                "schema": SOURCE_AUDIO_SCHEMA,
            },
        ],
        "dependencies": [],
        "output": {
            "artifact_kind": "transcript",
            "schema": {"id": "watchcraft.transcript", "version": 1},
        },
        "execution_profile": {
            "id": MLX_EXECUTION_PROFILE[0],
            "version": MLX_EXECUTION_PROFILE[1],
        },
        "lease_class": "accelerated",
        "retry_policy": {
            "max_attempts": 2,
            "retryable_classifications": [
                "artifact_store_failed",
                "lease_expired",
                "source_input_unavailable",
            ],
        },
    },
    YOUTUBE_PLAYLIST_ITERATOR_HANDLER: {
        "id": YOUTUBE_PLAYLIST_ITERATOR_HANDLER[0],
        "version": YOUTUBE_PLAYLIST_ITERATOR_HANDLER[1],
        "operation": "generate",
        "inputs": [],
        "dependencies": [],
        "output": {
            "artifact_kind": "collection-iterator-snapshot",
            "schema": COLLECTION_ITERATOR_SNAPSHOT_SCHEMA,
        },
        "execution_profile": {
            "id": PYTHON_EXECUTION_PROFILE[0],
            "version": PYTHON_EXECUTION_PROFILE[1],
        },
        "lease_class": "short",
        "retry_policy": {
            "max_attempts": 3,
            "retryable_classifications": [
                "artifact_store_failed",
                "lease_expired",
                "source_discovery_failed",
            ],
        },
    },
    PROJECT_PROCESSING_PLANNER_HANDLER: {
        "id": PROJECT_PROCESSING_PLANNER_HANDLER[0],
        "version": PROJECT_PROCESSING_PLANNER_HANDLER[1],
        "operation": "generate",
        "inputs": [
            {
                "artifact_kind": "collection-iterator-snapshot",
                "schema": COLLECTION_ITERATOR_SNAPSHOT_SCHEMA,
            },
        ],
        "dependencies": [],
        "output": {
            "artifact_kind": "project-processing-plan",
            "schema": PROJECT_PROCESSING_PLAN_SCHEMA,
        },
        "execution_profile": {
            "id": PYTHON_EXECUTION_PROFILE[0],
            "version": PYTHON_EXECUTION_PROFILE[1],
        },
        "lease_class": "short",
        "retry_policy": {
            "max_attempts": 3,
            "retryable_classifications": [
                "artifact_store_failed",
                "lease_expired",
                "source_input_unavailable",
            ],
        },
    },
}
LOCAL_EXECUTION_PROFILES = {
    PYTHON_EXECUTION_PROFILE: {
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
    },
    OPENAI_EXECUTION_PROFILE: {
        "id": OPENAI_EXECUTION_PROFILE[0],
        "version": OPENAI_EXECUTION_PROFILE[1],
        "dispatcher": {
            "kind": "github-actions",
            "workflow": OPENAI_EXECUTION_WORKFLOW,
        },
        "platform": {"os": "linux", "architecture": "x64"},
        "dependency_class": "python-openai-authoring-worker",
        "cache_class": "pip",
        "timeout_minutes": 60,
        "lease_duration_ms": 3_600_000,
        "heartbeat_interval_ms": 60_000,
        "data_access": "private-derived",
        "secret_capabilities": [
            "convex.worker",
            "openai.responses",
            "r2.read-write",
        ],
    },
    MLX_EXECUTION_PROFILE: {
        "id": MLX_EXECUTION_PROFILE[0],
        "version": MLX_EXECUTION_PROFILE[1],
        "dispatcher": {"kind": "github-actions", "workflow": MLX_EXECUTION_WORKFLOW},
        "platform": {"os": "macos", "architecture": "arm64"},
        "dependency_class": "python-mlx-authoring-worker",
        "cache_class": "huggingface",
        "timeout_minutes": 30,
        "lease_duration_ms": 2_700_000,
        "heartbeat_interval_ms": 60_000,
        "data_access": "public",
        "secret_capabilities": ["convex.worker", "r2.read-write"],
    },
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
        if not isinstance(references, list) or not isinstance(contracts, list):
            raise RegistrySupportError(
                f"Resolved handler {field} do not match the job specification"
            )
        reference_index = 0
        for contract in contracts:
            cardinality = contract.get("cardinality", {"minimum": 1, "maximum": 1})
            count = 0
            expected_artifact = {
                "artifact_kind": contract.get("artifact_kind"),
                "schema": contract.get("schema"),
            }
            while reference_index < len(references) and count < cardinality["maximum"]:
                reference = references[reference_index]
                actual_artifact = {
                    "artifact_kind": reference.get("artifact_kind"),
                    "schema": reference.get("schema"),
                } if isinstance(reference, dict) else None
                if actual_artifact != expected_artifact:
                    break
                reference_index += 1
                count += 1
            if count < cardinality["minimum"]:
                raise RegistrySupportError(
                    f"Resolved handler {field} do not match the job specification"
                )
        if reference_index != len(references):
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
    local_profile = LOCAL_EXECUTION_PROFILES.get(expected_profile)
    if profile != local_profile:
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

    def put_staged_file(
        self,
        source: Path,
        description: dict[str, Any],
        *,
        acquisition_id: str,
        expires_at: int,
    ) -> dict[str, Any]:
        try:
            normalized_acquisition_id = str(uuid.UUID(acquisition_id))
        except (ValueError, AttributeError) as error:
            raise ValueError("Staged artifact acquisition ID must be a UUID") from error
        if type(expires_at) is not int or expires_at < 1:
            raise ValueError("Staged artifact expiration must be a positive timestamp")
        try:
            payload = source.read_bytes()
        except OSError as error:
            raise RuntimeError(f"Could not read staged source media {source}") from error
        if not payload:
            raise RuntimeError("Refusing to stage an empty source-media artifact")
        digest = sha256_hex(payload)
        key = (
            f"staging/{normalized_acquisition_id}/sha256/"
            f"{digest[:2]}/{digest[2:]}"
        )
        reference = {
            "store": "r2",
            "algorithm": "sha256",
            "digest": digest,
            "byte_length": len(payload),
            "media_type": description["media_type"],
            "artifact_kind": description["artifact_kind"],
            "schema": description["schema"],
            "key": key,
            "retention": {
                "class": "ephemeral",
                "expires_at": expires_at,
            },
        }
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=payload,
                ContentLength=len(payload),
                ContentType=description["media_type"],
                IfNoneMatch="*",
                Metadata={
                    "sha256": digest,
                    "artifact_kind": description["artifact_kind"],
                    "schema_id": description["schema"]["id"],
                    "schema_version": str(description["schema"]["version"]),
                    "retention_class": "ephemeral",
                    "expires_at": str(expires_at),
                },
            )
        except Exception as error:
            status = getattr(error, "response", {}).get(
                "ResponseMetadata", {}
            ).get("HTTPStatusCode")
            if status != 412:
                raise
        if self.get_bytes(reference) != payload:
            raise RuntimeError("Staged R2 artifact did not round-trip exactly")
        return reference

    def delete(self, reference: dict[str, Any]) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=reference["key"])

    def get_bytes(self, reference: dict[str, Any]) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=reference["key"])
        except Exception as error:
            raise RuntimeError(f"Could not read R2 artifact {reference['key']}") from error
        payload = response["Body"].read()
        if len(payload) != reference["byte_length"] or sha256_hex(payload) != reference["digest"]:
            raise RuntimeError("R2 artifact failed content verification")
        return payload


class WorkerContext:
    """Own worker-side lease revisions, progress reports, and checkpoints."""

    def __init__(
        self,
        *,
        control: AuthoringHttpClient,
        job: dict[str, Any],
        attempt_id: str,
        lease_duration_ms: int,
        artifacts: R2ArtifactStore | None = None,
    ):
        self.control = control
        self.job = job
        self.attempt_id = attempt_id
        self.lease_duration_ms = lease_duration_ms
        self._artifacts = artifacts
        self._heartbeat_number = 0

    def artifact_store(self) -> R2ArtifactStore:
        if self._artifacts is None:
            self._artifacts = R2ArtifactStore.from_environment()
        return self._artifacts

    def report_progress(
        self,
        *,
        phase: str,
        completed: int,
        unit: str,
        total: int | None = None,
        current: str | None = None,
        checkpoint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._heartbeat_number += 1
        progress = {"phase": phase, "completed": completed, "unit": unit}
        if total is not None:
            progress["total"] = total
        if current:
            progress["current"] = current
        payload = {
            "job_id": self.job["job_id"],
            "command_id": f"{self.attempt_id}:heartbeat:{self._heartbeat_number}",
            "expected_revision": self.job["revision"],
            "attempt_id": self.attempt_id,
            "lease_duration_ms": self.lease_duration_ms,
            "progress": progress,
        }
        if checkpoint is not None:
            payload["checkpoint"] = checkpoint
        self.job = self.control.post("/jobs/heartbeat", payload)
        return self.job

    def save_checkpoint(
        self,
        value: dict[str, Any],
        *,
        sequence: int,
        phase: str,
        completed: int,
        total: int,
        unit: str,
        current: str | None = None,
        artifact_kind: str = "collection-iterator-checkpoint",
        schema: dict[str, Any] = COLLECTION_ITERATOR_CHECKPOINT_SCHEMA,
    ) -> dict[str, Any]:
        if not artifact_kind.endswith("-checkpoint"):
            raise ValueError("Checkpoint artifact kind must end in -checkpoint")
        artifact = self.artifact_store().put_json(
            value,
            {
                "artifact_kind": artifact_kind,
                "schema": schema,
            },
        )
        self.report_progress(
            phase=phase,
            completed=completed,
            total=total,
            unit=unit,
            current=current,
            checkpoint={
                "sequence": sequence,
                "spec_sha256": self.job["spec_sha256"],
                "artifact": artifact,
            },
        )
        return artifact

    def latest_checkpoint(
        self,
        *,
        artifact_kind: str = "collection-iterator-checkpoint",
        schema: dict[str, Any] = COLLECTION_ITERATOR_CHECKPOINT_SCHEMA,
    ) -> tuple[int, dict[str, Any]] | None:
        checkpoints = []
        for attempt in self.job.get("attempts", []):
            if not isinstance(attempt, dict):
                continue
            checkpoint = attempt.get("checkpoint")
            if (
                isinstance(checkpoint, dict)
                and checkpoint.get("spec_sha256") == self.job.get("spec_sha256")
                and type(checkpoint.get("sequence")) is int
            ):
                checkpoints.append(checkpoint)
        if not checkpoints:
            return None
        checkpoint = max(checkpoints, key=lambda value: value["sequence"])
        reference = validated_artifact_reference(checkpoint.get("artifact"))
        if (
            reference.get("artifact_kind") != artifact_kind
            or reference.get("schema") != schema
        ):
            raise RuntimeError("The latest checkpoint has the wrong artifact contract")
        payload = self.artifact_store().get_bytes(reference)
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("The latest checkpoint is not valid JSON") from error
        if not isinstance(value, dict):
            raise RuntimeError("The latest checkpoint must be an object")
        return checkpoint["sequence"], value


def validated_artifact_reference(
    value: Any,
    *,
    allow_staged: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("The completed job has an invalid artifact reference")
    digest = value.get("digest")
    byte_length = value.get("byte_length")
    media_type = value.get("media_type")
    if value.get("store") != "r2" or value.get("algorithm") != "sha256":
        raise RuntimeError("The completed job does not reference a SHA-256 R2 artifact")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise RuntimeError("The completed job has an invalid artifact digest")
    key = value.get("key")
    retention = value.get("retention")
    expected_key = f"objects/sha256/{digest[:2]}/{digest[2:]}"
    if retention is None:
        if key != expected_key:
            raise RuntimeError("The artifact key does not match its content digest")
    else:
        if not allow_staged:
            raise RuntimeError("A completed job cannot use a staged result artifact")
        if (
            not isinstance(retention, dict)
            or retention.get("class") != "ephemeral"
            or type(retention.get("expires_at")) is not int
            or retention["expires_at"] < 1
        ):
            raise RuntimeError("The staged artifact has invalid retention metadata")
        acquisition_id_pattern = (
            r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}"
        )
        key_pattern = (
            rf"staging/{acquisition_id_pattern}/sha256/"
            rf"{digest[:2]}/{digest[2:]}"
        )
        if not isinstance(key, str) or not re.fullmatch(key_pattern, key):
            raise RuntimeError("The staged artifact key does not match its content digest")
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


def r2_staging_writer(credential_source: str = "auto") -> R2ArtifactStore:
    access_key, secret_key = r2_staging_credentials(credential_source)
    return R2ArtifactStore.from_configuration(
        endpoint=production_configuration("WATCHCRAFT_R2_ENDPOINT"),
        bucket=production_configuration("WATCHCRAFT_R2_BUCKET"),
        access_key_id=access_key,
        secret_access_key=secret_key,
    )


class IteratorExecutionError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.classification = "source_discovery_failed"
        self.retryable = retryable


class ProjectPlanningError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.classification = "source_input_unavailable"
        self.retryable = retryable


def validate_json_schema(value: Any, path: Path, label: str) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as error:
        raise WorkerDependencyError(
            "JSON Schema validation requires the jsonschema worker dependency"
        ) from error
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read {label} schema {path}") from error
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise ValueError(f"{label} is invalid at {location}: {error.message}")


def iterator_structure_sha256(snapshot: dict[str, Any]) -> str:
    projection = {
        "source": {
            key: snapshot["source"][key]
            for key in ("source_id", "source_type")
        },
        "nodes": [
            {
                key: node[key]
                for key in ("node_id", "node_type", "parent_node_id", "position")
            }
            for node in snapshot["nodes"]
        ],
        "items": [
            {
                "item_id": item["item_id"],
                "media": [
                    {key: media[key] for key in ("type", "media_id")}
                    for media in item["media"]
                ],
            }
            for item in snapshot["items"]
        ],
        "placements": [
            {
                key: placement[key]
                for key in (
                    "placement_id",
                    "item_id",
                    "parent_node_id",
                    "position",
                )
            }
            for placement in snapshot["placements"]
        ],
    }
    return sha256_hex(canonical_json(projection))


def validate_iterator_snapshot(snapshot: dict[str, Any]) -> None:
    validate_json_schema(
        snapshot,
        ITERATOR_SNAPSHOT_SCHEMA_PATH,
        "Collection iterator snapshot",
    )
    if snapshot["coverage"]["expected"] != (
        snapshot["coverage"]["resolved"]
        + len(snapshot["coverage"]["unresolved"])
    ):
        raise ValueError("Collection iterator snapshot coverage is inconsistent")
    nodes = {node["node_id"]: node for node in snapshot["nodes"]}
    items = {item["item_id"]: item for item in snapshot["items"]}
    if len(nodes) != len(snapshot["nodes"]):
        raise ValueError("Collection iterator snapshot node identities are not unique")
    if len(items) != len(snapshot["items"]):
        raise ValueError("Collection iterator snapshot item identities are not unique")
    if sum(node["parent_node_id"] is None for node in snapshot["nodes"]) != 1:
        raise ValueError("Collection iterator snapshot must have exactly one root node")
    node_positions = set()
    for node in snapshot["nodes"]:
        position_key = (node["parent_node_id"], node["position"])
        if position_key in node_positions:
            raise ValueError("Collection iterator snapshot node positions are not unique")
        node_positions.add(position_key)
        seen = {node["node_id"]}
        parent_id = node["parent_node_id"]
        while parent_id is not None:
            if parent_id in seen or parent_id not in nodes:
                raise ValueError("Collection iterator snapshot node graph is invalid")
            seen.add(parent_id)
            parent_id = nodes[parent_id]["parent_node_id"]
    placement_ids = set()
    placement_positions = set()
    for placement in snapshot["placements"]:
        if placement["placement_id"] in placement_ids:
            raise ValueError("Collection iterator snapshot placement identities are not unique")
        placement_ids.add(placement["placement_id"])
        position_key = (placement["parent_node_id"], placement["position"])
        if position_key in placement_positions:
            raise ValueError("Collection iterator snapshot placement positions are not unique")
        placement_positions.add(position_key)
        if placement["item_id"] not in items or placement["parent_node_id"] not in nodes:
            raise ValueError("Collection iterator snapshot placement graph is invalid")
    if snapshot["structure_hash"] != iterator_structure_sha256(snapshot):
        raise ValueError("Collection iterator snapshot structure hash is invalid")


def project_processing_plan_sha256(plan: dict[str, Any]) -> str:
    projection = {
        key: value
        for key, value in plan.items()
        if key not in {"planned_at", "plan_hash"}
    }
    return sha256_hex(canonical_json(projection))


def validate_project_processing_plan(plan: dict[str, Any]) -> None:
    validate_json_schema(
        plan,
        PROJECT_PROCESSING_PLAN_SCHEMA_PATH,
        "Project processing plan",
    )
    item_task_ids: list[str] = []
    for item in plan["items"]:
        stages = item["stages"]
        if [stage["stage"] for stage in stages] != [
            "metadata-enrichment",
            "source-acquisition",
            "transcription",
            "analysis",
        ]:
            raise ValueError("Project processing plan item stages are out of order")
        expected_dependencies: list[str] = []
        for stage in stages:
            if stage["depends_on"] != expected_dependencies:
                raise ValueError("Project processing plan stage dependencies are inconsistent")
            item_task_ids.append(stage["task_id"])
            expected_dependencies = [stage["task_id"]]
    if len(item_task_ids) != len(set(item_task_ids)):
        raise ValueError("Project processing plan task identities are not unique")
    collection_tasks = plan["collection_tasks"]
    analysis_ids = [item["stages"][-1]["task_id"] for item in plan["items"]]
    if (
        len(collection_tasks) != 2
        or collection_tasks[0]["stage"] != "topic-normalization"
        or collection_tasks[0]["depends_on"] != analysis_ids
        or collection_tasks[1]["stage"] != "collection-compilation"
        or collection_tasks[1]["depends_on"] != [collection_tasks[0]["task_id"]]
    ):
        raise ValueError("Project processing plan collection dependencies are inconsistent")
    summary = plan["summary"]
    if summary != {
        "unique_items": len(plan["items"]),
        "placements": sum(len(item["placement_ids"]) for item in plan["items"]),
        "operator_local_tasks": len(plan["items"]) * 2,
        "registered_worker_jobs": len(plan["items"]) * 2,
        "deferred_collection_jobs": len(collection_tasks),
    }:
        raise ValueError("Project processing plan summary is inconsistent")
    if plan["plan_hash"] != project_processing_plan_sha256(plan):
        raise ValueError("Project processing plan hash is invalid")


def project_processing_plan_spec(
    project: dict[str, Any],
    *,
    planned_at: str | None = None,
) -> dict[str, Any]:
    validate_json_schema(project, CATALOG_PROJECT_SCHEMA_PATH, "Catalog project")
    accepted = project.get("iterator", {}).get("accepted_snapshot")
    if accepted is None:
        raise ValueError("Catalog project has no accepted iterator snapshot")
    reference = validated_artifact_reference(accepted)
    if (
        reference.get("artifact_kind") != "collection-iterator-snapshot"
        or reference.get("schema") != COLLECTION_ITERATOR_SNAPSHOT_SCHEMA
    ):
        raise ValueError("Catalog project accepted snapshot has the wrong artifact contract")
    observation_time = planned_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    return {
        "operation": "generate",
        "artifact_kind": "project-processing-plan",
        "output_schema": PROJECT_PROCESSING_PLAN_SCHEMA,
        "handler": {
            "id": PROJECT_PROCESSING_PLANNER_HANDLER[0],
            "version": PROJECT_PROCESSING_PLANNER_HANDLER[1],
        },
        "source": {"media_asset_id": f"catalog-project:{project['project_id']}"},
        "inputs": [reference],
        "dependencies": [],
        "configuration": {"project": project, "planned_at": observation_time},
    }


def youtube_playlist_iterator_spec(
    project: dict[str, Any],
    *,
    observed_at: str | None = None,
) -> dict[str, Any]:
    validate_youtube_playlist_project(project)
    iterator = project["iterator"]
    configuration = iterator["configuration"]
    playlist_id = configuration["playlist_id"]
    observation_time = observed_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    return {
        "operation": "generate",
        "artifact_kind": "collection-iterator-snapshot",
        "output_schema": COLLECTION_ITERATOR_SNAPSHOT_SCHEMA,
        "handler": {
            "id": YOUTUBE_PLAYLIST_ITERATOR_HANDLER[0],
            "version": YOUTUBE_PLAYLIST_ITERATOR_HANDLER[1],
        },
        "source": {"media_asset_id": f"youtube-playlist:{playlist_id}"},
        "inputs": [],
        "dependencies": [],
        "configuration": {
            "project": project,
            "observed_at": observation_time,
        },
    }


def validate_youtube_playlist_project(project: Any) -> dict[str, Any]:
    validate_json_schema(project, CATALOG_PROJECT_SCHEMA_PATH, "Catalog project")
    collection_type = project["collection_type"]
    if (
        collection_type.get("id") != "watchcraft.video-collection"
        or collection_type.get("version") != "1"
        or collection_type.get("configuration", {}).get("structure") != "ordered-list"
    ):
        raise ValueError(
            "watchcraft.youtube-playlist@1 requires watchcraft.video-collection@1 "
            "with ordered-list structure"
        )
    iterator = project["iterator"]
    if (
        iterator.get("id") != "watchcraft.youtube-playlist"
        or iterator.get("version") != "1"
    ):
        raise ValueError("The first queued iterator supports watchcraft.youtube-playlist@1")
    configuration = iterator["configuration"]
    playlist_id = configuration.get("playlist_id")
    canonical_url = configuration.get("canonical_url")
    if (
        not isinstance(playlist_id, str)
        or not isinstance(canonical_url, str)
        or youtube_playlist_id(canonical_url) != playlist_id
    ):
        raise ValueError("Catalog project has an invalid YouTube playlist identity")
    selection = configuration.get("selection")
    exclusions = selection.get("excluded_item_ids") if isinstance(selection, dict) else None
    if (
        iterator.get("access_profile") != "public-anonymous"
        or not isinstance(selection, dict)
        or selection.get("kind") != "published-order"
        or not isinstance(exclusions, list)
        or any(not isinstance(value, str) or not value for value in exclusions)
        or len(exclusions) != len(set(exclusions))
    ):
        raise ValueError("Catalog project has an invalid YouTube playlist selection")
    return project


def _playlist_checkpoint_state(
    context: WorkerContext,
    *,
    project: dict[str, Any],
    playlist: dict[str, Any],
    entries: list[str],
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    latest = context.latest_checkpoint()
    if latest is None:
        return 0, [], [], []
    _, checkpoint = latest
    expected = {
        "kind": "watchcraft.youtube-playlist-iterator-checkpoint",
        "schema_version": 1,
        "handler": {
            "id": YOUTUBE_PLAYLIST_ITERATOR_HANDLER[0],
            "version": YOUTUBE_PLAYLIST_ITERATOR_HANDLER[1],
        },
        "spec_sha256": context.job["spec_sha256"],
        "project": {
            "project_id": project["project_id"],
            "revision": project["revision"],
        },
        "playlist_id": playlist["playlist_id"],
        "entries_sha256": sha256_hex(canonical_json(entries)),
    }
    for key, value in expected.items():
        if checkpoint.get(key) != value:
            raise RuntimeError(f"Iterator checkpoint does not match {key}")
    next_index = checkpoint.get("next_index")
    items = checkpoint.get("items")
    placements = checkpoint.get("placements")
    unresolved = checkpoint.get("unresolved")
    if (
        type(next_index) is not int
        or not 0 <= next_index <= len(entries)
        or not isinstance(items, list)
        or not isinstance(placements, list)
        or not isinstance(unresolved, list)
        or len(placements) + len(unresolved) != next_index
    ):
        raise RuntimeError("Iterator checkpoint has inconsistent progress")
    return next_index, items, placements, unresolved


def youtube_playlist_iterator(
    job: dict[str, Any], context: WorkerContext | None = None
) -> dict[str, Any]:
    if context is None:
        raise RuntimeError("Queued iterator execution requires a worker context")
    configuration = job["spec"].get("configuration", {})
    project = configuration.get("project")
    observed_at = configuration.get("observed_at")
    validate_youtube_playlist_project(project)
    if not isinstance(observed_at, str):
        raise ValueError("Iterator observation time is required")
    iterator = project["iterator"]
    iterator_configuration = iterator["configuration"]
    playlist_id = iterator_configuration["playlist_id"]
    requested_url = iterator_configuration["canonical_url"]
    if job["spec"]["source"].get("media_asset_id") != f"youtube-playlist:{playlist_id}":
        raise ValueError("Iterator job source does not match its catalog project")

    context.report_progress(
        phase="resolving-source",
        completed=0,
        total=1,
        unit="source",
        current=requested_url,
    )
    try:
        playlist = discover_youtube_playlist(requested_url)
    except Exception as error:
        raise IteratorExecutionError(str(error), retryable=True) from error
    entries = playlist.get("entries") or playlist["video_ids"]
    if not isinstance(entries, list) or not all(isinstance(item, str) for item in entries):
        raise IteratorExecutionError("YouTube returned invalid playlist entries")
    context.report_progress(
        phase="resolving-source",
        completed=1,
        total=1,
        unit="source",
        current=playlist["title"][:500],
    )

    start, items, placements, unresolved = _playlist_checkpoint_state(
        context,
        project=project,
        playlist=playlist,
        entries=entries,
    )
    items_by_id = {item["item_id"]: item for item in items}
    excluded = set(iterator_configuration["selection"].get("excluded_item_ids", []))
    total = len(entries)
    context.report_progress(
        phase="enumerating",
        completed=start,
        total=total,
        unit="placements",
    )
    for index, video_id in enumerate(entries[start:], start=start):
        position = index + 1
        item_id = f"youtube:{video_id}"
        if video_id in excluded or item_id in excluded:
            unresolved.append({
                "source_ref": item_id,
                "classification": "excluded-by-project",
                "message": "The catalog project excludes this playlist entry.",
            })
            current = item_id
        else:
            item = items_by_id.get(item_id)
            if item is not None:
                current = str(item["title"])[:500]
            else:
                try:
                    metadata = discover_youtube_video(video_id)
                except Exception as error:
                    unresolved.append({
                        "source_ref": item_id,
                        "classification": "source-metadata-unavailable",
                        "message": str(error)[:500] or "YouTube metadata is unavailable.",
                    })
                    current = item_id
                    metadata = None
                if metadata is not None:
                    current = str(metadata["title"])[:500]
                    publisher = str(metadata.get("publisher") or "").strip()
                    if not publisher:
                        publisher = str(
                            project.get("metadata", {})
                            .get("publisher", {})
                            .get("name")
                            or "YouTube"
                        )
                    attribution = {"publisher": publisher}
                    publisher_url = str(metadata.get("publisher_url") or "").strip()
                    if publisher_url:
                        attribution["publisher_url"] = publisher_url
                    item = {
                        "item_id": item_id,
                        "title": str(metadata["title"]),
                        "canonical_url": metadata["url"],
                        "media": [{
                            "type": "youtube",
                            "media_id": video_id,
                            "canonical_url": metadata["url"],
                        }],
                        "attribution": attribution,
                        "source_provenance": {"playlist_id": playlist_id},
                        "metadata": {
                            "duration_seconds": metadata.get("duration_seconds"),
                            "published_at": metadata.get("published_at"),
                            "thumbnail_url": metadata.get("thumbnail_url"),
                            "chapters": metadata.get("chapters", []),
                        },
                    }
                    items.append(item)
                    items_by_id[item_id] = item
            if item is not None:
                placements.append({
                    "placement_id": f"playlist-entry:{position}",
                    "item_id": item_id,
                    "parent_node_id": "playlist-root",
                    "position": position,
                    "source_url": playlist["url"],
                    "metadata": {},
                })

        completed = position
        if completed % 10 == 0:
            checkpoint = {
                "kind": "watchcraft.youtube-playlist-iterator-checkpoint",
                "schema_version": 1,
                "handler": {
                    "id": YOUTUBE_PLAYLIST_ITERATOR_HANDLER[0],
                    "version": YOUTUBE_PLAYLIST_ITERATOR_HANDLER[1],
                },
                "spec_sha256": context.job["spec_sha256"],
                "project": {
                    "project_id": project["project_id"],
                    "revision": project["revision"],
                },
                "playlist_id": playlist_id,
                "entries_sha256": sha256_hex(canonical_json(entries)),
                "next_index": completed,
                "items": items,
                "placements": placements,
                "unresolved": unresolved,
            }
            context.save_checkpoint(
                checkpoint,
                sequence=completed // 10,
                phase="enumerating",
                completed=completed,
                total=total,
                unit="placements",
                current=current,
            )
        else:
            context.report_progress(
                phase="enumerating",
                completed=completed,
                total=total,
                unit="placements",
                current=current,
            )

    publisher_names = sorted({item["attribution"]["publisher"] for item in items})
    source_metadata: dict[str, Any] = {
        "description": playlist.get("description", ""),
        "duplicate_entries": playlist.get("duplicate_count", 0),
    }
    if len(publisher_names) == 1:
        source_metadata["publisher"] = publisher_names[0]
    warnings = []
    if playlist.get("duplicate_count"):
        warnings.append(
            f"The playlist contains {playlist['duplicate_count']} duplicate placement(s)."
        )
    snapshot = {
        "kind": "watchcraft.collection-iterator-snapshot",
        "schema_version": 1,
        "project": {
            "project_id": project["project_id"],
            "revision": project["revision"],
        },
        "iterator": {
            "id": iterator["id"],
            "version": iterator["version"],
        },
        "observed_at": observed_at,
        "source": {
            "source_id": f"youtube-playlist:{playlist_id}",
            "source_type": "youtube-playlist",
            "title": playlist["title"],
            "canonical_url": playlist["url"],
            "metadata": source_metadata,
        },
        "nodes": [{
            "node_id": "playlist-root",
            "node_type": "playlist",
            "title": playlist["title"],
            "canonical_url": playlist["url"],
            "parent_node_id": None,
            "position": 1,
            "metadata": {},
        }],
        "items": items,
        "placements": placements,
        "coverage": {
            "basis": "source-entries",
            "expected": total,
            "resolved": len(placements),
            "unresolved": unresolved,
        },
        "metadata_proposals": [{
            "field": "metadata.title",
            "value": playlist["title"],
            "basis": {"source_path": "source.title", "confidence": 1.0},
        }],
        "structure_hash": "",
        "provenance": {
            "access_profile": iterator["access_profile"],
            "discovery_mode": "bounded-crawl",
            "requested_url": requested_url,
            "retrieved_urls": list(dict.fromkeys(
                [playlist["url"]] + [item["canonical_url"] for item in items]
            )),
            "warnings": warnings,
        },
    }
    if playlist.get("description"):
        snapshot["metadata_proposals"].append({
            "field": "metadata.description",
            "value": playlist["description"],
            "basis": {"source_path": "source.metadata.description", "confidence": 1.0},
        })
    snapshot["structure_hash"] = iterator_structure_sha256(snapshot)
    context.report_progress(
        phase="validating",
        completed=0,
        total=1,
        unit="snapshot",
    )
    validate_iterator_snapshot(snapshot)
    context.report_progress(
        phase="validating",
        completed=1,
        total=1,
        unit="snapshot",
    )
    return snapshot


HANDLERS[YOUTUBE_PLAYLIST_ITERATOR_HANDLER] = youtube_playlist_iterator


def _planned_item_task_id(item_id: str, stage: str) -> str:
    return f"item:{sha256_hex(item_id)[:16]}:{stage}"


def project_processing_planner(
    job: dict[str, Any], context: WorkerContext | None = None
) -> dict[str, Any]:
    if context is None:
        raise RuntimeError("Project processing planner requires a worker context")
    spec = job["spec"]
    configuration = spec.get("configuration")
    if not isinstance(configuration, dict) or set(configuration) != {
        "project", "planned_at"
    }:
        raise ValueError("Project processing planner configuration is invalid")
    project = configuration["project"]
    validate_json_schema(project, CATALOG_PROJECT_SCHEMA_PATH, "Catalog project")
    accepted = project.get("iterator", {}).get("accepted_snapshot")
    inputs = spec.get("inputs")
    if accepted is None or inputs != [accepted]:
        raise ValueError("Project processing job is not bound to its accepted snapshot")
    reference = validated_artifact_reference(accepted)
    try:
        payload = context.artifact_store().get_bytes(reference)
    except Exception as error:
        raise ProjectPlanningError(
            "Could not retrieve and verify the accepted iterator snapshot",
            retryable=True,
        ) from error
    try:
        snapshot = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProjectPlanningError(
            "Accepted iterator snapshot is not valid UTF-8 JSON"
        ) from error
    if not isinstance(snapshot, dict):
        raise ProjectPlanningError("Accepted iterator snapshot must be an object")
    validate_iterator_snapshot(snapshot)
    snapshot_project = snapshot.get("project", {})
    if (
        snapshot_project.get("project_id") != project["project_id"]
        or snapshot_project.get("revision", project["revision"]) > project["revision"]
        or snapshot.get("iterator") != {
            "id": project["iterator"]["id"],
            "version": project["iterator"]["version"],
        }
        or snapshot.get("provenance", {}).get("access_profile")
        != project["iterator"]["access_profile"]
    ):
        raise ValueError("Accepted snapshot does not match the catalog project")

    placements_by_item: dict[str, list[str]] = {
        item["item_id"]: [] for item in snapshot["items"]
    }
    for placement in snapshot["placements"]:
        placements_by_item[placement["item_id"]].append(placement["placement_id"])

    item_plans = []
    known_duration_seconds = 0.0
    unknown_duration_items = 0
    total = len(snapshot["items"])
    for index, item in enumerate(snapshot["items"], start=1):
        youtube_media = next(
            (media for media in item["media"] if media["type"] == "youtube"),
            None,
        )
        if youtube_media is None:
            raise ValueError(
                f"Project processing planner does not support item {item['item_id']} media"
            )
        metadata = item.get("metadata", {})
        duration = metadata.get("duration_seconds")
        metadata_gaps = []
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
            metadata_gaps.append("duration")
            unknown_duration_items += 1
        else:
            known_duration_seconds += float(duration)
        if not metadata.get("published_at"):
            metadata_gaps.append("publication-date")
        if "captions" not in metadata:
            metadata_gaps.append("captions")

        metadata_task = _planned_item_task_id(item["item_id"], "metadata")
        acquisition_task = _planned_item_task_id(item["item_id"], "acquisition")
        transcription_task = _planned_item_task_id(item["item_id"], "transcription")
        analysis_task = _planned_item_task_id(item["item_id"], "analysis")
        item_plans.append({
            "item_id": item["item_id"],
            "title": item["title"],
            "placement_ids": placements_by_item[item["item_id"]],
            "source": {
                "media_asset_id": item["item_id"],
                "media_type": youtube_media["type"],
                "media_id": youtube_media["media_id"],
                "canonical_url": youtube_media.get("canonical_url", item["canonical_url"]),
            },
            "metadata_gaps": metadata_gaps,
            "stages": [
                {
                    "stage": "metadata-enrichment",
                    "task_id": metadata_task,
                    "disposition": "required",
                    "executor": "operator-local",
                    "handler": {"id": "watchcraft.metadata.youtube", "version": "1"},
                    "depends_on": [],
                    "reuse": {
                        "status": "not-applicable",
                        "reason": "Metadata is refreshed from the selected source item.",
                    },
                },
                {
                    "stage": "source-acquisition",
                    "task_id": acquisition_task,
                    "disposition": "required",
                    "executor": "operator-local",
                    "handler": {"id": "watchcraft.acquire.youtube-audio", "version": "1"},
                    "depends_on": [metadata_task],
                    "reuse": {
                        "status": "deferred",
                        "reason": "Safe reuse requires an exact source-audio content digest.",
                    },
                },
                {
                    "stage": "transcription",
                    "task_id": transcription_task,
                    "disposition": "required",
                    "executor": "registered-worker",
                    "handler": {
                        "id": PRODUCTION_TRANSCRIPTION_HANDLER[0],
                        "version": PRODUCTION_TRANSCRIPTION_HANDLER[1],
                    },
                    "execution_profile": {
                        "id": MLX_EXECUTION_PROFILE[0],
                        "version": MLX_EXECUTION_PROFILE[1],
                    },
                    "depends_on": [acquisition_task],
                    "reuse": {
                        "status": "deferred",
                        "reason": "Safe reuse requires the acquired audio digest and exact job spec.",
                    },
                },
                {
                    "stage": "analysis",
                    "task_id": analysis_task,
                    "disposition": "required",
                    "executor": "registered-worker",
                    "handler": {
                        "id": EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0],
                        "version": EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[1],
                    },
                    "execution_profile": {
                        "id": OPENAI_EXECUTION_PROFILE[0],
                        "version": OPENAI_EXECUTION_PROFILE[1],
                    },
                    "depends_on": [transcription_task],
                    "reuse": {
                        "status": "deferred",
                        "reason": "Safe reuse requires the authoritative transcript digest and exact job spec.",
                    },
                },
            ],
        })
        context.report_progress(
            phase="planning",
            completed=index,
            total=total,
            unit="items",
            current=item["title"],
        )

    analysis_ids = [item["stages"][-1]["task_id"] for item in item_plans]
    normalization_task = f"project:{sha256_hex(project['project_id'])[:16]}:topics"
    collection_tasks = [
        {
            "stage": "topic-normalization",
            "task_id": normalization_task,
            "disposition": "deferred",
            "reason": "Realized after every planned analysis has an immutable artifact.",
            "depends_on": analysis_ids,
        },
        {
            "stage": "collection-compilation",
            "task_id": f"project:{sha256_hex(project['project_id'])[:16]}:compile",
            "disposition": "deferred",
            "reason": "Realized after topic normalization has an immutable artifact.",
            "depends_on": [normalization_task],
        },
    ]
    plan = {
        "kind": "watchcraft.project-processing-plan",
        "schema_version": 1,
        "project": {
            "project_id": project["project_id"],
            "revision": project["revision"],
        },
        "planner": {
            "id": PROJECT_PROCESSING_PLANNER_HANDLER[0],
            "version": PROJECT_PROCESSING_PLANNER_HANDLER[1],
        },
        "source_snapshot": reference,
        "planned_at": configuration["planned_at"],
        "items": item_plans,
        "collection_tasks": collection_tasks,
        "summary": {
            "unique_items": len(item_plans),
            "placements": len(snapshot["placements"]),
            "operator_local_tasks": len(item_plans) * 2,
            "registered_worker_jobs": len(item_plans) * 2,
            "deferred_collection_jobs": len(collection_tasks),
        },
        "estimate": {
            "status": (
                "duration-informed" if unknown_duration_items == 0 else "bounded-only"
            ),
            "basis": "registered-worker-timeout-upper-bounds",
            "known_media_duration_seconds": known_duration_seconds,
            "unknown_duration_items": unknown_duration_items,
            "sequential_worker_upper_bound_minutes": len(item_plans) * (
                LOCAL_EXECUTION_PROFILES[MLX_EXECUTION_PROFILE]["timeout_minutes"]
                + LOCAL_EXECUTION_PROFILES[OPENAI_EXECUTION_PROFILE]["timeout_minutes"]
            ),
            "parallel_wall_clock_ms": None,
            "caveats": [
                "The bound excludes local metadata enrichment and source acquisition.",
                "Actual concurrency and queue latency are not known at planning time.",
                "Historical duration heuristics have not been calibrated yet.",
            ],
        },
        "plan_hash": "",
    }
    plan["plan_hash"] = project_processing_plan_sha256(plan)
    validate_project_processing_plan(plan)
    return plan


HANDLERS[PROJECT_PROCESSING_PLANNER_HANDLER] = project_processing_planner


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
    context = WorkerContext(
        control=control,
        job=job,
        attempt_id=attempt_id,
        lease_duration_ms=lease_duration_ms,
    )
    handler_key = (job["spec"]["handler"]["id"], job["spec"]["handler"]["version"])
    handler = HANDLERS[handler_key]
    try:
        output = handler(job, context)
        job = context.job
    except Exception as error:
        classification = getattr(error, "classification", "handler_failed")
        retryable = getattr(error, "retryable", False)
        if not isinstance(classification, str) or not classification:
            classification = "handler_failed"
        if not isinstance(retryable, bool):
            retryable = False
        control.post("/jobs/fail", {
            "job_id": job_id,
            "command_id": f"{attempt_id}:handler-fail",
            "expected_revision": context.job["revision"],
            "attempt_id": attempt_id,
            "failure": {
                "classification": classification,
                "message": str(error)[:500],
                "retryable": retryable,
            },
        })
        raise
    try:
        iterator_output = job["spec"]["artifact_kind"] == "collection-iterator-snapshot"
        if iterator_output:
            context.report_progress(
                phase="storing",
                completed=0,
                total=1,
                unit="snapshot",
            )
            job = context.job
        artifact = context.artifact_store().put_json(output, {
            "artifact_kind": job["spec"]["artifact_kind"],
            "schema": job["spec"]["output_schema"],
        })
        if iterator_output:
            context.report_progress(
                phase="storing",
                completed=1,
                total=1,
                unit="snapshot",
            )
            job = context.job
    except Exception as error:
        control.post("/jobs/fail", {
            "job_id": job_id,
            "command_id": f"{attempt_id}:storage-fail",
            "expected_revision": context.job["revision"],
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
        "expected_revision": context.job["revision"],
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


def educational_video_analysis_spec(
    *,
    source: dict[str, Any],
    transcript: dict[str, Any],
    source_metadata: dict[str, Any],
    video: str,
) -> dict[str, Any]:
    if isinstance(transcript, dict) and transcript.get("kind") == "job-output":
        reference = {
            "kind": "job-output",
            "job_id": transcript.get("job_id"),
            "artifact_kind": transcript.get("artifact_kind"),
            "schema": transcript.get("schema"),
        }
    else:
        reference = validated_artifact_reference(transcript)
    if (
        reference.get("artifact_kind") != "transcript"
        or reference.get("schema")
        != {"id": "watchcraft.transcript", "version": 1}
        or (
            reference.get("kind") != "job-output"
            and reference.get("media_type") != "application/json"
        )
        or (
            reference.get("kind") == "job-output"
            and (
                not isinstance(reference.get("job_id"), str)
                or not reference["job_id"]
            )
        )
    ):
        raise ValueError("Analysis requires an authoritative transcript@1 JSON artifact")
    if (
        not isinstance(source_metadata, dict)
        or source_metadata.get("source_id") != source.get("media_asset_id")
    ):
        raise ValueError("Analysis source metadata does not match the transcript source")
    return {
        "operation": "generate",
        "artifact_kind": "analysis",
        "output_schema": VIDEO_ANALYSIS_SCHEMA,
        "handler": {
            "id": EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0],
            "version": EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[1],
        },
        "source": source,
        "inputs": [],
        "dependencies": [reference],
        "configuration": {
            "model": EDUCATIONAL_VIDEO_ANALYSIS_MODEL,
            "prompt_version": EDUCATIONAL_VIDEO_ANALYSIS_PROMPT_VERSION,
            "retries": EDUCATIONAL_VIDEO_ANALYSIS_RETRIES,
            "timeout_seconds": EDUCATIONAL_VIDEO_ANALYSIS_TIMEOUT_SECONDS,
            "max_transcript_chars": EDUCATIONAL_VIDEO_ANALYSIS_MAX_TRANSCRIPT_CHARS,
            "source_metadata": source_metadata,
            "video": video,
        },
    }


def youtube_source_metadata(video_id: str) -> dict[str, Any]:
    from watchcraft_author import youtube_metadata

    return youtube_metadata(video_id)


def transcription_smoke_spec(fixture_text: str = TRANSCRIPTION_SMOKE_TEXT) -> dict[str, Any]:
    return {
        "operation": "generate",
        "artifact_kind": "transcript",
        "output_schema": {"id": "watchcraft.transcript", "version": 1},
        "handler": {
            "id": TRANSCRIPTION_SMOKE_HANDLER[0],
            "version": TRANSCRIPTION_SMOKE_HANDLER[1],
        },
        "source": {"media_asset_id": "synthetic:mlx-audio-smoke"},
        "inputs": [],
        "dependencies": [],
        "configuration": {
            "fixture_text": fixture_text,
            "language": "en",
            "model": TRANSCRIPTION_SMOKE_MODEL,
        },
    }


def http_transcription_smoke_spec() -> dict[str, Any]:
    return {
        "operation": "generate",
        "artifact_kind": "transcript",
        "output_schema": {"id": "watchcraft.transcript", "version": 1},
        "handler": {
            "id": HTTP_TRANSCRIPTION_SMOKE_HANDLER[0],
            "version": HTTP_TRANSCRIPTION_SMOKE_HANDLER[1],
        },
        "source": {"media_asset_id": "fixture:openai-whisper-jfk-flac"},
        "inputs": [],
        "dependencies": [],
        "configuration": {
            "url": HTTP_TRANSCRIPTION_SMOKE_URL,
            "expected_sha256": HTTP_TRANSCRIPTION_SMOKE_SHA256,
            "expected_bytes": HTTP_TRANSCRIPTION_SMOKE_BYTES,
            "maximum_bytes": HTTP_TRANSCRIPTION_SMOKE_MAX_BYTES,
            "timeout_seconds": HTTP_TRANSCRIPTION_SMOKE_TIMEOUT_SECONDS,
            "language": "en",
            "model": TRANSCRIPTION_SMOKE_MODEL,
        },
    }


def source_audio_media_type(container: Any) -> str:
    return {
        "aac": "audio/aac",
        "flac": "audio/flac",
        "m4a": "audio/mp4",
        "mp3": "audio/mpeg",
        "ogg": "audio/ogg",
        "opus": "audio/ogg",
        "wav": "audio/wav",
        "webm": "audio/webm",
    }.get(str(container).casefold(), "audio/x-unknown")


def youtube_acquisition_provenance(
    acquisition: dict[str, Any],
    *,
    elapsed_ms: int,
) -> dict[str, Any]:
    video_id = acquisition["video_id"]
    return {
        "method": {
            "id": "watchcraft.youtube.yt-dlp-local",
            "version": "1",
        },
        "source": {
            "media_asset_id": f"youtube:{video_id}",
            "provider": "youtube",
            "video_id": video_id,
            "canonical_url": acquisition["canonical_url"],
        },
        "observed_at": int(time.time() * 1000),
        "tool": {
            "id": "yt-dlp",
            "version": acquisition["yt_dlp_version"],
        },
        "timing": {"acquisition_ms": elapsed_ms},
        "media": {
            "algorithm": acquisition["algorithm"],
            "digest": acquisition["digest"],
            "byte_length": acquisition["byte_length"],
            "duration_seconds": acquisition["duration_seconds"],
            "format_id": acquisition.get("format_id"),
            "language": acquisition.get("audio_language"),
            "container": acquisition.get("container"),
        },
    }


def timestamp_delta_ms(later: Any, earlier: Any) -> int | None:
    if (
        isinstance(later, bool)
        or not isinstance(later, (int, float))
        or isinstance(earlier, bool)
        or not isinstance(earlier, (int, float))
        or later < earlier
    ):
        return None
    return round(later - earlier)


def completed_job_timing(job: dict[str, Any]) -> dict[str, int]:
    timing: dict[str, int] = {}
    submitted_to_completed_ms = timestamp_delta_ms(
        job.get("updated_at"), job.get("created_at")
    )
    if submitted_to_completed_ms is not None:
        timing["submitted_to_completed_ms"] = submitted_to_completed_ms

    dispatch = job.get("dispatch")
    dispatch_requested_at = (
        dispatch.get("requested_at") if isinstance(dispatch, dict) else None
    )
    submission_to_dispatch_ms = timestamp_delta_ms(
        dispatch_requested_at, job.get("created_at")
    )
    if submission_to_dispatch_ms is not None:
        timing["submission_to_dispatch_ms"] = submission_to_dispatch_ms
    dispatch_to_completed_ms = timestamp_delta_ms(
        job.get("updated_at"), dispatch_requested_at
    )
    if dispatch_to_completed_ms is not None:
        timing["dispatch_to_completed_ms"] = dispatch_to_completed_ms

    attempts = job.get("attempts")
    succeeded = (
        [attempt for attempt in attempts if attempt.get("state") == "succeeded"]
        if isinstance(attempts, list)
        else []
    )
    if succeeded:
        attempt = succeeded[-1]
        attempt_ms = timestamp_delta_ms(
            attempt.get("updated_at"), attempt.get("started_at")
        )
        if attempt_ms is not None:
            timing["worker_attempt_ms"] = attempt_ms
        dispatch_to_worker_ms = timestamp_delta_ms(
            attempt.get("started_at"), dispatch_requested_at
        )
        if dispatch_to_worker_ms is not None:
            timing["dispatch_to_worker_ms"] = dispatch_to_worker_ms
    return timing


def compact_transcription_result(
    completed: dict[str, Any],
    result: dict[str, Any],
    *,
    local_timing: dict[str, int],
) -> dict[str, Any]:
    text = result.get("text")
    normalized_text = " ".join(text.split()) if isinstance(text, str) else ""
    preview = normalized_text[:240]
    if len(normalized_text) > len(preview):
        preview += "…"
    provenance = result.get("provenance")
    worker_timing = (
        provenance.get("timing") if isinstance(provenance, dict) else None
    )
    acquisition = (
        provenance.get("acquisition") if isinstance(provenance, dict) else None
    )
    media = acquisition.get("media") if isinstance(acquisition, dict) else None
    source = result.get("source")
    segments = result.get("segments")
    return {
        "job_id": completed["job"]["job_id"],
        "run_id": completed["run"]["run_id"],
        "state": completed["job"]["state"],
        "artifact": completed["job"]["result"],
        "source": {
            "media_asset_id": (
                source.get("media_asset_id") if isinstance(source, dict) else None
            ),
            "audio_duration_seconds": (
                media.get("duration_seconds") if isinstance(media, dict) else None
            ),
        },
        "transcript": {
            "model": result.get("model"),
            "language": result.get("language"),
            "characters": len(text) if isinstance(text, str) else 0,
            "segments": len(segments) if isinstance(segments, list) else 0,
            "preview": preview,
        },
        "timing": {
            "local": local_timing,
            "ledger": completed_job_timing(completed["job"]),
            "worker": worker_timing if isinstance(worker_timing, dict) else {},
        },
    }


def compact_analysis_result(
    completed: dict[str, Any],
    result: dict[str, Any],
    *,
    local_timing: dict[str, int],
) -> dict[str, Any]:
    summary = result.get("summary")
    normalized_summary = (
        " ".join(summary.split()) if isinstance(summary, str) else ""
    )
    preview = normalized_summary[:240]
    if len(normalized_summary) > len(preview):
        preview += "…"
    provenance = result.get("provenance")
    worker_timing = (
        provenance.get("timing") if isinstance(provenance, dict) else None
    )
    topics = result.get("topics")
    sections = result.get("sections")
    techniques = result.get("featured_techniques")
    return {
        "job_id": completed["job"]["job_id"],
        "run_id": completed["run"]["run_id"],
        "state": completed["job"]["state"],
        "artifact": completed["job"]["result"],
        "analysis": {
            "video": result.get("video"),
            "title": result.get("title"),
            "model": result.get("analysis_model"),
            "topics": len(topics) if isinstance(topics, list) else 0,
            "sections": len(sections) if isinstance(sections, list) else 0,
            "featured_techniques": (
                len(techniques) if isinstance(techniques, list) else 0
            ),
            "summary_preview": preview,
        },
        "timing": {
            "local": local_timing,
            "ledger": completed_job_timing(completed["job"]),
            "worker": worker_timing if isinstance(worker_timing, dict) else {},
        },
    }


def compact_terminology_resolution_result(
    completed: dict[str, Any],
    result: dict[str, Any],
    *,
    local_timing: dict[str, int],
) -> dict[str, Any]:
    provenance = result.get("provenance")
    worker_timing = (
        provenance.get("timing") if isinstance(provenance, dict) else None
    )
    return {
        "job_id": completed["job"]["job_id"],
        "run_id": completed["run"]["run_id"],
        "state": completed["job"]["state"],
        "artifact": completed["job"]["result"],
        "project": result["project"],
        "stats": result["stats"],
        "automatic_safe": [
            {
                "observed_forms": item["observed_forms"],
                "canonical_term": item["canonical_term"],
                "display_label": item["display_label"],
                "confidence": item["confidence"],
            }
            for item in result["resolutions"]
            if item["disposition"] == "automatic-safe"
        ],
        "needs_review": [
            {
                "observed_forms": item["observed_forms"],
                "canonical_term": item["canonical_term"],
                "alternatives": item["alternatives"],
                "affected_items": item["affected_items"],
                "confidence": item["confidence"],
                "rationale": item["rationale"],
            }
            for item in result["resolutions"]
            if item["disposition"] == "needs-review"
        ],
        "timing": {
            "local": local_timing,
            "ledger": completed_job_timing(completed["job"]),
            "worker": worker_timing if isinstance(worker_timing, dict) else {},
        },
    }


def staged_transcription_spec(
    *,
    source: dict[str, Any],
    source_audio: dict[str, Any],
    acquisition: dict[str, Any],
    handler: tuple[str, str] = PRODUCTION_TRANSCRIPTION_HANDLER,
) -> dict[str, Any]:
    reference = validated_artifact_reference(source_audio, allow_staged=True)
    if (
        reference.get("artifact_kind") != "source-audio"
        or reference.get("schema") != SOURCE_AUDIO_SCHEMA
    ):
        raise ValueError("Staged transcription requires a source-audio artifact")
    acquisition_source = acquisition.get("source") if isinstance(acquisition, dict) else None
    acquisition_media = acquisition.get("media") if isinstance(acquisition, dict) else None
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("media_asset_id"), str)
        or not isinstance(acquisition_source, dict)
        or acquisition_source.get("media_asset_id") != source["media_asset_id"]
        or not isinstance(acquisition_media, dict)
        or acquisition_media.get("algorithm") != reference["algorithm"]
        or acquisition_media.get("digest") != reference["digest"]
        or acquisition_media.get("byte_length") != reference["byte_length"]
    ):
        raise ValueError("Acquisition provenance must bind the staged source audio")
    settings = STAGED_TRANSCRIPTION_SETTINGS.get(handler)
    if settings is None:
        raise ValueError("Staged transcription requires a registered handler identity")
    duration = acquisition_media.get("duration_seconds")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not 0 < duration <= settings["maximum_duration_seconds"]
        or reference["byte_length"] > settings["maximum_bytes"]
    ):
        raise ValueError("Staged source audio exceeds the handler media limits")
    return {
        "operation": "generate",
        "artifact_kind": "transcript",
        "output_schema": {"id": "watchcraft.transcript", "version": 1},
        "handler": {
            "id": handler[0],
            "version": handler[1],
        },
        "source": source,
        "inputs": [reference],
        "dependencies": [],
        "configuration": {
            "acquisition": acquisition,
            "maximum_bytes": settings["maximum_bytes"],
            "maximum_duration_seconds": settings["maximum_duration_seconds"],
            "language": "en",
            "model": settings["model"],
        },
    }


def ephemeral_request(kind: str, source_id: str, retention_days: int) -> dict[str, Any]:
    if not 1 <= retention_days <= 90:
        raise ValueError("--retention-days must be between 1 and 90")
    return {
        "kind": kind,
        "source_id": source_id,
        "purpose": "smoke",
        "retention": {
            "class": "ephemeral",
            "expires_at": int(time.time() * 1000) + retention_days * 86_400_000,
        },
    }


def submit_spec(
    control: AuthoringHttpClient,
    *,
    request: dict[str, Any],
    spec: dict[str, Any],
    job_id: str | None = None,
    run_id: str | None = None,
    command_prefix: str | None = None,
) -> dict[str, Any]:
    return control.post("/submissions/submit", {
        "job_id": job_id or str(uuid.uuid4()),
        "run_id": run_id or str(uuid.uuid4()),
        "command_prefix": command_prefix or str(uuid.uuid4()),
        "request": request,
        "spec": spec,
    })


def submit_pipeline(
    control: AuthoringHttpClient,
    *,
    request: dict[str, Any],
    jobs: list[dict[str, Any]],
    run_id: str | None = None,
    command_prefix: str | None = None,
) -> dict[str, Any]:
    return control.post("/pipelines/submit", {
        "run_id": run_id or str(uuid.uuid4()),
        "command_prefix": command_prefix or str(uuid.uuid4()),
        "request": request,
        "jobs": jobs,
    })


def dispatch_submission(control: AuthoringHttpClient, job: dict[str, Any]) -> dict[str, Any]:
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
    command = [
        "gh", "workflow", "run", workflow, "--ref", "main",
        "--repo", DEFAULT_GITHUB_REPOSITORY,
        "-f", f"job_id={pending['job_id']}",
        "-f", f"spec_sha256={pending['spec_sha256']}",
        "-f", f"dispatch_generation={pending['dispatch']['generation']}",
        "-f", f"expected_revision={pending['revision']}",
    ]
    if workflow == MLX_EXECUTION_WORKFLOW:
        handler = pending.get("spec", {}).get("handler", {})
        handler_identity = (handler.get("id"), handler.get("version"))
        cache_key = MLX_MODEL_CACHE_KEYS.get(handler_identity)
        if cache_key is None:
            raise RuntimeError("MLX job has no bounded model-cache identity")
        command.extend(["-f", f"model_cache_key={cache_key}"])
    subprocess.run(command, check=True)
    return pending


def verified_json_result_bytes(
    job: dict[str, Any], credential_source: str
) -> tuple[dict[str, Any], bytes]:
    if job.get("state") != "succeeded" or job.get("result") is None:
        raise RuntimeError(
            f"Job {job['job_id']} is {job.get('state', 'unknown')}; "
            "a result is available only after it succeeds"
        )
    reference = validated_artifact_reference(job["result"])
    payload = r2_artifact_reader(credential_source).get_bytes(reference)
    if reference["media_type"] != "application/json":
        raise RuntimeError(f"Artifact media type is {reference['media_type']}; expected JSON")
    try:
        result = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("The verified artifact is not valid UTF-8 JSON") from error
    if not isinstance(result, dict):
        raise RuntimeError("The verified JSON artifact must be an object")
    return result, payload


def verified_json_result(job: dict[str, Any], credential_source: str) -> dict[str, Any]:
    return verified_json_result_bytes(job, credential_source)[0]


def wait_for_terminal_job(
    control: AuthoringHttpClient,
    job_id: str,
    timeout_seconds: int,
    poll_seconds: float = 5.0,
    progress_seconds: float = 30.0,
) -> dict[str, Any]:
    if timeout_seconds < 1:
        raise ValueError("--timeout-seconds must be positive")
    if poll_seconds <= 0 or progress_seconds <= 0:
        raise ValueError("poll and progress intervals must be positive")
    started_at = time.monotonic()
    deadline = started_at + timeout_seconds
    next_progress_at = started_at + progress_seconds
    last_state = None
    last_progress = None
    while True:
        submission = control.post("/submissions/get", {"job_id": job_id})
        job = submission["job"]
        state = job.get("state")
        state_changed = state != last_state
        progress = formatted_job_progress(job)
        progress_changed = progress is not None and progress != last_progress
        terminal = state in {
            "succeeded", "retryable_failed", "terminal_failed", "cancelled"
        }
        if progress_changed and terminal:
            print(f"{job_id}: {progress}", flush=True)
            last_progress = progress
        if state_changed:
            print(f"{job_id}: {state}", flush=True)
            last_state = state
        if progress_changed and not terminal:
            print(f"{job_id}: {progress}", flush=True)
            last_progress = progress
        if state == "succeeded":
            return submission
        if state in {"retryable_failed", "terminal_failed", "cancelled"}:
            failure = job.get("failure") or {}
            raise RuntimeError(
                f"Job {job_id} ended as {state}: "
                f"{failure.get('classification', 'unknown')} {failure.get('message', '')}".strip()
            )
        now = time.monotonic()
        if now >= deadline:
            raise RuntimeError(f"Timed out after {timeout_seconds}s waiting for job {job_id}")
        if not state_changed and not progress_changed and now >= next_progress_at:
            elapsed_seconds = int(now - started_at)
            print(
                f"{job_id}: still waiting ({state}, {elapsed_seconds}s elapsed)",
                flush=True,
            )
            while next_progress_at <= now:
                next_progress_at += progress_seconds
        time.sleep(poll_seconds)


def formatted_job_progress(job: dict[str, Any]) -> str | None:
    attempts = job.get("attempts")
    if not isinstance(attempts, list) or not attempts or not isinstance(attempts[-1], dict):
        return None
    progress = attempts[-1].get("progress")
    if not isinstance(progress, dict):
        return None
    phase = progress.get("phase")
    completed = progress.get("completed")
    total = progress.get("total")
    unit = progress.get("unit")
    if not isinstance(phase, str) or not isinstance(completed, int) or not isinstance(unit, str):
        return None
    count = f"{completed} of {total}" if isinstance(total, int) else str(completed)
    message = f"{phase}: {count} {unit}"
    current = progress.get("current")
    if isinstance(current, str) and current:
        message += f" — {current}"
    return message


def run_smoke_command(args: argparse.Namespace, kind: str) -> int:
    control = operator_client(args.operator_token_source)
    if kind == "analysis":
        spec_args = argparse.Namespace(
            source_id="synthetic:lexical-analysis-smoke",
            title="Watchcraft lexical smoke",
            text="Balance exposure and color before applying the final grade.",
            max_topics=8,
        )
        spec = analysis_spec(spec_args)
        request_kind = "lexical-analysis-smoke"
    elif kind == "transcription":
        spec = transcription_smoke_spec()
        request_kind = "mlx-transcription-smoke"
    elif kind == "transcription-http":
        spec = http_transcription_smoke_spec()
        request_kind = "mlx-transcription-http-smoke"
    else:
        raise ValueError(f"Unsupported worker-only smoke kind {kind!r}")
    submitted = submit_spec(
        control,
        request=ephemeral_request(
            request_kind,
            spec["source"]["media_asset_id"],
            args.retention_days,
        ),
        spec=spec,
    )
    job = submitted["job"]
    print(f"submitted {job['job_id']} ({job['spec']['handler']['id']})", flush=True)
    approved = control.post("/submissions/approve", {
        "job_id": job["job_id"],
        "command_id": str(uuid.uuid4()),
        "expected_revision": job["revision"],
        "actor": "watchcraft-author-cli:smoke",
        "spec_sha256": job["spec_sha256"],
    })
    pending = dispatch_submission(control, approved["job"])
    print(
        f"dispatched {pending['job_id']} via {dispatch_workflow(pending)} "
        f"generation {pending['dispatch']['generation']}",
        flush=True,
    )
    completed = wait_for_terminal_job(control, job["job_id"], args.timeout_seconds)
    result = verified_json_result(completed["job"], args.r2_credentials_source)
    expected_kind = "watchcraft.analysis.lexical" if kind == "analysis" else "watchcraft.transcript"
    if result.get("kind") != expected_kind:
        raise RuntimeError(
            f"Smoke artifact kind is {result.get('kind')!r}; expected {expected_kind!r}"
        )
    if kind in {"transcription", "transcription-http"}:
        if not result.get("text") or not result.get("segments"):
            raise RuntimeError("Transcription smoke returned no text or segments")
        provenance = result.get("provenance", {})
        expected_handler = (
            TRANSCRIPTION_SMOKE_HANDLER
            if kind == "transcription"
            else HTTP_TRANSCRIPTION_SMOKE_HANDLER
        )
        if provenance.get("handler_id") != expected_handler[0]:
            raise RuntimeError("Transcription smoke provenance does not identify the MLX handler")
        if kind == "transcription-http":
            acquisition = provenance.get("acquisition", {})
            if (
                acquisition.get("digest") != HTTP_TRANSCRIPTION_SMOKE_SHA256
                or acquisition.get("byte_length") != HTTP_TRANSCRIPTION_SMOKE_BYTES
            ):
                raise RuntimeError("HTTP transcription smoke provenance has invalid media identity")
    print(json.dumps({
        "job_id": completed["job"]["job_id"],
        "run_id": completed["run"]["run_id"],
        "state": completed["job"]["state"],
        "artifact": completed["job"]["result"],
        "result": result,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def load_catalog_project(path: Path) -> dict[str, Any]:
    try:
        project = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read catalog project {path}: {error}") from error
    validate_json_schema(project, CATALOG_PROJECT_SCHEMA_PATH, "Catalog project")
    return project


def load_catalog_project_argument(
    value: str, control: AuthoringHttpClient
) -> dict[str, Any]:
    path = Path(value)
    if path.is_file():
        return load_catalog_project(path)
    if path.suffix == ".json" or len(path.parts) > 1:
        raise RuntimeError(f"Catalog project file does not exist: {path}")
    result = control.post("/projects/get", {"project_id": value})
    project = result.get("project")
    validate_json_schema(project, CATALOG_PROJECT_SCHEMA_PATH, "Catalog project")
    return project


def inferred_snapshot_path(project_path: Path) -> Path:
    suffix = ".project.json"
    if project_path.name.endswith(suffix):
        return project_path.with_name(
            project_path.name[: -len(suffix)] + ".snapshot.json"
        )
    return project_path.with_name(project_path.stem + ".snapshot.json")


def load_exact_json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read {label} {path}: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{label.capitalize()} must be a JSON object")
    return value, payload


def run_project_import(args: argparse.Namespace) -> int:
    control = operator_client(args.operator_token_source)
    project = load_catalog_project(args.project_file)
    snapshot_json = None
    accepted = project.get("iterator", {}).get("accepted_snapshot")
    if accepted is not None:
        snapshot_path = args.accepted_snapshot_file or inferred_snapshot_path(
            args.project_file
        )
        snapshot, snapshot_bytes = load_exact_json_object(
            snapshot_path, "accepted iterator snapshot"
        )
        validate_iterator_snapshot(snapshot)
        reference = validated_artifact_reference(accepted)
        if (
            len(snapshot_bytes) != reference["byte_length"]
            or sha256_hex(snapshot_bytes) != reference["digest"]
        ):
            raise RuntimeError(
                "Accepted iterator snapshot file does not match the project reference"
            )
        snapshot_json = snapshot_bytes.decode("utf-8")
    elif args.accepted_snapshot_file is not None:
        raise RuntimeError(
            "--accepted-snapshot-file requires a project with accepted_snapshot"
        )
    result = control.post("/projects/import", {
        "command_id": str(uuid.uuid4()),
        "actor": "watchcraft-author-cli",
        "project": project,
        **(
            {"accepted_snapshot_json": snapshot_json}
            if snapshot_json is not None
            else {}
        ),
    })
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def run_project_accept_snapshot(args: argparse.Namespace) -> int:
    control = operator_client(args.operator_token_source)
    current = control.post("/projects/get", {"project_id": args.project_id})
    project = current["project"]
    expected_revision = (
        args.expected_revision
        if args.expected_revision is not None
        else project["revision"]
    )
    if expected_revision != project["revision"]:
        raise RuntimeError(
            f"Expected revision {expected_revision} does not match current project "
            f"revision {project['revision']}"
        )
    submission = control.post("/submissions/get", {"job_id": args.job_id})
    snapshot, snapshot_bytes = verified_json_result_bytes(
        submission["job"], args.r2_credentials_source
    )
    validate_iterator_snapshot(snapshot)
    if snapshot.get("project") != {
        "project_id": args.project_id,
        "revision": expected_revision,
    }:
        raise RuntimeError(
            "Iterator candidate belongs to a different catalog project revision"
        )
    result = control.post("/projects/accept-snapshot", {
        "project_id": args.project_id,
        "job_id": args.job_id,
        "expected_revision": expected_revision,
        "command_id": str(uuid.uuid4()),
        "actor": "watchcraft-author-cli",
        "snapshot_json": snapshot_bytes.decode("utf-8"),
    })
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def run_iterate_project(args: argparse.Namespace) -> int:
    control = operator_client(args.operator_token_source)
    project = load_catalog_project_argument(args.project, control)
    spec = youtube_playlist_iterator_spec(project)
    submitted = submit_spec(
        control,
        request={
            "kind": "collection-iteration",
            "project_id": project["project_id"],
            "project_revision": project["revision"],
            "iterator": project["iterator"]["id"],
        },
        spec=spec,
    )
    job = submitted["job"]
    print(f"submitted {job['job_id']} ({job['spec']['handler']['id']})", flush=True)
    approved = control.post("/submissions/approve", {
        "job_id": job["job_id"],
        "command_id": str(uuid.uuid4()),
        "expected_revision": job["revision"],
        "actor": "watchcraft-author-cli",
        "spec_sha256": job["spec_sha256"],
    })
    pending = dispatch_submission(control, approved["job"])
    print(
        f"dispatched {pending['job_id']} via {dispatch_workflow(pending)} "
        f"generation {pending['dispatch']['generation']}",
        flush=True,
    )
    completed = wait_for_terminal_job(control, job["job_id"], args.timeout_seconds)
    snapshot = verified_json_result(completed["job"], args.r2_credentials_source)
    validate_iterator_snapshot(snapshot)
    if snapshot.get("project") != {
        "project_id": project["project_id"],
        "revision": project["revision"],
    }:
        raise RuntimeError("Iterator result belongs to a different catalog project revision")
    print(json.dumps({
        "job_id": completed["job"]["job_id"],
        "run_id": completed["run"]["run_id"],
        "state": completed["job"]["state"],
        "artifact": completed["job"]["result"],
        "iterator": snapshot["iterator"],
        "source": snapshot["source"],
        "coverage": snapshot["coverage"],
        "items": len(snapshot["items"]),
        "placements": len(snapshot["placements"]),
        "structure_hash": snapshot["structure_hash"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    print(
        "Full snapshot: ./authoring/watchcraft-author queue result "
        "--operator-token-source keychain --r2-credentials-source keychain "
        f"{completed['job']['job_id']}",
        flush=True,
    )
    return 0


def run_plan_project(args: argparse.Namespace) -> int:
    control = operator_client(args.operator_token_source)
    current = control.post("/projects/get", {"project_id": args.project_id})
    project = current.get("project")
    validate_json_schema(project, CATALOG_PROJECT_SCHEMA_PATH, "Catalog project")
    spec = project_processing_plan_spec(project)
    submitted = submit_spec(
        control,
        request={
            "kind": "project-processing-plan",
            "project_id": project["project_id"],
            "project_revision": project["revision"],
            "accepted_snapshot_sha256": project["iterator"]["accepted_snapshot"]["digest"],
        },
        spec=spec,
    )
    job = submitted["job"]
    print(f"submitted {job['job_id']} ({job['spec']['handler']['id']})", flush=True)
    approved = control.post("/submissions/approve", {
        "job_id": job["job_id"],
        "command_id": str(uuid.uuid4()),
        "expected_revision": job["revision"],
        "actor": "watchcraft-author-cli",
        "spec_sha256": job["spec_sha256"],
    })
    pending = dispatch_submission(control, approved["job"])
    print(
        f"dispatched {pending['job_id']} via {dispatch_workflow(pending)} "
        f"generation {pending['dispatch']['generation']}",
        flush=True,
    )
    completed = wait_for_terminal_job(control, job["job_id"], args.timeout_seconds)
    plan = verified_json_result(completed["job"], args.r2_credentials_source)
    validate_project_processing_plan(plan)
    if plan.get("project") != {
        "project_id": project["project_id"],
        "revision": project["revision"],
    } or plan.get("source_snapshot") != project["iterator"]["accepted_snapshot"]:
        raise RuntimeError("Processing plan does not match the authoritative project revision")
    print(json.dumps({
        "job_id": completed["job"]["job_id"],
        "run_id": completed["run"]["run_id"],
        "state": completed["job"]["state"],
        "artifact": completed["job"]["result"],
        "project": plan["project"],
        "plan_hash": plan["plan_hash"],
        "summary": plan["summary"],
        "estimate": plan["estimate"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    print(
        "Full plan: ./authoring/watchcraft-author queue result "
        "--operator-token-source keychain --r2-credentials-source keychain "
        f"{completed['job']['job_id']}",
        flush=True,
    )
    return 0


def validate_executable_project_plan_item(item: dict[str, Any]) -> dict[str, Any]:
    stages = item["stages"]
    expected = [
        ("metadata-enrichment", "watchcraft.metadata.youtube", "operator-local"),
        ("source-acquisition", "watchcraft.acquire.youtube-audio", "operator-local"),
        ("transcription", PRODUCTION_TRANSCRIPTION_HANDLER[0], "registered-worker"),
        ("analysis", EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0], "registered-worker"),
    ]
    if len(stages) != len(expected) or any(
        stage["stage"] != stage_name
        or stage["handler"] != {
            "id": handler_id,
            "version": "1",
        }
        or stage["executor"] != executor
        or stage["disposition"] != "required"
        for stage, (stage_name, handler_id, executor) in zip(stages, expected)
    ):
        raise ValueError("Processing plan item is not executable by this CLI version")
    if (
        item["source"]["media_type"] != "youtube"
        or item["source"]["media_asset_id"] != item["item_id"]
        or youtube_video_id(item["source"]["canonical_url"])
        != item["source"]["media_id"]
    ):
        raise ValueError("Processing plan item has an unsupported source identity")
    return item


def executable_project_plan_items(
    plan: dict[str, Any],
    *,
    item_id: str | None = None,
    limit: int | None = None,
    process_all: bool = False,
) -> list[dict[str, Any]]:
    candidates = plan["items"]
    if item_id is not None:
        candidates = [item for item in candidates if item["item_id"] == item_id]
        if not candidates:
            raise ValueError(f"Processing plan has no item {item_id!r}")
    elif limit is not None:
        if limit < 1:
            raise ValueError("--limit must be positive")
        candidates = candidates[:limit]
    elif not process_all:
        raise ValueError("Choose --all, --limit, or --item")
    if not candidates:
        raise ValueError("Processing plan contains no items")
    return [validate_executable_project_plan_item(item) for item in candidates]


def executable_project_plan_item(
    plan: dict[str, Any], item_id: str | None = None
) -> dict[str, Any]:
    """Compatibility helper for callers selecting one plan item."""
    return executable_project_plan_items(
        plan,
        item_id=item_id,
        limit=None if item_id is not None else 1,
    )[0]


def project_item_execution_context(
    *,
    args: argparse.Namespace,
    plan: dict[str, Any],
    plan_reference: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    stages = {stage["stage"]: stage for stage in item["stages"]}
    return {
        "plan_job_id": args.plan_job_id,
        "plan_artifact_sha256": plan_reference["digest"],
        "plan_hash": plan["plan_hash"],
        "project_id": plan["project"]["project_id"],
        "project_revision": plan["project"]["revision"],
        "item_id": item["item_id"],
        "logical_tasks": {
            name: stages[name]["task_id"]
            for name in (
                "metadata-enrichment",
                "source-acquisition",
                "transcription",
                "analysis",
            )
        },
    }


def project_topic_normalization_spec(
    *,
    plan_job_id: str,
    plan_reference: dict[str, Any],
    plan: dict[str, Any],
    dependencies: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(dependencies) != len(bindings) or not dependencies:
        raise ValueError("Topic normalization requires a complete non-empty analysis set")
    return {
        "operation": "generate",
        "artifact_kind": "topic-normalization",
        "output_schema": TOPIC_NORMALIZATION_SCHEMA,
        "handler": {
            "id": TOPIC_NORMALIZATION_HANDLER[0],
            "version": TOPIC_NORMALIZATION_HANDLER[1],
        },
        "source": {
            "media_asset_id": f"catalog-project:{plan['project']['project_id']}"
        },
        "inputs": [],
        "dependencies": dependencies,
        "configuration": {
            "project_id": plan["project"]["project_id"],
            "project_revision": plan["project"]["revision"],
            "plan_job_id": plan_job_id,
            "plan_artifact_sha256": plan_reference["digest"],
            "plan_hash": plan["plan_hash"],
            "logical_task_id": plan["collection_tasks"][0]["task_id"],
            "model": TOPIC_NORMALIZATION_MODEL,
            "prompt_version": TOPIC_NORMALIZATION_PROMPT_VERSION,
            "display_label_prompt_version": TOPIC_DISPLAY_LABEL_PROMPT_VERSION,
            "batch_size": TOPIC_NORMALIZATION_BATCH_SIZE,
            "retries": TOPIC_NORMALIZATION_RETRIES,
            "timeout_seconds": TOPIC_NORMALIZATION_TIMEOUT_SECONDS,
            "analyses": bindings,
        },
    }


def project_terminology_resolution_spec(
    *,
    project: dict[str, Any],
    plan_job_id: str,
    plan_reference: dict[str, Any],
    plan: dict[str, Any],
    transcript_references: list[dict[str, Any]],
    analysis_references: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    resume_checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if (
        not bindings
        or len(bindings) != len(transcript_references)
        or len(bindings) != len(analysis_references)
    ):
        raise ValueError("Terminology resolution requires a complete draft corpus")
    return {
        "operation": "generate",
        "artifact_kind": "terminology-resolution",
        "output_schema": TERMINOLOGY_RESOLUTION_SCHEMA,
        "handler": {
            "id": TERMINOLOGY_RESOLUTION_HANDLER[0],
            "version": TERMINOLOGY_RESOLUTION_HANDLER[1],
        },
        "source": {"media_asset_id": f"catalog-project:{project['project_id']}"},
        "inputs": [resume_checkpoint] if resume_checkpoint is not None else [],
        "dependencies": [*transcript_references, *analysis_references],
        "configuration": {
            "project": {
                "project_id": project["project_id"],
                "revision": project["revision"],
                "metadata": project.get("metadata", {}),
            },
            "plan_job_id": plan_job_id,
            "plan_artifact_sha256": plan_reference["digest"],
            "plan_hash": plan["plan_hash"],
            "logical_task_id": stable_project_execution_id(
                plan_reference["digest"],
                f"catalog-project:{project['project_id']}",
                "terminology-resolution-task",
            ),
            "model": TERMINOLOGY_RESOLUTION_MODEL,
            "prompt_version": TERMINOLOGY_RESOLUTION_PROMPT_VERSION,
            "retries": TERMINOLOGY_RESOLUTION_RETRIES,
            "timeout_seconds": TERMINOLOGY_RESOLUTION_TIMEOUT_SECONDS,
            "batch_max_terms": TERMINOLOGY_RESOLUTION_BATCH_MAX_TERMS,
            "batch_max_chars": TERMINOLOGY_RESOLUTION_BATCH_MAX_CHARS,
            "items": bindings,
        },
    }


def previous_terminology_checkpoint(
    control: AuthoringHttpClient,
    *,
    plan_reference: dict[str, Any],
    project_id: str,
) -> tuple[int, dict[str, Any]] | None:
    project_item_id = f"catalog-project:{project_id}"
    run_id = stable_project_execution_id(
        plan_reference["digest"],
        project_item_id,
        versioned_handler_execution_role(
            "terminology-resolution-run", PREVIOUS_TERMINOLOGY_RESOLUTION_HANDLER
        ),
    )
    pipeline = control.post("/pipelines/get", {"run_id": run_id})
    jobs = pipeline.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != 1:
        return None
    job = jobs[0]
    if (
        job.get("spec", {}).get("handler")
        != {
            "id": PREVIOUS_TERMINOLOGY_RESOLUTION_HANDLER[0],
            "version": PREVIOUS_TERMINOLOGY_RESOLUTION_HANDLER[1],
        }
        or not isinstance(job.get("spec_sha256"), str)
    ):
        return None
    checkpoints = [
        checkpoint
        for attempt in job.get("attempts", [])
        if isinstance(attempt, dict)
        and isinstance((checkpoint := attempt.get("checkpoint")), dict)
        and checkpoint.get("spec_sha256") == job["spec_sha256"]
        and type(checkpoint.get("sequence")) is int
    ]
    if not checkpoints:
        return None
    checkpoint = max(checkpoints, key=lambda value: value["sequence"])
    reference = validated_artifact_reference(checkpoint.get("artifact"))
    if (
        reference.get("artifact_kind") != "terminology-resolution-checkpoint"
        or reference.get("schema") != TERMINOLOGY_RESOLUTION_CHECKPOINT_SCHEMA
    ):
        raise RuntimeError("Previous terminology checkpoint has the wrong artifact contract")
    return checkpoint["sequence"], reference


def completed_project_analysis_set(
    control: AuthoringHttpClient,
    *,
    plan_job_id: str,
    plan: dict[str, Any],
    plan_reference: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    dependencies = []
    bindings = []
    job_ids = []
    for item in executable_project_plan_items(plan, process_all=True):
        analysis_job_id = stable_project_execution_id(
            plan_reference["digest"], item["item_id"], "analysis"
        )
        submission = control.post("/submissions/get", {"job_id": analysis_job_id})
        job = submission.get("job")
        run = submission.get("run")
        request = run.get("request") if isinstance(run, dict) else None
        if (
            not isinstance(job, dict)
            or job.get("state") != "succeeded"
            or job.get("spec", {}).get("handler") != {
                "id": EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0],
                "version": EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[1],
            }
            or not isinstance(request, dict)
            or request.get("kind") != "project-item-processing"
            or request.get("plan_job_id") != plan_job_id
            or request.get("plan_artifact_sha256") != plan_reference["digest"]
            or request.get("plan_hash") != plan["plan_hash"]
            or request.get("project_id") != plan["project"]["project_id"]
            or request.get("project_revision") != plan["project"]["revision"]
            or request.get("item_id") != item["item_id"]
        ):
            raise RuntimeError(
                f"Planned item {item['item_id']} has no successful bound analysis job"
            )
        reference = validated_artifact_reference(job.get("result"))
        if (
            reference.get("artifact_kind") != "analysis"
            or reference.get("schema") != VIDEO_ANALYSIS_SCHEMA
            or reference.get("media_type") != "application/json"
        ):
            raise RuntimeError(
                f"Planned item {item['item_id']} has an invalid analysis artifact"
            )
        dependencies.append(reference)
        bindings.append({
            "item_id": item["item_id"],
            "video": f"{item['source']['media_id']}.youtube",
            "digest": reference["digest"],
        })
        job_ids.append(analysis_job_id)
    return dependencies, bindings, job_ids


def completed_project_draft_corpus(
    control: AuthoringHttpClient,
    *,
    plan_job_id: str,
    plan: dict[str, Any],
    plan_reference: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    analysis_references, analysis_bindings, _ = completed_project_analysis_set(
        control,
        plan_job_id=plan_job_id,
        plan=plan,
        plan_reference=plan_reference,
    )
    transcript_references = []
    bindings = []
    for item, analysis_reference, analysis_binding in zip(
        executable_project_plan_items(plan, process_all=True),
        analysis_references,
        analysis_bindings,
    ):
        transcript_job_id = stable_project_execution_id(
            plan_reference["digest"], item["item_id"], "transcription"
        )
        submission = control.post("/submissions/get", {"job_id": transcript_job_id})
        job = submission.get("job")
        run = submission.get("run")
        request = run.get("request") if isinstance(run, dict) else None
        if (
            not isinstance(job, dict)
            or job.get("state") != "succeeded"
            or job.get("spec", {}).get("handler") != {
                "id": PRODUCTION_TRANSCRIPTION_HANDLER[0],
                "version": PRODUCTION_TRANSCRIPTION_HANDLER[1],
            }
            or not isinstance(request, dict)
            or request.get("plan_job_id") != plan_job_id
            or request.get("plan_artifact_sha256") != plan_reference["digest"]
            or request.get("item_id") != item["item_id"]
        ):
            raise RuntimeError(
                f"Planned item {item['item_id']} has no successful bound transcript job"
            )
        transcript_reference = validated_artifact_reference(job.get("result"))
        if (
            transcript_reference.get("artifact_kind") != "transcript"
            or transcript_reference.get("schema")
            != {"id": "watchcraft.transcript", "version": 1}
        ):
            raise RuntimeError(
                f"Planned item {item['item_id']} has an invalid transcript artifact"
            )
        transcript_references.append(transcript_reference)
        bindings.append({
            "item_id": item["item_id"],
            "source_title": item["title"],
            "video": analysis_binding["video"],
            "transcript_digest": transcript_reference["digest"],
            "analysis_digest": analysis_reference["digest"],
        })
    return transcript_references, analysis_references, bindings


def completed_project_compilation_inputs(
    control: AuthoringHttpClient,
    *,
    plan_job_id: str,
    plan: dict[str, Any],
    plan_reference: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    analysis_references, analysis_bindings, _ = completed_project_analysis_set(
        control,
        plan_job_id=plan_job_id,
        plan=plan,
        plan_reference=plan_reference,
    )
    transcript_references = []
    bindings = []
    for item, analysis_reference, analysis_binding in zip(
        executable_project_plan_items(plan, process_all=True),
        analysis_references,
        analysis_bindings,
    ):
        transcript_job_id = stable_project_execution_id(
            plan_reference["digest"], item["item_id"], "transcription"
        )
        submission = control.post("/submissions/get", {"job_id": transcript_job_id})
        job = submission.get("job")
        run = submission.get("run")
        request = run.get("request") if isinstance(run, dict) else None
        if (
            not isinstance(job, dict)
            or job.get("state") != "succeeded"
            or job.get("spec", {}).get("handler") != {
                "id": PRODUCTION_TRANSCRIPTION_HANDLER[0],
                "version": PRODUCTION_TRANSCRIPTION_HANDLER[1],
            }
            or not isinstance(request, dict)
            or request.get("plan_job_id") != plan_job_id
            or request.get("plan_artifact_sha256") != plan_reference["digest"]
            or request.get("item_id") != item["item_id"]
        ):
            raise RuntimeError(
                f"Planned item {item['item_id']} has no successful bound transcript job"
            )
        transcript_reference = validated_artifact_reference(job.get("result"))
        if (
            transcript_reference.get("artifact_kind") != "transcript"
            or transcript_reference.get("schema")
            != {"id": "watchcraft.transcript", "version": 1}
        ):
            raise RuntimeError(
                f"Planned item {item['item_id']} has an invalid transcript artifact"
            )
        transcript_references.append(transcript_reference)
        bindings.append({
            "item_id": item["item_id"],
            "video": analysis_binding["video"],
            "transcript_digest": transcript_reference["digest"],
            "analysis_digest": analysis_reference["digest"],
        })

    project_item_id = f"catalog-project:{plan['project']['project_id']}"
    normalization_job_id = stable_project_execution_id(
        plan_reference["digest"], project_item_id, "topic-normalization"
    )
    normalization_submission = control.post(
        "/submissions/get", {"job_id": normalization_job_id}
    )
    normalization_job = normalization_submission.get("job")
    normalization_run = normalization_submission.get("run")
    normalization_request = (
        normalization_run.get("request")
        if isinstance(normalization_run, dict)
        else None
    )
    if (
        not isinstance(normalization_job, dict)
        or normalization_job.get("state") != "succeeded"
        or normalization_job.get("spec", {}).get("handler") != {
            "id": TOPIC_NORMALIZATION_HANDLER[0],
            "version": TOPIC_NORMALIZATION_HANDLER[1],
        }
        or not isinstance(normalization_request, dict)
        or normalization_request.get("plan_job_id") != plan_job_id
        or normalization_request.get("plan_artifact_sha256")
        != plan_reference["digest"]
    ):
        raise RuntimeError("The project plan has no successful bound topic normalization")
    normalization_reference = validated_artifact_reference(
        normalization_job.get("result")
    )
    if (
        normalization_reference.get("artifact_kind") != "topic-normalization"
        or normalization_reference.get("schema") != TOPIC_NORMALIZATION_SCHEMA
    ):
        raise RuntimeError("The project topic-normalization artifact is invalid")
    return (
        transcript_references,
        analysis_references,
        bindings,
        normalization_reference,
    )


def project_collection_compilation_spec(
    *,
    project: dict[str, Any],
    plan_job_id: str,
    plan_reference: dict[str, Any],
    plan: dict[str, Any],
    transcript_references: list[dict[str, Any]],
    analysis_references: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    normalization_reference: dict[str, Any],
) -> dict[str, Any]:
    if (
        not bindings
        or len(bindings) != len(transcript_references)
        or len(bindings) != len(analysis_references)
    ):
        raise ValueError("Collection compilation requires a complete project item set")
    return {
        "operation": "compile",
        "artifact_kind": "collection-compilation",
        "output_schema": COLLECTION_COMPILATION_SCHEMA,
        "handler": {
            "id": COLLECTION_COMPILATION_HANDLER[0],
            "version": COLLECTION_COMPILATION_HANDLER[1],
        },
        "source": {"media_asset_id": f"catalog-project:{project['project_id']}"},
        "inputs": [plan_reference, plan["source_snapshot"]],
        "dependencies": [
            *transcript_references,
            *analysis_references,
            normalization_reference,
        ],
        "configuration": {
            "project": project,
            "plan_job_id": plan_job_id,
            "plan_artifact_sha256": plan_reference["digest"],
            "plan_hash": plan["plan_hash"],
            "logical_task_id": plan["collection_tasks"][1]["task_id"],
            "items": bindings,
        },
    }


def compact_project_item_execution(
    item: dict[str, Any], summary: dict[str, Any]
) -> dict[str, Any]:
    return {
        "item_id": item["item_id"],
        "title": item["title"],
        "run_id": summary["run_id"],
        "state": summary["state"],
        "disposition": summary["plan_execution"]["disposition"],
        "jobs": {
            role: summary["jobs"][role]["job_id"]
            for role in ("transcription", "analysis")
        },
        "command_total_ms": summary["timing"]["local"]["command_total_ms"],
    }


def run_process_project(args: argparse.Namespace) -> int:
    if args.concurrency < 1 or args.concurrency > 8:
        raise ValueError("--concurrency must be between 1 and 8")
    command_started_at = time.monotonic()
    control = operator_client(args.operator_token_source)
    plan_submission = control.post(
        "/submissions/get", {"job_id": args.plan_job_id}
    )
    plan_job = plan_submission.get("job")
    if (
        not isinstance(plan_job, dict)
        or plan_job.get("state") != "succeeded"
        or plan_job.get("spec", {}).get("handler") != {
            "id": PROJECT_PROCESSING_PLANNER_HANDLER[0],
            "version": PROJECT_PROCESSING_PLANNER_HANDLER[1],
        }
    ):
        raise RuntimeError(
            f"Job {args.plan_job_id} is not a successful project processing plan"
        )
    plan_reference = validated_artifact_reference(plan_job.get("result"))
    if (
        plan_reference.get("artifact_kind") != "project-processing-plan"
        or plan_reference.get("schema") != PROJECT_PROCESSING_PLAN_SCHEMA
    ):
        raise RuntimeError(
            f"Job {args.plan_job_id} is not a successful project processing plan"
        )
    plan = verified_json_result(plan_job, args.r2_credentials_source)
    validate_project_processing_plan(plan)
    current = control.post(
        "/projects/get", {"project_id": plan["project"]["project_id"]}
    )
    project = current.get("project")
    validate_json_schema(project, CATALOG_PROJECT_SCHEMA_PATH, "Catalog project")
    if (
        project["revision"] != plan["project"]["revision"]
        or project["iterator"].get("accepted_snapshot") != plan["source_snapshot"]
    ):
        raise RuntimeError(
            "Processing plan is stale relative to the authoritative catalog project"
        )
    items = executable_project_plan_items(
        plan,
        item_id=args.item_id,
        limit=args.limit,
        process_all=args.process_all,
    )
    concurrency = min(args.concurrency, len(items))
    print(
        f"executing {len(items)} of {len(plan['items'])} planned items "
        f"with concurrency {concurrency}",
        flush=True,
    )

    def execute(item: dict[str, Any]) -> dict[str, Any]:
        item_args = argparse.Namespace(**vars(args))
        item_args.youtube_url = item["source"]["canonical_url"]
        result = run_youtube_video_pipeline(
            item_args,
            project_execution=project_item_execution_context(
                args=args,
                plan=plan,
                plan_reference=plan_reference,
                item=item,
            ),
            emit_result=False,
        )
        if not isinstance(result, dict):
            raise RuntimeError(f"Processing {item['item_id']} returned no summary")
        return result

    completed: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(execute, item): item for item in items}
        for future in concurrent.futures.as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
                completed[item["item_id"]] = compact_project_item_execution(item, result)
                disposition = result["plan_execution"]["disposition"]
                done = len(completed) + len(failures)
                print(
                    f"[{done}/{len(items)}] {disposition}: {item['title']}",
                    flush=True,
                )
            except Exception as error:
                failures[item["item_id"]] = str(error)
                done = len(completed) + len(failures)
                print(
                    f"[{done}/{len(items)}] failed: {item['title']}: {error}",
                    flush=True,
                )

    ordered_results = [
        completed[item["item_id"]]
        for item in items
        if item["item_id"] in completed
    ]
    summary = {
        "plan_job_id": args.plan_job_id,
        "plan_artifact_sha256": plan_reference["digest"],
        "plan_hash": plan["plan_hash"],
        "project": plan["project"],
        "state": "complete" if not failures else "incomplete",
        "selected_items": len(items),
        "succeeded": len(completed),
        "already_complete": sum(
            result["disposition"] == "already-complete"
            for result in ordered_results
        ),
        "failed": len(failures),
        "concurrency": concurrency,
        "command_total_ms": elapsed_milliseconds(command_started_at),
        "items": ordered_results,
        "failures": [
            {
                "item_id": item["item_id"],
                "title": item["title"],
                "error": failures[item["item_id"]],
            }
            for item in items
            if item["item_id"] in failures
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if failures:
        raise RuntimeError(
            f"Project processing completed with {len(failures)} failed item(s); "
            "rerun after addressing the reported failures"
        )
    return 0


def run_resolve_project_terminology(args: argparse.Namespace) -> int:
    command_started_at = time.monotonic()
    control = operator_client(args.operator_token_source)
    plan_submission = control.post(
        "/submissions/get", {"job_id": args.plan_job_id}
    )
    plan_job = plan_submission.get("job")
    if (
        not isinstance(plan_job, dict)
        or plan_job.get("state") != "succeeded"
        or plan_job.get("spec", {}).get("handler") != {
            "id": PROJECT_PROCESSING_PLANNER_HANDLER[0],
            "version": PROJECT_PROCESSING_PLANNER_HANDLER[1],
        }
    ):
        raise RuntimeError(
            f"Job {args.plan_job_id} is not a successful project processing plan"
        )
    plan_reference = validated_artifact_reference(plan_job.get("result"))
    if (
        plan_reference.get("artifact_kind") != "project-processing-plan"
        or plan_reference.get("schema") != PROJECT_PROCESSING_PLAN_SCHEMA
    ):
        raise RuntimeError(
            f"Job {args.plan_job_id} is not a successful project processing plan"
        )
    plan = verified_json_result(plan_job, args.r2_credentials_source)
    validate_project_processing_plan(plan)
    current = control.post(
        "/projects/get", {"project_id": plan["project"]["project_id"]}
    )
    project = current.get("project")
    validate_json_schema(project, CATALOG_PROJECT_SCHEMA_PATH, "Catalog project")
    if (
        project["revision"] != plan["project"]["revision"]
        or project["iterator"].get("accepted_snapshot") != plan["source_snapshot"]
    ):
        raise RuntimeError(
            "Processing plan is stale relative to the authoritative catalog project"
        )
    transcript_references, analysis_references, bindings = (
        completed_project_draft_corpus(
            control,
            plan_job_id=args.plan_job_id,
            plan=plan,
            plan_reference=plan_reference,
        )
    )
    project_item_id = f"catalog-project:{project['project_id']}"
    previous_checkpoint = previous_terminology_checkpoint(
        control,
        plan_reference=plan_reference,
        project_id=project["project_id"],
    )
    resume_checkpoint = previous_checkpoint[1] if previous_checkpoint is not None else None
    if previous_checkpoint is not None:
        print(
            f"reusing terminology checkpoint after {previous_checkpoint[0]} batches",
            flush=True,
        )
    spec = project_terminology_resolution_spec(
        project=project,
        plan_job_id=args.plan_job_id,
        plan_reference=plan_reference,
        plan=plan,
        transcript_references=transcript_references,
        analysis_references=analysis_references,
        bindings=bindings,
        resume_checkpoint=resume_checkpoint,
    )
    run_id = stable_project_execution_id(
        plan_reference["digest"],
        project_item_id,
        versioned_handler_execution_role(
            "terminology-resolution-run", TERMINOLOGY_RESOLUTION_HANDLER
        ),
    )
    job_id = stable_project_execution_id(
        plan_reference["digest"],
        project_item_id,
        versioned_handler_execution_role(
            "terminology-resolution", TERMINOLOGY_RESOLUTION_HANDLER
        ),
    )
    command_prefix = stable_project_execution_id(
        plan_reference["digest"],
        project_item_id,
        versioned_handler_execution_role(
            "terminology-resolution-commands", TERMINOLOGY_RESOLUTION_HANDLER
        ),
    )
    request = {
        "kind": "project-terminology-resolution",
        "plan_job_id": args.plan_job_id,
        "plan_artifact_sha256": plan_reference["digest"],
        "plan_hash": plan["plan_hash"],
        "project_id": project["project_id"],
        "project_revision": project["revision"],
        "handler": {
            "id": TERMINOLOGY_RESOLUTION_HANDLER[0],
            "version": TERMINOLOGY_RESOLUTION_HANDLER[1],
        },
        "logical_task_id": spec["configuration"]["logical_task_id"],
    }
    existing = control.post("/pipelines/get", {"run_id": run_id})
    if existing.get("run") is None:
        submitted = submit_spec(
            control,
            job_id=job_id,
            run_id=run_id,
            command_prefix=command_prefix,
            request=request,
            spec=spec,
        )
        print(
            f"submitted terminology resolution {job_id} for {len(bindings)} items",
            flush=True,
        )
    else:
        submitted = existing
        jobs = submitted.get("jobs")
        if (
            submitted.get("run", {}).get("request") != request
            or not isinstance(jobs, list)
            or len(jobs) != 1
            or jobs[0].get("job_id") != job_id
            or {
                key: value
                for key, value in jobs[0].get("spec", {}).items()
                if key != "registry_snapshot"
            } != spec
        ):
            raise RuntimeError("Existing terminology resolution does not match its corpus")
        print(f"resuming terminology resolution {job_id}", flush=True)
    job = submitted.get("job")
    if not isinstance(job, dict):
        job = submitted["jobs"][0]
    if job["state"] == "awaiting_approval":
        job = control.post("/submissions/approve", {
            "job_id": job_id,
            "command_id": str(uuid.uuid4()),
            "expected_revision": job["revision"],
            "actor": "watchcraft-author-cli",
            "spec_sha256": job["spec_sha256"],
        })["job"]
    _resume_pipeline_job(control, job, "terminology resolution")
    completed = wait_for_terminal_job(control, job_id, args.timeout_seconds)
    result = verified_json_result(completed["job"], args.r2_credentials_source)
    validate_json_schema(
        result, TERMINOLOGY_RESOLUTION_SCHEMA_PATH, "Terminology resolution"
    )
    provenance = result.get("provenance")
    if (
        result.get("project") != {
            "project_id": project["project_id"],
            "revision": project["revision"],
            "metadata": project.get("metadata", {}),
        }
        or not isinstance(provenance, dict)
        or provenance.get("handler_id") != TERMINOLOGY_RESOLUTION_HANDLER[0]
        or provenance.get("plan_artifact_sha256") != plan_reference["digest"]
    ):
        raise RuntimeError("Terminology resolution returned an invalid project binding")
    summary = compact_terminology_resolution_result(
        completed,
        result,
        local_timing={"command_total_ms": elapsed_milliseconds(command_started_at)},
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(
        "Full resolution: ./authoring/watchcraft-author queue result "
        "--operator-token-source keychain --r2-credentials-source keychain "
        f"{job_id}",
        flush=True,
    )
    return 0


def run_normalize_project(args: argparse.Namespace) -> int:
    command_started_at = time.monotonic()
    control = operator_client(args.operator_token_source)
    plan_submission = control.post(
        "/submissions/get", {"job_id": args.plan_job_id}
    )
    plan_job = plan_submission.get("job")
    if (
        not isinstance(plan_job, dict)
        or plan_job.get("state") != "succeeded"
        or plan_job.get("spec", {}).get("handler") != {
            "id": PROJECT_PROCESSING_PLANNER_HANDLER[0],
            "version": PROJECT_PROCESSING_PLANNER_HANDLER[1],
        }
    ):
        raise RuntimeError(
            f"Job {args.plan_job_id} is not a successful project processing plan"
        )
    plan_reference = validated_artifact_reference(plan_job.get("result"))
    if (
        plan_reference.get("artifact_kind") != "project-processing-plan"
        or plan_reference.get("schema") != PROJECT_PROCESSING_PLAN_SCHEMA
    ):
        raise RuntimeError(
            f"Job {args.plan_job_id} is not a successful project processing plan"
        )
    plan = verified_json_result(plan_job, args.r2_credentials_source)
    validate_project_processing_plan(plan)
    current = control.post(
        "/projects/get", {"project_id": plan["project"]["project_id"]}
    )
    project = current.get("project")
    validate_json_schema(project, CATALOG_PROJECT_SCHEMA_PATH, "Catalog project")
    if (
        project["revision"] != plan["project"]["revision"]
        or project["iterator"].get("accepted_snapshot") != plan["source_snapshot"]
    ):
        raise RuntimeError(
            "Processing plan is stale relative to the authoritative catalog project"
        )
    dependencies, bindings, analysis_job_ids = completed_project_analysis_set(
        control,
        plan_job_id=args.plan_job_id,
        plan=plan,
        plan_reference=plan_reference,
    )
    spec = project_topic_normalization_spec(
        plan_job_id=args.plan_job_id,
        plan_reference=plan_reference,
        plan=plan,
        dependencies=dependencies,
        bindings=bindings,
    )
    project_item_id = f"catalog-project:{plan['project']['project_id']}"
    run_id = stable_project_execution_id(
        plan_reference["digest"], project_item_id, "topic-normalization-run"
    )
    job_id = stable_project_execution_id(
        plan_reference["digest"], project_item_id, "topic-normalization"
    )
    command_prefix = stable_project_execution_id(
        plan_reference["digest"], project_item_id, "topic-normalization-commands"
    )
    request = {
        "kind": "project-topic-normalization",
        "plan_job_id": args.plan_job_id,
        "plan_artifact_sha256": plan_reference["digest"],
        "plan_hash": plan["plan_hash"],
        "project_id": plan["project"]["project_id"],
        "project_revision": plan["project"]["revision"],
        "analysis_job_ids": analysis_job_ids,
        "logical_task_id": plan["collection_tasks"][0]["task_id"],
    }
    existing = control.post("/pipelines/get", {"run_id": run_id})
    if existing.get("run") is None:
        submitted = submit_spec(
            control,
            job_id=job_id,
            run_id=run_id,
            command_prefix=command_prefix,
            request=request,
            spec=spec,
        )
        print(
            f"submitted topic normalization {job_id} for {len(bindings)} analyses",
            flush=True,
        )
    else:
        submitted = existing
        jobs = submitted.get("jobs")
        if (
            submitted.get("run", {}).get("request") != request
            or not isinstance(jobs, list)
            or len(jobs) != 1
            or jobs[0].get("job_id") != job_id
            or {
                key: value
                for key, value in jobs[0].get("spec", {}).items()
                if key != "registry_snapshot"
            } != spec
        ):
            raise RuntimeError("Existing topic normalization does not match its plan")
        print(f"resuming topic normalization {job_id}", flush=True)
    run = submitted["run"]
    job = submitted.get("job")
    if not isinstance(job, dict):
        job = submitted["jobs"][0]
    if job["state"] == "awaiting_approval":
        approved = control.post("/submissions/approve", {
            "job_id": job_id,
            "command_id": str(uuid.uuid4()),
            "expected_revision": job["revision"],
            "actor": "watchcraft-author-cli",
            "spec_sha256": job["spec_sha256"],
        })
        job = approved["job"]
    _resume_pipeline_job(control, job, "topic normalization")
    completed = wait_for_terminal_job(control, job_id, args.timeout_seconds)
    result = verified_json_result(completed["job"], args.r2_credentials_source)
    provenance = result.get("provenance") if isinstance(result, dict) else None
    if (
        result.get("kind") != "watchcraft.topic-normalization"
        or result.get("status") != "complete"
        or result.get("collection_id") != plan["project"]["project_id"]
        or not isinstance(provenance, dict)
        or provenance.get("handler_id") != TOPIC_NORMALIZATION_HANDLER[0]
        or provenance.get("plan_artifact_sha256") != plan_reference["digest"]
        or len(provenance.get("analyses", [])) != len(bindings)
    ):
        raise RuntimeError("Project topic normalization returned an invalid result")
    total_ms = elapsed_milliseconds(command_started_at)
    print(f"completed topic normalization {job_id} in {format_elapsed(total_ms)}", flush=True)
    print(json.dumps({
        "job_id": job_id,
        "run_id": run_id,
        "state": completed["job"]["state"],
        "artifact": completed["job"]["result"],
        "project": plan["project"],
        "analysis_count": len(bindings),
        "model": result["model"],
        "source_hash": result["source_hash"],
        "stats": result["stats"],
        "timing": {
            "local": {"command_total_ms": total_ms},
            "ledger": completed_job_timing(completed["job"]),
            "worker": provenance.get("timing", {}),
        },
    }, ensure_ascii=False, indent=2, sort_keys=True))
    print(
        "Full normalization: ./authoring/watchcraft-author queue result "
        "--operator-token-source keychain --r2-credentials-source keychain "
        f"{job_id}",
        flush=True,
    )
    return 0


def collection_comparison(candidate: dict[str, Any], published: dict[str, Any]) -> dict[str, Any]:
    candidate_topics = {
        value.get("canonical_key")
        for value in candidate.get("topics", {}).values()
        if isinstance(value, dict)
    }
    published_topics = {
        value.get("canonical_key")
        for value in published.get("topics", {}).values()
        if isinstance(value, dict)
    }
    candidate_items = set(candidate.get("items", {}))
    published_items = set(published.get("items", {}))
    changed = candidate.get("content_hash") != published.get("content_hash")
    published_revision = published.get("revision")
    return {
        "content_changed": changed,
        "published_revision": published_revision,
        "proposed_revision": (
            published_revision + 1
            if changed and type(published_revision) is int
            else published_revision
        ),
        "items": {
            "candidate": len(candidate_items),
            "published": len(published_items),
            "shared_ids": len(candidate_items & published_items),
            "candidate_only": len(candidate_items - published_items),
            "published_only": len(published_items - candidate_items),
        },
        "topics": {
            "candidate": len(candidate_topics),
            "published": len(published_topics),
            "shared_canonical_keys": len(candidate_topics & published_topics),
            "candidate_only": len(candidate_topics - published_topics),
            "published_only": len(published_topics - candidate_topics),
        },
        "families": {
            "candidate": len(candidate.get("topic_families", {})),
            "published": len(published.get("topic_families", {})),
        },
    }


def collection_manifest_content_hash(manifest: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in manifest.items()
        if key not in {"revision", "content_hash"}
    }
    return sha256_hex(
        json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )


def git_no_index_diff(old_path: Path, new_path: Path) -> str:
    completed = subprocess.run(
        ["git", "diff", "--no-index", "--no-ext-diff", "--", str(old_path), str(new_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(
            f"Could not create review diff: {completed.stderr.strip() or 'git diff failed'}"
        )
    return completed.stdout


def materialization_diff(
    published_root: Path,
    candidate_root: Path,
    resource_paths: set[str],
) -> str:
    paths = {"collection.json", "catalog.csv", *resource_paths}
    old_analysis = published_root / "analysis"
    if old_analysis.is_dir():
        paths.update(
            path.relative_to(published_root).as_posix()
            for path in old_analysis.rglob("*.analysis.json")
        )
    chunks = []
    for relative in sorted(paths):
        old_path = published_root / relative
        new_path = candidate_root / relative
        if old_path.is_file() and new_path.is_file():
            chunks.append(git_no_index_diff(old_path, new_path))
        elif old_path.is_file():
            chunks.append(git_no_index_diff(old_path, Path("/dev/null")))
        elif new_path.is_file():
            chunks.append(git_no_index_diff(Path("/dev/null"), new_path))
    return "".join(chunks)


def run_materialize_project(args: argparse.Namespace) -> int:
    destination = args.output_directory.resolve()
    published_collection_path = args.published_collection.resolve()
    published_root = published_collection_path.parent
    diff_path = (
        args.diff_output.resolve()
        if args.diff_output is not None
        else Path(f"{destination}.diff")
    )
    if destination.exists():
        raise RuntimeError(f"Materialization destination already exists: {destination}")
    if diff_path.exists():
        raise RuntimeError(f"Materialization diff already exists: {diff_path}")
    if not destination.parent.is_dir():
        raise RuntimeError(
            f"Materialization destination parent does not exist: {destination.parent}"
        )
    try:
        published = json.loads(published_collection_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Could not read published collection {published_collection_path}"
        ) from error
    from build_collection import render_csv, validate_collection_manifest
    validate_collection_manifest(published)
    if published.get("content_hash") != collection_manifest_content_hash(published):
        raise RuntimeError("Published collection content_hash does not match its content")

    control = operator_client(args.operator_token_source)
    submission = control.post(
        "/submissions/get", {"job_id": args.compilation_job_id}
    )
    job = submission.get("job")
    if (
        not isinstance(job, dict)
        or job.get("state") != "succeeded"
        or job.get("spec", {}).get("handler") != {
            "id": COLLECTION_COMPILATION_HANDLER[0],
            "version": COLLECTION_COMPILATION_HANDLER[1],
        }
    ):
        raise RuntimeError(
            f"Job {args.compilation_job_id} is not a successful collection compilation"
        )
    bundle = verified_json_result(job, args.r2_credentials_source)
    manifest = bundle.get("manifest") if isinstance(bundle, dict) else None
    resources = bundle.get("resources") if isinstance(bundle, dict) else None
    provenance = bundle.get("provenance") if isinstance(bundle, dict) else None
    if (
        not isinstance(bundle, dict)
        or bundle.get("kind") != "watchcraft.collection-compilation"
        or bundle.get("schema_version") != COLLECTION_COMPILATION_SCHEMA["version"]
        or not isinstance(manifest, dict)
        or not isinstance(resources, list)
        or not isinstance(provenance, dict)
        or provenance.get("handler_id") != COLLECTION_COMPILATION_HANDLER[0]
        or provenance.get("job_id") != job["job_id"]
    ):
        raise RuntimeError("The compilation artifact is invalid")
    validate_collection_manifest(manifest)
    if manifest.get("content_hash") != collection_manifest_content_hash(manifest):
        raise RuntimeError("Candidate collection content_hash does not match its content")
    if manifest["collection_id"] != published["collection_id"]:
        raise RuntimeError("Candidate and published collection IDs do not match")

    candidate = json.loads(json.dumps(manifest, ensure_ascii=False))
    content_changed = candidate["content_hash"] != published["content_hash"]
    candidate["revision"] = (
        published["revision"] + 1 if content_changed else published["revision"]
    )
    validate_collection_manifest(candidate)

    expected_paths = {
        item["analysis"]["path"]
        for item in candidate["items"].values()
    }
    references_by_path = {}
    for resource in resources:
        path_value = resource.get("path") if isinstance(resource, dict) else None
        path = Path(path_value) if isinstance(path_value, str) else None
        reference = validated_artifact_reference(
            resource.get("artifact") if isinstance(resource, dict) else None
        )
        if (
            path is None
            or path.is_absolute()
            or ".." in path.parts
            or len(path.parts) < 2
            or path.parts[0] != "analysis"
            or not path.name.endswith(".analysis.json")
            or reference.get("artifact_kind") != "analysis"
            or reference.get("schema") != VIDEO_ANALYSIS_SCHEMA
            or reference.get("media_type") != "application/json"
            or path.as_posix() in references_by_path
        ):
            raise RuntimeError("The compilation artifact has an invalid resource binding")
        references_by_path[path.as_posix()] = reference
    if set(references_by_path) != expected_paths:
        raise RuntimeError("Compilation resources do not exactly cover manifest analyses")

    store = r2_artifact_reader(args.r2_credentials_source)
    analyses = []
    resource_payloads = {}
    for relative, reference in sorted(references_by_path.items()):
        payload = store.get_bytes(reference)
        try:
            analysis = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Analysis resource is invalid JSON: {relative}") from error
        if (
            not isinstance(analysis, dict)
            or analysis.get("schema_version") != VIDEO_ANALYSIS_SCHEMA["version"]
            or f"analysis/{Path(analysis.get('video', '')).stem}.analysis.json" != relative
        ):
            raise RuntimeError(f"Analysis resource does not match its path: {relative}")
        analyses.append(analysis)
        resource_payloads[relative] = (
            json.dumps(analysis, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")

    temporary = Path(tempfile.mkdtemp(
        prefix=f".{destination.name}.materializing-",
        dir=destination.parent,
    ))
    try:
        (temporary / "collection.json").write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (temporary / "catalog.csv").write_text(
            render_csv(analyses, candidate), encoding="utf-8"
        )
        for relative, payload in resource_payloads.items():
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        validate_collection_manifest(json.loads(
            (temporary / "collection.json").read_text(encoding="utf-8")
        ))
        for relative in expected_paths:
            if not (temporary / relative).is_file():
                raise RuntimeError(f"Materialized package is missing {relative}")
        diff = materialization_diff(published_root, temporary, expected_paths)
        diff = diff.replace(str(temporary), str(destination))
        os.replace(temporary, destination)
        try:
            with diff_path.open("x", encoding="utf-8") as handle:
                handle.write(diff)
        except Exception:
            raise RuntimeError(
                f"Materialized {destination}, but could not write review diff {diff_path}"
            )
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise

    print(json.dumps({
        "state": "materialized",
        "compilation_job_id": job["job_id"],
        "destination": str(destination),
        "diff": str(diff_path),
        "collection_id": candidate["collection_id"],
        "revision": candidate["revision"],
        "content_hash": candidate["content_hash"],
        "content_changed": content_changed,
        "resources": len(resource_payloads),
        "comparison": collection_comparison(candidate, published),
    }, ensure_ascii=False, indent=2, sort_keys=True))
    print(
        f"Review with: git apply --stat {diff_path}",
        flush=True,
    )
    return 0


def run_compile_project(args: argparse.Namespace) -> int:
    command_started_at = time.monotonic()
    control = operator_client(args.operator_token_source)
    plan_submission = control.post("/submissions/get", {"job_id": args.plan_job_id})
    plan_job = plan_submission.get("job")
    if (
        not isinstance(plan_job, dict)
        or plan_job.get("state") != "succeeded"
        or plan_job.get("spec", {}).get("handler") != {
            "id": PROJECT_PROCESSING_PLANNER_HANDLER[0],
            "version": PROJECT_PROCESSING_PLANNER_HANDLER[1],
        }
    ):
        raise RuntimeError(
            f"Job {args.plan_job_id} is not a successful project processing plan"
        )
    plan_reference = validated_artifact_reference(plan_job.get("result"))
    if (
        plan_reference.get("artifact_kind") != "project-processing-plan"
        or plan_reference.get("schema") != PROJECT_PROCESSING_PLAN_SCHEMA
    ):
        raise RuntimeError(
            f"Job {args.plan_job_id} is not a successful project processing plan"
        )
    plan = verified_json_result(plan_job, args.r2_credentials_source)
    validate_project_processing_plan(plan)
    current = control.post("/projects/get", {"project_id": plan["project"]["project_id"]})
    project = current.get("project")
    validate_json_schema(project, CATALOG_PROJECT_SCHEMA_PATH, "Catalog project")
    if (
        project["revision"] != plan["project"]["revision"]
        or project["iterator"].get("accepted_snapshot") != plan["source_snapshot"]
    ):
        raise RuntimeError(
            "Processing plan is stale relative to the authoritative catalog project"
        )
    (
        transcript_references,
        analysis_references,
        bindings,
        normalization_reference,
    ) = completed_project_compilation_inputs(
        control,
        plan_job_id=args.plan_job_id,
        plan=plan,
        plan_reference=plan_reference,
    )
    spec = project_collection_compilation_spec(
        project=project,
        plan_job_id=args.plan_job_id,
        plan_reference=plan_reference,
        plan=plan,
        transcript_references=transcript_references,
        analysis_references=analysis_references,
        bindings=bindings,
        normalization_reference=normalization_reference,
    )
    project_item_id = f"catalog-project:{project['project_id']}"
    run_id = stable_project_execution_id(
        plan_reference["digest"],
        project_item_id,
        versioned_handler_execution_role(
            "collection-compilation-run", COLLECTION_COMPILATION_HANDLER
        ),
    )
    job_id = stable_project_execution_id(
        plan_reference["digest"],
        project_item_id,
        versioned_handler_execution_role(
            "collection-compilation", COLLECTION_COMPILATION_HANDLER
        ),
    )
    command_prefix = stable_project_execution_id(
        plan_reference["digest"],
        project_item_id,
        versioned_handler_execution_role(
            "collection-compilation-commands", COLLECTION_COMPILATION_HANDLER
        ),
    )
    request = {
        "kind": "project-collection-compilation",
        "plan_job_id": args.plan_job_id,
        "plan_artifact_sha256": plan_reference["digest"],
        "plan_hash": plan["plan_hash"],
        "project_id": project["project_id"],
        "project_revision": project["revision"],
        "logical_task_id": plan["collection_tasks"][1]["task_id"],
        "handler": {
            "id": COLLECTION_COMPILATION_HANDLER[0],
            "version": COLLECTION_COMPILATION_HANDLER[1],
        },
    }
    existing = control.post("/pipelines/get", {"run_id": run_id})
    if existing.get("run") is None:
        submitted = submit_spec(
            control,
            job_id=job_id,
            run_id=run_id,
            command_prefix=command_prefix,
            request=request,
            spec=spec,
        )
        print(
            f"submitted collection compilation {job_id} for {len(bindings)} items",
            flush=True,
        )
    else:
        submitted = existing
        jobs = submitted.get("jobs")
        if (
            submitted.get("run", {}).get("request") != request
            or not isinstance(jobs, list)
            or len(jobs) != 1
            or jobs[0].get("job_id") != job_id
            or {
                key: value
                for key, value in jobs[0].get("spec", {}).items()
                if key != "registry_snapshot"
            } != spec
        ):
            raise RuntimeError("Existing collection compilation does not match its plan")
        print(f"resuming collection compilation {job_id}", flush=True)
    job = submitted.get("job")
    if not isinstance(job, dict):
        job = submitted["jobs"][0]
    if job["state"] == "awaiting_approval":
        job = control.post("/submissions/approve", {
            "job_id": job_id,
            "command_id": str(uuid.uuid4()),
            "expected_revision": job["revision"],
            "actor": "watchcraft-author-cli",
            "spec_sha256": job["spec_sha256"],
        })["job"]
    _resume_pipeline_job(control, job, "collection compilation")
    completed = wait_for_terminal_job(control, job_id, args.timeout_seconds)
    result = verified_json_result(completed["job"], args.r2_credentials_source)
    manifest = result.get("manifest") if isinstance(result, dict) else None
    provenance = result.get("provenance") if isinstance(result, dict) else None
    from build_collection import validate_collection_manifest
    if (
        result.get("kind") != "watchcraft.collection-compilation"
        or result.get("schema_version") != COLLECTION_COMPILATION_SCHEMA["version"]
        or result.get("project") != plan["project"]
        or not isinstance(manifest, dict)
        or manifest.get("collection_id") != project["publication"]["collection_id"]
        or len(manifest.get("items", {})) != len(bindings)
        or len(result.get("resources", [])) != len(bindings)
        or not isinstance(provenance, dict)
        or provenance.get("handler_id") != COLLECTION_COMPILATION_HANDLER[0]
        or provenance.get("plan") != plan_reference
        or provenance.get("normalization") != normalization_reference
    ):
        raise RuntimeError("Collection compilation returned an invalid result")
    validate_collection_manifest(manifest)
    summary = {
        "job_id": job_id,
        "run_id": run_id,
        "state": completed["job"]["state"],
        "artifact": completed["job"]["result"],
        "project": plan["project"],
        "collection": {
            "collection_id": manifest["collection_id"],
            "candidate_revision": manifest["revision"],
            "content_hash": manifest["content_hash"],
            "stats": manifest["stats"],
            "resources": len(result["resources"]),
        },
        "timing": {
            "local": {"command_total_ms": elapsed_milliseconds(command_started_at)},
            "ledger": completed_job_timing(completed["job"]),
            "worker": provenance.get("timing", {}),
        },
    }
    if args.compare_to is not None:
        try:
            published = json.loads(args.compare_to.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"Could not read comparison collection {args.compare_to}"
            ) from error
        validate_collection_manifest(published)
        if published["collection_id"] != manifest["collection_id"]:
            raise RuntimeError("Comparison collection has a different collection_id")
        summary["comparison"] = collection_comparison(manifest, published)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(
        "Full compilation: ./authoring/watchcraft-author queue result "
        "--operator-token-source keychain --r2-credentials-source keychain "
        f"{job_id}",
        flush=True,
    )
    return 0


def run_queued_video_analysis(args: argparse.Namespace) -> int:
    command_started_at = time.monotonic()
    control = operator_client(args.operator_token_source)
    transcription = control.post(
        "/submissions/get",
        {"job_id": args.transcription_job_id},
    )
    transcription_job = transcription.get("job")
    if (
        not isinstance(transcription_job, dict)
        or transcription_job.get("state") != "succeeded"
        or transcription_job.get("result") is None
    ):
        state = (
            transcription_job.get("state")
            if isinstance(transcription_job, dict)
            else "unknown"
        )
        raise RuntimeError(
            f"Transcription job {args.transcription_job_id} is {state}; "
            "analysis requires a successful authoritative transcript"
        )
    transcript_reference = validated_artifact_reference(transcription_job["result"])
    source = transcription_job.get("spec", {}).get("source")
    source_id = source.get("media_asset_id") if isinstance(source, dict) else None
    match = (
        re.fullmatch(r"youtube:([A-Za-z0-9_-]{11})", source_id)
        if isinstance(source_id, str)
        else None
    )
    if match is None:
        raise RuntimeError(
            "The initial queued analysis command supports YouTube transcript sources"
        )
    video_id = match.group(1)
    metadata_started_at = time.monotonic()
    source_metadata = youtube_source_metadata(video_id)
    metadata_fetch_ms = elapsed_milliseconds(metadata_started_at)
    if source_metadata.get("source_id") != source_id:
        raise RuntimeError("Resolved source metadata does not match the transcript job")
    print(
        f"analyzing transcript {args.transcription_job_id}: "
        f"{source_metadata.get('title') or video_id}",
        flush=True,
    )
    spec = educational_video_analysis_spec(
        source=source,
        transcript=transcript_reference,
        source_metadata=source_metadata,
        video=f"{video_id}.youtube",
    )
    submitted = submit_spec(
        control,
        request={
            "kind": "educational-video-analysis",
            "source_id": source_id,
            "transcription_job_id": args.transcription_job_id,
            "model": EDUCATIONAL_VIDEO_ANALYSIS_MODEL,
        },
        spec=spec,
    )
    job = submitted["job"]
    print(f"submitted {job['job_id']} ({job['spec']['handler']['id']})", flush=True)
    approved = control.post("/submissions/approve", {
        "job_id": job["job_id"],
        "command_id": str(uuid.uuid4()),
        "expected_revision": job["revision"],
        "actor": "watchcraft-author-cli",
        "spec_sha256": job["spec_sha256"],
    })
    pending = dispatch_submission(control, approved["job"])
    print(
        f"dispatched {pending['job_id']} via {dispatch_workflow(pending)} "
        f"generation {pending['dispatch']['generation']}",
        flush=True,
    )
    terminal_wait_started_at = time.monotonic()
    completed = wait_for_terminal_job(
        control,
        job["job_id"],
        args.timeout_seconds,
    )
    terminal_wait_ms = elapsed_milliseconds(terminal_wait_started_at)
    result_download_started_at = time.monotonic()
    result = verified_json_result(
        completed["job"],
        args.r2_credentials_source,
    )
    result_download_ms = elapsed_milliseconds(result_download_started_at)
    provenance = result.get("provenance")
    transcript_provenance = (
        provenance.get("transcript") if isinstance(provenance, dict) else None
    )
    if (
        result.get("schema_version") != VIDEO_ANALYSIS_SCHEMA["version"]
        or result.get("video") != f"{video_id}.youtube"
        or not result.get("title")
        or not result.get("summary")
        or not result.get("topics")
        or not result.get("sections")
        or not isinstance(provenance, dict)
        or provenance.get("handler_id") != EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0]
        or not isinstance(transcript_provenance, dict)
        or transcript_provenance.get("digest") != transcript_reference["digest"]
    ):
        raise RuntimeError("Queued educational-video analysis returned an invalid result")
    summary = compact_analysis_result(
        completed,
        result,
        local_timing={
            "source_metadata_fetch_ms": metadata_fetch_ms,
            "terminal_wait_ms": terminal_wait_ms,
            "result_download_ms": result_download_ms,
            "command_total_ms": elapsed_milliseconds(command_started_at),
        },
    )
    worker_analysis_ms = summary["timing"]["worker"].get("analysis_ms")
    completion_line = (
        f"completed {completed['job']['job_id']} in "
        f"{format_elapsed(summary['timing']['local']['command_total_ms'])}"
    )
    if isinstance(worker_analysis_ms, int):
        completion_line += f" (worker analysis {format_elapsed(worker_analysis_ms)})"
    print(completion_line, flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(
        "Full analysis: ./authoring/watchcraft-author queue result "
        "--operator-token-source keychain --r2-credentials-source keychain "
        f"{completed['job']['job_id']}",
        flush=True,
    )
    return 0


def run_local_youtube_transcription(
    args: argparse.Namespace,
    *,
    smoke: bool,
) -> int:
    command_started_at = time.monotonic()
    control = operator_client(args.operator_token_source)
    staging = r2_staging_writer(args.r2_staging_credentials_source)
    handler = (
        STAGED_TRANSCRIPTION_SMOKE_HANDLER
        if smoke
        else PRODUCTION_TRANSCRIPTION_HANDLER
    )
    settings = STAGED_TRANSCRIPTION_SETTINGS[handler]
    acquisition_timeout = (
        YOUTUBE_TRANSCRIPTION_SMOKE_TIMEOUT_SECONDS
        if smoke
        else YOUTUBE_TRANSCRIPTION_TIMEOUT_SECONDS
    )
    video_id = youtube_video_id(args.youtube_url)
    canonical_url = canonical_youtube_url(video_id)
    reference = None
    submitted = None
    completed = None
    with tempfile.TemporaryDirectory(prefix="watchcraft-youtube-acquisition-") as directory:
        audio_path = Path(directory) / "source-audio"
        print(f"acquiring {canonical_url} anonymously on this Mac", flush=True)
        acquisition_started_at = time.monotonic()
        acquisition_result = download_youtube_audio(
            video_id,
            audio_path,
            maximum_bytes=settings["maximum_bytes"],
            maximum_duration_seconds=settings["maximum_duration_seconds"],
            timeout_seconds=acquisition_timeout,
        )
        acquisition_ms = elapsed_milliseconds(acquisition_started_at)
        acquisition = youtube_acquisition_provenance(
            acquisition_result,
            elapsed_ms=acquisition_ms,
        )
        staging_started_at = time.monotonic()
        reference = staging.put_staged_file(
            audio_path,
            {
                "artifact_kind": "source-audio",
                "media_type": source_audio_media_type(
                    acquisition_result.get("container")
                ),
                "schema": SOURCE_AUDIO_SCHEMA,
            },
            acquisition_id=str(uuid.uuid4()),
            expires_at=(
                int(time.time() * 1000) + SOURCE_AUDIO_RETENTION_MILLISECONDS
            ),
        )
        staging_upload_ms = elapsed_milliseconds(staging_started_at)
    print(
        f"staged {reference['byte_length']} bytes as {reference['digest']}",
        flush=True,
    )
    spec = staged_transcription_spec(
        source={"media_asset_id": f"youtube:{video_id}"},
        source_audio=reference,
        acquisition=acquisition,
        handler=handler,
    )
    try:
        request = (
            ephemeral_request(
                "mlx-transcription-youtube-local-smoke",
                spec["source"]["media_asset_id"],
                args.retention_days,
            )
            if smoke
            else {
                "kind": "youtube-transcription",
                "source_id": spec["source"]["media_asset_id"],
                "model": settings["model"],
            }
        )
        submitted = submit_spec(
            control,
            request=request,
            spec=spec,
        )
        job = submitted["job"]
        print(f"submitted {job['job_id']} ({job['spec']['handler']['id']})", flush=True)
        approved = control.post("/submissions/approve", {
            "job_id": job["job_id"],
            "command_id": str(uuid.uuid4()),
            "expected_revision": job["revision"],
            "actor": (
                "watchcraft-author-cli:smoke"
                if smoke
                else "watchcraft-author-cli"
            ),
            "spec_sha256": job["spec_sha256"],
        })
        pending = dispatch_submission(control, approved["job"])
        print(
            f"dispatched {pending['job_id']} via {dispatch_workflow(pending)} "
            f"generation {pending['dispatch']['generation']}",
            flush=True,
        )
        terminal_wait_started_at = time.monotonic()
        completed = wait_for_terminal_job(
            control,
            job["job_id"],
            args.timeout_seconds,
        )
        terminal_wait_ms = elapsed_milliseconds(terminal_wait_started_at)
        result_download_started_at = time.monotonic()
        result = verified_json_result(
            completed["job"],
            args.r2_credentials_source,
        )
        result_download_ms = elapsed_milliseconds(result_download_started_at)
        provenance = result.get("provenance", {})
        source_audio = provenance.get("source_audio", {})
        if (
            result.get("kind") != "watchcraft.transcript"
            or not result.get("text")
            or not result.get("segments")
            or provenance.get("handler_id") != handler[0]
            or source_audio.get("digest") != reference["digest"]
            or source_audio.get("byte_length") != reference["byte_length"]
        ):
            raise RuntimeError("Staged YouTube transcription returned an invalid result")
    except Exception:
        if submitted is None and reference is not None:
            staging.delete(reference)
        raise

    staging.delete(reference)
    print(f"deleted staged source audio {reference['key']}", flush=True)
    summary = compact_transcription_result(
        completed,
        result,
        local_timing={
            "acquisition_ms": acquisition_ms,
            "staging_upload_ms": staging_upload_ms,
            "terminal_wait_ms": terminal_wait_ms,
            "result_download_ms": result_download_ms,
            "command_total_ms": elapsed_milliseconds(command_started_at),
        },
    )
    worker_transcription_ms = summary["timing"]["worker"].get("transcription_ms")
    completion_line = (
        f"completed {completed['job']['job_id']} in "
        f"{format_elapsed(summary['timing']['local']['command_total_ms'])}"
    )
    if isinstance(worker_transcription_ms, int):
        completion_line += (
            f" (worker transcription {format_elapsed(worker_transcription_ms)})"
        )
    print(completion_line, flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(
        "Full transcript: ./authoring/watchcraft-author queue result "
        "--operator-token-source keychain --r2-credentials-source keychain "
        f"{completed['job']['job_id']}",
        flush=True,
    )
    return 0


def stable_project_execution_id(
    plan_artifact_sha256: str, item_id: str, role: str
) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"https://watchcraft.dev/authoring/{plan_artifact_sha256}/{item_id}/{role}",
    ))


def versioned_handler_execution_role(
    role: str, handler: tuple[str, str]
) -> str:
    return f"{role}:{handler[0]}@{handler[1]}"


def _resume_pipeline_job(
    control: AuthoringHttpClient,
    job: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    state = job.get("state")
    if state == "retryable_failed":
        job = control.post("/submissions/retry", {
            "job_id": job["job_id"],
            "command_id": str(uuid.uuid4()),
            "expected_revision": job["revision"],
        })
        state = job["state"]
        print(f"retrying {label} {job['job_id']}", flush=True)
    if state in {"ready", "dispatch_pending"}:
        pending = dispatch_submission(control, job)
        print(
            f"dispatched {label} {job['job_id']} via {dispatch_workflow(pending)}",
            flush=True,
        )
        return pending
    if state in {"dispatched", "claimed", "running", "succeeded"}:
        if state != "succeeded":
            print(f"resuming {label} {job['job_id']} ({state})", flush=True)
        return job
    raise RuntimeError(
        f"Cannot resume {label} job {job.get('job_id')} from state {state}"
    )


def run_youtube_video_pipeline(
    args: argparse.Namespace,
    *,
    project_execution: dict[str, Any] | None = None,
    emit_result: bool = True,
) -> int | dict[str, Any]:
    command_started_at = time.monotonic()
    control = operator_client(args.operator_token_source)
    staging = r2_staging_writer(args.r2_staging_credentials_source)
    settings = STAGED_TRANSCRIPTION_SETTINGS[PRODUCTION_TRANSCRIPTION_HANDLER]
    video_id = youtube_video_id(args.youtube_url)
    canonical_url = canonical_youtube_url(video_id)
    source = {"media_asset_id": f"youtube:{video_id}"}
    if project_execution is None:
        run_id = str(uuid.uuid4())
        command_prefix = str(uuid.uuid4())
        transcription_job_id = str(uuid.uuid4())
        analysis_job_id = str(uuid.uuid4())
        pipeline_request = {
            "kind": "youtube-video",
            "source_id": source["media_asset_id"],
            "stages": ["transcription", "educational-video-analysis"],
        }
        existing = {"run": None, "jobs": []}
    else:
        run_id = stable_project_execution_id(
            project_execution["plan_artifact_sha256"], project_execution["item_id"], "run"
        )
        command_prefix = stable_project_execution_id(
            project_execution["plan_artifact_sha256"], project_execution["item_id"], "commands"
        )
        transcription_job_id = stable_project_execution_id(
            project_execution["plan_artifact_sha256"],
            project_execution["item_id"],
            "transcription",
        )
        analysis_job_id = stable_project_execution_id(
            project_execution["plan_artifact_sha256"], project_execution["item_id"], "analysis"
        )
        pipeline_request = {
            "kind": "project-item-processing",
            "plan_job_id": project_execution["plan_job_id"],
            "plan_artifact_sha256": project_execution["plan_artifact_sha256"],
            "plan_hash": project_execution["plan_hash"],
            "project_id": project_execution["project_id"],
            "project_revision": project_execution["project_revision"],
            "item_id": project_execution["item_id"],
            "logical_tasks": project_execution["logical_tasks"],
            "source_id": source["media_asset_id"],
            "stages": ["transcription", "educational-video-analysis"],
        }
        existing = control.post("/pipelines/get", {"run_id": run_id})
    existing_run = existing.get("run")
    existing_disposition = (
        "already-complete"
        if isinstance(existing_run, dict) and existing_run.get("state") == "complete"
        else "resumed"
        if existing_run is not None
        else "executed"
    )

    reference = None
    submitted = None
    submission_attempted = False
    metadata_fetch_ms = 0
    acquisition_ms = 0
    staging_upload_ms = 0
    try:
        if existing.get("run") is not None:
            submitted = existing
            run = submitted["run"]
            if run.get("request") != pipeline_request:
                raise RuntimeError("Existing project item execution does not match its plan")
            jobs_by_id = {job["job_id"]: job for job in submitted.get("jobs", [])}
            if set(jobs_by_id) != {transcription_job_id, analysis_job_id}:
                raise RuntimeError("Existing project item execution has an invalid job set")
            transcription_spec = jobs_by_id[transcription_job_id]["spec"]
            analysis_spec = jobs_by_id[analysis_job_id]["spec"]
            reference = validated_artifact_reference(
                transcription_spec["inputs"][0], allow_staged=True
            )
            acquisition = transcription_spec["configuration"]["acquisition"]
            source_metadata = analysis_spec["configuration"]["source_metadata"]
            print(f"resuming planned item run {run_id}", flush=True)
        else:
            metadata_started_at = time.monotonic()
            source_metadata = youtube_source_metadata(video_id)
            metadata_fetch_ms = elapsed_milliseconds(metadata_started_at)
            if source_metadata.get("source_id") != source["media_asset_id"]:
                raise RuntimeError("Resolved source metadata does not match the YouTube source")
            with tempfile.TemporaryDirectory(
                prefix="watchcraft-youtube-acquisition-"
            ) as directory:
                audio_path = Path(directory) / "source-audio"
                print(f"acquiring {canonical_url} anonymously on this Mac", flush=True)
                acquisition_started_at = time.monotonic()
                acquisition_result = download_youtube_audio(
                    video_id,
                    audio_path,
                    maximum_bytes=settings["maximum_bytes"],
                    maximum_duration_seconds=settings["maximum_duration_seconds"],
                    timeout_seconds=YOUTUBE_TRANSCRIPTION_TIMEOUT_SECONDS,
                )
                acquisition_ms = elapsed_milliseconds(acquisition_started_at)
                acquisition = youtube_acquisition_provenance(
                    acquisition_result,
                    elapsed_ms=acquisition_ms,
                )
                staging_started_at = time.monotonic()
                reference = staging.put_staged_file(
                    audio_path,
                    {
                        "artifact_kind": "source-audio",
                        "media_type": source_audio_media_type(
                            acquisition_result.get("container")
                        ),
                        "schema": SOURCE_AUDIO_SCHEMA,
                    },
                    acquisition_id=str(uuid.uuid4()),
                    expires_at=(
                        int(time.time() * 1000) + SOURCE_AUDIO_RETENTION_MILLISECONDS
                    ),
                )
                staging_upload_ms = elapsed_milliseconds(staging_started_at)
            print(
                f"staged {reference['byte_length']} bytes as {reference['digest']}",
                flush=True,
            )
            transcription_spec = staged_transcription_spec(
                source=source,
                source_audio=reference,
                acquisition=acquisition,
                handler=PRODUCTION_TRANSCRIPTION_HANDLER,
            )
            analysis_spec = educational_video_analysis_spec(
                source=source,
                transcript={
                    "kind": "job-output",
                    "job_id": transcription_job_id,
                    "artifact_kind": "transcript",
                    "schema": {"id": "watchcraft.transcript", "version": 1},
                },
                source_metadata=source_metadata,
                video=f"{video_id}.youtube",
            )
            submission_attempted = True
            submission_arguments = {}
            if project_execution is not None:
                submission_arguments = {
                    "run_id": run_id,
                    "command_prefix": command_prefix,
                }
            submitted = submit_pipeline(
                control,
                request=pipeline_request,
                jobs=[
                    {"job_id": transcription_job_id, "spec": transcription_spec},
                    {"job_id": analysis_job_id, "spec": analysis_spec},
                ],
                **submission_arguments,
            )
        run = submitted["run"]
        if existing.get("run") is None:
            print(
                f"submitted run {run['run_id']} with transcription "
                f"{transcription_job_id} and analysis {analysis_job_id}",
                flush=True,
            )
        if run["state"] == "planned":
            approved = control.post("/pipelines/approve", {
                "run_id": run["run_id"],
                "command_id": str(uuid.uuid4()),
                "expected_revision": run["revision"],
                "actor": "watchcraft-author-cli",
                "approval_sha256": run["approval_sha256"],
            })
            jobs_by_id = {job["job_id"]: job for job in approved["jobs"]}
        else:
            jobs_by_id = {job["job_id"]: job for job in submitted["jobs"]}

        _resume_pipeline_job(
            control, jobs_by_id[transcription_job_id], "transcription"
        )
        transcription_wait_started_at = time.monotonic()
        transcription_completed = wait_for_terminal_job(
            control,
            transcription_job_id,
            args.transcription_timeout_seconds,
        )
        transcription_wait_ms = elapsed_milliseconds(transcription_wait_started_at)
        transcript_download_started_at = time.monotonic()
        transcript = verified_json_result(
            transcription_completed["job"],
            args.r2_credentials_source,
        )
        transcript_download_ms = elapsed_milliseconds(transcript_download_started_at)
        transcript_provenance = transcript.get("provenance", {})
        if (
            transcript.get("kind") != "watchcraft.transcript"
            or not transcript.get("text")
            or not transcript.get("segments")
            or transcript_provenance.get("handler_id")
            != PRODUCTION_TRANSCRIPTION_HANDLER[0]
        ):
            raise RuntimeError("Pipeline transcription returned an invalid result")

        staging.delete(reference)
        print(f"deleted staged source audio {reference['key']}", flush=True)
        reference = None

        _resume_pipeline_job(control, jobs_by_id[analysis_job_id], "analysis")
        analysis_wait_started_at = time.monotonic()
        analysis_completed = wait_for_terminal_job(
            control,
            analysis_job_id,
            args.analysis_timeout_seconds,
        )
        analysis_wait_ms = elapsed_milliseconds(analysis_wait_started_at)
        analysis_download_started_at = time.monotonic()
        analysis = verified_json_result(
            analysis_completed["job"],
            args.r2_credentials_source,
        )
        analysis_download_ms = elapsed_milliseconds(analysis_download_started_at)
        analysis_provenance = analysis.get("provenance", {})
        transcript_reference = transcription_completed["job"]["result"]
        if (
            analysis.get("schema_version") != VIDEO_ANALYSIS_SCHEMA["version"]
            or analysis.get("video") != f"{video_id}.youtube"
            or not analysis.get("summary")
            or analysis_provenance.get("handler_id")
            != EDUCATIONAL_VIDEO_ANALYSIS_HANDLER[0]
            or analysis_provenance.get("transcription_job_id")
            != transcription_job_id
            or analysis_provenance.get("transcript", {}).get("digest")
            != transcript_reference["digest"]
        ):
            raise RuntimeError("Pipeline educational-video analysis returned an invalid result")
    except Exception:
        if submitted is None and not submission_attempted and reference is not None:
            staging.delete(reference)
        raise

    transcription_summary = compact_transcription_result(
        transcription_completed,
        transcript,
        local_timing={
            "terminal_wait_ms": transcription_wait_ms,
            "result_download_ms": transcript_download_ms,
        },
    )
    analysis_summary = compact_analysis_result(
        analysis_completed,
        analysis,
        local_timing={
            "terminal_wait_ms": analysis_wait_ms,
            "result_download_ms": analysis_download_ms,
        },
    )
    total_ms = elapsed_milliseconds(command_started_at)
    completed_run = analysis_completed["run"]
    run_elapsed_ms = timestamp_delta_ms(
        completed_run.get("updated_at"),
        completed_run.get("created_at"),
    )
    summary = {
        "run_id": completed_run["run_id"],
        "state": completed_run["state"],
        "source": {
            "media_asset_id": source["media_asset_id"],
            "url": canonical_url,
            "title": source_metadata.get("title"),
        },
        "jobs": {
            "transcription": transcription_summary,
            "analysis": analysis_summary,
        },
        "timing": {
            "local": {
                "source_metadata_fetch_ms": metadata_fetch_ms,
                "acquisition_ms": acquisition_ms,
                "staging_upload_ms": staging_upload_ms,
                "command_total_ms": total_ms,
            },
            "ledger": {
                **(
                    {"run_created_to_completed_ms": run_elapsed_ms}
                    if run_elapsed_ms is not None
                    else {}
                ),
            },
        },
    }
    if project_execution is not None:
        summary["plan_execution"] = {
            "plan_job_id": project_execution["plan_job_id"],
            "plan_artifact_sha256": project_execution["plan_artifact_sha256"],
            "plan_hash": project_execution["plan_hash"],
            "project_id": project_execution["project_id"],
            "project_revision": project_execution["project_revision"],
            "item_id": project_execution["item_id"],
            "logical_tasks": project_execution["logical_tasks"],
            "disposition": existing_disposition,
        }
    if not emit_result:
        return summary
    print(f"completed run {completed_run['run_id']} in {format_elapsed(total_ms)}", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(
        "Full transcript: ./authoring/watchcraft-author queue result "
        "--operator-token-source keychain --r2-credentials-source keychain "
        f"{transcription_job_id}",
        flush=True,
    )
    print(
        "Full analysis: ./authoring/watchcraft-author queue result "
        "--operator-token-source keychain --r2-credentials-source keychain "
        f"{analysis_job_id}",
        flush=True,
    )
    return 0


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
    transcription_submit = commands.add_parser(
        "submit-transcription-smoke",
        parents=[credentials],
        help="Submit a real MLX transcription of a generated audio fixture",
        description=(
            "Submit a macOS/MLX transcription job whose temporary spoken-audio "
            "fixture is generated by the worker and never retained."
        ),
    )
    transcription_submit.add_argument(
        "--fixture-text",
        default=TRANSCRIPTION_SMOKE_TEXT,
        help="Short English phrase synthesized and transcribed by the worker",
    )
    transcription_submit.add_argument("--retention-days", type=int, default=7)
    http_transcription_submit = commands.add_parser(
        "submit-transcription-http-smoke",
        parents=[credentials],
        help="Submit MLX transcription of a pinned HTTPS audio fixture",
        description=(
            "Submit a macOS/MLX transcription job that downloads, bounds, and "
            "hash-verifies an immutable public audio fixture before inference."
        ),
    )
    http_transcription_submit.add_argument("--retention-days", type=int, default=7)
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
    production_transcription = commands.add_parser(
        "transcribe-youtube",
        parents=[credentials],
        help="Acquire and transcribe one YouTube video with the production MLX model",
        description=(
            "Acquire one public YouTube audio stream anonymously on this Mac, bind "
            "and stage its exact bytes in private R2, then approve, dispatch, wait "
            "for, retrieve, and verify production MLX transcription. The registered "
            f"model is {PRODUCTION_TRANSCRIPTION_MODEL}; initial limits are two hours "
            "and 100 MB of compressed audio."
        ),
    )
    production_transcription.add_argument(
        "youtube_url",
        help="One public YouTube URL or video ID",
    )
    production_transcription.add_argument("--timeout-seconds", type=int, default=3600)
    production_transcription.add_argument(
        "--r2-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help="Read-only result credential source (default: auto)",
    )
    production_transcription.add_argument(
        "--r2-staging-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help="Temporary source-media uploader credential source (default: auto)",
    )
    video_pipeline = commands.add_parser(
        "process-youtube",
        parents=[credentials],
        help="Transcribe and analyze one YouTube video as a durable pipeline run",
        description=(
            "Acquire and stage one public YouTube audio stream, then execute production "
            "MLX transcription and educational-video analysis as two explicitly dependent "
            "jobs in one durable run."
        ),
    )
    video_pipeline.add_argument("youtube_url", help="One public YouTube URL or video ID")
    video_pipeline.add_argument(
        "--transcription-timeout-seconds", type=int, default=3600
    )
    video_pipeline.add_argument("--analysis-timeout-seconds", type=int, default=3600)
    video_pipeline.add_argument(
        "--r2-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help="Read-only result credential source (default: auto)",
    )
    video_pipeline.add_argument(
        "--r2-staging-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help="Temporary source-media uploader credential source (default: auto)",
    )
    project_import = commands.add_parser(
        "project-import",
        parents=[credentials],
        help="Import an initial CatalogProject revision into the control plane",
        description=(
            "Validate and import one CatalogProject as its immutable initial Convex "
            "revision. If it already accepts a snapshot, its exact local snapshot "
            "bytes are verified and imported with it."
        ),
    )
    project_import.add_argument("project_file", type=Path)
    project_import.add_argument(
        "--accepted-snapshot-file",
        type=Path,
        help=(
            "Exact snapshot file bound by accepted_snapshot; defaults to the sibling "
            "*.snapshot.json file"
        ),
    )
    project_status = commands.add_parser(
        "project-status",
        parents=[credentials],
        help="Show the current authoritative CatalogProject revision",
    )
    project_status.add_argument("project_id")
    project_history = commands.add_parser(
        "project-history",
        parents=[credentials],
        help="Show immutable CatalogProject revision history",
    )
    project_history.add_argument("project_id")
    project_history.add_argument("--limit", type=int, default=20)
    project_accept = commands.add_parser(
        "project-accept-snapshot",
        parents=[credentials],
        help="Accept a succeeded iterator candidate as a new project revision",
        description=(
            "Retrieve and verify a succeeded iterator job's exact R2 snapshot, bind "
            "it to the current CatalogProject using compare-and-swap, and create one "
            "new immutable project revision."
        ),
    )
    project_accept.add_argument("project_id")
    project_accept.add_argument("job_id")
    project_accept.add_argument(
        "--expected-revision",
        type=int,
        help="Compare-and-swap revision; defaults to the observed current revision",
    )
    project_accept.add_argument(
        "--r2-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help="Read-only candidate snapshot credential source (default: auto)",
    )
    iterate_project = commands.add_parser(
        "iterate-project",
        parents=[credentials],
        help="Discover a catalog project's members into an immutable snapshot",
        description=(
            "Validate a CatalogProject, run its registered collection iterator, "
            "report member progress, and retrieve the verified candidate snapshot. "
            "The first executable iterator is watchcraft.youtube-playlist@1."
        ),
    )
    iterate_project.add_argument(
        "project",
        help="CatalogProject JSON file or an imported project ID",
    )
    iterate_project.add_argument("--timeout-seconds", type=int, default=1800)
    iterate_project.add_argument(
        "--r2-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help="Read-only result credential source (default: auto)",
    )
    plan_project = commands.add_parser(
        "plan-project",
        parents=[credentials],
        help="Plan processing for an imported project's accepted snapshot",
        description=(
            "Load the authoritative imported CatalogProject and accepted iterator "
            "snapshot, then create an immutable logical processing plan. This does "
            "not acquire media or dispatch transcription and analysis jobs."
        ),
    )
    plan_project.add_argument("project_id")
    plan_project.add_argument("--timeout-seconds", type=int, default=900)
    plan_project.add_argument(
        "--r2-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help="Read-only result credential source (default: auto)",
    )
    process_project = commands.add_parser(
        "process-project",
        parents=[credentials],
        help="Execute items from an immutable project processing plan",
        description=(
            "Verify an immutable project-processing plan and its authoritative "
            "project revision, then execute selected YouTube items through local "
            "acquisition, MLX transcription, and educational analysis. Deterministic "
            "queue identities make reruns resume the same pipelines."
        ),
    )
    process_project.add_argument("--plan-job-id", required=True)
    selection = process_project.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--limit",
        type=int,
        help="Process the first N plan items",
    )
    selection.add_argument(
        "--item",
        dest="item_id",
        help="Process the exact plan item ID",
    )
    selection.add_argument(
        "--all",
        dest="process_all",
        action="store_true",
        help="Process every item in the plan",
    )
    process_project.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Maximum simultaneous item pipelines, from 1 to 8 (default: 2)",
    )
    process_project.add_argument(
        "--transcription-timeout-seconds", type=int, default=3600
    )
    process_project.add_argument("--analysis-timeout-seconds", type=int, default=3600)
    process_project.add_argument(
        "--r2-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help="Read-only result credential source (default: auto)",
    )
    process_project.add_argument(
        "--r2-staging-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help="Temporary source-media uploader credential source (default: auto)",
    )
    resolve_terminology = commands.add_parser(
        "resolve-project-terminology",
        parents=[credentials],
        help="Infer reviewable terminology resolutions from a completed draft corpus",
        description=(
            "Bind every completed transcript and draft analysis from an immutable "
            "project plan, infer domain-aware terminology corrections across the "
            "whole corpus, and preserve ambiguous semantic changes for review."
        ),
    )
    resolve_terminology.add_argument("--plan-job-id", required=True)
    resolve_terminology.add_argument("--timeout-seconds", type=int, default=3600)
    resolve_terminology.add_argument(
        "--r2-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help="Read-only transcript, analysis, and result credential source (default: auto)",
    )
    normalize_project = commands.add_parser(
        "normalize-project-topics",
        parents=[credentials],
        help="Normalize topics across every completed analysis in a project plan",
        description=(
            "Verify a successful immutable project plan and every deterministic "
            "per-item analysis, then dispatch the registered collection-wide topic "
            "normalizer with those exact analysis artifacts as dependencies."
        ),
    )
    normalize_project.add_argument("--plan-job-id", required=True)
    normalize_project.add_argument("--timeout-seconds", type=int, default=3600)
    normalize_project.add_argument(
        "--r2-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help="Read-only plan and result credential source (default: auto)",
    )
    compile_project = commands.add_parser(
        "compile-project",
        parents=[credentials],
        help="Compile a completed project plan into a candidate collection package",
        description=(
            "Bind the accepted iterator snapshot, every completed transcript and "
            "analysis, and the completed topic normalization into an immutable "
            "candidate watchcraft.collection package. This does not publish it."
        ),
    )
    compile_project.add_argument("--plan-job-id", required=True)
    compile_project.add_argument("--timeout-seconds", type=int, default=1800)
    compile_project.add_argument(
        "--r2-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help="Read-only plan and result credential source (default: auto)",
    )
    compile_project.add_argument(
        "--compare-to",
        type=Path,
        help="Published collection.json to compare with the candidate",
    )
    materialize_project = commands.add_parser(
        "materialize-project",
        parents=[credentials],
        help="Materialize a successful compilation into a new review directory",
        description=(
            "Retrieve and verify one immutable collection-compilation result and all "
            "of its analysis resources, assign the next revision relative to an "
            "existing published collection, and write a new validated review package "
            "plus a Git-readable diff. Existing paths are never overwritten."
        ),
    )
    materialize_project.add_argument("compilation_job_id")
    materialize_project.add_argument(
        "--published-collection",
        required=True,
        type=Path,
        help="Current published collection.json used as the revision and diff baseline",
    )
    materialize_project.add_argument(
        "--output-directory",
        required=True,
        type=Path,
        help="New directory to create for the materialized candidate",
    )
    materialize_project.add_argument(
        "--diff-output",
        type=Path,
        help="New patch path; defaults to OUTPUT_DIRECTORY.diff",
    )
    materialize_project.add_argument(
        "--r2-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help="Read-only compilation and resource credential source (default: auto)",
    )
    queued_analysis = commands.add_parser(
        "analyze-transcript",
        parents=[credentials],
        help="Analyze one successful queued transcript with the production analyzer",
        description=(
            "Resolve source metadata for a successful YouTube transcription job, "
            "then approve, dispatch, wait for, retrieve, and verify the existing "
            f"educational-video analysis logic using {EDUCATIONAL_VIDEO_ANALYSIS_MODEL}."
        ),
    )
    queued_analysis.add_argument(
        "transcription_job_id",
        help="Job ID of a successful authoritative transcript",
    )
    queued_analysis.add_argument("--timeout-seconds", type=int, default=3600)
    queued_analysis.add_argument(
        "--r2-credentials-source",
        choices=("auto", "keychain", "environment"),
        default="auto",
        help="Read-only result credential source (default: auto)",
    )
    for name, help_text, timeout in (
        ("smoke-analysis", "Run the complete lexical-analysis queue smoke", 600),
        ("smoke-transcription", "Run the complete macOS/MLX transcription smoke", 1800),
        (
            "smoke-transcription-http",
            "Run the complete verified-HTTPS macOS/MLX transcription smoke",
            1800,
        ),
        (
            "smoke-transcription-youtube",
            "Acquire one YouTube audio stream locally, then run the cloud MLX smoke",
            1800,
        ),
    ):
        smoke = commands.add_parser(
            name,
            parents=[credentials],
            help=help_text,
            description=(
                help_text + ": submit, approve, dispatch, wait, retrieve, and verify."
            ),
        )
        smoke.add_argument("--timeout-seconds", type=int, default=timeout)
        smoke.add_argument("--retention-days", type=int, default=7)
        smoke.add_argument(
            "--r2-credentials-source",
            choices=("auto", "keychain", "environment"),
            default="auto",
        )
        if name == "smoke-transcription-youtube":
            smoke.add_argument(
                "--r2-staging-credentials-source",
                choices=("auto", "keychain", "environment"),
                default="auto",
                help=(
                    f"Temporary source-media uploader credential source: environment "
                    f"uses {R2_STAGING_ACCESS_KEY_ENV} and {R2_STAGING_SECRET_KEY_ENV}; "
                    "auto uses them when set and otherwise reads the macOS Keychain "
                    "(default: auto)"
                ),
            )
            smoke.add_argument(
                "youtube_url",
                nargs="?",
                default=YOUTUBE_TRANSCRIPTION_SMOKE_URL,
                help=f"One public YouTube URL or video ID (default: {YOUTUBE_TRANSCRIPTION_SMOKE_URL})",
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
            command.add_argument(
                "--expected-active-revision",
                "--expected-revision",
                dest="expected_revision",
                type=int,
                help=(
                    "Current activation-pointer revision for compare-and-set. The CLI "
                    "reads it automatically when omitted. This is not the registry "
                    "document version."
                ),
            )
    cleanup_list = commands.add_parser(
        "cleanup-list",
        parents=[admin_credentials],
        help="List terminal runs eligible for or relevant to cleanup",
        description=(
            "List terminal ephemeral runs; --include-unmarked also shows legacy "
            "runs and orphaned terminal jobs that require explicit cleanup authority."
        ),
    )
    cleanup_list.add_argument("--include-unmarked", action="store_true")
    cleanup_list.add_argument("--limit", type=int, default=50)
    cleanup_run = commands.add_parser(
        "cleanup-run",
        parents=[admin_credentials],
        help="Purge one confirmed terminal run and its Convex event projections",
        description=(
            "Purge one terminal run from Convex. R2 artifacts are reported but retained."
        ),
    )
    cleanup_run.add_argument("run_id")
    cleanup_run.add_argument("--confirm", required=True, metavar="RUN_ID")
    cleanup_run.add_argument(
        "--allow-unmarked",
        action="store_true",
        help="Permit explicit cleanup of a legacy run without expired ephemeral retention",
    )
    cleanup_orphan = commands.add_parser(
        "cleanup-orphan-job",
        parents=[admin_credentials],
        help="Purge one confirmed terminal job whose run aggregate is missing",
        description=(
            "Purge one legacy orphan job from Convex. R2 artifacts are reported but retained."
        ),
    )
    cleanup_orphan.add_argument("job_id")
    cleanup_orphan.add_argument("--confirm", required=True, metavar="JOB_ID")


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


def active_registry_revision(
    control: AuthoringHttpClient,
    environment: str,
) -> int:
    observed = control.post("/registry/get-active", {"environment": environment})
    active = observed.get("active")
    if active is None:
        return 0
    if not isinstance(active, dict):
        raise RuntimeError("Authoring control returned an invalid active registry pointer")
    revision = active.get("revision")
    if (
        active.get("environment") != environment
        or type(revision) is not int
        or revision < 1
    ):
        raise RuntimeError("Authoring control returned an invalid active registry pointer")
    return revision


def run_queue_command(args: argparse.Namespace) -> int:
    if args.queue_command in {"cleanup-list", "cleanup-run", "cleanup-orphan-job"}:
        control = registry_admin_client(args.registry_admin_token_source)
        if args.queue_command == "cleanup-list":
            result = control.post("/cleanup/list", {
                "include_unmarked": args.include_unmarked,
                "limit": args.limit,
            })
        elif args.queue_command == "cleanup-run":
            result = control.post("/cleanup/purge-run", {
                "run_id": args.run_id,
                "confirmation": args.confirm,
                "command_id": str(uuid.uuid4()),
                "actor": "watchcraft-author-cli",
                "allow_unmarked": args.allow_unmarked,
            })
        else:
            result = control.post("/cleanup/purge-orphan-job", {
                "job_id": args.job_id,
                "confirmation": args.confirm,
                "command_id": str(uuid.uuid4()),
                "actor": "watchcraft-author-cli",
            })
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
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
            expected_revision = args.expected_revision
            revision_source = "override"
            if expected_revision is None:
                expected_revision = active_registry_revision(control, args.environment)
                revision_source = "observed"
            print(
                f"Activating registry document {registry['registry_version']} in "
                f"{args.environment}; {revision_source} active-pointer revision "
                f"{expected_revision}.",
                file=sys.stderr,
            )
            result = control.post("/registry/activate", {
                "environment": args.environment,
                "command_id": str(uuid.uuid4()),
                "actor": "watchcraft-author-cli",
                "registry_version": registry["registry_version"],
                "registry_sha256": sha256_hex(canonical_json(registry)),
                "expected_revision": expected_revision,
            })
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.queue_command in {
        "smoke-analysis",
        "smoke-transcription",
        "smoke-transcription-http",
    }:
        return run_smoke_command(
            args,
            {
                "smoke-analysis": "analysis",
                "smoke-transcription": "transcription",
                "smoke-transcription-http": "transcription-http",
            }[args.queue_command],
        )
    if args.queue_command == "smoke-transcription-youtube":
        return run_local_youtube_transcription(args, smoke=True)
    if args.queue_command == "transcribe-youtube":
        return run_local_youtube_transcription(args, smoke=False)
    if args.queue_command == "process-youtube":
        return run_youtube_video_pipeline(args)
    if args.queue_command == "project-import":
        return run_project_import(args)
    if args.queue_command == "project-accept-snapshot":
        return run_project_accept_snapshot(args)
    if args.queue_command == "iterate-project":
        return run_iterate_project(args)
    if args.queue_command == "plan-project":
        return run_plan_project(args)
    if args.queue_command == "process-project":
        return run_process_project(args)
    if args.queue_command == "resolve-project-terminology":
        return run_resolve_project_terminology(args)
    if args.queue_command == "normalize-project-topics":
        return run_normalize_project(args)
    if args.queue_command == "compile-project":
        return run_compile_project(args)
    if args.queue_command == "materialize-project":
        return run_materialize_project(args)
    if args.queue_command == "analyze-transcript":
        return run_queued_video_analysis(args)

    control = operator_client(args.operator_token_source)
    if args.queue_command == "registry-status":
        result = control.post("/registry/get-active", {"environment": args.environment})
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.queue_command == "project-status":
        result = control.post("/projects/get", {"project_id": args.project_id})
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.queue_command == "project-history":
        if not 1 <= args.limit <= 100:
            raise ValueError("--limit must be between 1 and 100")
        result = control.post("/projects/history", {
            "project_id": args.project_id,
            "limit": args.limit,
        })
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.queue_command == "submit-analysis":
        if not 1 <= args.max_topics <= 20:
            raise ValueError("--max-topics must be between 1 and 20")
        result = submit_spec(control, request={
            "kind": "lexical-analysis", "source_id": args.source_id,
        }, spec=analysis_spec(args))
        print(canonical_json({"job": result["job"], "run": result["run"]}))
        return 0
    if args.queue_command == "submit-transcription-smoke":
        result = submit_spec(control, request=ephemeral_request(
            "mlx-transcription-smoke",
            "synthetic:mlx-audio-smoke",
            args.retention_days,
        ), spec=transcription_smoke_spec(args.fixture_text))
        print(canonical_json({"job": result["job"], "run": result["run"]}))
        return 0
    if args.queue_command == "submit-transcription-http-smoke":
        spec = http_transcription_smoke_spec()
        result = submit_spec(control, request=ephemeral_request(
            "mlx-transcription-http-smoke",
            spec["source"]["media_asset_id"],
            args.retention_days,
        ), spec=spec)
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
        pending = dispatch_submission(control, job)
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
