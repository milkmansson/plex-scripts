# plextool audit

Reports problems across the libraries. Read-only.

Handy when:
- Some items never matched an online source, and they need finding before they get lost in the library.
- Files were moved or deleted on disk, and Plex still lists the items.
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
