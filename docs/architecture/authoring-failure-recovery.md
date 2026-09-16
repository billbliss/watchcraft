# Diagnosing and recovering authoring failures

A collection can finish every video and still fail during terminology resolution,
topic organization, compilation, or preview publication. Check the stage before
retrying. The portal's Diagnostics expander provides the execution ID, failed job
ID, worker log link, and a read-only CLI command.

## Read the underlying failure

Run the command shown in Diagnostics (`watchcraft-author queue status` with the
job ID and operator credentials). Inspect its failure classification, message,
attempt count, and last worker progress. A portal retry can resume an existing
job without creating another worker attempt, so these counts are different.

A transient dependency fetch or provider failure can be retried within its policy.
A `terminal_failed` job cannot be resumed unchanged. Repeatedly clicking Retry
will not repair an invalid input or an incompatible worker. Preserve the failed
job for diagnosis, fix the cause, then create a replacement with a new handler
version or corrected input binding. Never edit an immutable artifact in place.
Completed video jobs are reusable; do not submit the whole collection again.

## Jeanne Bliss topic organization

The failed normalization job `636c7028-6fff-5f55-8901-4b810c95778d` rejected video
`dgxtwDDbTAc` because its analysis had no sections. The 1,482-character transcript
was short enough for the analysis generator to accept an empty chapter list.
It still had 16 topics. The normalizer and collection builder already support
topic-only analyses; the normalization worker's extra non-empty chapter check
was inconsistent with that contract.

Normalizer version 10 accepts an empty sections list while continuing to reject
missing/non-list sections, empty/non-list topics, mismatched video identity,
wrong schema versions, and invalid provenance. Validation errors name the field.
The new handler version produces a distinct deterministic normalization job,
leaving the old terminal failure intact and reusing the 104 completed analyses
and completed terminology resolution.

Deployment order: publish the targeted worker code to main, publish/activate the
updated capability registry, then restart the idle portal worker and retry this
stage once. Hosted jobs currently check out main, so changing only the local
Python file is insufficient. Do not activate the new registry before the worker
code is available. Verify the new normalization succeeds before proceeding to
compilation and preview testing.

Local acquisition failures additionally include a diagnostic ID identifying an
owner-readable, Git-ignored log in `authoring/diagnostics/`. Those logs contain
sanitized tool output and expire after 30 days when another failure is recorded.
They are separate from hosted worker logs and cannot reconstruct older failures.
