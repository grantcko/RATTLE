# External Media and Repo-Safe Metadata

This repository intentionally does not track the full `00-SOURCE` contents, render movies, proxies, licensed music, stock footage, or temporary Resolve working output. Forks get the folder structure, project exports, timeline exports, scripts, and the repo-safe metadata listed here.

Use this file as the first stop when a timeline opens with missing media.

## Downloaded Separately

The public README lists the current large-file download entry points:

- Full-size footage: `rattle-footage`
- Proxy footage: `rattle-proxies`
- Production audio: `rattle-audio`
- Miscellaneous source assets: `rattle-00-source-misc`

Large files should stay outside Git. If a PR adds or changes required media, include the download location and Resolve relink notes in the PR body.

## Repo-Safe Metadata

These tracked files preserve useful local context without committing the media itself:

| File | Purpose |
| --- | --- |
| `docs/assets-manifest.json` | High-level manifest of external media groups and metadata snapshots. |
| `docs/metadata/external-media/gigafile-broll-download-manifest.json` | Sanitized post-footage transfer manifest with filenames, target paths, sizes, hashes, and actions. Transient GigaFile URLs were removed. |
| `docs/metadata/resolve/resolve-clip-context-broll-log.json` | Resolve timeline clip-context snapshot for the b-roll review before the correction pass. |
| `docs/metadata/resolve/resolve-clip-context-broll-log-post.json` | Resolve timeline clip-context snapshot after the b-roll correction pass. This local snapshot is currently byte-identical to the pre-correction snapshot, but kept under the original audit filename. |
| `docs/metadata/audio/premiumbeat-waveform-alignment.json` | Waveform-alignment evidence used when replacing PremiumBeat preview audio with licensed files. |
| `docs/metadata/render-logs/1801-final-final-tweaks-frameio-hq-4k-noproxy-20260701-193655-render-log.json` | Render log for the Frame.io HQ 4K no-proxy export. |
| `docs/metadata/render-logs/1801-final-tweaks_2-render-log.json` | Render log for the `1801-final-tweaks_2` export. |
| `docs/metadata/resolve/rattle-v001-pre-color-science-settings-20260625-075923.json` | Resolve project color-management settings captured before color-science changes. |

## Licensing Boundaries

Do not commit these categories directly unless redistribution rights have been verified and documented:

- PremiumBeat music files, stems, loops, short edits, ZIPs, preview MP3s, and license PDFs.
- Mixkit, Envato, Pexels, or other stock footage files.
- Freesound or other third-party sound effects without a clear license and attribution manifest.
- Generated or purchased AI media unless the license allows redistribution through this repository.

The local PremiumBeat cue in use is `Dark Altar Ritual`. The repo stores waveform/relink evidence, not the music files or the purchase license PDF.

## Relink Notes

The Resolve project expects the `00-SOURCE` folder structure to remain stable. Contributors can place downloaded media inside their own local mirror of that structure or relink Resolve bins to another external storage location.

When contributing:

- Keep the `00-SOURCE` folder structure unchanged.
- Keep large media out of Git.
- Commit small metadata only when it helps another contributor relink, verify, or reproduce the work.
- Explain all new external-media requirements in the PR.
