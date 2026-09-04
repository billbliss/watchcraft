# ADR 0004: Authoring control, execution, and artifact planes

- Status: Accepted
- Date: 2026-09-03

## Context

ADR 0003 defines authoring as a resumable, fail-closed state machine whose tasks
produce versioned artifacts. It deliberately does not choose where that state runs,
where workers execute, or where large immutable inputs and results live.

The state-machine source of truth should retain the semantics of a versioned JSON
file: one coherent aggregate can be read, validated, compared, and atomically
replaced. It should not become a collection of relational fields whose meaning is
only recoverable through joins. It also should not create a stream of generated files
in the Watchcraft Git repository. Git remains the authority for source code and
deliberately published collection packages, not live queue state.

GitHub Actions is already Watchcraft's remote build executor and is a good fit for
bounded, reproducible authoring attempts. It is not a durable database or artifact
store: workflow runs are an execution record, while Actions artifacts and caches have
retention and lifecycle policies that make them unsuitable as authoring authority.

Some authoring jobs can run on an ephemeral hosted runner. Others may require a
machine with local media, private source material, or hardware-specific inference.
The execution contract must support both without changing the task model.

## Decision

Watchcraft separates authoring into three planes:

1. **Convex is the control plane.** It stores authoritative state-machine aggregates,
   validates transitions, binds approvals, issues leases, and reconciles dispatches.
2. **GitHub Actions is the execution plane.** A workflow run is one replaceable
   attempt to execute an already-authorized task on a hosted or isolated self-hosted
   worker.
3. **Cloudflare R2 is the artifact plane.** A private bucket stores immutable,
   content-addressed source snapshots, accepted inputs, and validated outputs too
   large or unsuitable for the control plane.

Git remains a fourth, deliberately separate publication plane. A successful
authoring run may prepare a collection package, but publication to Git requires an
explicit validated publication transition. Neither a successful worker exit nor an
R2 upload silently changes published collection content.

### Aggregate semantics

Each independently changing state machine is stored as one versioned JSON-like
Convex document rather than being normalized by field across SQL-style tables:

- an `AuthoringRun` represents a requested collection-level outcome and binds the
  source snapshot, plan, approval, task graph, completeness result, and publication
  result; and
- an `AuthoringJob` represents one leaseable task that produces or validates one
  typed artifact.

This split occurs at the concurrency boundary: jobs can be claimed, retried, and
completed independently. It is not a reason to fragment one job's specification or
lifecycle across tables. Large course maps, plans, transcripts, analyses, and task
graphs may be immutable R2 objects referenced by hash so the controlling document
remains bounded.

Every aggregate contains at least:

- `schema_version`, a stable ID, and a monotonically increasing `revision`;
- its immutable specification or a content-addressed reference to that
  specification;
- the current state and the command/request ID that produced it;
- creation and update timestamps recorded by the control plane;
- approval identity, decision, time, and the exact approved specification hash when
  approval is required;
- bounded attempt summaries and the active dispatch or lease, if any; and
- a typed success result or a classified failure.

An `AuthoringJob` specification contains the generic task fields established by ADR
0003: operation, artifact kind and schema, source/media/edition/coordinate identity,
immutable input and dependency references, handler identity and version, material
configuration, and expected output schema.

The job's semantic idempotency key is derived from the complete immutable task
specification. A change to an approved material field creates a new job specification
and requires approval again; it does not mutate the meaning of the existing job.

File-like storage does not by itself make operations idempotent. Every state-changing
command therefore supplies both a stable `command_id` and the `expected_revision`.
Convex mutations perform compare-and-swap validation and atomically either:

- apply the transition once and increment `revision`;
- return the previously recorded result for the same `command_id`; or
- reject a stale revision or incompatible transition without changing state.

An append-only event record may be written in the same Convex transaction for audit
and diagnostics. It is a projection of an accepted transition, not a second source of
current state and not something that must be replayed to understand the aggregate.

### Job lifecycle and leases

The initial job lifecycle is:

```text
proposed -> awaiting_approval -> ready -> dispatch_pending -> dispatched
                                 ^                                |
                                 |                                v
                          retryable_failed <- running <- claimed
                                                |
                                                +-> succeeded
                                                +-> terminal_failed

any nonterminal state -> cancelled
```

Transitions that are not meaningful for a task may be skipped, but they may not be
invented by a worker. In particular:

- approval binds an exact task-specification hash;
- dispatch increments a `dispatch_generation` and is safe to repeat;
- a worker claims a job with its ID, specification hash, dispatch generation, and a
  unique attempt ID;
- the claim mutation grants a time-bounded lease to exactly one attempt;
- a running worker heartbeats to extend that lease within configured limits;
- a completion mutation must match the active attempt and lease;
- a late or duplicate completion cannot overwrite a newer accepted result; and
- retry policy and backoff are control-plane decisions, not ad hoc worker behavior.

Cancellation is cooperative. It prevents new claims immediately and causes a worker
to stop at its next safe boundary. Artifacts uploaded by a cancelled, expired, or
superseded attempt are not authoritative merely because they exist.

### Dispatch and reconciliation

Dispatch crosses the Convex/GitHub boundary and cannot be one transaction. It is
therefore explicitly at-least-once:

1. A Convex mutation commits `dispatch_pending`, increments the dispatch generation,
   and schedules a dispatch action.
2. The action calls the GitHub `workflow_dispatch` API with only the job ID, expected
   specification hash, and dispatch generation.
3. The action records the returned workflow run ID and URL in the job aggregate.
4. The workflow claims the job before reading inputs or doing expensive work.
5. A scheduled reconciler re-dispatches requests left pending and makes expired
   leases eligible for retry according to policy.

Duplicate workflow runs are harmless because only one matching attempt can acquire
the lease. GitHub's run status is useful evidence, but Convex state is authoritative.
The first implementation may use a human-triggered `workflow_dispatch` with a job ID
before automatic dispatch and reconciliation are enabled; it must still use the same
claim and completion protocol.

### Worker contract

The workflow receives identifiers, not an embedded job description. A worker:

1. authenticates to a narrow Convex service endpoint;
2. claims the job and receives the immutable specification plus short-lived or
   narrowly scoped artifact access;
3. verifies every downloaded input's size and SHA-256 digest;
4. invokes the registered typed handler;
5. validates the output against the declared schema;
6. uploads the output under its content-derived R2 key; and
7. reports success with the artifact reference, or reports a classified failure.

The initial machine-to-machine authentication may be a high-entropy shared worker
secret stored independently in Convex deployment environment variables and GitHub
Actions secrets. Public Convex functions must compare it before reading or changing
job state. This credential is distinct from the Convex production deploy key: workers
must not receive a deploy or admin key. A stronger workload identity mechanism may
replace the shared secret without changing the job protocol.

Workers advertise supported `(operation, artifact_kind, schema_version,
handler_version)` tuples. Unsupported work fails before acquisition. Hosted and
self-hosted runners implement the same contract; runner selection is a dispatch
policy based on capability and data-access requirements.

Convex control-plane functions are TypeScript because that is Convex's native
execution model. The worker protocol is language-neutral JSON over authenticated HTTP,
and artifact bytes are exchanged through R2. Watchcraft's production discovery,
transcription, analysis, and compilation handlers remain Python unless a particular
handler has a reason to use another language. The initial TypeScript synthetic
transcript handler is only an infrastructure smoke harness, not a migration of the
authoring engine.

### Artifact identity and storage

The R2 bucket is private. Authoritative objects use canonical keys of the form:

```text
objects/sha256/<first-two-hex>/<remaining-hex>
```

An artifact reference records at least the algorithm, digest, byte length, media
type, logical artifact kind, schema version, and storage key. The digest is computed
over the exact stored bytes. Upload uses a create-if-absent operation where supported;
an existing object is reused only after its stored length and downloaded digest are
verified. Consumers never trust the key alone.

Temporary acquisitions and diagnostic bundles use a separate `staging/` prefix with
an explicit lifecycle policy. No lifecycle expiration applies to an object while an
authoritative run or job references it. Garbage collection is reachability-based and
must tolerate orphan uploads from failed attempts.

Source rights and privacy determine whether media itself may enter R2. A self-hosted
worker may consume a local media binding and upload only permitted derived artifacts.
Object keys and metadata must not contain source URLs, titles, user names, or other
sensitive values.

Browser access is not part of the initial design. The bucket therefore has no public
development URL, custom public domain, or CORS policy. If direct browser access is
later required, the control plane will issue narrowly scoped, short-lived presigned
URLs and the bucket will allow only the required origins, methods, and headers.

### GitHub Actions boundaries

An authoring workflow is dispatch-only and reads its implementation from a reviewed
revision. It does not run authoring work in response to `pull_request`. Workflow
permissions default to `contents: read`; additional permissions must be justified.
Secrets are scoped to an authoring environment or repository and are never passed in
workflow inputs, command-line arguments, logs, caches, or uploaded Actions artifacts.

Actions logs and artifacts are diagnostic and temporary. They are not accepted task
results, source snapshots, or the pipeline ledger. Diagnostic uploads must be
redacted, have short retention, and exclude source media, transcripts, analyses, and
credentials.

The Watchcraft repository is public. A persistent self-hosted runner, especially a
personal Mac with local media or credentials, must not be registered to this public
repository. Hardware-specific or private-data execution requires a separate private
operations repository with narrowly restricted workflow triggers and access, or a
different isolated worker substrate. That repository may check out the public
Watchcraft implementation at an explicitly approved commit.

### Secrets and configuration

Production configuration is divided by responsibility:

- Convex CI receives a least-privilege production deploy key used only to deploy
  control-plane code.
- Convex runtime environment variables receive any GitHub dispatch credential and a
  verifier for the worker service credential.
- The GitHub authoring environment receives the Convex deployment URL, the worker
  service credential, the R2 endpoint and bucket name, and bucket-scoped R2 S3
  credentials.
- Local development uses ignored `.env.local` files or interactive tooling. No
  production credential is committed or copied into collection packages.

Credential rotation must allow an overlap window or explicit drain of active jobs.
Revoking a credential does not alter the integrity of already content-addressed
artifacts.

## Initial implementation slice

The first vertical slice will:

1. define and validate versioned `AuthoringRun`, `AuthoringJob`, command, lease,
   failure, and artifact-reference schemas;
2. implement Convex mutations for create, approve, claim, heartbeat, succeed, fail,
   cancel, and retry using command IDs and expected revisions;
3. implement a private R2 adapter with hash verification and create-if-absent writes;
4. add a manually dispatched GitHub Actions workflow for one transcript-generation
   handler using the generic job envelope;
5. prove duplicate dispatch, duplicate completion, expired-lease recovery, orphan
   upload safety, and persistence across process restarts; and
6. leave automatic GitHub dispatch, the self-hosted Mac worker, and Git publication
   behind later explicit decisions.

The slice is complete only when the same submitted job can be interrupted and safely
resumed without duplicate authoritative results, and its validated result can be
resolved from Convex to exact R2 bytes by digest.

## Consequences

The design preserves file-like aggregate semantics while gaining atomic
compare-and-swap transitions, durable coordination, and queryability. Convex's
transaction model handles the few cross-document updates introduced by genuine
concurrency boundaries; it does not justify normalizing the domain model.

GitHub Actions can be replaced or supplemented without migrating authoritative state
or artifacts. R2 can contain orphan objects safely because existence does not confer
authority. Git stays quiet during ordinary processing and records only reviewed,
published outputs.

The system now depends on three hosted services and on explicit reconciliation at
their boundaries. Service credentials, cost limits, retention rules, monitoring, and
backups become operational responsibilities. The public repository also means local
hardware execution needs a private security boundary before it is enabled.

## Deferred decisions

- the user-facing queue and approval interface;
- automatic GitHub dispatch credentials (GitHub App versus a fine-grained token);
- private operations-repository ownership and self-hosted runner installation;
- artifact retention periods, storage quotas, backup policy, and garbage collection;
- publication automation and signing;
- multi-user identity and authorization beyond the initial operator/service model;
- whether later workloads need a dedicated queue or compute provider in addition to
  GitHub Actions; and
- the exact representation of collection-wide task graphs once real Khan course
  sizes have been measured against Convex document limits.

## References

- [Convex optimistic concurrency control and atomicity](https://docs.convex.dev/database/advanced/occ)
- [Convex limits](https://docs.convex.dev/production/state/limits)
- [Convex service authentication](https://docs.convex.dev/auth/overview#service-authentication)
- [Convex production deployment](https://docs.convex.dev/production/overview)
- [Cloudflare R2 consistency](https://developers.cloudflare.com/r2/reference/consistency/)
- [Cloudflare R2 S3 API compatibility](https://developers.cloudflare.com/r2/api/s3/api/)
- [GitHub workflow dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)
- [GitHub Actions artifact access and retention](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)
- [GitHub guidance for self-hosted runner security](https://docs.github.com/en/actions/reference/security/secure-use#hardening-for-self-hosted-runners)
