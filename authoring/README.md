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
  --registry-admin-token-source keychain \
  --expected-revision 0

./authoring/watchcraft-author queue registry-status \
  --operator-token-source keychain
```

`registry-publish` and `registry-activate` default to the checked-in document; an
alternate JSON path may be supplied as their positional argument. Activation requires
the currently observed pointer revision, so a stale administrator cannot overwrite a
newer selection. Use the revision returned by `registry-status` after the first
activation. Publishing the same version with different content is rejected.

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

Only the transcript JSON enters R2. The result provenance records the verified media
identity but not a retained audio object. A later YouTube adapter can resolve a watch
URL to a temporary media stream and hand that stream to the same bounded acquisition
boundary; YouTube extraction and access behavior remain the single variable deferred
by this smoke.

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
