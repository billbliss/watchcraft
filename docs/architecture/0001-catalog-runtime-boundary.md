# ADR 0001: Catalog/runtime boundary

- Status: Accepted
- Date: 2026-08-21

## Context

The prototype authors catalogs and emits the entire browser UI from Python. That
was useful while discovering the product, but it couples analysis, storage,
navigation, and presentation. Watchcraft must support a regular web reader, a
desktop application with local-file access, multiple independently updated
collections, and possible future mobile clients.

## Decision

The versioned collection package is the contract between authoring and reading.

Python authoring tools produce a collection manifest plus transcript and analysis
resources. They do not generate or import reader UI. The schema is maintained in
`packages/catalog-schema`; fixtures and compatibility tests are shared by both
Python and TypeScript implementations.

The React renderer talks to a small `CatalogRepository` interface rather than to
the filesystem, SQLite, or HTTP directly. Runtime adapters provide the data:

- the web adapter fetches published collection packages over HTTP;
- the Electron adapter installs packages, records local media mappings, and
  exposes media through a restricted application protocol;
- a future mobile adapter can implement the same repository contract.

Portable collection packages contain stable IDs, relative resource paths, and no
machine-specific absolute paths. A device-local SQLite database records installed
collections, local video locations, package revisions, download state, and user
preferences. Catalog JSON remains the source of truth for authored content;
SQLite is an index and local-state store, not the publishing format.

A device has one Watchcraft catalog containing multiple top-level collections.
Groups beneath a collection may be nested arbitrarily. Topics, topic families,
related-topic links, counts, and noise thresholds are scoped to their top-level
collection and are not implicitly aggregated across collections.

Published collections are discovered through a small remote feed containing
collection identity, current revision, manifest URL, content hash, and optional
package metadata. Updates download to a temporary location, validate against the
schema and hash, and replace the installed revision atomically. Existing data
remains usable while an update is in progress or fails.

Electron owns privileged operations in its main process. The renderer uses
context isolation and a narrow preload API; it receives neither raw Node.js access
nor arbitrary filesystem access.

## Consequences

The current HTML generator remains only as a migration baseline and will be
removed after feature parity. Authoring and reader releases may proceed
independently as long as they honor supported schema versions. Web deployments
cannot discover arbitrary local files; desktop and future mobile shells supply
that platform capability without changing the React UI's data model.

