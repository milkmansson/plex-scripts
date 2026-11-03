# plextool scan

Asks the server to scan libraries for new files, refresh metadata, and tidy up.
This is the step you need after moving files around or after
[`plextool subs extract`](subs.md).

Handy when:
- You moved or added files outside Plex and the library has not noticed.
- You just ran `plextool subs extract` and Plex needs to see the new subtitle files.
- Metadata for a library looks out of date and you want it refreshed.
- The trash needs emptying, or the database needs optimising.

```console
$ plextool scan                                     # scan every library
$ plextool scan -l Movies --path /mnt/media/Movies/New --wait
$ plextool scan -l "TV Shows" --refresh
$ plextool scan --empty-trash --optimize
```

| Option | Meaning |
| --- | --- |
| `-l`, `--library NAME` | Library to act on. Repeat for several. Default is all movie and TV libraries. |
| `--path DIR` | Scan only this folder, as the server sees the path. Needs exactly one `--library`. |
| `--refresh` | Force a metadata refresh from the internet. Slow on big libraries. Locked fields are left alone. |
| `--empty-trash` | Empty each library's trash. |
| `--optimize` | Optimize the server database. |
| `--clean-bundles` | Remove unused metadata bundles. |
| `--wait` | Wait until the libraries stop scanning. |

With only maintenance options (`--empty-trash`, `--optimize`, `--clean-bundles`)
no scan is started. Scans run on the server, so the command returns quickly
unless you use `--wait`.
