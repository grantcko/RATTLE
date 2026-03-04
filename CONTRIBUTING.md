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

#### Adding new source files to the source folder

This is fine as long as they're small and you explain what was added and why. Don't change the structure of the source folder, is it will cause unnecessary linking issues for everyone else. For larger files follow the Large Files Workflow.

#### Large Files Workflow

Do not commit large media directly to git.

- Keep large media outside the repository 
- In PRs, include:
  - required large files
  - download location(s)
  - Resolve relink notes

Recommended host for shareable large files: Archive.org.
