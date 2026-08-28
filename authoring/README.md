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
into that directory, while retrieved captions remain private authoring inputs.

```bash
python watchcraft_author.py youtube add \
  --workspace ~/dev/watchcraft-collections/collections/premiere-pro-ai-tools \
  --collection-title "Premiere Pro AI Tools" \
  --position 1 \
  "https://www.youtube.com/watch?v=PjObX9XQvgI"

python watchcraft_author.py process \
  --workspace ~/dev/watchcraft-collections/collections/premiere-pro-ai-tools
```

Import every visible video from a public or unlisted playlist without downloading
the videos or requiring `yt-dlp`, a YouTube API key, or account credentials:

```bash
python watchcraft_author.py youtube add \
  --workspace ~/dev/watchcraft-collections/collections/premiere-pro-course \
  --collection-title "Premiere Pro Course" \
  --playlist "https://www.youtube.com/playlist?list=PLAYLIST_ID"

python watchcraft_author.py process \
  --workspace ~/dev/watchcraft-collections/collections/premiere-pro-course
```

Playlist imports retain YouTube ordering and are resumable. Videos that are private,
unavailable, or do not expose the requested caption language are reported and skipped.
Use `--position N` to place the first playlist video at a position other than one.
The `--playlist` value may be either a playlist URL or a YouTube watch URL containing
both `v=` and `list=` parameters, such as the URL copied while playing the first video.
Watchcraft uses the `list=` value and imports the playlist from its actual first entry.

`youtube add` retrieves public metadata and the requested caption track without
downloading the video. `process` analyzes unfinished sources, repairs an
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
`--limit N` to work with the first `N` selected videos.

If YouTube blocks caption requests from the current IP, Watchcraft stops after
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
