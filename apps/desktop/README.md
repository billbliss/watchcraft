# Watchcraft desktop experiment

This workspace is a deliberately narrow Tauri 2 shell around the shared
Watchcraft React reader. It is isolated on the `experiment/tauri` branch.

The desktop boundary exposes only:

- a native directory picker;
- read-only asset-protocol access to a directory the user selected;
- persisted restoration of that user-approved scope.

It does not expose arbitrary filesystem commands, writing, shell execution,
downloads, SQLite, authoring, or custom Rust commands.

## Run

```sh
npm run desktop:dev
```

Choose the root of a local video library. The adapter recognizes both a
portable `collection.json` at that root and the current
`Video Catalog/collection.json` layout.
