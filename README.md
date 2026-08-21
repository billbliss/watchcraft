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

The intended runtime is:

- a React/Vite web application for the portable reader;
- an Electron desktop shell for local files, downloads, and durable local state;
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

