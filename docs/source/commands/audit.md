# plextool audit

Reports problems across your libraries. Read-only.

Handy when:
- You want a list of what Plex could not match, so you can fix it before it gets lost in the library.
- You moved or deleted files on disk and want to know which items now point at nothing.
- You are about to add subtitles or audio tracks and want to know which items lack a language.
- You are tidying up and want the low-resolution items, or those with no poster or summary.

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
