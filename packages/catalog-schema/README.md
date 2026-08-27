# Catalog schema

This package owns the portable Watchcraft collection contract. `collection.schema.json`
describes the current collection manifest emitted by the Python authoring toolchain.

Schema changes must be versioned. Authoring validates its output, and readers
reject unsupported versions without damaging an already installed collection.
