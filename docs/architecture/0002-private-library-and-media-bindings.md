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

`media_root_hint` is optional installation guidance for local-file collections.
It is never runtime authority and may be omitted by publishers.

The desktop app copies the manifest and its referenced analysis/transcript
resources into versioned storage under Watchcraft's private app-data directory.
It records installed collections, the current collection, original source, and
device-local media binding in a private `library.json`. Local videos remain in
place. Hosted URLs remain authored in the portable manifest.

Installation succeeds for exact, partial, and superset local folders. Missing
videos remain unavailable until a suitable binding is supplied; unreferenced
videos are ignored. Match counts are retained as local state so a future
settings/install UI can explain the result without changing the collection.

There is no central registry of approved collections. Future add flows may
accept a URL, a manifest file, or a folder. Import validation and atomic private
installation provide the trust boundary.

## Consequences

Portable manifests remain immutable authored content, while machine-specific
state is mutable and private. Multiple collections can be installed without
rewriting publisher files. The current UI may continue to display one collection
while the registry and repository boundary grow to support many. YouTube player
integration and remote collection acquisition are deferred until a real hosted
collection is available.
