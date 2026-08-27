# Watchcraft desktop app

This workspace is a deliberately narrow Tauri 2 shell around the shared
Watchcraft React reader.

The desktop boundary exposes only:

- a native directory picker;
- read-only asset-protocol access to a directory the user selected;
- a private collection registry and metadata cache;
- persisted local-media bindings and restoration of their approved scope;
- managed local-media copies stored only under private application data;
- opening a supported video inside that scope with the OS default player.

The default-player command validates both the selected-directory scope and the
video extension before invoking a fixed platform opener. It does not expose
arbitrary filesystem commands, shell execution, arbitrary downloads, SQLite, or
authoring. Its collection installer downloads only manifest-declared resources
into private application storage.
Its only writes are versioned collection metadata and `library.json` inside
Watchcraft's private app-data directory.

## Run

```sh
npm run desktop:dev
```

Choose a collection folder or its parent. A manifest is identified by
`kind: "watchcraft.collection"`; neither its filename nor its folder name is
significant. The optional `media_root_hint` is consulted only while installing
referenced local media. Managed local media is copied or downloaded into private
storage; referenced files remain in place and their binding is stored privately. The
development build is titled **Watchcraft Dev** and uses a separate app identity
from bundled builds, so it will ask for the library once even if Watchcraft was
configured previously.

## Build channels

- **Watchcraft Dev** is the local development app and has its own identity and
  private settings.
- **Watchcraft Beta** is produced by prerelease tags such as
  `v0.1.0-beta.1`. It can be installed alongside the stable app and keeps a
  separate collection registry.
- **Watchcraft** is produced by stable tags such as `v0.1.0` and uses the
  production identity and settings.

To build the beta identity locally, run `npm run desktop:build:beta` from the
repository root. See `docs/releases.md` for the tag-driven release process.
