# Watchcraft

**Learn a craft by watching.**

Watchcraft is a local-first catalog for instructional video. It makes a video
library searchable by concept, connects topics to the chapters where they are
taught, and plays media without uploading it.

This repository separates two products at a versioned catalog boundary:

- `authoring/` builds and updates portable collection packages from videos,
  transcripts, and analysis.
- `apps/` and `packages/` contain the web and desktop reader. The reader consumes
  catalogs; it does not know how they were authored.

## Repository status

The working Python application has been preserved in `authoring/prototype/` as
the behavioral baseline. The next migration step is to extract its generated UI
into React + TypeScript while keeping the Python authoring pipeline intact.

The runtime is being introduced in stages:

- a React/Vite web application for the portable reader;
- an experimental Tauri 2 shell for narrowly scoped local-library access;
- later desktop work for collection downloads and durable local state;
- Python command-line authoring tools;
- JSON collection packages validated by `packages/catalog-schema`;
- SQLite only for device-specific state such as media locations and download
  status. Portable catalog content remains data, never embedded application code.

See [the architecture decision](docs/architecture/0001-catalog-runtime-boundary.md)
for the boundary and update model.

## Current prototype

```sh
cd authoring/prototype
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest -v
```

The prototype commands are intentionally retained during the migration so the
new reader can be compared with the existing behavior.

## Web reader

The first wrapper-free reader milestone lives in `apps/web`. Its default fixture
contains catalog metadata but no copyrighted media:

```sh
npm install --prefer-offline --no-audit --no-fund
npm run dev
```

To use a live catalog, keep the Python catalog server running and pass its
manifest URL to the web reader:

```text
http://127.0.0.1:5173/?catalog=http://127.0.0.1:8765/Video%20Catalog/collection.json
```

The query parameter is an adapter setting, not catalog content. The React reader
only uses the shared `CatalogRepository` contract.

## Tauri desktop experiment

The `experiment/tauri` branch contains a deliberately small native shell in
`apps/desktop`. It reuses the React reader and adds only a native folder picker,
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

The first launch asks for the root folder of a local video library. The adapter
recognizes both `collection.json` at that root and the current
`Video Catalog/collection.json` layout.
