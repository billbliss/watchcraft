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
interpreter instead of relying on a system copy. FFmpeg remains a host prerequisite.
Comparison reports and all transcripts are private authoring outputs. Pass
`--yt-dlp /path/to/yt-dlp` to the comparison tool only when deliberately testing
another executable.

When a workspace lives at `collections/<slug>/` in a content repository whose
`site/collections.json` defines `base_url`, every successful build adds or updates
the collection in that website directory. Existing hand-edited directory
descriptions are preserved. Pass `--unlisted` to `youtube add` or `collection
create` to publish a collection by URL without advertising it; the choice is
stored in `watchcraft-authoring.json` and respected by later builds.

For a listed `collection create`, the authoring tool also chooses a public-directory
category after import. It reuses an existing directory category when suitable and
prints `(new category)` when it creates one. The choice is saved in
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

Resumed imports are reported as `cached`. If any selected video cannot be
imported, the command preserves completed work, exits with an error, and stops
before analysis. It also verifies that every selected video has a matching source,
transcript, and analysis before normalization. The publishable collection manifest
is rebuilt only after normalization reaches `complete`; failed label batches save
their valid results and report the exact unresolved topics for the next run.
The durable phase boundaries and failure guarantees are recorded in
[ADR 0003](../docs/architecture/0003-resumable-fail-closed-authoring.md).

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
the first blocked request and preserves completed work. Retry from another
network, or configure a proxy without putting credentials in the command:

```bash
# Any HTTP/HTTPS proxy URL (credentials may be embedded in the URL)
export WATCHCRAFT_YOUTUBE_PROXY_URL="http://user:password@proxy.example:8080"

# Or youtube-transcript-api's built-in Webshare rotating-residential integration
export WATCHCRAFT_YOUTUBE_WEBSHARE_USERNAME="proxy username"
export WATCHCRAFT_YOUTUBE_WEBSHARE_PASSWORD="proxy password"
```

Use only one proxy method. Proxy credentials are read from the environment and
are never written to the collection workspace.
