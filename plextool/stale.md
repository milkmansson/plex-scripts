# plextool stale

Finds what is taking disk space and not being watched. Movies are listed
individually; TV is summed per show. Read-only.

```console
$ plextool stale --unwatched --age 365 --min-size 5GB
$ plextool stale -l Movies --idle 730 -n 20
```

| Option | Meaning |
| --- | --- |
| `-l`, `--library NAME` | Library to scan. Default is all movie and TV libraries. |
| `--unwatched` | Only things never watched. |
| `--idle DAYS` | Only things not watched in the last DAYS days (or never). |
| `--age DAYS` | Only things added more than DAYS days ago. |
| `--min-size SIZE` | Ignore anything smaller, eg `500MB`, `5GB`. |
| `-n`, `--limit N` | Show the N biggest (default 50). |
| `--json` | Print JSON instead of text. |

Conditions combine with AND. Sizes add up every file attached to an item,
including duplicate versions.

Watch history is the **token owner's**. Other users' viewing doesn't count, so
don't treat "unwatched" as "nobody watched it" on a shared server.
