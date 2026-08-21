#!/usr/bin/env python3
"""Serve the catalog locally with video seeking and macOS player launching."""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import subprocess
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from video_catalog import CATALOG_DIR_NAME, VIDEO_EXTENSIONS, validated_root

RANGE_PATTERN = re.compile(r"bytes=(\d*)-(\d*)$")


class CatalogHandler(BaseHTTPRequestHandler):
    root: Path

    def log_message(self, format: str, *args: object) -> None:
        if args and str(args[1]) not in {"200", "204", "206"}:
            super().log_message(format, *args)

    def send_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def resolve_url_path(self) -> Path:
        root = self.root.resolve()
        url_path = unquote(urlsplit(self.path).path)
        if url_path == "/" or re.fullmatch(
            r"/video/[^/]+/?", url_path
        ):
            candidate = root / CATALOG_DIR_NAME / "catalog.html"
        else:
            candidate = root / url_path.lstrip("/")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise PermissionError("path outside collection")
        return resolved

    def parse_range(self, size: int) -> tuple[int, int] | None:
        header = self.headers.get("Range")
        if not header:
            return None
        match = RANGE_PATTERN.fullmatch(header.strip())
        if not match:
            raise ValueError("invalid byte range")
        start_text, end_text = match.groups()
        if not start_text and not end_text:
            raise ValueError("empty byte range")
        if not start_text:
            length = min(int(end_text), size)
            return size - length, size - 1
        start = int(start_text)
        end = min(int(end_text), size - 1) if end_text else size - 1
        if start >= size or end < start:
            raise ValueError("unsatisfiable byte range")
        return start, end

    def serve_file(self, *, head_only: bool = False) -> None:
        try:
            path = self.resolve_url_path()
        except PermissionError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        size = path.stat().st_size
        try:
            byte_range = self.parse_range(size)
        except ValueError:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return

        start, end = byte_range if byte_range else (0, size - 1)
        length = end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT if byte_range else HTTPStatus.OK)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if byte_range:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return

        remaining = length
        with path.open("rb") as handle:
            handle.seek(start)
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    # Browsers routinely abandon one video range request when
                    # pausing, seeking, reloading, or choosing another video.
                    return
                remaining -= len(chunk)

    def do_HEAD(self) -> None:
        self.serve_file(head_only=True)

    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        self.serve_file()

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/open-video":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 64 * 1024:
                raise ValueError("invalid request size")
            payload = json.loads(self.rfile.read(length))
            relative = payload["video"]
            if not isinstance(relative, str):
                raise ValueError("video must be a path")
            root = self.root.resolve()
            target = (root / relative).resolve()
            if not target.is_relative_to(root):
                raise ValueError("path outside collection")
            if not target.is_file() or target.suffix.lower() not in VIDEO_EXTENSIONS:
                raise FileNotFoundError(relative)
            subprocess.run(["/usr/bin/open", str(target)], check=True)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Invalid video path"})
            return
        except FileNotFoundError:
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Video not found"})
            return
        except subprocess.CalledProcessError:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "macOS could not open the video"})
            return
        self.send_json(HTTPStatus.OK, {"ok": True})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=validated_root)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the catalog in the default browser")
    args = parser.parse_args()

    handler = type("ConfiguredCatalogHandler", (CatalogHandler,), {"root": args.root})
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Video Catalog is available at {url}")
    print("Keep this window open while using the catalog; press Control-C to stop.")
    if args.open:
        webbrowser.open_new_tab(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCatalog stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
