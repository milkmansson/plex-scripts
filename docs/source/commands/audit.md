# plextool audit

Reports problems across the libraries. Read-only, except for `--clean-missing`.

Handy when:
- Some items never matched an online source, and they need finding before they get lost in the library.
- Files were moved or deleted on disk, and Plex still lists the items (`--clean-missing` removes them).
- Subtitles or audio tracks are about to be added, and the items missing a language need finding.
- A library is being tidied, and the low-resolution items, or those with no poster or summary, are the target.

```console
$ plextool audit                                  # the checks that need no extra option
$ plextool audit -c missing-files -c unmatched
$ plextool audit -c no-subs --lang eng -l "TV Shows"
```

| Check | Reports |
| --- | --- |
| `unmatched` | Movies/shows not matched to an online source. |
| `no-poster` | Items with no poster. |
| `no-summary` | Items with no summary. |
| `missing-files` | Items whose files Plex says are gone from disk. |
| `low-res` | Items that only exist in SD or 480p-and-below. |
| `no-subs` | Items with no subtitle track in `--lang`. |
| `no-audio` | Items with no audio track in `--lang`. |

With no `--check`, every check that doesn't need `--lang` runs.

`--lang` is the three-letter code Plex shows, such as `eng`, `fra`, `deu`.
`no-subs` and `no-audio` load every item to read its tracks, so they are slow
on large libraries. In TV libraries, `unmatched`, `no-poster` and `no-summary`
look at shows, and the rest look at each episode.

Other options: `-l` for a library, `-n` to cap problems shown per check, `--json`.

## Removing items whose files are gone

```console
$ plextool audit --clean-missing                 # preview
$ plextool audit --clean-missing --commit
```

Plex keeps listing an item after its file is deleted until the library is scanned and the trash is emptied.
`--clean-missing` does exactly that, the way Plex does: it lists the items with missing files, then (with `--commit`)
scans each affected library so Plex moves them to the trash, waits for the scan to finish, and empties the trash.
It never deletes an item itself and never touches files on disk, and it works through Plex's API, not the database.

Two things to know before committing. Emptying the trash removes everything already in it, not only the items
listed, and the watch history of removed items is lost. And if more than 25% of a library is missing, nothing is
changed and the command says why, because that usually means a drive or network share is not mounted, not that
files were deleted. Fix the storage first, or pass `--force` to go ahead. Plex's article on
[emptying the library trash](https://support.plex.tv/articles/200289326-emptying-library-trash/) describes the same steps in the web app.
