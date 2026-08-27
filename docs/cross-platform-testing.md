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

Test both the local-media and YouTube examples from
`watchcraft-collections` on each OS:

1. Install the local Hello World folder and play the video.
2. Click each chapter and confirm the color changes at the expected timestamp.
3. Confirm **Open in …** launches the OS default video player.
4. Install the Premiere Pro manifest URL and play and seek a YouTube video.
5. Quit and reopen Watchcraft; confirm both collections remain registered.
6. Remove and re-add each collection in Settings.

