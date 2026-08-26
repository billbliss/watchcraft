# Authoring

Watchcraft authoring is a Python toolchain that turns source media, transcripts,
and analysis into versioned collection packages. Authors may clone this repository
and run the tools locally; authoring is not required by the reader application.

`prototype/` contains the current command-line implementation. Its collection
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
python prototype/watchcraft_author.py youtube add \
  --workspace ~/dev/watchcraft-collections/collections/premiere-pro-ai-tools \
  --collection-title "Premiere Pro AI Tools" \
  --position 1 \
  "https://www.youtube.com/watch?v=PjObX9XQvgI"

python prototype/watchcraft_author.py process \
  --workspace ~/dev/watchcraft-collections/collections/premiere-pro-ai-tools
```

`youtube add` retrieves public metadata and the requested caption track without
downloading the video. `process` analyzes unfinished sources, repairs an
underspecified timeline, validates the resulting `collection.json` against the
canonical schema, and preserves the collection revision when content is unchanged.
Publisher-authored timestamps in the YouTube description are authoritative when
present: Watchcraft keeps those chapter titles and boundaries while enriching them
with its generated descriptions and concepts. AI-generated chapters are the fallback.
Use `--position N` when a collection has an intentional lesson sequence; the
compiler retains that ordering across subsequent rebuilds.

The content repository should ignore `**/transcripts/`, downloaded media, caches,
credentials, and other private working material. YouTube collection items publish
only their video ID/URL and analysis; their `transcript` reference is empty.

Legacy local-media libraries continue to use the `Video Catalog/` metadata folder.
