#!/usr/bin/env python3
"""Materialize placeholder targets from downloaded files.

Reads placeholders/manifest.json and for each entry finds matching file under --source-dir.
Then either:
- move source file into repo target path, or
- create symlink at target path pointing to source file
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MANIFEST = Path("placeholders/manifest.json")


@dataclass
class Entry:
    target_relpath: str
    basename: str
    size_bytes: int
    sha256: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_entries(manifest_path: Path) -> list[Entry]:
    if not manifest_path.exists():
        raise RuntimeError(f"Manifest not found: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_entries = data.get("entries", [])
    out = []
    for r in raw_entries:
        out.append(
            Entry(
                target_relpath=r["target_relpath"],
                basename=r["basename"],
                size_bytes=int(r["size_bytes"]),
                sha256=str(r["sha256"]),
            )
        )
    return out


def build_source_index(source_dir: Path) -> dict[str, list[Path]]:
    idx: dict[str, list[Path]] = {}
    for p in source_dir.rglob("*"):
        if p.is_file():
            idx.setdefault(p.name.lower(), []).append(p)
    return idx


def choose_source(entry: Entry, index: dict[str, list[Path]]) -> Path | None:
    candidates = index.get(entry.basename.lower(), [])
    if not candidates:
        return None

    # Fast filter by size first.
    sized = [p for p in candidates if p.stat().st_size == entry.size_bytes]
    if not sized:
        return None

    # Verify by sha256 to avoid wrong file picks.
    for p in sized:
        if sha256_file(p) == entry.sha256:
            return p
    return None


def materialize_target(target: Path, source: Path, mode: str, overwrite: bool):
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() or target.is_symlink():
        if not overwrite:
            raise RuntimeError(f"Target exists (use --overwrite): {target}")
        if target.is_dir() and not target.is_symlink():
            raise RuntimeError(f"Refusing to overwrite directory target: {target}")
        target.unlink()

    if mode == "move":
        shutil.move(str(source), str(target))
    elif mode == "symlink":
        os.symlink(str(source.resolve()), str(target))
    else:
        raise RuntimeError(f"Unsupported mode: {mode}")


def main():
    ap = argparse.ArgumentParser(description="Replace placeholders by moving/symlinking real files.")
    ap.add_argument("--source-dir", required=True, help="Folder containing downloaded files")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Manifest JSON path")
    ap.add_argument("--mode", choices=["move", "symlink"], default="symlink")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing target files")
    ap.add_argument("--dry-run", action="store_true", help="Preview actions without changing files")
    args = ap.parse_args()

    repo_root = Path.cwd().resolve()
    source_dir = Path(args.source_dir).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()

    if not source_dir.exists() or not source_dir.is_dir():
        raise RuntimeError(f"Source dir not found: {source_dir}")

    entries = load_entries(manifest_path)
    if not entries:
        raise RuntimeError("Manifest has no entries.")

    index = build_source_index(source_dir)

    matched = []
    missing = []
    for e in entries:
        src = choose_source(e, index)
        if src is None:
            missing.append(e)
        else:
            matched.append((e, src))

    print("=== Replace Placeholders ===")
    print(f"Repo root      : {repo_root}")
    print(f"Manifest       : {manifest_path}")
    print(f"Source dir     : {source_dir}")
    print(f"Mode           : {args.mode}")
    print(f"Entries total  : {len(entries)}")
    print(f"Matched        : {len(matched)}")
    print(f"Missing        : {len(missing)}")
    print(f"Dry run        : {'yes' if args.dry_run else 'no'}")

    if missing:
        for e in missing[:30]:
            print(f"  - missing: {e.target_relpath} ({e.basename})")
        if len(missing) > 30:
            print(f"  - ... and {len(missing)-30} more")

    if args.dry_run:
        return

    for e, src in matched:
        target = repo_root / e.target_relpath
        materialize_target(target, src, args.mode, args.overwrite)

    print("Materialize     : success")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
