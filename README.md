# RATTLE!

An open source narrative horror video about man finds himself at peace, having a picnic with a woman he doesn't know, at a place he can't recall. The bliss is short lived. 

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

# import timeline
python3 rscripts/import_timeline.py path/to/drt # choose the timeline you want
```
Of course, these can be opened manually, too. Everything you need is in the `project/` folder.

2. Download and connect large files

Full Sized Footage
```bash
ia download rattle-footage --destdir "path/to/footagestorage"
```
Or download manually from: [https://archive.org/details/rattle-footage](https://archive.org/details/rattle-footage)

Proxy Footage
```bash
ia download rattle-proxies --destdir "path/to/proxystorage"
```
Or download manually from: [https://archive.org/details/rattle-proxies](https://archive.org/details/rattle-proxies)

Audio
```bash
ia download rattle-audio --destdir "path/to/audiostorage"
```
Or download manually from: [https://archive.org/details/rattle-audio](https://archive.org/details/rattle-audio)

## Requirements

- Python 3.10+
- Dependencies from `requirements.txt`
- DaVinci Resolve installed with scripting enabled (`DaVinciResolveScript.py` available)
- `ia` CLI available (provided by the `internetarchive` dependency)

## Project Structure

- The Resolve project has a 00-SOURCE bin that is a direct mirrored import of the "source" folder 00-source. `Folder` = actual folder on disk. `Bin` = Resolve's version of a "folder" in the media pool. 
- Project only bins: for timelines, compound/fusion clips, capture audio. *Mostly* for resolve "items" - not actual files.
- DaVinci Resolve project files are databases and are not ideal for direct multi-user git collaboration, so this repo uses exported and versioned artifacts  under `project/`. 

### Projects (.drp)

Stored at `project/projects/`.

- Major checkpoints only (not every timeline change)
- Contains source/media structure and project settings
- Intentionally no timelines
- Versioned as `vNNN`

### Timelines (.drt)

Stored at `project/timelines/`.

- Versioned as `MMmm-[category]` (example: `1406-sound`)
- Import the timeline you are working on
- Use `rscripts/import_timeline.py` to reduce duplicate media-pool clutter from timeline import

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

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

## Credits

Producers: Grant Hall and David Narbecki
