

# RATTLE!

An open source video about a man at a picnic who does not quite know where he is, or the lady sitting across from him.

## Status

Post production - sound 

## Latest Export

[1400-sound](https://archive.org/details/1400-edit-1) 

## Build

1. Clone the repository
2. Run `rscripts/import_project.py path/to/latestdrp` or manually import `File>Import Project`
3. Relink everything inside Resolve
4. Run `rscripts/import_timeline.py path/to/drt` or manually import timeline `File>Import>Import Timeline`

## Structure

How is this setup? DaVinci Resolve project files are databases and are not made for open source contributions, so we work off exported, versioned projects (`.drp`) and timelines (`.drt`) stored at `project/`.

#### Projects (.drp)

Stored at `project/projects/` - exported project files. New versions are created at major checkpoints, not with each timeline. This includes the primary source files and project settings. This purposely has no timelines. You should start by importing this into your Resolve library. It is versioned `vNNN`.

- This project has source files in a Resolve bin called `00-SOURCE` - this directly matches the source folder `00-SOURCE` in this repo. It is set up so everything in that Resolve bin is backed and there is no confusion.
- Project structure doesn't really matter for most editors, as contributions happen at the timeline level. These are suggestions for organization.

#### Timelines (.drt)

Stored at `project/timelines/` - exported timeline files. Versioned `MMmm-[category]` with `MM` being the major version number and `mm` being the minor version number (e.g. `1406-sound`). You should find the timeline you want to work on and import it into your project.

- When importing `.drt` files, Resolve populates the media pool with extra imported clips (duplicates) specific to that imported timeline. This is very annoying. The solution is to use the timeline import script in `rscripts/`. This does a lot of cleanup and only leaves duplicate Resolve and Fusion clips (which cannot really be "merged" because they might have changes).

## Contributing

Use an issue + PR versioning workflow.

- Start from the issue for the major cycle (example: `14-sound`).
- Import the latest timeline for that cycle (example: `1401-sound.drt`).
- Each PR must be exactly one minor increment on latest accepted (example: `1401-sound.drt` is accepted, then your PR includes `1402-sound.drt`).
- Export your updated timeline to `project/timelines/` using the exact next versioned filename.
- Link your PR to the issue (`Closes #<issue>` or `Refs #<issue>`).
- Explain any new files added to the repo.
- If external files are required, include links and repo placeholders.

What's generally not allowed (what introduces linking problems):

- 00-SOURCE folder structure changes
- Removed files

## Plot

#### Scene 1:

- tea is poured
- lady asks "where are we?"
- man doesn't know
- she keeps on asking him
- he freaks out
- she grabs his face and turns to a monster with the scream of an alarm clock

#### Scene 2:

- alarm clock (sound carries over)
- he wakes up from nightmare

#### Scene 3:

- on balcony 
- wife comes out and pours tea (it's the lady in the dream)
- Man "I want a divorce"

