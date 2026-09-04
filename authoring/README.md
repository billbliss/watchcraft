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
```

`dispatch` starts the manual `Authoring worker` GitHub workflow with identifiers only.
The Python worker records the GitHub run, claims a lease, selects its handler from the
approved specification, writes and verifies the result in private R2, and reports the
authoritative artifact reference to Convex. `queue retry JOB_ID` and
`queue cancel JOB_ID` use the same compare-and-swap state transitions.

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
