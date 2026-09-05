"""Operator and worker primitives for queued Watchcraft authoring."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
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
from pathlib import Path
from typing import Any, Callable

from youtube_audio import (
    canonical_youtube_url,
    download_youtube_audio,
    youtube_video_id,
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
DEFAULT_GITHUB_REPOSITORY = "billbliss/watchcraft"
DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages" / "authoring-pipeline" / "registry" / "default-registry.json"
)
ANALYSIS_HANDLER = ("watchcraft.analysis.lexical", "1")
TRANSCRIPTION_SMOKE_HANDLER = ("watchcraft.transcript.mlx-whisper-smoke", "1")
HTTP_TRANSCRIPTION_SMOKE_HANDLER = (
    "watchcraft.transcript.mlx-whisper-http-smoke",
    "1",
)
YOUTUBE_TRANSCRIPTION_HANDLER = (
    "watchcraft.transcript.mlx-whisper-youtube",
    "1",
)
PYTHON_EXECUTION_PROFILE = ("python-portable", "1")
PYTHON_EXECUTION_WORKFLOW = "authoring-worker.yml"
MLX_EXECUTION_PROFILE = ("macos-mlx", "1")
MLX_EXECUTION_WORKFLOW = "authoring-mlx-worker.yml"
TRANSCRIPTION_SMOKE_MODEL = "mlx-community/whisper-tiny-mlx"
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
YOUTUBE_TRANSCRIPTION_SMOKE_URL = "https://www.youtube.com/watch?v=WPtpUu3uIUI"
YOUTUBE_TRANSCRIPTION_MAX_BYTES = 10_000_000
YOUTUBE_TRANSCRIPTION_MAX_DURATION_SECONDS = 300
YOUTUBE_TRANSCRIPTION_TIMEOUT_SECONDS = 180
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


def mlx_transcription_smoke(job: dict[str, Any]) -> dict[str, Any]:
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


def mlx_http_transcription_smoke(job: dict[str, Any]) -> dict[str, Any]:
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


def mlx_youtube_transcription(job: dict[str, Any]) -> dict[str, Any]:
    configuration = job["spec"]["configuration"]
    required_keys = {
        "canonical_url",
        "video_id",
        "maximum_bytes",
        "maximum_duration_seconds",
        "timeout_seconds",
        "language",
        "model",
    }
    if not isinstance(configuration, dict) or set(configuration) != required_keys:
        raise ValueError("the YouTube transcript configuration is invalid")
    if not isinstance(configuration["canonical_url"], str) or not isinstance(
        configuration["video_id"], str
    ):
        raise ValueError("the YouTube transcript source identity is invalid")
    video_id = youtube_video_id(configuration["canonical_url"])
    if (
        configuration["video_id"] != video_id
        or configuration["canonical_url"] != canonical_youtube_url(video_id)
        or job["spec"]["source"] != {"media_asset_id": f"youtube:{video_id}"}
    ):
        raise ValueError("the YouTube transcript source identity is inconsistent")
    if configuration["language"] != "en":
        raise ValueError("the initial YouTube transcript handler supports only English")
    if configuration["model"] != TRANSCRIPTION_SMOKE_MODEL:
        raise ValueError(
            f"the initial YouTube transcript handler requires {TRANSCRIPTION_SMOKE_MODEL}"
        )
    if (
        type(configuration["maximum_bytes"]) is not int
        or not 1 <= configuration["maximum_bytes"] <= YOUTUBE_TRANSCRIPTION_MAX_BYTES
        or type(configuration["maximum_duration_seconds"]) is not int
        or not 1
        <= configuration["maximum_duration_seconds"]
        <= YOUTUBE_TRANSCRIPTION_MAX_DURATION_SECONDS
        or type(configuration["timeout_seconds"]) is not int
        or not 1 <= configuration["timeout_seconds"] <= YOUTUBE_TRANSCRIPTION_TIMEOUT_SECONDS
    ):
        raise ValueError("the YouTube transcript acquisition limits are invalid")

    with tempfile.TemporaryDirectory(prefix="watchcraft-mlx-youtube-") as directory:
        audio_path = Path(directory) / "source-audio"
        acquisition = download_youtube_audio(
            video_id,
            audio_path,
            maximum_bytes=configuration["maximum_bytes"],
            maximum_duration_seconds=configuration["maximum_duration_seconds"],
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
            "handler_id": YOUTUBE_TRANSCRIPTION_HANDLER[0],
            "handler_version": YOUTUBE_TRANSCRIPTION_HANDLER[1],
            "job_id": job["job_id"],
            "spec_sha256": job["spec_sha256"],
            "acquisition": acquisition,
            "audio_retained": False,
        },
    }


HANDLERS: dict[tuple[str, str], Callable[[dict[str, Any]], dict[str, Any]]] = {
    ANALYSIS_HANDLER: lexical_analysis,
    TRANSCRIPTION_SMOKE_HANDLER: mlx_transcription_smoke,
    HTTP_TRANSCRIPTION_SMOKE_HANDLER: mlx_http_transcription_smoke,
    YOUTUBE_TRANSCRIPTION_HANDLER: mlx_youtube_transcription,
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
    YOUTUBE_TRANSCRIPTION_HANDLER: {
        "id": YOUTUBE_TRANSCRIPTION_HANDLER[0],
        "version": YOUTUBE_TRANSCRIPTION_HANDLER[1],
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
                "artifact_store_failed",
                "lease_expired",
                "source_acquisition_failed",
                "source_acquisition_timeout",
                "source_rate_limited",
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
        classification = getattr(error, "classification", "handler_failed")
        retryable = getattr(error, "retryable", False)
        if not isinstance(classification, str) or not classification:
            classification = "handler_failed"
        if not isinstance(retryable, bool):
            retryable = False
        control.post("/jobs/fail", {
            "job_id": job_id,
            "command_id": f"{attempt_id}:handler-fail",
            "expected_revision": job["revision"],
            "attempt_id": attempt_id,
            "failure": {
                "classification": classification,
                "message": str(error)[:500],
                "retryable": retryable,
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


def youtube_transcription_spec(value: str) -> dict[str, Any]:
    video_id = youtube_video_id(value)
    canonical_url = canonical_youtube_url(video_id)
    return {
        "operation": "generate",
        "artifact_kind": "transcript",
        "output_schema": {"id": "watchcraft.transcript", "version": 1},
        "handler": {
            "id": YOUTUBE_TRANSCRIPTION_HANDLER[0],
            "version": YOUTUBE_TRANSCRIPTION_HANDLER[1],
        },
        "source": {"media_asset_id": f"youtube:{video_id}"},
        "inputs": [],
        "dependencies": [],
        "configuration": {
            "canonical_url": canonical_url,
            "video_id": video_id,
            "maximum_bytes": YOUTUBE_TRANSCRIPTION_MAX_BYTES,
            "maximum_duration_seconds": YOUTUBE_TRANSCRIPTION_MAX_DURATION_SECONDS,
            "timeout_seconds": YOUTUBE_TRANSCRIPTION_TIMEOUT_SECONDS,
            "language": "en",
            "model": TRANSCRIPTION_SMOKE_MODEL,
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
) -> dict[str, Any]:
    return control.post("/submissions/submit", {
        "job_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "command_prefix": str(uuid.uuid4()),
        "request": request,
        "spec": spec,
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
    subprocess.run([
        "gh", "workflow", "run", workflow, "--ref", "main",
        "--repo", DEFAULT_GITHUB_REPOSITORY,
        "-f", f"job_id={pending['job_id']}",
        "-f", f"spec_sha256={pending['spec_sha256']}",
        "-f", f"dispatch_generation={pending['dispatch']['generation']}",
        "-f", f"expected_revision={pending['revision']}",
    ], check=True)
    return pending


def verified_json_result(job: dict[str, Any], credential_source: str) -> dict[str, Any]:
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
    return result


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
    while True:
        submission = control.post("/submissions/get", {"job_id": job_id})
        job = submission["job"]
        state = job.get("state")
        state_changed = state != last_state
        if state_changed:
            print(f"{job_id}: {state}", flush=True)
            last_state = state
        if state == "succeeded":
            return submission
        if state in {"retryable_failed", "terminal_failed", "cancelled"}:
            failure = job.get("failure") or {}
            raise RuntimeError(
                f"Smoke job {job_id} ended as {state}: "
                f"{failure.get('classification', 'unknown')} {failure.get('message', '')}".strip()
            )
        now = time.monotonic()
        if now >= deadline:
            raise RuntimeError(f"Timed out after {timeout_seconds}s waiting for smoke job {job_id}")
        if not state_changed and now >= next_progress_at:
            elapsed_seconds = int(now - started_at)
            print(
                f"{job_id}: still waiting ({state}, {elapsed_seconds}s elapsed)",
                flush=True,
            )
            while next_progress_at <= now:
                next_progress_at += progress_seconds
        time.sleep(poll_seconds)


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
        spec = youtube_transcription_spec(args.youtube_url)
        request_kind = "mlx-transcription-youtube-smoke"
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
    if kind in {"transcription", "transcription-http", "transcription-youtube"}:
        if not result.get("text") or not result.get("segments"):
            raise RuntimeError("Transcription smoke returned no text or segments")
        provenance = result.get("provenance", {})
        expected_handler = (
            TRANSCRIPTION_SMOKE_HANDLER
            if kind == "transcription"
            else (
                HTTP_TRANSCRIPTION_SMOKE_HANDLER
                if kind == "transcription-http"
                else YOUTUBE_TRANSCRIPTION_HANDLER
            )
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
        if kind == "transcription-youtube":
            acquisition = provenance.get("acquisition", {})
            if (
                acquisition.get("video_id") != spec["configuration"]["video_id"]
                or acquisition.get("canonical_url")
                != spec["configuration"]["canonical_url"]
                or acquisition.get("byte_length", 0) < 1
                or not re.fullmatch(r"[a-f0-9]{64}", acquisition.get("digest", ""))
            ):
                raise RuntimeError("YouTube transcription provenance has invalid media identity")
    print(json.dumps({
        "job_id": completed["job"]["job_id"],
        "run_id": completed["run"]["run_id"],
        "state": completed["job"]["state"],
        "artifact": completed["job"]["result"],
        "result": result,
    }, ensure_ascii=False, indent=2, sort_keys=True))
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
    youtube_transcription_submit = commands.add_parser(
        "submit-transcription-youtube",
        parents=[credentials],
        help="Submit MLX transcription of one public YouTube video",
        description=(
            "Submit one canonical YouTube video for bounded, temporary audio "
            "acquisition and macOS/MLX transcription."
        ),
    )
    youtube_transcription_submit.add_argument("youtube_url")
    youtube_transcription_submit.add_argument("--retention-days", type=int, default=7)
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
            "Run the complete single-video YouTube macOS/MLX transcription smoke",
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
        "smoke-transcription-youtube",
    }:
        return run_smoke_command(
            args,
            {
                "smoke-analysis": "analysis",
                "smoke-transcription": "transcription",
                "smoke-transcription-http": "transcription-http",
                "smoke-transcription-youtube": "transcription-youtube",
            }[args.queue_command],
        )

    control = operator_client(args.operator_token_source)
    if args.queue_command == "registry-status":
        result = control.post("/registry/get-active", {"environment": args.environment})
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
    if args.queue_command == "submit-transcription-youtube":
        spec = youtube_transcription_spec(args.youtube_url)
        result = submit_spec(control, request=ephemeral_request(
            "mlx-transcription-youtube",
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
