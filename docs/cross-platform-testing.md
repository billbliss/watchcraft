# Cross-platform desktop testing

Watchcraft's native installers must be built on their target operating systems.
The `Desktop installers` GitHub Actions workflow builds unsigned Windows x64 and
Linux x64 packages without adding any runtime services to the app.

## Automated builds

Open **Actions → Desktop installers → Run workflow** in GitHub. When the two jobs
finish, download these workflow artifacts:

- `watchcraft-windows-x64`: NSIS `.exe` and MSI `.msi` installers;
- `watchcraft-linux-x64`: Debian `.deb` and portable `.AppImage` packages.

Pushing a version tag such as `v0.1.0-beta.1` runs the same workflow. The
artifacts are retained by GitHub Actions; the workflow does not create a public
release or require signing credentials.

Unsigned Windows builds will trigger a SmartScreen warning when downloaded.
Signing is a release concern, not a requirement for this compatibility pass.

## Local Windows build

Install the Tauri Windows prerequisites, Node.js 22, and Rust, then run from the
repository root:

```powershell
npm ci
npm test
npm run desktop:build:windows
```

Installers are written beneath
`apps/desktop/src-tauri/target/release/bundle/`.

## Local Ubuntu build

Install the Tauri Linux prerequisites, Node.js 22, and Rust. On Ubuntu, the
native packages needed by Watchcraft are:

```sh
sudo apt update
sudo apt install -y libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf xdg-utils
npm ci
npm test
npm run desktop:build:linux
```

## Manual smoke pass

Test all three media delivery modes on each OS:

1. Install the managed-local manifest URL:
   `https://billbliss.github.io/watchcraft-collections/collections/hello-world-managed/collection.json`.
2. Play it, seek through all three color chapters, restart Watchcraft, and
   confirm it still plays from private application storage.
3. Download and extract the referenced-local package:
   `https://billbliss.github.io/watchcraft-collections/downloads/hello-world-referenced.zip`.
   Choose the extracted folder in Watchcraft.
4. Play and seek the referenced video, then confirm **Open in …** launches the
   OS default player. Remove the collection and verify its extracted video still exists.
5. Install the remote-media manifest URL:
   `https://billbliss.github.io/watchcraft-collections/collections/premiere-pro-ai-tools/collection.json`.
   Play and seek a YouTube video.
6. Confirm Settings identifies the three modes as **Managed local media**,
   **Referenced local media**, and **Remote media**.
