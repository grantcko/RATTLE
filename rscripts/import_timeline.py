#!/usr/bin/env python3
"""Import .drt timelines into the currently selected Media Pool bin and clean duplicates."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import sys
from pathlib import Path

SCRIPT_MODULE_NAME = "DaVinciResolveScript"
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


def clip_type(clip):
    get_prop = getattr(clip, "GetClipProperty", None)
    if callable(get_prop):
        try:
            typ = get_prop("Type")
            if isinstance(typ, str):
                return typ.strip().lower()
        except Exception:
            pass
    return ""


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
    return ""


def clip_duration(clip):
    get_prop = getattr(clip, "GetClipProperty", None)
    if callable(get_prop):
        for key in ("Duration", "Frames", "End"):
            try:
                val = get_prop(key)
            except Exception:
                val = ""
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


def clip_id(clip):
    for method_name in ("GetMediaId", "GetUniqueId"):
        method = getattr(clip, method_name, None)
        if callable(method):
            try:
                value = method()
            except Exception:
                value = None
            if isinstance(value, str) and value:
                return value
    return f"{clip_name(clip)}|{clip_type(clip)}|{id(clip)}"


def normalize_name(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def strip_import_suffix(name: str) -> str:
    normalized = normalize_name(name)
    if normalized.endswith(" import"):
        return normalized[:-7]
    return normalized


def timeline_bin_name_from_drt(drt_path: Path) -> str:
    return drt_path.stem.strip() or "timeline"


def find_folder_exact(root, name: str):
    for folder in walk_folders(root):
        if folder_name(folder) == name:
            return folder
    return None


def ensure_subfolder(media_pool, parent, name: str):
    for child in subfolders(parent):
        if folder_name(child) == name:
            return child
    add_subfolder = getattr(media_pool, "AddSubFolder", None)
    if not callable(add_subfolder):
        raise RuntimeError("Resolve API does not support AddSubFolder.")
    created = add_subfolder(parent, name)
    if created:
        return created
    for child in subfolders(parent):
        if folder_name(child) == name:
            return child
    raise RuntimeError(f"Could not create/find bin '{name}'.")


def require_existing_subfolder(parent, name: str):
    for child in subfolders(parent):
        if folder_name(child) == name:
            return child
    raise RuntimeError(
        f"Required bin missing: '{folder_name(parent)}/{name}'. "
        "Make sure that you have the latest project (.drp)."
    )


def import_timeline_file(media_pool, project, timeline_file: Path):
    before = project.GetTimelineCount() or 0
    imported = False

    import_fn = getattr(media_pool, "ImportTimelineFromFile", None)
    if callable(import_fn):
        try:
            result = import_fn(str(timeline_file))
            imported = result is not None
        except Exception:
            imported = False

    if not imported:
        import_fn_project = getattr(project, "ImportTimelineFromFile", None)
        if callable(import_fn_project):
            try:
                result = import_fn_project(str(timeline_file))
                imported = result is not None
            except Exception:
                imported = False

    after = project.GetTimelineCount() or 0
    if not imported and after <= before:
        raise RuntimeError("Timeline import failed.")
    return before, after


def collect_referenced_media_ids(project):
    referenced_ids = set()
    timeline_count = project.GetTimelineCount() or 0
    for index in range(1, timeline_count + 1):
        timeline = project.GetTimelineByIndex(index)
        if not timeline:
            continue
        for track_type in ("video", "audio"):
            track_count = timeline.GetTrackCount(track_type) or 0
            for track_index in range(1, track_count + 1):
                items = timeline.GetItemListInTrack(track_type, track_index) or []
                for item in items:
                    media_pool_item = item.GetMediaPoolItem()
                    if media_pool_item:
                        referenced_ids.add(clip_id(media_pool_item))
    return referenced_ids


def run_cleanup(project, media_pool, root, target_bin):
    all_clips = []
    folder_of_clip = {}
    id_to_clip = {}
    for folder in walk_folders(root):
        for clip in clips(folder):
            clip_id_value = clip_id(clip)
            all_clips.append((clip, folder))
            folder_of_clip[clip_id_value] = folder
            id_to_clip[clip_id_value] = clip

    referenced_ids = collect_referenced_media_ids(project)
    delete_candidates = []
    kept_referenced = 0
    kept_no_match = 0
    replace_attempted = 0
    replace_ok = 0
    replace_fail = 0

    timeline_items_in_target = [clip for clip in clips(target_bin) if clip_type(clip) == "timeline"]
    if not timeline_items_in_target:
        return {
            "candidates": 0,
            "deleted": False,
            "kept_referenced": 0,
            "kept_no_match": 0,
            "replace_attempted": 0,
            "replace_ok": 0,
            "replace_fail": 0,
            "skipped_reason": "No timeline clip found in target workspace sub-bin; cleanup aborted.",
        }

    # Build duplicate index across the entire project, excluding timeline clips.
    path_index = {}
    prop_index = {}
    for clip, folder in all_clips:
        clip_t = clip_type(clip)
        if clip_t == "timeline":
            continue
        c_id = clip_id(clip)
        c_path = clip_file_path(clip).strip()
        if c_path:
            key_path = c_path.lower()
            path_index.setdefault(key_path, []).append(c_id)
        key_prop = (normalize_name(clip_name(clip)), clip_t, clip_duration(clip))
        prop_index.setdefault(key_prop, []).append(c_id)

    def external_match_ids(candidate_clip):
        candidate_id = clip_id(candidate_clip)
        candidate_path = clip_file_path(candidate_clip).strip()
        if candidate_path:
            matches = path_index.get(candidate_path.lower(), [])
        else:
            key_prop = (
                normalize_name(clip_name(candidate_clip)),
                clip_type(candidate_clip),
                clip_duration(candidate_clip),
            )
            matches = prop_index.get(key_prop, [])
        out = []
        for match_id in matches:
            if match_id == candidate_id:
                continue
            folder = folder_of_clip.get(match_id)
            if folder is target_bin:
                continue
            out.append(match_id)
        return out

    # First, attempt to replace timeline item references that point to target sub-bin duplicates.
    target_timeline_names = {clip_name(c) for c in timeline_items_in_target}
    timeline_count = project.GetTimelineCount() or 0
    for index in range(1, timeline_count + 1):
        timeline = project.GetTimelineByIndex(index)
        if not timeline or (timeline.GetName() or "") not in target_timeline_names:
            continue
        for track_type in ("video", "audio"):
            track_count = timeline.GetTrackCount(track_type) or 0
            for track_index in range(1, track_count + 1):
                items = timeline.GetItemListInTrack(track_type, track_index) or []
                for item in items:
                    media_pool_item = item.GetMediaPoolItem()
                    if not media_pool_item:
                        continue
                    media_id = clip_id(media_pool_item)
                    media_folder = folder_of_clip.get(media_id)
                    if media_folder is not target_bin:
                        continue
                    candidates = external_match_ids(media_pool_item)
                    if not candidates:
                        continue
                    target_clip = id_to_clip.get(candidates[0])
                    if not target_clip:
                        continue
                    replace_attempted += 1
                    ok = False
                    try:
                        ok = bool(item.ReplaceClip(target_clip))
                    except Exception:
                        ok = False
                    if ok:
                        replace_ok += 1
                    else:
                        replace_fail += 1

    # Recompute references after replacement attempts.
    referenced_ids = collect_referenced_media_ids(project)

    for clip in clips(target_bin):
        clip_t = clip_type(clip)
        if clip_t == "timeline":
            continue
        if clip_id(clip) in referenced_ids:
            kept_referenced += 1
            continue
        matches_outside_target = external_match_ids(clip)
        if not matches_outside_target:
            kept_no_match += 1
            continue
        delete_candidates.append(clip)

    deleted = False
    if delete_candidates:
        deleted = bool(media_pool.DeleteClips(delete_candidates))

    return {
        "candidates": len(delete_candidates),
        "deleted": deleted,
        "kept_referenced": kept_referenced,
        "kept_no_match": kept_no_match,
        "replace_attempted": replace_attempted,
        "replace_ok": replace_ok,
        "replace_fail": replace_fail,
        "skipped_reason": "",
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Import a .drt timeline into the currently selected Media Pool bin "
            "and clean redundant duplicate clips."
        )
    )
    parser.add_argument(
        "input_paths",
        nargs="+",
        help="One or more .drt files and/or folders containing .drt files.",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Skip post-import duplicate cleanup in the target bin.",
    )
    parser.add_argument(
        "--cleanup-only",
        action="store_true",
        help="Skip import and run duplicate cleanup in the target bin only.",
    )
    return parser


def resolve_drt_files(input_paths):
    drt_files = []
    seen = set()
    for raw_path in input_paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            raise RuntimeError(f"Input path does not exist: {path}")
        if path.is_file():
            if path.suffix.lower() != ".drt":
                raise RuntimeError(f"Expected a .drt file, got: {path.name}")
            resolved = path.resolve()
            key = str(resolved)
            if key not in seen:
                seen.add(key)
                drt_files.append(resolved)
            continue
        if path.is_dir():
            if path.name.lower() != "timelines":
                raise RuntimeError(
                    f"Folder input must be named 'timelines', got: {path}"
                )
            found_any = False
            for candidate in sorted(path.rglob("*")):
                if candidate.is_file() and candidate.suffix.lower() == ".drt":
                    found_any = True
                    resolved = candidate.resolve()
                    key = str(resolved)
                    if key not in seen:
                        seen.add(key)
                        drt_files.append(resolved)
            if not found_any:
                raise RuntimeError(f"No .drt files found in folder: {path}")
            continue
        raise RuntimeError(f"Unsupported input path type: {path}")

    if not drt_files:
        raise RuntimeError("No .drt files resolved from input paths.")
    return drt_files


def main():
    args = build_parser().parse_args()
    drt_files = resolve_drt_files(args.input_paths)

    resolve_module = load_resolve_script_module()
    resolve = resolve_module.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to DaVinci Resolve.")

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if not project:
        raise RuntimeError("No current Resolve project is open.")

    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()
    if not root:
        raise RuntimeError("Could not get Media Pool root folder.")

    get_current_folder = getattr(media_pool, "GetCurrentFolder", None)
    if not callable(get_current_folder):
        raise RuntimeError("Resolve API does not support GetCurrentFolder; cannot determine target bin.")
    workspace_bin = get_current_folder()
    if not workspace_bin:
        raise RuntimeError(
            "Could not determine current Media Pool folder. "
            "Select a bin in the Media Pool and try again."
        )

    set_current_folder = getattr(media_pool, "SetCurrentFolder", None)
    if not callable(set_current_folder):
        raise RuntimeError("Resolve API does not support SetCurrentFolder.")
    print("=== Import Timeline ===")
    print(f"Project      : {project.GetName()}")
    print(f"Target bin   : {folder_name(workspace_bin)} (current Media Pool folder)")
    print(f"DRT files    : {len(drt_files)}")
    for file_path in drt_files:
        print(f"  - {file_path}")
    print("=======================")

    if not args.cleanup_only:
        total_before = project.GetTimelineCount() or 0
        imported = 0
        failed = 0
        cleanup_summaries = []
        for drt_path in drt_files:
            timeline_subbin_name = timeline_bin_name_from_drt(drt_path)
            target_bin = ensure_subfolder(media_pool, workspace_bin, timeline_subbin_name)
            if not set_current_folder(target_bin):
                raise RuntimeError(
                    "Could not set current folder to "
                    f"{folder_name(workspace_bin)}/{timeline_subbin_name}."
                )
            before, after = import_timeline_file(media_pool, project, drt_path)
            delta = max(0, after - before)
            if delta > 0:
                imported += 1
                print(
                    f"Imported               : {drt_path} -> "
                    f"{folder_name(workspace_bin)}/{timeline_subbin_name}"
                )
            else:
                failed += 1
                print(f"Import unchanged count : {drt_path}")
            if not args.no_cleanup:
                cleanup = run_cleanup(project, media_pool, root, target_bin)
                cleanup_summaries.append((timeline_subbin_name, cleanup))
        total_after = project.GetTimelineCount() or 0
        print(f"Timelines before import: {total_before}")
        print(f"Timelines after import : {total_after}")
        print(f"Import summary         : success={imported}, failed={failed}")
        if args.no_cleanup:
            print("Cleanup                : skipped (--no-cleanup)")
            return
        print("\n--- Post-import cleanup ---")
        for timeline_subbin_name, cleanup in cleanup_summaries:
            print(f"[{timeline_subbin_name}]")
            if cleanup["skipped_reason"]:
                print(f"Cleanup skipped            : {cleanup['skipped_reason']}")
            print(f"Replace attempted          : {cleanup['replace_attempted']}")
            print(f"Replace succeeded          : {cleanup['replace_ok']}")
            print(f"Replace failed             : {cleanup['replace_fail']}")
            print(f"Delete candidates          : {cleanup['candidates']}")
            print(
                f"DeleteClips result         : "
                f"{cleanup['deleted'] if cleanup['candidates'] else 'n/a'}"
            )
            print(f"Kept (still referenced)    : {cleanup['kept_referenced']}")
            print(f"Kept (no canonical match)  : {cleanup['kept_no_match']}")
        return
    else:
        print("Import result          : skipped (--cleanup-only)")

    cleanup_summaries = []
    for drt_path in drt_files:
        timeline_subbin_name = timeline_bin_name_from_drt(drt_path)
        target_bin = require_existing_subfolder(workspace_bin, timeline_subbin_name)
        cleanup = run_cleanup(project, media_pool, root, target_bin)
        cleanup_summaries.append((timeline_subbin_name, cleanup))

    print("\n--- Post-import cleanup ---")
    for timeline_subbin_name, cleanup in cleanup_summaries:
        print(f"[{timeline_subbin_name}]")
        if cleanup["skipped_reason"]:
            print(f"Cleanup skipped            : {cleanup['skipped_reason']}")
        print(f"Replace attempted          : {cleanup['replace_attempted']}")
        print(f"Replace succeeded          : {cleanup['replace_ok']}")
        print(f"Replace failed             : {cleanup['replace_fail']}")
        print(f"Delete candidates          : {cleanup['candidates']}")
        print(f"DeleteClips result         : {cleanup['deleted'] if cleanup['candidates'] else 'n/a'}")
        print(f"Kept (still referenced)    : {cleanup['kept_referenced']}")
        print(f"Kept (no canonical match)  : {cleanup['kept_no_match']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
