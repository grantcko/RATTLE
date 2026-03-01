#!/usr/bin/env python3
"""Manually relink stale Resolve source-bin clips to files under a source folder."""

from __future__ import annotations

import argparse
from pathlib import Path

from import_hot_storage import (
    TARGET_BIN_NAME,
    clip_name,
    clip_file_path,
    collect_bin_item_rows,
    find_child_folder,
    folder_name,
    load_resolve_script_module,
    path_matches_source_set,
    use_source_root_subbin,
    validate_source_of_truth,
    walk_folders,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Relink stale/offline clips in Resolve source bin to matching files under a source folder."
        )
    )
    parser.add_argument("source_folder", help="Filesystem source folder (usually 00-SOURCE)")
    parser.add_argument(
        "--target-bin",
        default=TARGET_BIN_NAME,
        help=f"Resolve target bin name. Default: {TARGET_BIN_NAME}",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply relinks. Without this flag the script is dry-run only.",
    )
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    parser.add_argument(
        "--max-log",
        type=int,
        default=200,
        help="Maximum number of item lines to print. Default: %(default)s",
    )
    return parser.parse_args()


def clip_file_name(clip):
    get_prop = getattr(clip, "GetClipProperty", None)
    if callable(get_prop):
        for key in ("File Name", "Clip Name"):
            try:
                val = get_prop(key)
            except Exception:
                val = ""
            if isinstance(val, str) and val.strip():
                return val.strip()
    return clip_name(clip)


def build_source_basename_index(source_files):
    index = {}
    for p in source_files:
        index.setdefault(p.name.lower(), []).append(p)
    return index


def try_replace_clip(clip_obj, matched_path: Path) -> bool:
    targets = [clip_obj]
    mp_item_fn = getattr(clip_obj, "GetMediaPoolItem", None)
    if callable(mp_item_fn):
        try:
            mp_item = mp_item_fn()
        except Exception:
            mp_item = None
        if mp_item:
            targets.append(mp_item)

    for target in targets:
        replace_fn = getattr(target, "ReplaceClip", None)
        if not callable(replace_fn):
            continue
        try:
            if replace_fn(str(matched_path)):
                return True
        except Exception:
            continue
    return False


def relink_clip(media_pool, row, matched_path: Path) -> bool:
    folder_obj = row["folder_obj"]
    clip_obj = row["clip_obj"]
    if not media_pool.SetCurrentFolder(folder_obj):
        return False
    if try_replace_clip(clip_obj, matched_path):
        return True
    relink_fn = getattr(media_pool, "RelinkClips", None)
    if callable(relink_fn):
        try:
            return bool(relink_fn([clip_obj], str(matched_path.parent)))
        except Exception:
            return False
    return False


def stale_or_offline(path: str) -> bool:
    if not path:
        return True
    s = path.strip()
    if not s:
        return True
    if s.upper().startswith("OFFLINE"):
        return True
    return "/.dead_media/" in s


def row_file_name(row) -> str:
    clip_obj = row.get("clip_obj")
    if clip_obj:
        name = clip_file_name(clip_obj).strip()
        if name:
            return name
    path = row.get("path") or ""
    if path:
        return Path(path).name
    return row.get("clip_name") or ""


def row_relative_dir(row, root_bin_name: str) -> Path:
    bin_path = row.get("bin_path") or root_bin_name
    parts = bin_path.split("/")
    if parts and parts[0] == root_bin_name:
        parts = parts[1:]
    if not parts:
        return Path(".")
    return Path(*parts)


def main():
    args = parse_args()
    source_folder = Path(args.source_folder).expanduser().resolve()
    if not source_folder.exists() or not source_folder.is_dir():
        raise RuntimeError(f"Source folder not found: {source_folder}")

    source_files = [p for p in source_folder.rglob("*") if p.is_file()]
    source_set = {str(p.resolve()) for p in source_files}
    basename_index = build_source_basename_index(source_files)

    resolve_module = load_resolve_script_module()
    resolve = resolve_module.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to DaVinci Resolve.")
    pm = resolve.GetProjectManager()
    if not pm:
        raise RuntimeError("Could not access Project Manager.")
    project = pm.GetCurrentProject()
    if not project:
        raise RuntimeError("No current Resolve project is open.")
    media_pool = project.GetMediaPool()
    if not media_pool:
        raise RuntimeError("Could not access Media Pool.")
    root = media_pool.GetRootFolder()
    if not root:
        raise RuntimeError("Could not access Media Pool root.")

    bins = [f for f in walk_folders(root) if folder_name(f) == args.target_bin]
    if len(bins) > 1:
        raise RuntimeError(f"Multiple bins named '{args.target_bin}' found.")
    if not bins:
        raise RuntimeError(f"Bin '{args.target_bin}' not found.")
    target_bin = bins[0]

    include_source_root_subbin = use_source_root_subbin(folder_name(target_bin), source_folder.name)
    if include_source_root_subbin:
        import_scope_bin = find_child_folder(target_bin, source_folder.name) or target_bin
    else:
        import_scope_bin = target_bin

    rows = collect_bin_item_rows(import_scope_bin)
    root_bin_name = folder_name(import_scope_bin)
    candidates = []
    unresolved = []
    ambiguous = []
    skipped = 0

    for row in rows:
        path = row.get("path") or ""
        if path and path_matches_source_set(path, source_set):
            continue
        if not stale_or_offline(path):
            skipped += 1
            continue

        file_name = row_file_name(row)
        if not file_name:
            unresolved.append((row, "missing-name"))
            continue

        rel_dir = row_relative_dir(row, root_bin_name)
        same_folder_target = source_folder / rel_dir / file_name
        if same_folder_target.exists():
            candidates.append((row, same_folder_target.resolve(), "same-folder"))
            continue

        name_hits = basename_index.get(file_name.lower(), [])
        if len(name_hits) == 1:
            candidates.append((row, name_hits[0].resolve(), "unique-basename"))
            continue
        if len(name_hits) > 1:
            ambiguous.append((row, len(name_hits)))
            continue
        unresolved.append((row, "not-found"))

    print("=== Manual Relink Preview ===")
    print(f"Project           : {project.GetName()}")
    print(f"Target Bin        : {folder_name(target_bin)}")
    print(f"Import Scope Bin  : {folder_name(import_scope_bin)}")
    print(f"Source Folder     : {source_folder}")
    print(f"Relink candidates : {len(candidates)}")
    print(f"Ambiguous         : {len(ambiguous)}")
    print(f"Unresolved        : {len(unresolved)}")
    print(f"Skipped non-stale : {skipped}")
    print("")

    for idx, (row, target, reason) in enumerate(candidates[: args.max_log], start=1):
        print(
            f"{idx}. [{row['bin_path']}] {row['clip_name']} :: {row['path']} -> {target} ({reason})"
        )
    if len(candidates) > args.max_log:
        print(f"... and {len(candidates) - args.max_log} more candidate(s)")

    if ambiguous:
        print("")
        print("Ambiguous items:")
        for idx, (row, count) in enumerate(ambiguous[: args.max_log], start=1):
            print(f"{idx}. [{row['bin_path']}] {row['clip_name']} :: {row['path']} ({count} matches)")
        if len(ambiguous) > args.max_log:
            print(f"... and {len(ambiguous) - args.max_log} more ambiguous item(s)")

    if unresolved:
        print("")
        print("Unresolved items:")
        for idx, (row, reason) in enumerate(unresolved[: args.max_log], start=1):
            print(f"{idx}. [{row['bin_path']}] {row['clip_name']} :: {row['path']} ({reason})")
        if len(unresolved) > args.max_log:
            print(f"... and {len(unresolved) - args.max_log} more unresolved item(s)")

    if not args.apply:
        print("")
        print("Dry-run only. Re-run with --apply to perform relinks.")
        return

    if not args.yes:
        reply = input(f"Relink {len(candidates)} item(s)? [y/N]: ").strip().lower()
        if reply not in {"y", "yes"}:
            print("Aborted.")
            return

    success = 0
    failed = 0
    for row, target, _reason in candidates:
        if relink_clip(media_pool, row, target):
            success += 1
        else:
            failed += 1

    print("")
    print(f"Relink applied. success={success}, failed={failed}")

    validation = validate_source_of_truth(
        import_scope_bin=import_scope_bin,
        source_folder=source_folder,
        source_files=source_files,
        recursive=True,
        include_source_root_subbin=include_source_root_subbin,
    )
    if validation["ok"]:
        print("Source-of-truth validation: OK")
    else:
        print(
            "Source-of-truth validation still failing: "
            f"no_path={len(validation['no_path'])}, "
            f"extra={len(validation['extra'])}, "
            f"stale_folders={len(validation['stale_folders'])}"
        )


if __name__ == "__main__":
    main()

