#!/usr/bin/env python3
"""Generate/update placeholder manifest entries for large files.

Creates/updates placeholders/manifest.json with metadata for each target file:
- target_relpath
- basename
- size_bytes
- sha256
- optional source_url

Inputs can be files and/or directories. Directories are scanned recursively.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

DEFAULT_MANIFEST = Path("placeholders/manifest.json")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_files(inputs: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in inputs:
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            out.extend(sorted([x for x in p.rglob("*") if x.is_file()]))
        else:
            raise RuntimeError(f"Path not found: {p}")
    # stable unique
    seen = set()
    uniq = []
    for p in out:
        rp = str(p.resolve())
        if rp not in seen:
            seen.add(rp)
            uniq.append(p)
    return uniq


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "entries": []}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {"version": 1, "entries": []}
    data = json.loads(raw)
    if not isinstance(data, dict) or "entries" not in data:
        raise RuntimeError(f"Invalid manifest format: {path}")
    if not isinstance(data["entries"], list):
        raise RuntimeError(f"Invalid manifest entries list: {path}")
    return data


def save_manifest(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def upsert_entries(manifest: dict, new_entries: list[dict]):
    by_target = {}
    for entry in manifest.get("entries", []):
        by_target[entry["target_relpath"]] = entry
    for entry in new_entries:
        by_target[entry["target_relpath"]] = entry
    manifest["entries"] = sorted(by_target.values(), key=lambda e: e["target_relpath"])


def main():
    ap = argparse.ArgumentParser(description="Generate placeholder manifest entries.")
    ap.add_argument("paths", nargs="+", help="File(s) and/or folder(s) to include")
    ap.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Manifest JSON path (default: placeholders/manifest.json)",
    )
    ap.add_argument(
        "--source-url",
        default="",
        help="Optional download/storage URL to include for generated entries",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview entries without writing manifest",
    )
    args = ap.parse_args()

    repo_root = Path.cwd().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()

    inputs = [Path(p).expanduser().resolve() for p in args.paths]
    files = collect_files(inputs)
    if not files:
        raise RuntimeError("No files found from input paths.")

    new_entries = []
    for f in files:
        try:
            rel = f.resolve().relative_to(repo_root)
        except Exception:
            raise RuntimeError(f"Input must be inside repo root ({repo_root}): {f}")
        entry = {
            "target_relpath": rel.as_posix(),
            "basename": f.name,
            "size_bytes": f.stat().st_size,
            "sha256": sha256_file(f),
        }
        if args.source_url:
            entry["source_url"] = args.source_url
        new_entries.append(entry)

    manifest = load_manifest(manifest_path)
    upsert_entries(manifest, new_entries)

    print("=== Generate Placeholders ===")
    print(f"Repo root      : {repo_root}")
    print(f"Manifest       : {manifest_path}")
    print(f"Files scanned  : {len(files)}")
    print(f"Entries upsert : {len(new_entries)}")
    print(f"Dry run        : {'yes' if args.dry_run else 'no'}")

    if not args.dry_run:
        save_manifest(manifest_path, manifest)
        print("Manifest write : success")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
