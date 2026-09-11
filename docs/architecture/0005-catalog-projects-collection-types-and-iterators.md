# ADR 0005: Catalog projects, collection types, and iterators

- Status: Proposed
- Date: 2026-09-06

## Context

The current authoring workspace and published `watchcraft.collection` package use "collection" for two different things: the durable intention to gather and shape material, and the compiled package installed by a reader. We need an authoring identity that survives discovery refreshes and publication revisions without complicating the simple act of defining a collection.

Current projects are primarily manually curated lists or YouTube playlists. Near-term additions include a Khan Academy course and a changing channel ranking such as YouTube "Popular videos". These differ along two practical axes: what kind of collection Watchcraft is building, and how Watchcraft enumerates its members.

The existing seventeen collections must remain usable and publishable without retranscription, analysis, topic normalization, or a content-revision change merely to adopt the new authoring model.

## Decision

The author-facing model has two extensibility points:

1. A `CollectionType` defines what the resulting collection means. It owns type-specific fields, validation, compilation rules, and reader presentation.
2. A `CollectionIterator` defines how to discover and enumerate the collection's members. It owns provider access, traversal, source normalization, observed metadata, and completeness reporting.

A `CatalogProject` is a durable, revisioned instance that chooses and configures one collection type and one iterator:

```text
CatalogProject
  ├── CollectionType: what the collection means
  └── CollectionIterator: where its members come from

CollectionIterator run
  └── immutable iterator snapshot

CollectionType + snapshot + processing artifacts
  └── published CollectionPackage
```

The schemas are:

- `packages/authoring-pipeline/project/catalog-project.schema.json`
- `packages/authoring-pipeline/project/collection-iterator-snapshot.schema.json`
- `packages/authoring-pipeline/project/project-processing-plan.schema.json`

The schemas validate the language-neutral envelopes. Registered collection types and iterators additionally validate their own versioned configuration.

## Catalog projects

A project contains stable `project_id` and `revision` fields, approved collection metadata, publication configuration, a configured collection type, and a configured iterator. Its essential shape is:

```json
{
  "kind": "watchcraft.catalog-project",
  "schema_version": 1,
  "project_id": "gdc-popular-videos",
  "revision": 1,
  "collection_type": {
    "id": "watchcraft.ranked-video-catalog",
    "version": "1",
    "configuration": {}
  },
  "iterator": {
    "id": "watchcraft.youtube-channel-popular",
    "version": "1",
    "configuration": {},
    "access_profile": "public-anonymous",
    "refresh": {
      "mode": "on-demand",
      "stale_while_refresh": true
    }
  }
}
```

`project_id` identifies the long-lived authoring project. `publication.collection_id` identifies its current published output. They may initially be equal, but they are not aliases: project history and unpublished revisions can exist independently of a published collection revision.

Catalog projects are revisioned JSON aggregates stored in Convex. Their semantics are defined by the JSON contract rather than the physical Convex tables, and they must be exportable as JSON.

## Collection types

A collection type is a registered, versioned capability. It defines:

- its custom configuration and metadata fields;
- structural invariants expected of iterator output;
- compilation rules for producing a collection package;
- reader navigation and presentation; and
- compatibility with iterator output shapes.

Reader presentation is deliberately part of the collection type rather than an independent registry. A type may expose presentation settings in its configuration and may support additional named views later, but project documents do not contain arbitrary JavaScript, HTML, or remote executable code.

The candidate v1 types are:

- `watchcraft.video-collection@1`: the conservative ordered-video type used by current collections;
- `watchcraft.course@1`: an ordered course hierarchy with explicit units, lessons, coverage, and placements; and
- `watchcraft.ranked-video-catalog@1`: membership and ordering relative to a recorded provider ranking.

## Collection iterators

A collection iterator is a registered, versioned class of discovery operation. It accepts validated configuration and returns a normalized iterator snapshot. Although the name evokes a programming-language iterator, an implementation may make paginated requests, perform a bounded crawl, checkpoint long work, coalesce concurrent requests, use cached observations, and report partial coverage.

An iterator owns source recognition, fetching, traversal, and normalization. It does not decide the collection's semantics or manufacture reader routes. It may recommend compatible collection types and propose metadata, but the project records the author's accepted choice.

The initial iterator families are:

- `watchcraft.youtube-playlist@1`: enumerate a playlist in its published order;
- `watchcraft.khan-course@1`: crawl the bounded Khan course outline and enumerate its curricular placements;
- `watchcraft.youtube-channel-popular@1`: observe a channel's provider-defined popular-video ranking; and
- a legacy import path for adopting existing workspaces without rediscovery.

The first schema permits one iterator per project. Multiple or composed iterators are deferred until a concrete project requires them.

### Iterator execution, progress, and resumption

One iterator invocation is one ordinary authoring job. The state machine does not create a durable state for every member and does not expand `running` into `processing_1`, `processing_2`, and so on. Instead, the active attempt may attach a bounded progress report to its lease heartbeat:

```json
{
  "phase": "enumerating",
  "completed": 12,
  "total": 42,
  "unit": "placements",
  "current": "Lesson 13: Color spaces"
}
```

The total may be absent while the iterator is still discovering the source. Within one phase and attempt, `completed` is monotonic and a known total is stable. Phase names and units are handler-defined, versioned behavior; likely phases include resolving the source, enumerating members, validating coverage, and storing the candidate snapshot. These reports exist for operator visibility and scheduling heuristics. They are not completion evidence and do not alter the job's lifecycle state.

At a safe boundary, such as after a page of provider results or a complete course unit, the iterator may upload a content-addressed `*-checkpoint` artifact and attach its reference and a monotonic sequence number to the same heartbeat. The checkpoint is bound to the exact job-specification hash. A replacement attempt may load the latest matching checkpoint, verify its bytes, and resume with the next stable provider cursor or placement rather than starting over. Repeating a checkpoint or enumerated member is idempotent because stable item and placement identities are deduplicated by the iterator.

Progress and checkpointing do not weaken fail-closed publication. A partial checkpoint is never an iterator snapshot, never satisfies the job's output contract, and never changes the project's accepted snapshot. Only after enumeration and coverage validation finish does the job publish one complete immutable candidate snapshot and enter `succeeded`. Cancellation, terminal failure, or exhausted retry leaves the previously accepted project revision untouched.

## Iterator snapshots

The output of an iterator is stored as an immutable, content-addressed `watchcraft.collection-iterator-snapshot`. This is pipeline bookkeeping and evidence, not a third author-facing abstraction.

A snapshot records:

- the project revision and iterator identity that produced it;
- source identity, canonical URL, and observed source metadata;
- hierarchy `nodes`, when applicable;
- deduplicated `items` and their media identities;
- ordered `placements` connecting items to nodes;
- expected, resolved, and classified unresolved coverage;
- metadata proposals and their source paths;
- observation time, retrieval provenance, and warnings; and
- a deterministic structural hash.

Items and placements remain separate because one item may appear more than once in a course, shelf, playlist, or future combined collection. A Khan item remains a Khan source item even when its resolved media identity has `type: "youtube"`.

`structure_hash` is SHA-256 over the canonical structural projection: source stable identity, node IDs/types/parents/positions, item and media identities, and placement IDs/items/parents/positions. It excludes observation time, volatile popularity metrics, metadata proposals, and retrieval diagnostics.

The project's iterator may exist before discovery without an `accepted_snapshot`. Approving an observation creates a new project revision whose iterator points to the exact R2 object key, digest, byte length, and schema identity of that snapshot. Refresh creates another immutable candidate; it never mutates the snapshot accepted by an existing revision.

Acceptance is a compare-and-swap transition against the current project revision. The candidate must be the successful output of an iterator job whose embedded project aggregate exactly equals that current revision. The operator retrieves and verifies the exact R2 bytes, then submits those bytes with the acceptance command; the control plane independently hashes them, compares them with the job's artifact reference, validates the snapshot and collection-type policy, and writes the next immutable project revision. A replayed command is idempotent, while a stale revision, changed project configuration, mismatched job, or changed byte fails closed.

## Project processing plans

Processing starts from the authoritative project revision and its accepted iterator snapshot, never from an unaccepted candidate or a fresh provider crawl. `watchcraft.planner.video-collection@1` reads and verifies those exact snapshot bytes, then emits an immutable, content-addressed `watchcraft.project-processing-plan` artifact. Planning is one ordinary portable-worker job and does not acquire media or dispatch the jobs it describes.

The planner creates one item plan per unique snapshot item, not per placement. Each item retains all of its placement IDs and has the same logical sequence: source metadata enrichment on the operator machine, local source-audio acquisition and staging, registered MLX transcription, then registered educational-video analysis. Topic normalization depends on every analysis, and collection compilation depends on normalization. A deferred collection-wide task may be realized later when its handler becomes active without changing the immutable plan or rerunning completed item work.

The plan fixes stable logical task IDs, handler and execution-profile identities, dependency edges, output roles, and conservative worker timeout bounds. It does not claim that a downstream job can be reused before its exact content-addressed input exists. Acquisition reuse is decided only after an audio digest is known; transcription reuse is decided against that audio digest and an exact job specification; analysis reuse is decided against the authoritative transcript digest and its exact job specification. Execution realizes those logical tasks into immutable `AuthoringJobSpec` records as their inputs become available and binds operator approval to that realized plan.

The executor can realize one selected item, the first bounded number of items, or the complete plan. It schedules item pipelines with explicitly bounded local concurrency; this concurrency limit controls local acquisition and remote dispatch together rather than creating an unbounded fan-out. Each pipeline run and worker-job ID is a deterministic function of the exact plan artifact digest, item ID, and task role. The durable run request records the source plan job, semantic plan hash, and logical task IDs, while the exact staged-audio digest remains part of the realized transcription specification. Before acquiring media, a retry looks up the deterministic run; if it exists, execution verifies its plan binding and resumes its current job states rather than creating another pipeline. Already complete pipelines are verified and reported without reacquiring their sources. A multi-item invocation waits for all selected work, preserves successful results when peers fail, and emits a compact aggregate summary so the same command can safely resume only unfinished work.

The first corpus-derived task is terminology resolution. It binds every immutable raw transcript and draft analysis from the exact plan, creates a deterministic corpus inventory, and partitions candidate terms into bounded map units containing compact collection context and only relevant timed transcript evidence. The initial executor runs those units sequentially inside one leased worker and persists every completed batch as an immutable specification-bound checkpoint; a replacement attempt resumes after the last valid batch instead of repeating successful model calls. The batch shape permits later promotion to independently scheduled child jobs without changing the aggregate contract. A deterministic reducer merges compatible proposals and emits `watchcraft.terminology-resolution@1`. Batch term and character bounds are material approved configuration, and a context-limit response is terminal for that specification rather than retryable. The artifact records proposed canonical terms, display forms, alternatives, affected items, evidence, confidence, and disposition. Only high-confidence orthographic changes without alternatives are marked `automatic-safe`; domain corrections and possible acoustic confusions remain `needs-review`. Raw transcripts and draft analyses are never mutated. This first slice creates the durable inference and review boundary; applying an accepted resolution to derived transcripts and selectively regenerating affected analyses is a subsequent registered transition.

Terminology resolution is deliberately useful outside instructional collections. It estimates a term from acoustic evidence, local linguistic context, project/domain priors, and corpus repetition without pretending those signals prove what was literally spoken. The same artifact pattern can resolve character names, fictional vocabulary, locations, and technical film language while preserving the raw timed observation and its work/edition/media coordinates.

Topic normalization follows draft-analysis terminology resolution. The operator resolves every deterministic item-analysis job from the exact plan, verifies that it succeeded under that plan and project revision, and submits one normalization job whose approval binds every immutable analysis artifact. Capability-registry artifact contracts may declare bounded cardinality for this fan-in; the topic normalizer accepts one through ten thousand `watchcraft.video-analysis@2` dependencies rather than hiding a mutable list of references in configuration. The OpenAI worker executes the existing topic-family, assignment, compact-label, and related-topic logic and emits an immutable `watchcraft.topic-normalization@1` artifact with the complete analysis set and plan identity in its provenance. Its deterministic collection-task identity provides the same safe lookup and resumption behavior as item processing. Until resolution application is implemented, normalization continues to consume the original draft analyses rather than silently applying proposed terminology.

Collection compilation is the second realized collection-wide task. The portable compiler binds the exact processing plan and accepted iterator snapshot, every successful transcript and analysis, and the completed normalization artifact. It executes the existing schema-v4 collection compiler, using source-observed item titles as authoritative display titles and transcripts only to recover topic-to-chapter mappings, and emits an immutable `watchcraft.collection-compilation@1` candidate. Analysis-generated titles remain descriptive analysis metadata and are only a compatibility fallback when an older source record has no title. The candidate contains a validated `watchcraft.collection` manifest and content-addressed references for each analysis resource needed to materialize the package. Transcript artifacts remain provenance-bound compilation inputs but are not publication resources. Compilation does not update Git, advance a published revision, or make the candidate visible to readers; review and publication remain an explicit later transition against the current package.

Materialization is an operator-local projection of one successful compilation into a new review directory. It verifies the immutable bundle and every referenced analysis object, advances the candidate revision only when its schema-v4 content hash differs from the explicitly selected published baseline, validates the complete projected package, and produces a scoped Git-readable diff. Materialization refuses existing output paths and does not mutate the published workspace. The resulting directory is still a review candidate; making it visible to readers requires a distinct publication transition.

Planning also produces a deterministic preflight estimate before processing approval. The estimator walks the complete intended task graph—including deferred terminology resolution, topic normalization, and compilation—without acquiring media or invoking an AI model. Its immutable policy records pricing inputs, runtime coefficients, assumed concurrency, and a policy version. The plan reports expected and conservative elapsed-time bounds, expected and conservative marginal cost, a per-model cost breakdown, confidence, unknown source duration, and exclusions. The estimate is part of the plan hash, so approval binds the exact work and the estimate shown to the operator.

The first policy is deliberately conservative and low-confidence. It uses accepted-snapshot media durations, empirical handler timing, and estimated model token quantities; it excludes queue contention and cannot promise reuse before exact input digests exist. GitHub Actions cost is explicitly conditioned on the repository and runner billing class, while R2 and Convex remain unpriced until account usage and free-tier consumption are known. Workers should record actual model token usage as well as phase timing so later policy versions can compare estimated and actual outcomes without consulting workflow logs. Estimation itself must not invoke a paid model merely to predict model cost.

## Metadata observation and approval

Iterators capture useful surrounding context while enumerating members, including course, unit, lesson, playlist, channel, shelf, and item-page metadata. Observed titles, descriptions, publisher identities, canonical URLs, artwork, attribution, licenses, provider IDs, published dates, chapters, ranking observations, and parent relationships belong in the iterator snapshot.

The snapshot may propose collection metadata with a source path and confidence. Accepted values live in the project, and `metadata_basis` records whether each value is editorial, copied from an iterator snapshot, generated, or imported from a legacy workspace. Refreshing an iterator may propose a new value but never silently overwrites approved project metadata.

## Storage and lifecycle

Catalog projects are stored as revisioned JSON aggregates in Convex. Iterator snapshots, plans, transcripts, analyses, normalization results, and compilation results are content-addressed objects in R2. Reviewed collection packages remain publication artifacts, currently stored in Git.

A pipeline run binds an exact `(project_id, revision)`, which in turn binds the accepted iterator snapshot. Publishing creates a new collection revision only when compiled package content changes.

## Adoption of current collections

Each of the seventeen legacy `watchcraft-authoring.json` workspaces can be imported as a CatalogProject without changing its published collection. Ordinary playlist and curated-list collections use `watchcraft.video-collection@1`; the Marc Adamus hierarchy uses the reusable `watchcraft.grouped-video-collection@1`. Existing source enumeration becomes an iterator snapshot, while existing transcripts, analyses, normalization results, and published packages remain authoritative.

Migration freezes the already-published membership rather than refreshing an external provider. The CLI validates the entire selected set before writing, stores each frozen snapshot in the immutable R2 object namespace, binds that exact digest into the initial project aggregate, and imports the project into Convex. An existing project ID is skipped and is never rewritten by migration; this lets newly authored projects and partially completed migration batches coexist safely. Repeating a migration is idempotent because the snapshot bytes and import command identity are content-derived.

| Existing field or artifact | Adopted representation |
| --- | --- |
| `collection.collection_id` | project ID and publication collection ID |
| collection title, description, publisher | approved project metadata with `legacy-import` or editorial basis |
| `collection.source` | iterator configuration |
| `sources` video records | snapshot items and ordered placements |
| `position` | placement position |
| explicit source exclusions | iterator selection configuration and classified exclusion records |
| caption/audio/embedding exclusions | downstream processing policy and classified exclusion records |
| transcript files | existing authoritative transcription inputs |
| analysis files | existing authoritative analysis inputs |
| `topic-normalization.json` | existing normalization input to compilation |
| `collection.json` | unchanged published collection package |

Adoption must preserve collection IDs, ordering, exclusions, analysis content, topic IDs, package revision, and content hash. It is an envelope around existing work, not regeneration.

The representative current design is shown in:

- `project/examples/current-playlist.project.json`
- `project/examples/current-playlist.snapshot.json`

## Candidate v1: Khan Academy course

The Khan candidate combines `watchcraft.course@1` with `watchcraft.khan-course@1`. The collection type owns course semantics, hierarchy requirements, completion rules, and the course-oriented reader UI. The iterator owns the Khan URL, bounded crawl, provider IDs, hierarchy normalization, and completeness observation.

The Khan course outline is the completeness authority. YouTube playlists may be hints or cross-checks, and YouTube may provide the resolved media, but neither changes the source identity from Khan Academy. The snapshot preserves ordered course, unit, and lesson nodes; deduplicated items; separate curricular placements; attribution; and coverage.

The example deliberately places one video in two lessons to demonstrate that item identity and curricular placement are independent:

- `project/examples/khan-course.project.json`
- `project/examples/khan-course.snapshot.json`

## Candidate v1: YouTube channel popular videos

The channel candidate combines `watchcraft.ranked-video-catalog@1` with `watchcraft.youtube-channel-popular@1`. The collection type owns snapshot-relative ranking semantics and the ranked-gallery reader UI. The iterator owns channel discovery and observation of YouTube's provider-defined popular order.

"Popular" is a provider query, not a stable playlist and not necessarily a simple sort by displayed view count. The iterator snapshot freezes exact membership, order, access profile, and observation time. Volatile metrics may explain an observation but do not replace ordered placements as authority. Refresh proposes a new snapshot and project revision; the published collection remains active until the changes are approved.

The example uses symbolic video IDs because it illustrates the contract rather than claiming to be a current crawl of the pictured channel:

- `project/examples/youtube-popular.project.json`
- `project/examples/youtube-popular.snapshot.json`

## Registration and compatibility

Collection types and iterators are registered capabilities. A type registration provides its configuration validator, snapshot-shape requirements, compiler, and reader implementation. An iterator registration provides its configuration validator, output contract, discovery implementation, and execution requirements.

The first implementation keeps a versioned static registry in the authoring-pipeline package. This establishes typed identities, configuration validation, output capabilities, and compatibility checks without prematurely choosing the persistent registry administration model.

Compatibility is checked explicitly. For example, the course type requires hierarchical nodes and curricular placements, while a flat playlist iterator would need either to provide that shape or be rejected for that project. This check is a seam between the two abstractions, not a third abstraction exposed to authors.

Legacy authored membership is represented by the provider-neutral `watchcraft.explicit-membership@1` iterator. Its configuration preserves stable items, placements, and optional group nodes without rediscovering or reprocessing media. A flat list is compatible with `watchcraft.video-collection@1`; a preserved authored hierarchy uses the reusable `watchcraft.grouped-video-collection@1` type. Media identities may describe YouTube or local-file assets, but portable project state never embeds machine-specific local paths; those remain private installation bindings. This allows the Marc Adamus collection to preserve its existing groups while ordinary curated lists remain flat, with neither case becoming a publisher-specific type.

The first executable implementation is `watchcraft.youtube-playlist@1`, registered as the `watchcraft.iterator.youtube-playlist@1` authoring handler on the portable Python worker. It reuses the existing source-only playlist discovery behavior, emits an immutable candidate snapshot, reports placement progress through the generic worker context, and checkpoints every ten source entries. This establishes the execution seam before Khan course and channel-ranking adapters are added.

The first project planner is registered as `watchcraft.planner.video-collection@1` on the same portable worker. It supports accepted snapshots whose items resolve to YouTube media and records operator-local acquisition separately from GitHub-hosted transcription and analysis. Adding another iterator does not require changing this planner when it produces the same compatible video-item contract.

Catalog project persistence and candidate acceptance are implemented in the Convex control plane. `project-import` creates the initial immutable revision, `project-status` reads the current aggregate, `project-history` lists its revision transitions, and `project-accept-snapshot` verifies a succeeded iterator artifact and advances the project exactly once. `iterate-project` accepts either a local project document or an imported project ID, so refreshes use the authoritative stored revision.

## Validation beyond JSON Schema

Application validation must additionally prove that:

- project revisions are compare-and-swap transitions;
- accepted-snapshot byte lengths, digests, and content-addressed keys match the bytes;
- iterator identity in the snapshot matches the configured project iterator;
- metadata-basis snapshot digests match the accepted snapshot;
- exactly one node is the snapshot root, node parents exist, and the graph is acyclic;
- node sibling and placement positions are positive and unambiguous;
- item, node, placement, and media identities are unique in their scopes;
- every placement references an existing item and node;
- coverage arithmetic and collection-type policy are satisfied;
- structure hashes match canonical content; and
- the selected collection type and iterator are compatible registered capabilities.

## Consequences

The model has one obvious authoring object and two understandable plug-in points. Playlist fan-out becomes an iterator implementation rather than the definition of a collection. Khan and ranked-channel projects can add source-specific discovery and type-specific UI without contaminating the generic video model. The immutable snapshot still supplies the auditability, idempotence, approval binding, and reproducibility required by the queued pipeline.

## Deferred decisions

- composed or supplemental iterators;
- promotion between collection types;
- independently distributed or signed third-party collection types;
- exact collection-type and iterator registry storage APIs;
- merge policy if multiple iterators are introduced; and
- automatic versus explicit approval thresholds for ranked-source refreshes.
