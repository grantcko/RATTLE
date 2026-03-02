# RATTLE!

An open source video about a man at a picnic with a woman he does not know in a place he cannot recall.

## Status

Postproduction 🖥️ | [Latest Nightly Export](https://archive.org/details/1400-edit-1)

## Build

1. Clone the repository.
2. Create and activate a virtual environment:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
3. Install dependencies:
   - `pip install -r requirements.txt`
4. Verify external tools:
   - `ia --version`
   - DaVinci Resolve installed with scripting enabled (`DaVinciResolveScript.py` available)
5. Import project:
   - `python3 rscripts/import_project.py`
6. Download large files (if needed):
   - `python3 rscripts/download_external_files.py --list-url "https://archive.org/details/@grantcko/lists/1/rattle!" --destdir "path/to/storage"`
7. Relink everything inside Resolve.
8. Import timeline:
   - `python3 rscripts/import_timeline.py path/to/drt`
   - or manually: `File > Import > Import Timeline`.

## Structure

How is this setup? DaVinci Resolve project files are databases and are not made for open source contributions, so we work off exported, versioned projects (`.drp`) and timelines (`.drt`) stored at `project/`.

#### Projects (.drp)

Stored at `project/projects/` - exported project files. New versions are created at major checkpoints, not with each timeline. This includes the primary source files and project settings. This purposely has no timelines. You should start by importing this into your Resolve library. It is versioned `vNNN`.

- This project has source files in a Resolve bin called `00-SOURCE` - this directly matches the source folder `00-SOURCE` in this repo. It is set up so everything in that Resolve bin is backed and there is no confusion.
- Project structure does not matter for most editors, as contributions happen at the timeline level.

#### Timelines (.drt)

Stored at `project/timelines/` - exported timeline files. Versioned `MMmm-[category]` where `MM` is the major version number and `mm` is the minor version number (e.g. `1406-sound`).

- When importing `.drt` files, Resolve populates the media pool with extra imported clips (duplicates) specific to that imported timeline. Use the timeline import script in `rscripts/` to clean this up.

## Contributing

Use an issue + PR versioning workflow.

- Start from the issue for the major cycle (example: `14-sound`).
- Import the latest timeline for that cycle (example: `1401-sound.drt`).
- Each PR must be exactly one minor increment on latest accepted (example: `1401-sound.drt` accepted, PR adds `1402-sound.drt`).
- Export your updated timeline to `project/timelines/` using the exact next versioned filename.
- Link your PR to the issue (`Closes #<issue>` or `Refs #<issue>`).
- Explain any new files added to the repo.
- If external files are required, include links and brief setup/relink notes.

What is generally not allowed (introduces linking problems):

- `00-SOURCE` folder structure changes
- Removed files

### Large Files Workflow

Do not commit large media files directly to git.

1. Keep large media outside the repository
2. In each PR, include:
   - what large files are required
   - where to download them
   - any relink notes needed in Resolve

Recommended storage for shareable large files: Archive.org.

## Plot

#### Scene 1:

- tea is poured
- lady asks "where are we?"
- man does not know
- she keeps asking him
- he freaks out
- she grabs his face and turns into a monster with the scream of an alarm clock

#### Scene 2:

- alarm clock (sound carries over)
- he wakes up from nightmare

#### Scene 3:

- on balcony
- wife comes out and pours tea (it is the lady in the dream)
- Man: "I want a divorce"
