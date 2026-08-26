# Watchcraft web app

This is the portable React + TypeScript reader. It consumes collection packages
through the shared repository interface and builds as an ordinary static web
application.

The app must not import Electron, Python, filesystem APIs, or authored catalog
content into its source bundle.

The default development catalog is a metadata-only fixture under `public/demo`.
Pass `?catalog=<manifest-url>` to use a collection published by any ordinary
HTTP server:

```text
?catalog=https://example.com/courses/collection.json
```

Local filesystem collections are tested through the Tauri desktop adapter, not
through a Python web server.
