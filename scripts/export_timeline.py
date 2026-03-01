#!/usr/bin/env python3
"""Export the currently open Resolve timeline to project/timelines as a .drt."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import re
import sys
from pathlib import Path

SCRIPT_MODULE_NAME = "DaVinciResolveScript"
MODULE_PATH_CANDIDATES = [
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py",
    os.path.expandvars(
        "$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py"
    ),
]
DRT_EXPORT_TYPE = 1


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


def sanitize_filename(value: str) -> str:
    safe = re.sub(r"[^\w\-. ]+", "_", (value or "").strip())
    safe = re.sub(r"\s+", "-", safe)
    safe = safe.strip(".-_")
    return safe or "timeline"


def default_timelines_dir() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "project" / "timelines"


def build_parser():
    parser = argparse.ArgumentParser(
        description="Export currently open timeline to project/timelines as a .drt file."
    )
    parser.add_argument(
        "--output-dir",
        default=str(default_timelines_dir()),
        help="Target folder for exported .drt files (default: %(default)s).",
    )
    parser.add_argument(
        "--output-name",
        default="",
        help="Optional file name (without extension). Default uses current timeline name.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .drt if it already exists.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Export all project timelines to .drt files.",
    )
    return parser


def main():
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.name.lower() != "timelines":
        raise RuntimeError(f"Output folder must be named 'timelines': {output_dir}")
    if not output_dir.exists():
        raise RuntimeError(
            f"Required folder missing: {output_dir}\n"
            "Make sure that you have the latest project (.drp)."
        )

    resolve_module = load_resolve_script_module()
    resolve = resolve_module.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to DaVinci Resolve.")

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if not project:
        raise RuntimeError("No current Resolve project is open.")

    print("=== Export Timeline ===")
    print(f"Project      : {project.GetName()}")
    print(f"Output dir   : {output_dir}")
    print(f"Export all   : {'yes' if args.all else 'no'}")
    print("=======================")

    if args.all:
        count = project.GetTimelineCount() or 0
        exported = 0
        failed = 0
        for i in range(1, count + 1):
            timeline = project.GetTimelineByIndex(i)
            if not timeline:
                failed += 1
                continue
            timeline_name = timeline.GetName() or f"timeline-{i}"
            output_name = sanitize_filename(timeline_name)
            output_path = output_dir / f"{output_name}.drt"
            if output_path.exists() and not args.force:
                failed += 1
                print(f"Skipped (exists): {output_path.name}")
                continue
            ok = bool(timeline.Export(str(output_path), DRT_EXPORT_TYPE))
            if ok and output_path.exists():
                exported += 1
                print(f"Exported: {timeline_name} -> {output_path.name}")
            else:
                failed += 1
                print(f"Failed: {timeline_name}")
        print(f"Summary: exported={exported}, failed={failed}")
        if failed:
            raise RuntimeError("One or more timeline exports failed.")
        return

    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("No current/open timeline found.")

    timeline_name = timeline.GetName() or "timeline"
    output_name = sanitize_filename(args.output_name or timeline_name)
    output_path = output_dir / f"{output_name}.drt"
    if output_path.exists() and not args.force:
        raise RuntimeError(
            f"Output file already exists: {output_path}\n"
            "Re-run with --force to overwrite."
        )

    print(f"Timeline     : {timeline_name}")
    print(f"Output path  : {output_path}")
    ok = bool(timeline.Export(str(output_path), DRT_EXPORT_TYPE))
    if not ok or not output_path.exists():
        raise RuntimeError("Timeline export failed.")

    print(f"Export result: success ({output_path})")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
