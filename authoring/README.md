# Authoring

Watchcraft authoring is a Python toolchain that turns source media, transcripts,
and analysis into versioned collection packages. Authors may clone this repository
and run the tools locally; authoring is not required by the reader application.

This directory contains the current command-line implementation. Its collection
compiler writes the portable collection manifest and an optional CSV export;
all presentation and local-library access belong to the React readers and the
Tauri desktop adapter.

The authoring output must validate against `packages/catalog-schema` and must not
contain absolute paths to an author's media files.

## YouTube collection workspace

Real collections belong in a separate content repository rather than this
application repository. A source-neutral workspace is identified by
`watchcraft-authoring.json`; its public manifest and analysis are written directly
into that directory, while generated transcripts remain private authoring inputs.

```bash
python watchcraft_author.py youtube add \
  --workspace ~/dev/watchcraft-collections/collections/premiere-pro-ai-tools \
  --collection-title "Premiere Pro AI Tools" \
  --position 1 \
  "https://www.youtube.com/watch?v=PjObX9XQvgI"

python watchcraft_author.py process \
  --workspace ~/dev/watchcraft-collections/collections/premiere-pro-ai-tools
```

Import every visible video from a public or unlisted playlist. Watchcraft streams
each video's audio into the local Whisper model without retaining the media:

```bash
python watchcraft_author.py youtube add \
  --workspace ~/dev/watchcraft-collections/collections/premiere-pro-course \
  --collection-title "Premiere Pro Course" \
  --playlist "https://www.youtube.com/playlist?list=PLAYLIST_ID"

python watchcraft_author.py process \
  --workspace ~/dev/watchcraft-collections/collections/premiere-pro-course
```

Playlist imports retain YouTube ordering and are resumable. Private, unavailable,
or otherwise inaccessible videos are reported without discarding completed work.
Use `--position N` to place the first playlist video at a position other than one.
The `--playlist` value may be either a playlist URL or a YouTube watch URL containing
both `v=` and `list=` parameters, such as the URL copied while playing the first video.
Watchcraft uses the `list=` value and imports the playlist from its actual first entry.

`youtube add` retrieves public metadata and generates a private transcript from a
streamed audio source. `process` analyzes unfinished sources, repairs an
underspecified timeline, validates the resulting `collection.json` against the
canonical schema, and preserves the collection revision when content is unchanged.
Publisher-authored timestamps in the YouTube description are authoritative when
present: Watchcraft keeps those chapter titles and boundaries while enriching them
with its generated descriptions and concepts. AI-generated chapters are the fallback.
Use `--position N` when a collection has an intentional lesson sequence; the
compiler retains that ordering across subsequent rebuilds.

Topic normalization also generates compact, unique UI labels of two to five
words and no more than 32 characters. The original analytical phrase remains a
searchable alias, so shortening a label does not change topic identity or chapter
mapping. Regenerate only these labels with
`normalize_topics.py --rebuild-display-labels`.

The content repository should ignore `**/transcripts/`, downloaded media, caches,
credentials, and other private working material. Transcripts are private authoring
inputs used to produce analysis; published collection items omit transcript references.

### YouTube transcript sources

The default `audio` source streams the best available audio through `yt-dlp` and
FFmpeg, detects spoken ranges locally with Silero VAD, and sends only those original
timeline ranges to MLX Whisper. This avoids spending transcription time on music
and preserves timestamps across mixed speech/music videos. Videos with less than
three seconds of detected speech receive a resumable `audio_exclusions` entry.
Neither the audio nor video is retained. Use YouTube's caption track explicitly
when desired:

```bash
python watchcraft_author.py youtube add \
  --transcript-source captions \
  --workspace ~/dev/watchcraft-collections/collections/example-course \
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

The standalone comparison tool measures a locally generated transcript against an
existing or freshly retrieved caption transcript:

```bash
python poc_youtube_audio_transcript.py \
  --workspace ~/dev/watchcraft-collections/collections/example-course \
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

The Python 3.13 authoring environment installs a pinned current `yt-dlp` release
from `requirements.txt`, and the importer invokes that module with the same Python
interpreter instead of relying on a system copy. It explicitly makes the repository's
Node.js 22+ prerequisite available to `yt-dlp` for YouTube JavaScript challenges.
FFmpeg remains a host prerequisite. Comparison reports and all transcripts are
private authoring outputs. Pass
`--yt-dlp /path/to/yt-dlp` to the comparison tool only when deliberately testing
another executable.

When a workspace lives at `collections/<slug>/` in a content repository whose
`site/collections.json` defines `base_url`, every successful build adds or updates
the collection in that website directory. Existing hand-edited directory
descriptions are preserved. Pass `--unlisted` to `youtube add` or `collection
create` to publish a collection by URL without advertising it; the choice is
stored in `watchcraft-authoring.json` and respected by later builds.

For a listed `collection create`, the authoring tool also creates the public-directory
description and chooses its category after import, using the topic-normalization model.
When YouTube supplies a playlist description, Watchcraft uses that text verbatim;
otherwise it generates a description from the available publisher and video titles.
Existing hand-written directory descriptions are preserved. Category selection reuses
an existing directory category when suitable and prints `(new category)` when it creates
one. The results are saved in
`watchcraft-authoring.json` and copied only to the public directory, not the
installable collection manifest. Directory entries also carry the collection's
video count for the website's collection cards. Pass `--category "Category Name"`
to choose the category explicitly.

Legacy local-media libraries continue to use the `Video Catalog/` metadata folder.

## Local credentials

Copy `.env.example` to `.env.local` at the repository root and fill in the
credentials used by your authoring setup. The authoring command loads this file
automatically, while variables explicitly exported in the shell take precedence.
`.env.local` is ignored by Git and must never be committed.

## Generate a collection from a YouTube playlist

From the Watchcraft repository root, generate a complete collection workspace in
one step:

```bash
./authoring/watchcraft-author collection create \
  --from-youtube-playlist "https://www.youtube.com/playlist?list=PLAYLIST_ID" \
  --collections-repo ~/dev/watchcraft-collections
```

The command derives the collection title and slug, creates
`collections/<slug>/`, imports the playlist in its published order, analyzes
unfinished videos, normalizes topics into compact UI labels, validates the
manifest, and writes a collection README. It is resumable: rerun the same command
to reuse completed imports, analyses, and normalization work. It does not stage,
commit, push, fork, or open a pull request.

Resumed imports are reported as `cached`. Videos whose owners disable embedded
playback are excluded with a clear warning and remembered on later resumptions;
use `--force` to check them again. Other unexpected import failures preserve
completed work, exit with an error, and stop before analysis. The command also
verifies that every selected video has a matching source, transcript, and analysis
before normalization. The publishable collection manifest is rebuilt only after
normalization reaches `complete`; failed label batches save their valid results and
report the exact unresolved topics for the next run.
The durable phase boundaries and failure guarantees are recorded in
[ADR 0003](../docs/architecture/0003-resumable-fail-closed-authoring.md).

## Queued authoring smoke test

The manually dispatched `Authoring pipeline smoke` GitHub Actions workflow is the
first production-shaped queued-authoring slice. It deploys the Convex control-plane
functions, creates and approves a synthetic transcript job, claims a time-bounded
lease, writes the transcript as an immutable SHA-256-addressed object in private R2,
records the validated result in Convex, and downloads it again to verify the exact
bytes.

This workflow proves orchestration and storage, not speech recognition. The synthetic
handler is intentionally isolated behind the same generic handler contract that a
later audio or caption transcript generator will implement. Actions logs contain only
job IDs, lifecycle state, sizes, and digests; transcripts and credentials are not
uploaded as Actions artifacts.

The required GitHub environments and variables are described by
[ADR 0004](../docs/architecture/0004-authoring-control-execution-and-artifact-planes.md).
Because this repository is public, do not attach a self-hosted Mac runner to this
workflow or use it with private source material.

## Operator queue CLI

Queued authoring operator commands use a credential distinct from the GitHub worker
credential. On macOS the CLI reads the raw value from the login Keychain item named
`Watchcraft authoring operator token`, account `watchcraft-operator-cli`. Set
`WATCHCRAFT_AUTHORING_OPERATOR_TOKEN` only when an explicit non-Keychain override is
needed. Convex production stores only its SHA-256 verifier as
`AUTHORING_OPERATOR_TOKEN_SHA256`.

Queue commands accept `--operator-token-source auto|keychain|environment` after the
queue subcommand. `auto` prefers `WATCHCRAFT_AUTHORING_OPERATOR_TOKEN` when present and
otherwise uses Keychain. `keychain` deliberately ignores the environment override;
`environment` requires it. Raw token values are not accepted as command-line arguments
because they can leak through shell history and process listings.

Handler availability and runner routing come from an immutable capability-registry
document. The checked-in bootstrap document is
`packages/authoring-pipeline/registry/default-registry.json`; its language-neutral
contract is the adjacent JSON Schema. Convex stores published versions and a separate
revisioned active pointer for each environment. Deploying code never publishes or
activates this document implicitly.

Registry publication and activation use a credential distinct from both operator and
worker credentials. On macOS the CLI reads the raw value from the login Keychain item
named `Watchcraft authoring registry admin token`, account
`watchcraft-registry-admin-cli`. Convex stores only its SHA-256 verifier as
`AUTHORING_REGISTRY_ADMIN_TOKEN_SHA256`. An explicit override may use
`WATCHCRAFT_AUTHORING_REGISTRY_ADMIN_TOKEN` with
`--registry-admin-token-source environment`.

After deploying registry-aware control-plane code, bootstrap production explicitly:

```bash
./authoring/watchcraft-author queue registry-publish \
  --registry-admin-token-source keychain

./authoring/watchcraft-author queue registry-activate \
  --registry-admin-token-source keychain

./authoring/watchcraft-author queue registry-status \
  --operator-token-source keychain
```

`registry-publish` and `registry-activate` default to the checked-in document; an
alternate JSON path may be supplied as their positional argument. Before activation,
the CLI uses the registry-admin credential to read the current activation-pointer
revision and supplies it to the compare-and-set mutation. This preserves stale-write
protection without requiring the operator to copy a revision manually. The immutable
registry document version (for example `2026-09-05.5`) and the activation-pointer
revision (for example `2`) are separate values. Advanced scripts may explicitly pass
`--expected-active-revision`; the older `--expected-revision` spelling remains an
alias. Publishing the same version with different content is rejected.

The first Python worker handler produces a deterministic lexical-analysis artifact.
It is an infrastructure and protocol proof, not the model-backed instructional-video
analysis used by the existing local authoring commands. Submit, approve, dispatch, and
inspect it separately:

```bash
./authoring/watchcraft-author queue submit-analysis \
  --title "Color workflow" \
  --text "Balance exposure and color before applying the final grade."

./authoring/watchcraft-author queue approve JOB_ID
./authoring/watchcraft-author queue dispatch JOB_ID
./authoring/watchcraft-author queue status JOB_ID
./authoring/watchcraft-author queue result JOB_ID
```

`dispatch` starts the reviewed GitHub workflow named by the approved execution-profile
snapshot, with identifiers only. The initial `python-portable@1` profile selects the
`Authoring worker` workflow on Ubuntu.
The Python worker records the GitHub run, claims a lease, selects its handler from the
approved specification, writes and verifies the result in private R2, and reports the
authoritative artifact reference to Convex. `queue retry JOB_ID` and
`queue cancel JOB_ID` use the same compare-and-swap state transitions.

The repeatable queue regression is available as a single command. It performs the
complete submit, approve, dispatch, wait, artifact-download, and digest-verification
ritual and marks the resulting run as ephemeral with a seven-day retention deadline:

```bash
./authoring/watchcraft-author queue smoke-analysis \
  --operator-token-source keychain \
  --r2-credentials-source keychain
```

The first real speech-recognition slice uses the same envelope but resolves to the
`macos-mlx@1` execution profile and its dedicated Apple-silicon GitHub Actions
workflow. The worker synthesizes a short public audio fixture with macOS `say`,
transcribes it with MLX Whisper, discards the temporary audio, and retains only the
content-addressed transcript JSON:

```bash
./authoring/watchcraft-author queue smoke-transcription \
  --operator-token-source keychain \
  --r2-credentials-source keychain
```

This is intentionally a real inference smoke rather than the eventual production
audio-input handler. It proves capability-based routing and MLX execution without
requiring an input uploader, retaining source audio, or granting the worker private
source access.

The next remote-input smoke keeps YouTube extraction out of scope while exercising
the media path that follows it. It downloads OpenAI Whisper's 11-second JFK FLAC test
fixture from a URL pinned to an exact upstream Git commit. The approved job binds the
URL, byte length, SHA-256, download ceiling, and timeout. The macOS worker streams it
into a temporary file, rejects redirects away from HTTPS and any size or digest drift,
transcribes it with the same MLX implementation, then deletes the audio:

```bash
./authoring/watchcraft-author queue smoke-transcription-http \
  --operator-token-source keychain \
  --r2-credentials-source keychain
```

Only the transcript JSON enters authoritative R2 storage. The result provenance
records the verified media identity but not a retained audio object.

Direct YouTube acquisition is intentionally not assigned to a GitHub-hosted worker:
both `yt-dlp` on hosted macOS and full Chromium on hosted Ubuntu were denied before
media playback. The single-video smoke instead acquires bounded audio anonymously on
the operator's Mac, uploads it under an expiring private `staging/` key, and submits
that exact digest as the input to the provider-neutral MLX handler. The cloud worker
reads and verifies R2; it never contacts YouTube. Shorts, share, embed, and watch URLs
are normalized to the stable video ID and canonical watch URL before acquisition:

```bash
./authoring/watchcraft-author queue smoke-transcription-youtube \
  --operator-token-source keychain \
  --r2-staging-credentials-source keychain \
  --r2-credentials-source keychain
```

The default fixture is the 59-second `D_jOvlB_D7A`, previously acquired successfully
while authoring the All About Lights collection. One other public YouTube URL or ID
may be supplied as the positional argument. The local adapter invokes pinned `yt-dlp`
with `--ignore-config`, no browser cookies, explicit transfer limits, and the
provider-designated original audio track. It records canonical source identity,
selected format and language, tool version, duration, byte count, and SHA-256. The
approved job binds that provenance and the staged object reference. After a successful
transcription and verified result download, the CLI deletes the staged audio. An R2
lifecycle rule on the `staging/` prefix must remove interrupted or abandoned uploads
after one day. This command still does not discover playlists, create a collection,
or assign the video to an authored grouping.

Local staging upload uses a write-capable credential distinct from the result reader.
Its Keychain service is `Watchcraft R2 staging uploader`, with accounts
`access-key-id` and `secret-access-key`. Select
`--r2-staging-credentials-source environment` to use
`WATCHCRAFT_R2_STAGING_ACCESS_KEY_ID` and
`WATCHCRAFT_R2_STAGING_SECRET_ACCESS_KEY`; `auto` prefers that complete pair and
otherwise uses Keychain. This bootstrap credential belongs only on the operator's
machine. A future browser or multi-user acquisition client must receive a short-lived,
job-scoped presigned upload instead.

For an actual single-video authoring run, use `transcribe-youtube` instead of the
smoke command:

```bash
./authoring/watchcraft-author queue transcribe-youtube \
  --operator-token-source keychain \
  --r2-staging-credentials-source keychain \
  --r2-credentials-source keychain \
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

This follows the same local acquisition, exact-byte staging, approval, GitHub dispatch,
result verification, and staged-input deletion path. It creates a durable authoring run
rather than an ephemeral diagnostic record and is bound by its registered handler to
`mlx-community/whisper-large-v3-turbo-q4`, the production model already used by local
Watchcraft authoring. The CLI intentionally provides no arbitrary model override: a
model change is reviewed and versioned as a new handler capability. The initial command
accepts English videos up to two hours and 100 MB of compressed source audio. Use
`queue result --output PATH JOB_ID` later to retrieve the exact authoritative transcript
artifact again.

The command finishes with a compact summary rather than printing every transcript
segment. Its `timing` object reports local acquisition, staging upload, terminal wait,
result download, and total command milliseconds; durable ledger timestamps provide
dispatch-to-worker, worker-attempt, and submission-to-completion milliseconds; and the
transcript provenance records worker input-fetch, model-transcription, and total-handler
milliseconds. The audio duration, byte length, handler/model identity, and these phase
measurements are machine-readable inputs for future runtime estimates. Use the printed
`queue result` command when the full transcript is needed.

Analyze one successful queued transcript with the existing production video analyzer:

```bash
./authoring/watchcraft-author queue analyze-transcript \
  --operator-token-source keychain \
  --r2-credentials-source keychain \
  TRANSCRIPTION_JOB_ID
```

The command verifies that the referenced job completed with an authoritative
`watchcraft.transcript@1` artifact, resolves the same YouTube source metadata used by
the file-backed authoring path, and submits that transcript as an immutable dependency.
The registered `watchcraft.analysis.educational-video@1` handler calls the existing
analysis implementation: prompt version 3, `gpt-5-nano`, Pydantic structured output,
normalization, authoritative YouTube publication-date replacement, and publisher
chapter alignment. Its output remains the current video-analysis schema version 2,
with additive queue provenance and phase timing. The terminal prints only counts and a
summary preview; the printed `queue result` command retrieves the complete analysis.

This handler runs in the dedicated `python-openai@1` execution profile because it reads
a private derived transcript and calls the OpenAI Responses API. Add `OPENAI_API_KEY`
as a secret on the GitHub `authoring-production` environment before dispatching it.
The key is an execution secret and must not appear in the registry, job specification,
workflow inputs, transcript, analysis, or logs. Registry version `2026-09-05.5` adds
the handler and profile; publish and activate that immutable registry after pushing the
worker code. No Convex function deployment is required for this registry-only change.

This command analyzes one video; it does not normalize collection-wide topics, choose
a category, create a grouping, or publish a collection. Those remain later pipeline
phases.

Run the complete production path for one YouTube video as one durable authoring run:

```bash
./authoring/watchcraft-author queue process-youtube \
  --operator-token-source keychain \
  --r2-staging-credentials-source keychain \
  --r2-credentials-source keychain \
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

The command creates separate transcription and analysis jobs and approves them as one
immutable plan. Analysis declares the transcription job's typed output as its
dependency; the control plane refuses to dispatch it before the transcript succeeds.
The jobs retain their existing macOS MLX and Linux OpenAI execution profiles, and each
publishes its own authoritative artifact. The run completes only after both jobs
succeed.

The final compact result includes each job's artifact, worker and ledger timings plus
the local acquisition phases and total command duration. `run_created_to_completed_ms`
measures durable control-plane latency across both workers. The two printed `queue
result` commands retrieve the full transcript and analysis independently. This command
requires the updated Convex functions to be deployed; it does not require a new
capability-registry version because it composes existing registered handlers.

Run the first queued collection iterator against a `CatalogProject` document:

```bash
./authoring/watchcraft-author queue iterate-project \
  --operator-token-source keychain \
  --r2-credentials-source keychain \
  packages/authoring-pipeline/project/examples/current-playlist.project.json
```

`watchcraft.iterator.youtube-playlist@1` runs on the portable Linux worker. It resolves
the public playlist, observes each visible video into deduplicated items and separate
ordered placements, validates the complete snapshot, and stores it as an immutable R2
artifact. The CLI prints phase changes and `n of total placements` as the worker
heartbeats. Every ten entries the worker stores a specification-bound checkpoint; a
replacement attempt verifies and resumes that checkpoint only when its project
revision, playlist identity, and exact source-entry digest still agree. Excluded or
unavailable entries remain explicit classified coverage records rather than silently
disappearing.

This command produces a candidate iterator snapshot. It does not accept that snapshot
into a new `CatalogProject` revision, fan out transcription and analysis jobs, compile
a collection, or publish it. Those are subsequent orchestration transitions. The
iterator handler requires a capability registry containing
`watchcraft.iterator.youtube-playlist@1` to be published and activated
after the worker code is available on `main`, which is the branch dispatched by the
operator CLI.

Import the initial project aggregate into Convex once. A project that already binds an
accepted snapshot also requires its exact snapshot bytes; for the checked-in examples
the CLI finds the sibling `*.snapshot.json` file automatically:

```bash
./authoring/watchcraft-author queue project-import \
  --operator-token-source keychain \
  packages/authoring-pipeline/project/examples/current-playlist.project.json
```

Accept a completed iterator candidate by its authoritative job ID:

```bash
./authoring/watchcraft-author queue project-accept-snapshot \
  --operator-token-source keychain \
  --r2-credentials-source keychain \
  essence-of-linear-algebra \
  ITERATOR_JOB_ID
```

The command observes the current revision by default, downloads and verifies the exact
candidate bytes from R2, and submits them to the control plane. Convex independently
checks the digest and byte length against the succeeded job, verifies that the job ran
against the exact current project aggregate, validates the snapshot contract and type
compatibility, and creates the next immutable project revision. It does not adopt
metadata proposals automatically. Use `--expected-revision N` when a script needs an
explicit compare-and-swap precondition.

Inspect the current aggregate and its immutable transition history with:

```bash
./authoring/watchcraft-author queue project-status \
  --operator-token-source keychain \
  essence-of-linear-algebra

./authoring/watchcraft-author queue project-history \
  --operator-token-source keychain \
  essence-of-linear-algebra
```

After import, a refresh can use the project ID instead of a local file so iteration is
always bound to the authoritative current revision:

```bash
./authoring/watchcraft-author queue iterate-project \
  --operator-token-source keychain \
  --r2-credentials-source keychain \
  essence-of-linear-algebra
```

Project persistence adds Convex schema and function changes, so deploy them with
`npx convex deploy` before using these commands. It does not add a worker handler and
therefore does not require publishing or activating a new capability registry.

Create an immutable processing plan from the authoritative imported project and its
accepted iterator snapshot:

```bash
./authoring/watchcraft-author queue plan-project \
  --operator-token-source keychain \
  --r2-credentials-source keychain \
  essence-of-linear-algebra
```

The portable planner verifies the exact accepted R2 snapshot and plans once per unique
video item, preserving all placement IDs. It describes local metadata enrichment and
audio acquisition followed by the registered MLX transcription and educational-video
analysis handlers. Topic normalization and collection compilation are present as
deferred collection-wide tasks. Reuse decisions for derived artifacts remain deferred
until their exact input digests exist.

This command creates only the planner job and its immutable plan artifact. It does not
download video audio or dispatch any of the described processing jobs. The compact
result reports task counts, duration coverage, and conservative sequential worker
timeout bounds; the printed `queue result` command retrieves the full plan. The
planner requires capability registry `2026-09-08.2` or later to be published and activated
after its code is available on `main`. It does not require another Convex deployment.

Execute every item from a successful immutable plan with bounded concurrency:

```bash
./authoring/watchcraft-author queue process-project \
  --plan-job-id PLAN_JOB_ID \
  --all \
  --concurrency 2 \
  --operator-token-source keychain \
  --r2-staging-credentials-source keychain \
  --r2-credentials-source keychain
```

Use `--item ITEM_ID` to choose a specific plan item or `--limit N` to process the
first N items. `--concurrency` defaults to two and is bounded from one through eight.
The executor verifies that the plan still matches the current authoritative project
revision and accepted snapshot, then uses the existing local YouTube acquisition, MLX
transcription, and educational-analysis pipeline. Multiple placements of a selected
video do not produce duplicate work.

The exact plan artifact digest and item identity deterministically derive the pipeline run,
transcription-job, and analysis-job IDs. The run request records the plan job, project
revision, item ID, and logical task IDs. Rerunning the command retrieves and resumes
each pipeline instead of downloading or submitting it again. Completed items are
verified and reported as already complete; incomplete items resume from their durable
run and job states. The command waits for all selected items, prints per-item completion
lines and a compact aggregate summary, and returns an error after the summary if any
item failed. Rerun the same command to continue only the unfinished work. A staged input
left by a failure before pipeline submission expires under the existing R2 retention
policy. Retryable and interrupted jobs resume automatically; terminal failures still
require the underlying problem to be addressed before another attempt can be created.

`process-project` adds the read-only `/pipelines/get` Convex endpoint, so deploy the
Convex functions with `npx convex deploy` after pushing the code. It composes existing
handlers and does not require another capability-registry publication.

After every planned item has a successful analysis, normalize the complete collection
topic set:

```bash
./authoring/watchcraft-author queue normalize-project-topics \
  --plan-job-id PLAN_JOB_ID \
  --operator-token-source keychain \
  --r2-credentials-source keychain
```

The command derives every analysis-job identity from the exact plan artifact and
rejects missing, failed, foreign, or stale item executions. The normalization job binds
the immutable R2 reference for every analysis as a typed dependency, then runs the
existing topic-family, assignment, compact-label, and related-topic logic on the OpenAI
worker. Its deterministic run and job IDs make the command safe to resume. The compact
result reports the raw and canonical topic counts, families, labels, related pairs, and
timing; the printed `queue result` command retrieves the complete normalization artifact.

This adds a variable-cardinality dependency contract and capability registry
`2026-09-08.3`. After committing and pushing, deploy Convex with `npx convex deploy`,
then publish and activate the checked-in registry before running the command:

```bash
./authoring/watchcraft-author queue registry-publish \
  --registry-admin-token-source keychain

./authoring/watchcraft-author queue registry-activate \
  --registry-admin-token-source keychain
```

`queue result` resolves the artifact reference from the authoritative completed job,
downloads the object from private R2, and verifies its declared byte length and SHA-256
digest. JSON is displayed in readable form by default; `--output PATH` writes the exact
verified bytes to a new file and refuses to overwrite an existing file. The command
uses a separate read-only R2 S3 credential. Its Keychain service is
`Watchcraft R2 artifact reader`, with accounts `access-key-id` and
`secret-access-key`. Select `--r2-credentials-source environment` to use
`WATCHCRAFT_R2_READER_ACCESS_KEY_ID` and
`WATCHCRAFT_R2_READER_SECRET_ACCESS_KEY` instead. `auto` prefers that complete
environment pair and otherwise uses Keychain. These names are deliberately distinct
from the worker's write-capable credential. The non-secret bucket and endpoint use the
corresponding environment variables when present and otherwise come from the GitHub
`authoring-production` environment variables.

Smoke runs carry an explicit ephemeral retention policy. List expired or upcoming
marked runs with:

```bash
./authoring/watchcraft-author queue cleanup-list \
  --registry-admin-token-source keychain
```

After the reported deadline, purge one run's Convex aggregate and event projections
by repeating its exact ID as confirmation:

```bash
./authoring/watchcraft-author queue cleanup-run RUN_ID \
  --confirm RUN_ID \
  --registry-admin-token-source keychain
```

Use `cleanup-list --include-unmarked` to audit older debug runs and terminal jobs left
by the original synthetic smoke before it created run aggregates. Removing an unmarked
run requires the additional `cleanup-run --allow-unmarked` flag. Remove a listed
orphan only by its exact job ID:

```bash
./authoring/watchcraft-author queue cleanup-orphan-job JOB_ID \
  --confirm JOB_ID \
  --registry-admin-token-source keychain
```

Cleanup is restricted to terminal runs and jobs, is command-idempotent, and records
its own audit event. It reports but does not delete R2 artifacts; object deletion
remains deferred until reachability-based garbage collection can prove that no
authoritative record references the content-addressed object.

Use `--dry-run` to inspect the playlist without writing files or making AI calls,
`--import-only` to postpone analysis, `--exclude VIDEO_ID` to omit a video, or
`--limit N` to work with the first `N` selected videos. Use `--unlisted` when the
manifest should remain directly installable but absent from the website directory.

The legacy caption path remains available with `--transcript-source captions`.
Add `--skip-missing-captions` when that mode should exclude videos without captions
in the requested language. The command records those terminal caption failures as
collection exclusions and reuses them on later caption-mode resumptions. Running
the collection again in the default audio mode retries and clears those exclusions
when transcription succeeds. Other import failures remain fatal. Use `--force`
with caption mode to check previously excluded videos again.

If YouTube blocks caption requests in caption mode, Watchcraft stops after
the first blocked request and preserves completed work. Retry later to resume
from the completed imports.
