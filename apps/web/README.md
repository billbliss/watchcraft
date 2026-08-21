# Watchcraft web app

This is the portable React + TypeScript reader. It consumes collection packages
through the shared repository interface and builds as an ordinary static web
application.

The app must not import Electron, Python, filesystem APIs, or authored catalog
content into its source bundle.

The default development catalog is a metadata-only fixture under `public/demo`.
Pass `?catalog=<manifest-url>` to use another catalog. For the existing Python
server, use:

```text
?catalog=http://127.0.0.1:8765/Video%20Catalog/collection.json
```
