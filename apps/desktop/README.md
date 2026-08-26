# Watchcraft desktop app

This workspace is a deliberately narrow Tauri 2 shell around the shared
Watchcraft React reader.

The desktop boundary exposes only:

- a native directory picker;
- read-only asset-protocol access to a directory the user selected;
- a private collection registry and metadata cache;
- persisted local-media bindings and restoration of their approved scope;
- opening a supported video inside that scope with the OS default player.

The default-player command validates both the selected-directory scope and the
video extension before invoking a fixed platform opener. It does not expose
arbitrary filesystem commands, shell execution, downloads, SQLite, or authoring.
Its only writes are versioned collection metadata and `library.json` inside
Watchcraft's private app-data directory.

## Run

```sh
npm run desktop:dev
```

Choose a collection folder or its parent. A manifest is identified by
`kind: "watchcraft.collection"`; neither its filename nor its folder name is
significant. The optional `media_root_hint` is consulted only while installing
the collection. The resulting local-video binding is stored privately. The
development build is titled **Watchcraft Dev** and uses a separate app identity
from bundled builds, so it will ask for the library once even if Watchcraft was
configured previously.
