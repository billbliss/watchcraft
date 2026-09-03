# Watchcraft web app

This is the portable React + TypeScript reader. It consumes collection packages
through the shared repository interface and builds as an ordinary static web
application.

The app must not import Electron, Python, filesystem APIs, or authored catalog
content into its source bundle.

On a first visit, the app opens Settings with a featured web-video collection
picker. Featured collections come from the public collection directory, with
the published “Essence of linear algebra” collection bundled as a fallback if
the directory is unavailable. Pass `?catalog=<manifest-url>` to open a specific
collection published by any ordinary HTTP server:

```text
https://watchcraft.stream/app/?catalog=https://example.com/courses/collection.json
```

The production build is published beneath `/app/` as part of the same GitHub
Pages artifact as the Watchcraft homepage. It remembers the most recently opened
collection in browser storage. Video selection uses a query parameter so shared
and refreshed URLs continue to work on static hosting without a rewrite rule.

Local filesystem collections are tested through the Tauri desktop adapter, not
through a Python web server.

Public YouTube items play through `youtube-nocookie.com`; chapter navigation uses
the embedded-player command API. Local filesystem media remains a desktop-only
capability. Collections with fewer than five videos bypass corpus-frequency
filtering because percentage and repetition thresholds are not meaningful at
that size.

Topic labels are compact UI names. Search and the topic facet also match their
canonical keys and longer source aliases, preserving the analytical detail that
was removed from display.
