# Watchcraft build channels and releases

Watchcraft has three deliberately separate build channels:

- **Development** runs locally as `Watchcraft Dev` with the identifier
  `app.watchcraft.reader.dev`. It is never distributed.
- **Beta** is built from prerelease tags such as `v0.1.0-beta.1`. It is
  published as a GitHub prerelease under the name `Watchcraft Beta` with the
  identifier `app.watchcraft.reader.beta` and a separate private data folder.
- **Release** is built from stable tags such as `v0.1.0`. It is published as a
  normal GitHub Release under the name `Watchcraft` with the production
  identifier `app.watchcraft.reader`.

## Publishing a beta

Start from a clean, tested `main` branch. Create and push an annotated tag:

```sh
git tag -a v0.1.0-beta.1 -m "Watchcraft 0.1.0 beta 1"
git push origin v0.1.0-beta.1
```

The `Desktop installers` workflow builds Windows x64, Linux x64, and macOS
Apple Silicon packages. After every platform succeeds, it creates a GitHub
prerelease and attaches the installers. The public Watchcraft site discovers
the prerelease through the GitHub API, so no download links need to be edited.
Windows beta builds publish the NSIS `.exe` installer only because MSI does not
accept named semantic-version prerelease identifiers such as `beta.1`. Stable
Windows releases publish both `.exe` and `.msi` installers.

Increment only the beta suffix for another candidate:

```sh
git tag -a v0.1.0-beta.2 -m "Watchcraft 0.1.0 beta 2"
git push origin v0.1.0-beta.2
```

## Publishing a stable release

After validating the beta, create the corresponding stable tag:

```sh
git tag -a v0.1.0 -m "Watchcraft 0.1.0"
git push origin v0.1.0
```

The same workflow builds the production identity and creates a normal GitHub
Release. GitHub then treats it as the latest stable release, and the public site
lists it separately from the newest beta.

## Untagged workflow runs

A manual `Desktop installers` run can select either the Beta or Release build
identity for testing. Its files are ordinary expiring Actions artifacts. It
does not create a GitHub Release. Pull requests build the Beta identity.

Published installers are currently unsigned. Signing, Apple notarization, and
Windows reputation are later release-hardening steps; they do not change the
channel or versioning model.
