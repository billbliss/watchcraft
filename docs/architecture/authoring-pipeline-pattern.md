# Authoring pipeline pattern

- Document type: Architecture brief
- Status: Describes the in-progress Watchcraft implementation
- Date: 2026-09-07

## Purpose

This brief extracts the reusable architecture of Watchcraft's authoring pipeline so another product, especially Filmcraft, can adopt the pattern without first reconstructing it from the detailed ADR history. It is an overview, not a new architectural decision. The linked ADRs and code remain authoritative when implementation detail matters.

The pattern coordinates long-running, expensive, and sometimes hardware-specific processing while preserving four properties:

- work can resume after interruption without repeating valid completed work;
- approval binds the exact work that will run;
- duplicated dispatch or late workers cannot corrupt authoritative state; and
- partial output cannot be mistaken for a publishable result.

The pipeline is artifact-oriented rather than transcription-oriented. A job may generate, import, validate, or compile any versioned artifact kind. Watchcraft currently produces transcripts, educational analyses, normalized topics, and collection packages. Filmcraft could use the same lifecycle for shots, scenes, dialogue, speakers, characters, music cues, evidence, corrections, or other time-indexed annotation layers.

Terminology resolution is an independently versioned processing layer rather than an in-place transcript edit. It combines raw timed text, source context, corpus repetition, and domain or entity priors into explicit resolution proposals with alternatives, confidence, evidence, and review disposition. Candidate terms are partitioned into deterministic, context-bounded map units and their validated proposals are reduced into one corpus artifact; small corpora may execute those units sequentially inside one leased worker while preserving a future child-job boundary. Raw observations remain immutable. Accepted resolution artifacts may later produce a resolved transcript view and selectively invalidate dependent analyses. This pattern applies equally to instructional vocabulary and to film dialogue, names, fictional terms, locations, credits, and edition-specific evidence.

## Pattern at a glance

```text
Domain request or project
          │
          ▼
   immutable run plan ───── approval
          │
          ▼
  dependency graph of typed jobs
          │
          ▼
 capability registry resolves handler + execution profile
          │
          ▼
 replaceable leased worker attempts
          │
          ▼
 validated, content-addressed artifacts
          │
          ▼
 explicit completeness and publication transition
```

The durable records describe what should happen and what has been accepted. Workers are replaceable attempts that execute those records; they are not the source of truth.

## Four planes

| Plane | Responsibility | Current Watchcraft choice |
| --- | --- | --- |
| Control | Authoritative run and job aggregates, transitions, approvals, leases, and routing policy | Convex |
| Execution | Replaceable attempts that claim and perform authorized jobs | GitHub Actions hosted runners |
| Artifact | Immutable inputs and results addressed by content digest | Private Cloudflare R2 bucket |
| Publication | Deliberate release of validated domain output | Collection packages in Git |

These responsibilities are architectural. The named products are replaceable implementation choices. In particular, GitHub Actions is an executor rather than a database, and an artifact upload is not a publication.

## Core contracts

### Domain request or project

The domain layer states the intended outcome. In Watchcraft this is moving toward a `CatalogProject` containing a collection type and collection iterator. Filmcraft may instead have a film project binding a work, edition, media asset, coordinate system, requested annotation layers, and publication target.

The domain object is not required to know how a worker runs. It supplies stable identity, author intent, approved configuration, and the source facts needed to produce a run plan.

### AuthoringRun

An `AuthoringRun` represents one requested domain-level outcome. It binds:

- the request and source snapshot;
- an immutable plan and approval digest;
- the set of jobs required by that plan;
- the run's revision and state; and
- the final completeness outcome.

The run is the coordination boundary for the whole result. It becomes complete only when its plan's domain-specific completeness rules pass; the mere success of one or more jobs is insufficient.

### AuthoringJob

An `AuthoringJob` is the independently leaseable concurrency boundary. Its immutable specification names:

- an operation such as `generate`, `import`, `validate`, or `compile`;
- the artifact kind and output schema;
- stable source, media asset, edition, and coordinate identities as applicable;
- immutable inputs and typed dependencies;
- the handler identity and version;
- material configuration; and
- the capability-registry resolution used for routing.

Operation and artifact kind are separate. A transcript, scene layer, or correction set might be generated, imported, or validated without changing the queue lifecycle.

The canonical SHA-256 of the complete specification is both its semantic idempotency key and the object to which approval is bound. Changing a material input, handler version, configuration value, schema, or dependency produces different work.

### ArtifactReference

Large inputs and results travel by reference rather than being embedded in control-plane records. An artifact reference includes:

- storage class and content-addressed key;
- SHA-256 digest and exact byte length;
- media type and artifact kind;
- output schema identity and version; and
- optional expiration metadata for staged inputs.

A key alone is never proof that stored bytes are correct. Readers and workers verify the digest and length, and the control plane accepts a result only when its kind and schema match the approved job specification.

### Capability registry

The versioned registry separates requested processing from executable implementations. A handler definition declares accepted inputs and dependencies, produced artifact contract, retry policy, lease class, and required execution profile. An execution profile declares dispatcher, operating system, architecture, dependency and cache classes, timeout and heartbeat policy, data-access classification, and named secret capabilities.

The active registry is control-plane data rather than an opaque conditional inside an orchestration function. A job copies the exact resolved handler, profile, registry version, and registry digest into its approved specification. Later registry changes cannot reinterpret already approved work.

Workers retain a reviewed local mapping from handler identities to executable code. Registry data can select known code, but it cannot inject commands or create executable behavior.

### Worker attempt

A worker receives identifiers, claims the job, and receives the immutable specification only after a successful claim. It then:

1. verifies the approved handler and execution profile against local capabilities;
2. verifies every downloaded input's digest and length;
3. runs the typed handler;
4. validates the output schema;
5. uploads the exact output under its content-derived key; and
6. reports either the artifact reference or a classified failure.

Logs and temporary files are diagnostic evidence, not authoritative output. Hosted, self-hosted, local, TypeScript, and Python workers can implement the same language-neutral protocol.

## State and concurrency invariants

### File-like aggregate semantics

Each run and job is one coherent, revisioned JSON-like aggregate. The aggregate should be readable and valid without replaying events or joining relational fragments. This preserves the useful semantics of a state file while allowing transactional mutation in the control plane.

Every state-changing command carries:

- a stable `command_id`, making retries idempotent; and
- `expected_revision`, making concurrent updates compare-and-swap operations.

The control plane atomically applies a command once, returns its previously accepted result, or rejects it as stale or incompatible.

### Job lifecycle

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

Approval binds the immutable specification hash. Dispatch increments a generation. A worker claim must match the job ID, specification hash, and dispatch generation.

### Leases and duplicate dispatch

Dispatch crosses service boundaries and is intentionally at-least-once. Duplicate workflow runs are harmless because only one matching attempt can acquire the active lease. The attempt heartbeats while working; completion is accepted only from the active, unexpired lease.

A late, duplicate, expired, cancelled, or superseded worker may leave an orphaned immutable object, but it cannot replace the authoritative result. Retry and backoff remain control-plane decisions rather than ad hoc worker behavior.

### Fail-closed completion

Each phase and domain output has an explicit completeness condition. Structural file existence is not enough. A result must belong to the expected source, validate against the expected schema, cover the planned input set, and satisfy any cross-artifact invariants.

Completed artifacts are checkpoints and may be reused. A long-running job may also
publish an immutable, specification-bound checkpoint at a safe boundary and expose
bounded progress such as `enumerating: 12 of 42 placements`. These progress reports
remain details of the current attempt rather than additional job states. A retry may
resume from the latest valid checkpoint, but partial work is never treated as a
successful result. Incomplete work is a normal recoverable state, but it never crosses
the publication boundary. A previous valid publication may remain active while a
replacement run is incomplete.

## What is reusable and what is incidental

### Reusable invariants

- immutable and canonically hashed job specifications;
- approval bound to exact specifications and plans;
- revisioned aggregate state with idempotent commands;
- at-least-once dispatch plus lease-protected authoritative completion;
- typed, schema-validated, content-addressed artifacts;
- explicit dependency graphs and completeness conditions;
- versioned capability and execution routing;
- classified failures and policy-controlled retries;
- replaceable workers with no authority derived from local output alone; and
- an explicit publication transition.

### Current choices that Filmcraft need not copy

- Convex, GitHub Actions, R2, and Git as the particular four services;
- TypeScript for the Convex control plane and Python for production handlers;
- macOS MLX and Linux portable execution profiles;
- Keychain-backed bootstrap credentials;
- YouTube acquisition and staged-audio mechanics;
- collection types, collection iterators, topic normalization, and collection manifests; and
- the current CLI command names and smoke fixtures.

Filmcraft may initially reuse all the current infrastructure because it exists and works. It should treat those choices as adapters around the contracts, not bake them into artifact semantics.

## Watchcraft-to-Filmcraft mapping

| Watchcraft concept | Filmcraft analogue |
| --- | --- |
| Catalog project | Film analysis or annotation project |
| Collection source snapshot | Work, edition, media-asset, and coordinate snapshot |
| Video media identity | Edition-specific media asset identity |
| Transcript artifact | Dialogue or transcript annotation layer |
| Educational analysis | Scene, shot, speaker, character, music, or style analysis layer |
| Topic normalization | Entity resolution and cross-layer normalization |
| Collection compilation | Versioned annotation-bundle compilation |
| Collection package publication | Publication of a reviewed film knowledge package |

Filmcraft's artifact schemas can represent instant events, intervals, or sampled and continuous signals without changing the orchestration lifecycle. Time-indexed artifacts should bind work, edition, media asset, and coordinate identity; use integer presentation-time ticks with an explicit timescale; and carry provenance, evidence, confidence, and entity relations appropriate to the layer. Optional geometry should identify its coordinate system explicitly.

The same media may support multiple independently authored and versioned layers. Their job specifications and artifact references keep those layers independent while typed dependencies allow later jobs to consume earlier results.

## Adding a new processing capability

A new Watchcraft or Filmcraft capability should require this sequence:

1. Define the artifact kind, schema, identity rules, and completeness conditions.
2. Define the handler's operation, immutable inputs, typed dependencies, output contract, material configuration, and failure classifications.
3. Implement the typed handler and output validation in an appropriate worker runtime.
4. Register the handler and its execution profile as a new immutable registry version.
5. Make the planner produce the exact job specification and dependency edges.
6. Approve the plan and specification digests before dispatch.
7. Verify claim, input integrity, output schema, content-addressed upload, and completion behavior.
8. Add regression tests for success, interruption, replay, stale completion, invalid output, and incomplete publication.

Adding an artifact kind or handler should not require a new queue lifecycle. A new lifecycle is justified only when its concurrency or authority boundary is genuinely different.

## Minimal reading and implementation references

Read this brief first. Use the following only when more detail is needed:

- [ADR 0003: Resumable, fail-closed authoring](0003-resumable-fail-closed-authoring.md) defines artifact-oriented jobs, checkpointing, phase completeness, and recovery.
- [ADR 0004: Authoring control, execution, and artifact planes](0004-authoring-control-execution-and-artifact-planes.md) defines aggregate state, dispatch, leases, worker protocol, registry, storage, secrets, and current operational choices.
- [ADR 0005: Catalog projects, collection types, and iterators](0005-catalog-projects-collection-types-and-iterators.md) is a Watchcraft-specific example of keeping domain semantics separate from discovery mechanics.
- [`contracts.ts`](../../packages/authoring-pipeline/src/contracts.ts) is the canonical current wire-model implementation.
- [`state-machine.ts`](../../packages/authoring-pipeline/src/state-machine.ts) implements job transition and lease invariants.
- [`run-state-machine.ts`](../../packages/authoring-pipeline/src/run-state-machine.ts) implements run-level planning, approval, and completion transitions.
- [`registry.ts`](../../packages/authoring-pipeline/src/registry.ts) validates and resolves handler and execution capabilities.
- [`worker.ts`](../../packages/authoring-pipeline/src/worker.ts) implements the replaceable worker contract.

## Current maturity

The control, artifact, execution, registry, portable-analysis, Apple-silicon transcription, staged-media, composed transcription-and-analysis, status, result retrieval, smoke, and cleanup paths have working implementations and regression coverage. The generalized catalog model now has runtime contract validation and a static versioned registry; project persistence, iterator execution, and migration remain proposed. Automatic dispatch reconciliation, richer identity, stronger workload authentication, and production-scale operational policy remain evolutionary work rather than prerequisites for reusing the core pattern.
