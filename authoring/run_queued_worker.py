#!/usr/bin/env python3
"""Run one already-approved queued authoring job."""

from __future__ import annotations

import json
import os

from queued_authoring import run_worker


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> int:
    job = run_worker(
        job_id=required("WATCHCRAFT_JOB_ID"),
        spec_sha256=required("WATCHCRAFT_JOB_SPEC_SHA256"),
        dispatch_generation=int(required("WATCHCRAFT_DISPATCH_GENERATION")),
        expected_revision=int(required("WATCHCRAFT_EXPECTED_REVISION")),
    )
    print(json.dumps({
        "job_id": job["job_id"],
        "state": job["state"],
        "revision": job["revision"],
        "artifact_sha256": job["result"]["digest"],
        "artifact_bytes": job["result"]["byte_length"],
        "artifact_kind": job["result"]["artifact_kind"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
