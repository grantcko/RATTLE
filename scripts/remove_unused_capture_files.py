#!/usr/bin/env python3
"""Remove capture audio files not used by the current Resolve timeline.

Default mode is dry-run. Use --apply to actually delete files.
"""

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
AUDIO_EXTS = {
    ".wav",
    ".aif",
    ".aiff",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".w64",
    ".bwf",
    ".caf",
}


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


def get_current_timeline(resolve):
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        raise RuntimeError("Could not get Project Manager.")

    project = project_manager.GetCurrentProject()
    if not project:
        raise RuntimeError("No current project is open.")

    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("No current timeline is selected.")

    return timeline


def collect_timeline_audio_paths(timeline):
    selected = set()

    track_count = timeline.GetTrackCount("audio") or 0
    for track_index in range(1, track_count + 1):
        items = timeline.GetItemListInTrack("audio", track_index) or []
        for item in items:
            media_pool_item = item.GetMediaPoolItem()
            if not media_pool_item:
                continue

            path = (
                media_pool_item.GetClipProperty("File Path")
                or media_pool_item.GetClipProperty("Clip Path")
                or ""
            ).strip()

            if not path:
                continue

            p = Path(path)
            if not p.exists():
                continue

            selected.add(p.resolve())

    return sorted(selected)


def collect_capture_audio_files(capture_root: Path):
    files = []
    for child in capture_root.rglob("*"):
        if child.is_file() and child.suffix.lower() in AUDIO_EXTS:
            files.append(child.resolve())
    return sorted(set(files))


def format_concatenated(items):
    # Single-line, copy/pastable representation of full list.
    return " | ".join(str(p) for p in items)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Delete capture audio files not used by current Resolve timeline audio tracks."
    )
    parser.add_argument(
        "--capture-root",
        default="/Volumes/TASTY/RATTLE/project/RATTLE_1/Capture",
        help="Capture root to scan (default: %(default)s). If missing, script fuzzy-finds a Capture dir under ./project.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete candidates. Without this flag, script runs in dry-run mode.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full file lists for both delete candidates and saved files.",
    )
    return parser.parse_args()


def ensure_running_in_rattle_repo() -> Path:
    cwd = Path.cwd().resolve()
    if cwd.name != "RATTLE":
        raise RuntimeError(
            f"Run this script from the RATTLE repo root. Current directory: {cwd}"
        )

    project_dir = cwd / "project"
    if not project_dir.exists() or not project_dir.is_dir():
        raise RuntimeError(
            f"Expected project directory at {project_dir}. Run from the RATTLE repo root."
        )
    return cwd


def fuzzy_find_capture_dir(repo_root: Path) -> Path | None:
    project_dir = repo_root / "project"
    candidates = []
    for path in project_dir.rglob("*"):
        if not path.is_dir():
            continue
        name = path.name.lower()
        if "capture" in name:
            score = (
                0 if name == "capture" else 1,
                len(path.parts),
                str(path).lower(),
            )
            candidates.append((score, path.resolve()))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def main():
    args = parse_args()
    repo_root = ensure_running_in_rattle_repo()
    capture_root = Path(args.capture_root).resolve()
    if not capture_root.exists() or not capture_root.is_dir():
        fallback = fuzzy_find_capture_dir(repo_root)
        if not fallback:
            raise RuntimeError(
                f"Capture root not found: {capture_root}. Also could not find any capture-like folder under {repo_root / 'project'}."
            )
        print(
            f"Capture root not found at {capture_root}. Using fuzzy-found capture root: {fallback}"
        )
        capture_root = fallback

    resolve_module = load_resolve_script_module()
    resolve = resolve_module.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to DaVinci Resolve.")

    timeline = get_current_timeline(resolve)

    timeline_audio = collect_timeline_audio_paths(timeline)
    saved_files = sorted([p for p in timeline_audio if capture_root in p.parents])
    saved_set = set(saved_files)

    capture_audio = collect_capture_audio_files(capture_root)
    delete_candidates = [p for p in capture_audio if p not in saved_set]

    mode = "APPLY (DELETING FILES)" if args.apply else "DRY RUN (NO FILES DELETED)"
    print(f"Mode: {mode}")
    print(f"Capture root: {capture_root}")
    print(f"Capture audio files scanned: {len(capture_audio)}")
    print(f"Files to save (used by current timeline): {len(saved_files)}")
    print(f"Files to delete (unused in current timeline): {len(delete_candidates)}")

    print("--- Concatenated keep list ---")
    print(format_concatenated(saved_files))
    print("--- Concatenated delete list ---")
    print(format_concatenated(delete_candidates))

    if args.verbose:
        print("--- Verbose keep list ---")
        for path in saved_files:
            print(path)

        print("--- Verbose delete list ---")
        for path in delete_candidates:
            print(path)

    if args.apply:
        deleted = 0
        failed = []
        for path in delete_candidates:
            try:
                path.unlink()
                deleted += 1
            except Exception as exc:
                failed.append((path, str(exc)))

        print(f"Deleted files: {deleted}")
        if failed:
            print(f"Failed deletions: {len(failed)}")
            for path, err in failed:
                print(f"FAILED: {path} :: {err}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
