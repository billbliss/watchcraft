# ADR 0002: Private library registry and media bindings

- Status: Accepted
- Date: 2026-08-25

## Context

Collections may be published independently, may use local video files or hosted
video references, and need not come from a centrally governed directory. A
portable collection must not contain a user's machine-specific filesystem paths.
The videos present on a device may be an exact, partial, or superset match for a
collection.

## Decision

A portable schema-v4 collection is identified by
`kind: "watchcraft.collection"`, not by its filename. Local folder discovery
looks in the selected folder and its immediate children. A collection manifest
may contain three explicit media reference types:

- `local-file`, with a portable relative path;
- `youtube`, with a video ID and optional canonical URL;
- `http-video`, with a directly playable URL.

Each media reference also describes its delivery and ownership mode:

- `managed-local`: Watchcraft copies or downloads a `local-file` into private
  application storage and owns that installed copy;
- `referenced-local`: Watchcraft records a binding to a user-owned folder and
  never moves or deletes its videos;
- `remote`: Watchcraft streams a `youtube` or `http-video` reference.

Delivery is a media-reference property, not a collection type, so a collection
may mix modes. A legacy `local-file` without `delivery` is treated as
`referenced-local`.

`media_root_hint` is optional installation guidance for referenced-local media.
It is never runtime authority and may be omitted by publishers.

The desktop app copies the manifest, its referenced analysis resources, and
managed-local media into versioned storage under Watchcraft's
private app-data directory.
It records installed collections, the current collection, original source, and
device-local media binding in a private `library.json`. Referenced local videos
remain in place. Hosted URLs remain authored in the portable manifest.

Installation succeeds for exact, partial, and superset local folders. Missing
videos remain unavailable until a suitable binding is supplied; unreferenced
videos are ignored. A URL-installed collection containing `referenced-local`
media prompts for a device-local folder after its metadata is installed.
Settings can locate or change that folder later. Match counts are retained as
local state without changing the portable collection.

Reinstalling or updating a URL collection accepts the same revision only when
its content hash is unchanged, rejects revision downgrades, and installs newer
revisions atomically. The device-local media binding survives an update, while
earlier installed revisions remain in private storage.

There is no central registry of approved collections. Add flows accept a URL or
a folder. Import validation and atomic private installation provide the trust
boundary.

## Consequences

Portable manifests remain immutable authored content, while machine-specific
state is mutable and private. Multiple collections can be installed without
rewriting publisher files. The current UI may continue to display one collection
while the registry supports many. Published metadata and local media can evolve
independently without embedding machine-specific paths in authored content.
