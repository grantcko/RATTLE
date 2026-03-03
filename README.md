# RATTLE!

An open source short film project built around collaborative DaVinci Resolve timeline iterations.

## Status

Postproduction 🖥️ | [Latest Nightly Export](https://archive.org/details/1400-edit-1)

## Quick Start

1. Setup

```bash
git clone https://github.com/grantcko/RATTLE.git
cd RATTLE
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Open latest project version (RATTLE_vNNN) automatically
open -a "DaVinci Resolve"
python3 rscripts/import_project.py

# Run scripts
python3 rscripts/download_external_files.py --list-url "https://archive.org/details/@grantcko/lists/1/rattle!" --destdir "path/to/storage"
python3 rscripts/import_timeline.py path/to/drt
```

## Requirements

- Python 3.10+
- Dependencies from `requirements.txt`
- DaVinci Resolve installed with scripting enabled (`DaVinciResolveScript.py` available)
- `ia` CLI available (provided by the `internetarchive` dependency)

## Project Structure

DaVinci Resolve project files are databases and are not ideal for direct multi-user git collaboration, so this repo uses exported and versioned artifacts under `project/`.

### Projects (.drp)

Stored at `project/projects/`.

- Major checkpoints only (not every timeline change)
- Contains source/media structure and project settings
- Intentionally no timelines
- Versioned as `vNNN`

Source mapping:

- Resolve bin `00-SOURCE` is intended to mirror repo folder `00-SOURCE`.

### Timelines (.drt)

Stored at `project/timelines/`.

- Versioned as `MMmm-[category]` (example: `1406-sound`)
- Import the timeline you are working on
- Use `rscripts/import_timeline.py` to reduce duplicate media-pool clutter from timeline import

## Contributing

Use issue + PR versioning.

- Start from the issue for the target major cycle (example: `14-sound`)
- Import the latest accepted timeline for that cycle (example: `1401-sound.drt`)
- Each PR must be exactly one minor increment (if `1401-*` is accepted, PR should add `1402-*`)
- Export timeline to `project/timelines/` with the exact next versioned filename
- Link PR to issue (`Closes #<issue>` or `Refs #<issue>`)
- Explain new files added to the repo
- If external files are required, include links and relink/setup notes

Generally not allowed (causes linking/consistency problems):

- Changing `00-SOURCE` folder structure
- Removing required source files without explicit coordination

## Large Files Workflow

Do not commit large media directly to git.

- Keep large media outside the repository
- In PRs, include:
  - required large files
  - download location(s)
  - Resolve relink notes

Recommended host for shareable large files: Archive.org.

## Plot

### Scene 1

- tea is poured
- lady asks "where are we?"
- man does not know
- she keeps asking him
- he freaks out
- she grabs his face and turns into a monster with the scream of an alarm clock

### Scene 2

- alarm clock (sound carries over)
- he wakes up from nightmare

### Scene 3

- on balcony
- wife comes out and pours tea (it is the lady in the dream)
- Man: "I want a divorce"
