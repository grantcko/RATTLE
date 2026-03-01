#!/usr/bin/env python3
"""Create mirrored folder copies that contain symlinks to source files.

Example:
  python3 scripts/create_symlinked_hot_storage.py \
    "/Volumes/COCO/RATTLE/footage" \
    "/Volumes/TASTY/RATTLE/00-SOURCE/footage" \
    --recursive
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Mirror immediate child folders from cold storage into hot storage, "
            "creating symlinks for files."
        )
    )
    parser.add_argument(
        "cold_storage_root",
        help="Source root folder (cold storage). Its immediate child folders are mirrored.",
    )
    parser.add_argument(
        "hot_storage_root",
        help="Destination root folder (hot storage). Mirrored child folders are created here.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without creating links.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Include files in nested subfolders (default: only top-level files).",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace existing destination files/symlinks when conflicts occur.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each created/skipped/replaced link.",
    )
    return parser.parse_args()


def safe_unlink(path: Path):
    if path.is_dir() and not path.is_symlink():
        raise RuntimeError(f"Refusing to remove real directory: {path}")
    path.unlink()


def main():
    args = parse_args()
    cold_root = Path(args.cold_storage_root).expanduser().resolve()
    hot_root = Path(args.hot_storage_root).expanduser().resolve()

    if not cold_root.exists() or not cold_root.is_dir():
        raise RuntimeError(f"Cold storage root not found: {cold_root}")

    if not args.dry_run:
        hot_root.mkdir(parents=True, exist_ok=True)

    created = 0
    replaced = 0
    skipped = 0
    source_folder_count = 0

    source_dirs = sorted(p for p in cold_root.iterdir() if p.is_dir())
    for src_dir in source_dirs:
        source_folder_count += 1
        dest_day = hot_root / src_dir.name
        if not args.dry_run:
            dest_day.mkdir(parents=True, exist_ok=True)

        if args.recursive:
            source_files = sorted(p for p in src_dir.rglob("*") if p.is_file())
        else:
            source_files = sorted(p for p in src_dir.iterdir() if p.is_file())

        for src_file in source_files:
            rel = src_file.relative_to(src_dir)
            dst = dest_day / rel

            if not args.dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)

            if dst.exists() or dst.is_symlink():
                if args.replace:
                    if args.verbose:
                        print(f"REPLACE: {dst} -> {src_file}")
                    if not args.dry_run:
                        safe_unlink(dst)
                        os.symlink(str(src_file), str(dst))
                    replaced += 1
                else:
                    if args.verbose:
                        print(f"SKIP existing: {dst}")
                    skipped += 1
                continue

            if args.verbose:
                action = "DRY LINK" if args.dry_run else "LINK"
                print(f"{action}: {dst} -> {src_file}")

            if not args.dry_run:
                os.symlink(str(src_file), str(dst))
            created += 1

    print(
        "SUMMARY "
        f"source_folders={source_folder_count} created={created} replaced={replaced} skipped={skipped} "
        f"dry_run={'yes' if args.dry_run else 'no'}"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user (Ctrl-C).", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
