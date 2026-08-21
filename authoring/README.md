# Authoring

Watchcraft authoring is a Python toolchain that turns source media, transcripts,
and analysis into versioned collection packages. Authors may clone this repository
and run the tools locally; authoring is not required by the reader application.

`prototype/` is the current working implementation imported as a behavioral
baseline. It still includes the legacy HTML generator and local server. During
the reader migration, catalog generation will be retained and presentation code
will move to `apps/web` and `packages/ui`.

The authoring output must validate against `packages/catalog-schema` and must not
contain absolute paths to an author's media files.

