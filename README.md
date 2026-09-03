# Watchcraft

[![License: MIT](https://img.shields.io/badge/License-MIT-72cf91.svg)](LICENSE)

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
cd authoring
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest -v
```

Python 3.13 is the supported authoring runtime and is recorded in
`authoring/.python-version`. The requirements install the authoring toolchain's
own current `yt-dlp`; authoring does not depend on a separately installed system
copy.

The authoring tools generate versioned collection metadata and CSV exports. They
do not generate or serve reader UI. YouTube authoring generates transcripts locally
from streamed audio by default; pass `--transcript-source captions` to use YouTube's
caption track instead.

From the repository root, generate a collection from a public YouTube playlist:

```sh
./authoring/watchcraft-author collection create \
  --from-youtube-playlist "https://www.youtube.com/playlist?list=PLAYLIST_ID" \
  --collections-repo ../watchcraft-collections
```

Generation and Git publication are deliberately separate operations.
The command is resumable; rerunning it reuses completed import, analysis, and
topic-normalization work.

See the [authoring guide](authoring/README.md) for operation and recovery, and
[ADR 0003](docs/architecture/0003-resumable-fail-closed-authoring.md) for the
pipeline's checkpoint, failure, and publishability guarantees.

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

Collection items may use managed local media, referenced local media, HTTP
video, or public YouTube videos.
YouTube playback uses a privacy-enhanced embed and does not require a local media
binding.

## Tauri desktop app

`apps/desktop` contains a deliberately small native shell. It reuses the React
reader and adds only a native folder picker,
read-only asset-protocol access to the chosen library, restoration of that
user-approved scope, and a command that opens a supported video in the OS
default player. That command accepts only existing video files already covered
by the user-approved asset scope. The renderer has no arbitrary filesystem,
shell, arbitrary write/download, SQLite, or authoring capability. Collection
installation can download only manifest-declared resources into private storage.

After installing the [Tauri prerequisites](https://v2.tauri.app/start/prerequisites/):

```sh
npm install --prefer-offline --no-audit --no-fund
npm run desktop:dev
```

The first launch asks for a collection folder or its parent. A collection
manifest is identified by `kind: "watchcraft.collection"`; its filename and
folder name are not significant. Watchcraft copies the manifest, referenced
metadata, and managed local media into its private app-data directory.
Referenced local videos remain in place and are connected through a private
directory binding. When a URL-installed collection references local videos,
Watchcraft prompts for the folder containing them and stores that late binding
only on the device. Settings can change the folder later. Updating the URL
collection installs its newer revision while retaining both the media binding
and earlier private revisions. An optional `media_root_hint` helps establish a
folder-installed binding but is not used as runtime authority. Development runs
as **Watchcraft Dev** with its own app identity, so an installed or previously
bundled Watchcraft copy cannot be mistaken for the freshly launched development
build. Published collection pages can open the installer directly with
`watchcraft://install?url=…`. Both stable and beta builds accept that public
scheme. Beta also retains `watchcraft-beta://install?url=…` for explicitly
targeting beta when testing a schema or behavior that stable does not support.

Before merging desktop playback changes, run the native smoke test:

```sh
npm run desktop:smoke
```

This checks both referenced local videos and videos copied into Watchcraft-managed storage.

It generates a complete one-video schema-v4 collection with an arbitrarily
named manifest and a small H.264/AAC fixture,
launches the normal catalog and player UI in an isolated Watchcraft profile,
verifies that the player decodes a preview frame and seeks through the stream,
then restarts the profile and repeats the check using restored read-only folder
access. The runner fails unless the app itself reports a playback pass. The
command requires `ffmpeg` and does not read or modify the user's configured
library.

## Desktop installers and releases

The `Desktop installers` GitHub Actions workflow builds unsigned Windows x64
(`.exe` for betas; `.exe` and `.msi` for stable releases), Linux x64 (`.deb` and
`.AppImage`), and signed and notarized macOS Apple Silicon (`.dmg`) packages.
Prerelease tags publish **Watchcraft Beta** with a separate application identity
and private data directory; stable tags publish the production identity. See the
[release guide](docs/releases.md) for the exact tag conventions and the
[cross-platform testing guide](docs/cross-platform-testing.md) for the
compatibility smoke checklist.

The public landing page is deployed from `site/` to
<https://watchcraft.stream/>. It discovers permanent installer
assets from GitHub Releases and the optional advertised collection directory
from `watchcraft-collections`. The same Pages deployment publishes the Web Video
reader at <https://watchcraft.stream/app/>; desktop installers remain separately
versioned GitHub Release assets.

## License

Watchcraft is available under the [MIT License](LICENSE).
