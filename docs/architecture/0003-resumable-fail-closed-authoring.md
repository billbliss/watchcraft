# ADR 0003: Resumable, fail-closed authoring

- Status: Accepted
- Date: 2026-08-28
- Amended: 2026-09-03

## Context

Collection authoring is a long-running pipeline that depends on external systems:
source sites, caption services, proxies, and AI models. A collection may contain
dozens of videos and thousands of topics, so restarting from zero after a transient
failure is expensive. At the same time, silently treating a partial run as complete
can produce a valid-looking manifest that omits videos or publishes unfinished topic
normalization.

The pipeline therefore needs two properties that can be in tension:

- completed work must survive interruptions and be reusable;
- incomplete work must not be mistaken for a publishable result.

## Decision

The automated collection-creation path is an ordered, resumable state machine:

1. import source metadata and transcripts;
2. analyze every selected source;
3. normalize topics, labels, families, and related-topic links;
4. validate and build the publishable collection manifest.

The initial implementation specializes the first phase as transcript generation or
import and the second phase as per-source analysis. This sequencing does not make a
transcript the queue's fundamental unit of work. Queued processing is expressed as a
generic authoring task that names, separately:

- the operation being performed, such as `generate`, `import`, `validate`, or
  `compile`;
- the versioned artifact kind being produced or consumed, initially `transcript` and
  later potentially chapters, shots, scenes, dialogue, speakers, music cues, topics,
  or another time-indexed annotation layer;
- immutable input and dependency references, including the source media asset and,
  when relevant, its edition and coordinate identity;
- the handler or generator identity, version, and material configuration; and
- the expected output schema and version.

Operation and artifact kind remain distinct because the same kind of artifact may be
generated, imported, corrected, or validated. Workers advertise the task kinds they
can handle and dispatch accepted tasks to typed handlers. The first worker may support
only transcript generation without putting transcript-specific fields or lifecycle
rules into the shared queue envelope.

Approval and idempotency bind to the complete task specification. Reuse therefore
depends on the operation, artifact kind and schema, source and coordinate identity,
handler version and material configuration, and the hashes of every input and
dependency. A successful task records an immutable, validated artifact reference in
the durable ledger; worker logs and temporary output are not authoritative results.
This generalization applies to authoring orchestration and does not require publishing
future annotation layers in the current collection schema. Whether an artifact holds
instant events, intervals, or a sampled or continuous signal is defined by that
artifact's output schema rather than by the queue lifecycle.

Each phase has an explicit completeness condition:

- An imported YouTube source has matching source metadata and a parseable transcript
  state whose `video` key identifies that source.
- An analyzed source has a parseable analysis artifact whose `video` key identifies
  the same source.
- Topic normalization is complete only when every raw topic has an assignment, every
  canonical topic has a valid unique display label and related-topic result, and
  `topic-normalization.json` has `status: "complete"`.
- A collection-created manifest is final only after all earlier conditions pass and
  schema validation succeeds.

Completeness is checked against the exact selected playlist IDs, after exclusions and
limits. File existence alone is not sufficient. A malformed file or an artifact that
belongs to another source is incomplete.

The pipeline is fail-closed at phase boundaries. Individual import attempts may be
collected so the run can preserve as much progress as possible, but any failed
selected video makes `collection create` exit nonzero before analysis begins. After
analysis, the selected source, transcript, and analysis sets are checked again before
normalization. The automated path does not rebuild the manifest until normalization
reaches `complete`. When updating an existing collection, the previous valid manifest
may remain in place while a new authoring run is incomplete.

Progress is written atomically and at the smallest useful recovery boundary:

- each completed task artifact is its own checkpoint; in the initial pipeline this
  means each source transcript and analysis;
- normalization assignments, display labels, and related-topic batches are saved
  incrementally;
- valid results from a partially invalid display-label batch are saved before the
  command exits;
- the checkpoint records the exact unresolved topics and rejection reasons.

Rerunning the same command is the normal recovery operation. Structurally complete
imports are reported as `cached`; newly completed imports are `added`; unsuccessful
imports are `failed` or `skipped` with a reason. `--force` is an explicit request to
discard normal cache behavior and regenerate work. Recovery must not require deleting
an entire collection workspace.

Display-label recovery may apply only conservative deterministic transformations after
repeated invalid model output. All labels must still satisfy length, word-count,
punctuation, and collection-wide uniqueness rules. Ambiguous cases remain failures
rather than accepting an arbitrary label.

Secrets are operational inputs, never collection content. Local authoring may load
`.env.local`, which is ignored by Git; explicitly exported shell variables take
precedence. API keys and other credentials must not be written to authoring state,
transcripts, analyses, manifests, logs, or committed examples.

Regression tests are required at every failure boundary. They cover partial imports,
cache validation, task dispatch by operation and artifact kind, dependency and output
schema validation, deferred manifest builds, partial normalization checkpoints,
deterministic-label validation, and successful resume behavior. Generated manifests
must also pass the canonical JSON Schema.

## Consequences

An incomplete workspace is a normal and recoverable state, not corruption. Commands
may return nonzero even after doing useful work; the error indicates that the
publishability boundary was not reached. Operators can inspect dry-run counts and
checkpoint status, fix the underlying cause, and rerun without repeating completed
phases.

The authoring implementation carries more validation and checkpoint bookkeeping, but
the resulting state is auditable: every selected source is accounted for, failures are
actionable, and publication is separated from partial generation. Standalone low-level
commands remain available for deliberate maintenance, but they do not weaken the
completion guarantees of `collection create`.

New derived artifact types require a typed handler, schema, validation rules, and
declared dependencies, but do not require a new queue lifecycle. This is deliberate
forward compatibility rather than a commitment to implement the broader film
annotation model in the instructional-video pipeline.
