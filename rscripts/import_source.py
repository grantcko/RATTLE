#!/usr/bin/env python3
"""Import files from a filesystem folder into a named Resolve Media Pool bin."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import re
import sys
from fnmatch import fnmatch
from pathlib import Path

SCRIPT_MODULE_NAME = "DaVinciResolveScript"
TARGET_BIN_NAME = "00-SOURCE"
ALLOWED_SOURCE_FOLDER_NAME = "00-SOURCE"
# Fuzzy project-name guardrail. Change this when reusing the script.
EXPECTED_PROJECT_FUZZY = "rattle"
DEFAULT_IGNORE_PATTERNS = [
    ".DS_Store",
    "**/.DS_Store",
    ".gitkeep",
    "**/.gitkeep",
    "__MACOSX/**",
    "**/__MACOSX/**",
    "._*",
    "**/._*",
    "*.mdt",
    "**/*.mdt",
    "*.pdf",
    "**/*.pdf",
    "*.txt",
    "**/*.txt",
]
MODULE_PATH_CANDIDATES = [
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py",
    os.path.expandvars(
        "$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py"
    ),
]


def load_resolve_script_module():
    module_dirs = []
    for path in MODULE_PATH_CANDIDATES:
        parent = str(Path(path).parent)
        if Path(parent).exists():
            module_dirs.append(parent)

    for module_dir in reversed(module_dirs):
        if module_dir in sys.path:
            sys.path.remove(module_dir)
        sys.path.insert(0, module_dir)

    if SCRIPT_MODULE_NAME in sys.modules:
        mod = sys.modules[SCRIPT_MODULE_NAME]
        if hasattr(mod, "scriptapp"):
            return mod
        del sys.modules[SCRIPT_MODULE_NAME]

    try:
        mod = importlib.import_module(SCRIPT_MODULE_NAME)
        if hasattr(mod, "scriptapp"):
            return mod
    except ImportError:
        pass

    for path in MODULE_PATH_CANDIDATES:
        module_path = Path(path)
        if not module_path.exists():
            continue
        spec = importlib.util.spec_from_file_location(SCRIPT_MODULE_NAME, module_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "scriptapp"):
                return module

    raise RuntimeError("Could not load DaVinciResolveScript with scriptapp().")


def folder_name(folder):
    try:
        return folder.GetName() or "<unnamed>"
    except Exception:
        return "<unknown>"


def subfolders(folder):
    fn = getattr(folder, "GetSubFolderList", None)
    if callable(fn):
        return list(fn() or [])
    return []


def walk_folders(folder):
    yield folder
    for child in subfolders(folder):
        yield from walk_folders(child)


def clips(folder):
    fn = getattr(folder, "GetClipList", None)
    if callable(fn):
        return list(fn() or [])
    return []


def clip_name(clip):
    fn = getattr(clip, "GetName", None)
    if callable(fn):
        try:
            return fn() or "<unnamed-clip>"
        except Exception:
            return "<unknown-clip>"
    return "<unknown-clip>"


def clip_file_path(clip):
    get_prop = getattr(clip, "GetClipProperty", None)
    if callable(get_prop):
        for key in ("File Path", "Clip Path"):
            try:
                val = get_prop(key)
            except Exception:
                val = ""
            if isinstance(val, str) and val.strip():
                return val.strip()
    mp_item_fn = getattr(clip, "GetMediaPoolItem", None)
    if callable(mp_item_fn):
        try:
            mp_item = mp_item_fn()
        except Exception:
            mp_item = None
        if mp_item:
            get_prop2 = getattr(mp_item, "GetClipProperty", None)
            if callable(get_prop2):
                for key in ("File Path", "Clip Path"):
                    try:
                        val = get_prop2(key)
                    except Exception:
                        val = ""
                    if isinstance(val, str) and val.strip():
                        return val.strip()
    return ""


def norm_path_str(p: str) -> str:
    pp = Path(p).expanduser()
    try:
        return str(pp.resolve())
    except Exception:
        return str(pp)


def file_identity(path_str: str):
    """Return stable file identity for symlink-aware matching.

    Uses followed symlink target identity (device, inode) when available.
    """
    try:
        st = Path(path_str).expanduser().stat()
    except Exception:
        return None
    return (st.st_dev, st.st_ino)


def collect_existing_paths_under_bin(target_bin):
    existing = set()
    for f in walk_folders(target_bin):
        for c in clips(f):
            p = clip_file_path(c)
            if p:
                existing.add(norm_path_str(p))
    return existing


def collect_bin_item_rows(target_bin):
    rows = []
    root_name = folder_name(target_bin)

    def walk(folder, path_parts):
        for c in clips(folder):
            raw_path = clip_file_path(c)
            rows.append(
                {
                    "folder": folder_name(folder),
                    "folder_obj": folder,
                    "bin_path": "/".join(path_parts),
                    "clip_name": clip_name(c),
                    "clip_obj": c,
                    "path": norm_path_str(raw_path) if raw_path else "",
                }
            )
        for child in subfolders(folder):
            walk(child, path_parts + [folder_name(child)])

    walk(target_bin, [root_name])
    return rows


def collect_source_relative_dirs(source_folder: Path, recursive: bool):
    """Return source-relative directory paths expected to exist in mirrored bins.

    Includes "." for the source root itself.
    """
    dirs = {Path(".")}
    if recursive:
        for p in source_folder.rglob("*"):
            if p.is_dir():
                dirs.add(p.relative_to(source_folder))
    return dirs


def collect_bin_folder_rows_under_source_root(
    import_scope_bin,
    source_root_name: str,
    include_source_root_subbin: bool,
):
    """Return folder rows in import scope mapped to source-relative paths."""
    root_name = folder_name(import_scope_bin)
    rows = []

    def walk(folder, rel_parts):
        if rel_parts:
            rel_path = "/".join(rel_parts)
        else:
            rel_path = "."
        full_path = root_name
        if rel_path != ".":
            full_path = f"{full_path}/{rel_path}"
        rows.append(
            {
                "folder_obj": folder,
                "folder_name": folder_name(folder),
                "source_rel_path": rel_path,
                "bin_path": full_path,
            }
        )
        for child in subfolders(folder):
            walk(child, rel_parts + [folder_name(child)])

    if include_source_root_subbin:
        src_root = find_child_folder(import_scope_bin, source_root_name)
        if not src_root:
            return []
        walk(src_root, [])
    else:
        walk(import_scope_bin, [])
    return rows


def validate_source_of_truth(
    import_scope_bin,
    source_folder: Path,
    source_files,
    recursive: bool,
    include_source_root_subbin: bool,
):
    """Ensure bin items map to disk files from source folder. Return violations."""
    source_set = {norm_path_str(str(p)) for p in source_files}
    source_identity_set = {ident for ident in (file_identity(str(p)) for p in source_files) if ident}
    rows = collect_bin_item_rows(import_scope_bin)
    expected_rel_dirs = collect_source_relative_dirs(source_folder, recursive)
    folder_rows = collect_bin_folder_rows_under_source_root(
        import_scope_bin, source_folder.name, include_source_root_subbin
    )
    stale_folders = [
        r for r in folder_rows if Path(r["source_rel_path"]) not in expected_rel_dirs
    ]

    no_path = [r for r in rows if not r["path"]]
    extra = [
        r
        for r in rows
        if r["path"] and not path_matches_source_set(r["path"], source_set, source_identity_set)
    ]
    return {
        "ok": not (no_path or extra or stale_folders),
        "no_path": no_path,
        "extra": extra,
        "stale_folders": stale_folders,
    }


def path_matches_source_set(path: str, source_set: set[str], source_identity_set: set[tuple[int, int]]) -> bool:
    """Return True if a Resolve path is represented by source_set.

    Handles direct matches and Resolve image-sequence notation such as:
      /path/to/name[1-2].png
    matching:
      /path/to/name1.png
      /path/to/name2.png
    """
    if path in source_set:
        return True

    norm = norm_path_str(path)
    if norm in source_set:
        return True

    ident = file_identity(path)
    if ident and ident in source_identity_set:
        return True

    m = re.match(r"^(.*)\[(\d+)-(\d+)\](.*)$", path)
    if not m:
        return False

    prefix, start_s, end_s, suffix = m.groups()
    try:
        start = int(start_s)
        end = int(end_s)
    except ValueError:
        return False

    if end < start:
        return False

    # Guard against pathological ranges.
    if (end - start) > 5000:
        return False

    width = max(len(start_s), len(end_s))
    for n in range(start, end + 1):
        candidate = f"{prefix}{n:0{width}d}{suffix}"
        if not path_matches_source_set(candidate, source_set, source_identity_set):
            return False
    return True


def delete_rows(media_pool, rows):
    by_folder = {}
    for r in rows:
        folder_obj = r.get("folder_obj")
        clip_obj = r.get("clip_obj")
        if not folder_obj or not clip_obj:
            continue
        by_folder.setdefault(id(folder_obj), {"folder": folder_obj, "clips": []})
        by_folder[id(folder_obj)]["clips"].append(clip_obj)

    deleted = 0
    failed = 0
    for payload in by_folder.values():
        folder = payload["folder"]
        clip_list = payload["clips"]
        if not media_pool.SetCurrentFolder(folder):
            failed += len(clip_list)
            continue
        ok = media_pool.DeleteClips(clip_list)
        if ok:
            deleted += len(clip_list)
        else:
            failed += len(clip_list)
    return deleted, failed


def delete_folder_rows(media_pool, rows):
    # Delete deepest paths first so children are removed before parents.
    ordered = sorted(rows, key=lambda r: len(str(r.get("bin_path", "")).split("/")), reverse=True)
    deleted = 0
    failed = 0

    delete_folders_fn = getattr(media_pool, "DeleteFolders", None)
    if not callable(delete_folders_fn):
        return 0, len(ordered)

    for r in ordered:
        folder_obj = r.get("folder_obj")
        if not folder_obj:
            failed += 1
            continue
        ok = delete_folders_fn([folder_obj])
        if ok:
            deleted += 1
        else:
            failed += 1
    return deleted, failed


def find_child_folder(parent_folder, child_name):
    for child in subfolders(parent_folder):
        if folder_name(child) == child_name:
            return child
    return None


def get_or_create_child_folder(media_pool, parent_folder, child_name):
    existing = find_child_folder(parent_folder, child_name)
    if existing:
        return existing
    created = media_pool.AddSubFolder(parent_folder, child_name)
    if not created:
        raise RuntimeError(
            f"Failed to create sub-bin '{child_name}' under '{folder_name(parent_folder)}'."
        )
    return created


def use_source_root_subbin(target_bin_name: str, source_root_name: str) -> bool:
    """Only create/use nested source root sub-bin when names differ."""
    return target_bin_name != source_root_name


def parse_args():
    parser = argparse.ArgumentParser(
        description="Import files from a source folder into a named Resolve bin."
    )
    parser.add_argument("source_folder", help="Filesystem folder path to import")
    parser.add_argument(
        "--create-if-missing",
        action="store_true",
        help=(
            "Create the hardcoded target bin under Media Pool root if it does not exist. "
            "Default behavior is to fail fast when missing."
        ),
    )
    parser.add_argument(
        "--non-recursive",
        action="store_true",
        help="Only import files directly inside source folder.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    parser.add_argument(
        "--delete-resolve-items",
        action="store_true",
        help=(
            "Delete target-bin project items not backed by source disk files "
            "(items with no path or path outside source folder), then continue."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Preview mode: do not modify Resolve project items and do not import files. "
            "With --delete-resolve-items, shows what would be deleted."
        ),
    )
    parser.add_argument(
        "--ignore-file",
        default=".import_hot_storage.ignore",
        help=(
            "Optional ignore-pattern file (gitignore-style globs, one per line) "
            "resolved relative to source folder. Default: %(default)s"
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full preview mapping/details instead of a short sample.",
    )
    return parser.parse_args()


def load_ignore_patterns(source_folder: Path, ignore_file_name: str):
    patterns = list(DEFAULT_IGNORE_PATTERNS)
    if not ignore_file_name:
        return patterns

    p = source_folder / ignore_file_name
    if not p.exists() or not p.is_file():
        return patterns

    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        patterns.append(s)
    return patterns


def should_ignore(path: Path, source_folder: Path, patterns: list[str]) -> bool:
    rel = path.relative_to(source_folder).as_posix()
    name = path.name
    for pat in patterns:
        if fnmatch(rel, pat) or fnmatch(name, pat):
            return True
    return False


def collect_candidate_files(source_folder: Path, recursive: bool):
    if recursive:
        # Follow symlinked directories so storage aliases/mount indirections are included.
        files = []
        for root, _, names in os.walk(source_folder, followlinks=True):
            root_path = Path(root)
            for name in names:
                p = root_path / name
                # Include symlinked file entries even when the link target is currently offline.
                if p.is_file() or p.is_symlink():
                    files.append(p)
    else:
        files = [p for p in source_folder.iterdir() if p.is_file() or p.is_symlink()]
    return sorted(files)


def apply_ignore_filters(files: list[Path], source_folder: Path, ignore_patterns: list[str]):
    filtered = []
    ignored = []
    for p in files:
        if should_ignore(p, source_folder, ignore_patterns):
            ignored.append(p)
        else:
            filtered.append(p)
    return sorted(filtered), sorted(ignored)


def collect_file_groups_from_files(source_folder: Path, files: list[Path]):
    """Return list of (relative_dir, [files]) grouped by source folder layout."""
    groups = {}
    for f in sorted(files):
        rel_dir = f.parent.relative_to(source_folder)
        groups.setdefault(rel_dir, []).append(f)
    return sorted(groups.items(), key=lambda x: str(x[0]))


def preview_import_plan(
    project_name: str,
    source_folder: Path,
    target_bin,
    include_source_root_subbin: bool,
    files,
    ignored_files,
    existing_paths,
    verbose: bool,
):
    norm_files = [norm_path_str(str(p)) for p in files]
    existing_path_list = [p for p in norm_files if p in existing_paths]
    new_path_list = [p for p in norm_files if p not in existing_paths]
    already_present = len(existing_path_list)
    new_files = len(new_path_list)
    path_to_file = {norm_path_str(str(p)): p for p in files}
    print("=== Import Preview ===")
    print(f"Project      : {project_name}")
    print(f"Target Bin   : {folder_name(target_bin)}")
    print(f"Source Folder: {source_folder}")
    print(f"Discovered   : {len(files)}")
    print(f"Ignored      : {len(ignored_files)}")
    print(f"New Files    : {new_files}")
    print(f"Existing     : {already_present}")
    print("")

    # One-to-one mapping for actual changes (new files only).
    row_map = []
    for p in new_path_list:
        fp = path_to_file.get(p)
        if not fp:
            continue
        rel_dir = fp.parent.relative_to(source_folder)
        base = folder_name(target_bin)
        if include_source_root_subbin:
            base = f"{base}/{source_folder.name}"
        dest_bin = f"{base}/{rel_dir.as_posix()}" if str(rel_dir) != "." else base
        row_map.append((p, dest_bin, fp.name))

    if verbose:
        sample_limit = len(row_map)
        print("New Import Mapping (ITEM path + SOURCE FILE)")
    else:
        sample_limit = 8
        print(f"New Import Mapping (first {sample_limit}, ITEM path + SOURCE FILE)")

    idx = 1
    for src_path, dest_bin, item_name in row_map[:sample_limit]:
        item_path = f"{dest_bin}/{item_name}"
        print(f"{idx}.")
        print(f"   -> ITEM       : {item_path}")
        print(f"   -> SOURCE FILE: {src_path}")
        idx += 1

    if len(row_map) > sample_limit:
        print(f"  ... and {len(row_map) - sample_limit} more new file mapping(s)")
    print("======================")

    if verbose:
        discovered_paths = [str(p) for p in sorted(files)]
        ignored_paths = [str(p) for p in sorted(ignored_files)]
        existing_source_paths = [str(path_to_file[p]) for p in sorted(existing_path_list)]
        new_source_paths = [str(path_to_file[p]) for p in sorted(new_path_list)]

        print("All Discovered Files:")
        for p in discovered_paths:
            print(f"  - {p}")
        print("")

        print("All Ignored Files:")
        for p in ignored_paths:
            print(f"  - {p}")
        print("")

        print("All Existing Files (already in Resolve bin):")
        for p in existing_source_paths:
            print(f"  - {p}")
        print("")

        print("All New Files (to import):")
        for p in new_source_paths:
            print(f"  - {p}")
        print("")

    return {
        "discovered_count": len(files),
        "new_count": len(new_path_list),
        "already_present_count": already_present,
    }


def main():
    args = parse_args()
    source_folder = Path(args.source_folder).expanduser().resolve()
    if not source_folder.exists() or not source_folder.is_dir():
        raise RuntimeError(f"Source folder not found: {source_folder}")
    if source_folder.name != ALLOWED_SOURCE_FOLDER_NAME:
        raise RuntimeError(
            f"Invalid source folder: {source_folder}. "
            f"This script only allows importing from a folder named '{ALLOWED_SOURCE_FOLDER_NAME}'."
        )

    resolve_module = load_resolve_script_module()
    resolve = resolve_module.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to DaVinci Resolve.")

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        raise RuntimeError("Could not get Project Manager.")

    project = project_manager.GetCurrentProject()
    if not project:
        raise RuntimeError("No current project is open.")
    project_name = project.GetName() or ""
    if EXPECTED_PROJECT_FUZZY and EXPECTED_PROJECT_FUZZY.lower() not in project_name.lower():
        print(
            "WARNING: Current Resolve project name "
            f"'{project_name}' does not fuzzy-match expected keyword "
            f"'{EXPECTED_PROJECT_FUZZY}'."
        )
        if not args.yes:
            reply = input("Continue anyway? [y/N]: ").strip().lower()
            if reply not in {"y", "yes"}:
                print("Aborted.")
                return

    media_pool = project.GetMediaPool()
    if not media_pool:
        raise RuntimeError("Could not access Media Pool.")

    root = media_pool.GetRootFolder()
    if not root:
        raise RuntimeError("Could not access Media Pool root folder.")

    matching_bins = [f for f in walk_folders(root) if folder_name(f) == TARGET_BIN_NAME]

    if len(matching_bins) > 1:
        raise RuntimeError(
            f"Found multiple bins named '{TARGET_BIN_NAME}'. Resolve project structure is ambiguous; clean up duplicate bin names."
        )

    if not matching_bins:
        if args.create_if_missing:
            target_bin = media_pool.AddSubFolder(root, TARGET_BIN_NAME)
            if not target_bin:
                raise RuntimeError(
                    f"Failed to create bin '{TARGET_BIN_NAME}' under '{folder_name(root)}'."
                )
        else:
            raise RuntimeError(
                "Required target bin "
                f"'{TARGET_BIN_NAME}' was not found in project '{project.GetName()}'. "
                "Stop and verify you are in the correct Resolve project/version and that media bins are imported correctly. "
                "If you are certain setup is correct, raise an issue."
            )
    else:
        target_bin = matching_bins[0]
    include_source_root_subbin = use_source_root_subbin(
        folder_name(target_bin), source_folder.name
    )

    if include_source_root_subbin:
        import_scope_bin = find_child_folder(target_bin, source_folder.name)
        if not import_scope_bin:
            import_scope_bin = target_bin
    else:
        import_scope_bin = target_bin

    ignore_patterns = load_ignore_patterns(source_folder, args.ignore_file)
    all_candidate_files = collect_candidate_files(
        source_folder, recursive=not args.non_recursive
    )
    files, ignored_files = apply_ignore_filters(
        all_candidate_files, source_folder, ignore_patterns
    )
    if not files:
        raise RuntimeError(f"No files found in source folder: {source_folder}")

    # Enforce source-of-truth: bin items must map to source disk files.
    validation = validate_source_of_truth(
        import_scope_bin=import_scope_bin,
        source_folder=source_folder,
        source_files=files,
        recursive=not args.non_recursive,
        include_source_root_subbin=include_source_root_subbin,
    )
    cleanup_items_deleted = 0
    cleanup_items_failed = 0
    cleanup_bins_deleted = 0
    cleanup_bins_failed = 0
    if not validation["ok"]:
        print("WARNING: Source-of-truth validation failed.")
        print("The target bin contains project items that are not backed by source disk files.")

        if validation["no_path"]:
            print(f"Items with no disk path ({len(validation['no_path'])}):")
            for r in validation["no_path"][:100]:
                print(f"  - [{r['bin_path']}] {r['clip_name']} :: <no-path>")
            if len(validation["no_path"]) > 100:
                print(f"  ... and {len(validation['no_path']) - 100} more")

        if validation["extra"]:
            print(f"Items not present under source folder ({len(validation['extra'])}):")
            for r in validation["extra"][:200]:
                print(f"  - [{r['bin_path']}] {r['clip_name']} :: {r['path']}")
            if len(validation["extra"]) > 200:
                print(f"  ... and {len(validation['extra']) - 200} more")
        if validation["stale_folders"]:
            print(
                f"Bins not present under source folder ({len(validation['stale_folders'])}):"
            )
            for r in validation["stale_folders"][:200]:
                print(f"  - [{r['bin_path']}] <bin>")
            if len(validation["stale_folders"]) > 200:
                print(f"  ... and {len(validation['stale_folders']) - 200} more")

        if args.delete_resolve_items:
            rows_to_delete = validation["no_path"] + validation["extra"]
            folders_to_delete = validation["stale_folders"]
            if args.dry_run:
                print(
                    "DRY RUN delete (--delete-resolve-items): "
                    f"would_delete_items={len(rows_to_delete)} "
                    f"(no_path={len(validation['no_path'])}, non_matching={len(validation['extra'])}), "
                    f"would_delete_bins={len(folders_to_delete)}"
                )
            else:
                deleted, failed = delete_rows(media_pool, rows_to_delete)
                f_deleted, f_failed = delete_folder_rows(media_pool, folders_to_delete)
                cleanup_items_deleted += deleted
                cleanup_items_failed += failed
                cleanup_bins_deleted += f_deleted
                cleanup_bins_failed += f_failed
                print(
                    "Auto-cleanup (--delete-resolve-items): "
                    f"deleted_items={deleted}, failed_items={failed}, "
                    f"deleted_bins={f_deleted}, failed_bins={f_failed}"
                )
                # Re-check after cleanup.
                validation = validate_source_of_truth(
                    import_scope_bin=import_scope_bin,
                    source_folder=source_folder,
                    source_files=files,
                    recursive=not args.non_recursive,
                    include_source_root_subbin=include_source_root_subbin,
                )
                if not validation["ok"]:
                    raise RuntimeError(
                        "Target bin still contains non-disk-backed items after auto-cleanup. "
                        "Verify project/version and bin imports; if this is unexpected after verification, raise an issue."
                    )
                print("Source-of-truth validation passed after auto-cleanup.")
        else:
            raise RuntimeError(
                "there are items in resolve's source bin that don't actually have matching source files "
                f"in {source_folder}. This is not allowed. "
                "Re-run with --delete-resolve-items to delete them automatically."
            )

    groups = collect_file_groups_from_files(source_folder, files)
    existing_paths = collect_existing_paths_under_bin(import_scope_bin)

    plan = preview_import_plan(
        project_name=project_name,
        source_folder=source_folder,
        target_bin=target_bin,
        include_source_root_subbin=include_source_root_subbin,
        files=files,
        ignored_files=ignored_files,
        existing_paths=existing_paths,
        verbose=args.verbose,
    )

    if plan["new_count"] == 0:
        if not args.dry_run and not args.yes:
            reply = input("No new files to import. Exit now? [Y/n]: ").strip().lower()
            if reply in {"n", "no"}:
                print("Exit cancelled.")
                return
        if (
            cleanup_items_deleted
            or cleanup_items_failed
            or cleanup_bins_deleted
            or cleanup_bins_failed
        ):
            print(
                "No new files to import. Import step made no changes. "
                "Cleanup summary: "
                f"deleted_items={cleanup_items_deleted}, failed_items={cleanup_items_failed}, "
                f"deleted_bins={cleanup_bins_deleted}, failed_bins={cleanup_bins_failed}."
            )
        else:
            print("No new files to import. Exiting without changes.")
        return

    if args.dry_run:
        print("Dry run mode: skipping confirmation prompt.")
    elif not args.yes:
        reply = input(
            f"Import {plan['new_count']} new file(s) from '{source_folder}' into bin '{folder_name(target_bin)}'? [y/N]: "
        ).strip().lower()
        if reply not in {"y", "yes"}:
            print("Aborted.")
            return

    if args.dry_run:
        print("DRY RUN import: no files were imported.")
        print(f"Project: {project.GetName()}")
        print(f"Target bin: {folder_name(target_bin)}")
        print(f"Source folder: {source_folder}")
        print(f"Requested files: {plan['discovered_count']}")
        print(f"New files that would be imported: {plan['new_count']}")
        return

    imported_count = 0
    # Mirror source folder tree under target import scope.
    if include_source_root_subbin:
        root_dest_bin = get_or_create_child_folder(media_pool, target_bin, source_folder.name)
    else:
        root_dest_bin = target_bin
    for rel_dir, group_files in groups:
        dest_folder = root_dest_bin
        if str(rel_dir) != ".":
            for part in rel_dir.parts:
                dest_folder = get_or_create_child_folder(media_pool, dest_folder, part)
        if not media_pool.SetCurrentFolder(dest_folder):
            raise RuntimeError(
                f"Failed to set current folder to destination bin '{folder_name(dest_folder)}'."
            )
        imported = media_pool.ImportMedia([str(p) for p in group_files])
        imported_count += len(imported or [])

    print(f"Project: {project.GetName()}")
    print(f"Target bin: {folder_name(target_bin)}")
    print(f"Source folder: {source_folder}")
    print(f"Requested files: {plan['discovered_count']}")
    print(f"New files imported: {plan['new_count']}")
    print(f"Imported clips reported by Resolve: {imported_count}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user (Ctrl-C).", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
