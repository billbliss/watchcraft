# Cross-platform desktop testing

Watchcraft's native installers must be built on their target operating systems.
The `Desktop installers` GitHub Actions workflow builds unsigned Windows x64,
Linux x64, and macOS Apple Silicon packages without adding any runtime services
to the app.

## Automated builds

Open **Actions → Desktop installers → Run workflow** in GitHub. When the three jobs
finish, download these workflow artifacts:

- `watchcraft-beta-windows-x64`: NSIS `.exe` installer (stable Windows builds
  also include MSI);
- `watchcraft-beta-linux-x64`: Debian `.deb` and portable `.AppImage` packages;
- `watchcraft-beta-macos-arm64`: Apple Silicon `.dmg` package.

Pushing a prerelease tag such as `v0.1.0-beta.1` runs the same workflow and
creates a permanent GitHub prerelease with all installers attached. A stable tag
such as `v0.1.0` creates a normal GitHub Release. See [the release
guide](releases.md) for the channel rules. No signing credentials are currently
required.

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
   Add its URL-installed manifest:
   `https://billbliss.github.io/watchcraft-collections/collections/hello-world-referenced/collection.json`.
   Confirm Watchcraft prompts for the videos, then choose the extracted folder.
4. Play and seek the referenced video, then confirm **Open in …** launches the
   OS default player. Use **Change folder** in Settings and bind the same folder
   again. Remove the collection and verify its extracted video still exists.
5. Install the Web Video collection manifest URL:
   `https://billbliss.github.io/watchcraft-collections/collections/premiere-pro-ai-tools/collection.json`.
   Play and seek a YouTube video. On Linux, confirm the player does not report
   configuration error 153 when opened or after seeking.
6. Confirm Settings identifies the three modes as **Managed local media**,
   **Referenced local media**, and **Web Video**.
7. With Watchcraft closed, open a collection link from `watchcraft.stream` and
   confirm the browser launches the installed app, Watchcraft asks before
   installing, and the collection opens. Repeat while Watchcraft is already
   running to verify single-instance delivery. Test a beta build with both the
   public `watchcraft://` form and the explicit `watchcraft-beta://` form. Test a
   stable build with `watchcraft://`.

Installed Debian packages should register these links through the desktop entry.
An AppImage may require desktop integration; moving it after registration can
invalidate the handler because Linux records its absolute executable path.
