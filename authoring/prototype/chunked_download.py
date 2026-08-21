#!/usr/bin/env python3
"""Download a large file as independently validated HTTP range chunks."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    index: int
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start + 1


def chunk_plan(total_size: int, chunk_size: int) -> list[Chunk]:
    if total_size <= 0 or chunk_size <= 0:
        raise ValueError("Sizes must be positive")
    chunks: list[Chunk] = []
    for index, start in enumerate(range(0, total_size, chunk_size)):
        chunks.append(
            Chunk(index=index, start=start, end=min(start + chunk_size, total_size) - 1)
        )
    return chunks


def part_path(parts_dir: Path, chunk: Chunk) -> Path:
    return parts_dir / f"part-{chunk.index:05d}.bin"


def download_chunk(url: str, parts_dir: Path, chunk: Chunk) -> tuple[int, bool]:
    destination = part_path(parts_dir, chunk)
    if destination.is_file() and destination.stat().st_size == chunk.size:
        return chunk.index, True

    temporary = destination.with_suffix(".partial")
    command = [
        "curl",
        "-L",
        "--fail",
        "--silent",
        "--show-error",
        "--retry",
        "100",
        "--retry-all-errors",
        "--retry-delay",
        "5",
        "--connect-timeout",
        "30",
        "--max-time",
        "900",
        "--range",
        f"{chunk.start}-{chunk.end}",
        "--output",
        str(temporary),
        url,
    ]
    subprocess.run(command, check=True)
    actual_size = temporary.stat().st_size
    if actual_size != chunk.size:
        raise RuntimeError(
            f"Chunk {chunk.index} has {actual_size} bytes; expected {chunk.size}"
        )
    os.replace(temporary, destination)
    return chunk.index, False


def assemble(output: Path, parts_dir: Path, chunks: list[Chunk]) -> None:
    temporary = output.with_suffix(output.suffix + ".assembling")
    with temporary.open("wb") as destination:
        for chunk in chunks:
            source_path = part_path(parts_dir, chunk)
            if source_path.stat().st_size != chunk.size:
                raise RuntimeError(f"Invalid or missing chunk: {source_path}")
            with source_path.open("rb") as source:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
    expected_size = sum(chunk.size for chunk in chunks)
    if temporary.stat().st_size != expected_size:
        raise RuntimeError("Assembled file size does not match expected size")
    os.replace(temporary, output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--size", required=True, type=int)
    parser.add_argument("--chunk-size", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--workers", type=int, default=4)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    parts_dir = args.output.with_suffix(args.output.suffix + ".parts")
    parts_dir.mkdir(parents=True, exist_ok=True)
    chunks = chunk_plan(args.size, args.chunk_size)

    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(download_chunk, args.url, parts_dir, chunk): chunk
            for chunk in chunks
        }
        for future in concurrent.futures.as_completed(futures):
            index, reused = future.result()
            completed += 1
            disposition = "reused" if reused else "downloaded"
            print(
                f"[{completed}/{len(chunks)}] chunk {index + 1} {disposition}",
                flush=True,
            )

    assemble(args.output, parts_dir, chunks)
    print(f"assembled {args.output} ({args.output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)

