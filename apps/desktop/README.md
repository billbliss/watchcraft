# Watchcraft desktop experiment

This workspace is a deliberately narrow Tauri 2 shell around the shared
Watchcraft React reader. It is isolated on the `experiment/tauri` branch.

The desktop boundary exposes only:

- a native directory picker;
- read-only asset-protocol access to a directory the user selected;
- persisted restoration of that user-approved scope;
- opening a supported video inside that scope with the OS default player.

The default-player command validates both the selected-directory scope and the
video extension before invoking a fixed platform opener. It does not expose
arbitrary filesystem commands, writing, shell execution, downloads, SQLite, or
authoring.

## Run

```sh
npm run desktop:dev
```

Choose a collection folder or its parent. A collection folder is identified
only by `collection.json`; its folder name is not significant. The manifest's
required `media_root` field locates the videos relative to the manifest. The
development build is titled **Watchcraft Dev** and uses a separate app identity
from bundled builds, so it will ask for the library once even if Watchcraft was
configured previously.
