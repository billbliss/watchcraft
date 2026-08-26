# Watchcraft

**Learn a craft by watching.**

Watchcraft is a local-first catalog for instructional video. It makes a video
library searchable by concept, connects topics to the chapters where they are
taught, and plays media without uploading it.

This repository separates two products at a versioned catalog boundary:

- `authoring/` builds and updates portable collection packages from local videos
  or public YouTube sources, transcripts, and analysis.
- `apps/` and `packages/` contain the web and desktop reader. The reader consumes
  catalogs; it does not know how they were authored.

## Repository status

The runtime and authoring pipeline are separated by the versioned collection
schema:

- a React/Vite web application for the portable reader;
- a Tauri 2 shell for narrowly scoped local-library access and private state;
- later desktop work for collection downloads and multi-collection UI;
- Python command-line authoring tools;
- JSON collection packages validated by `packages/catalog-schema`;
- private device-specific state for media locations and installed revisions.
  Portable collection content remains data, never embedded application code.

See [the architecture decision](docs/architecture/0001-catalog-runtime-boundary.md)
for the boundary and update model.

## Python authoring

```sh
cd authoring/prototype
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest -v
```

The authoring tools generate versioned collection metadata and CSV exports. They
do not generate or serve reader UI.

## Web reader

The first wrapper-free reader milestone lives in `apps/web`. Its default fixture
contains catalog metadata but no copyrighted media:

```sh
npm install --prefer-offline --no-audit --no-fund
npm run dev
```

To use a published collection, pass its manifest URL to the web reader:

```text
http://127.0.0.1:5173/?catalog=https://example.com/courses/collection.json
```

The query parameter is an adapter setting, not catalog content. The React reader
only uses the shared `CatalogRepository` contract.

Collection items may reference local files, HTTP video, or public YouTube videos.
YouTube playback uses a privacy-enhanced embed and does not require a local media
binding.

## Tauri desktop app

`apps/desktop` contains a deliberately small native shell. It reuses the React
reader and adds only a native folder picker,
read-only asset-protocol access to the chosen library, restoration of that
user-approved scope, and a command that opens a supported video in the OS
default player. That command accepts only existing video files already covered
by the user-approved asset scope. The renderer has no arbitrary filesystem,
shell, write, download, SQLite, or authoring capability.

After installing the [Tauri prerequisites](https://v2.tauri.app/start/prerequisites/):

```sh
npm install --prefer-offline --no-audit --no-fund
npm run desktop:dev
```

The first launch asks for a collection folder or its parent. A collection
manifest is identified by `kind: "watchcraft.collection"`; its filename and
folder name are not significant. Watchcraft copies the manifest and referenced
metadata into its private app-data directory, while local videos remain in place
and are connected through a private directory binding. An optional
`media_root_hint` helps establish that binding during installation but is not
used as runtime authority. Development runs as **Watchcraft Dev** with its own app identity, so
an installed or previously bundled Watchcraft copy cannot be mistaken for the
freshly launched development build.

Before merging desktop playback changes, run the native smoke test:

```sh
npm run desktop:smoke
```

It generates a complete one-video schema-v4 collection with an arbitrarily
named manifest and a small H.264/AAC fixture,
launches the normal catalog and player UI in an isolated Watchcraft profile,
verifies that playback advances, then restarts the profile and verifies playback
again using restored read-only folder access. The runner fails unless the app
itself reports a playback pass. The command requires `ffmpeg` and does not read
or modify the user's configured library.
