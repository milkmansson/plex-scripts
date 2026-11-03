# plextool scan

Asks the server to [scan libraries](https://support.plex.tv/articles/200392106-library-actions/) for new files, refresh metadata, and tidy up.
This is the step needed after moving files around or after
[`plextool subs extract`](subs.md).

Handy when:
- Files were moved or added outside Plex and the library has not noticed.
- `plextool subs extract` has just run and Plex needs to see the new subtitle files.
- Metadata for a library looks out of date and needs refreshing.
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
| `--empty-trash` | [Empty](https://support.plex.tv/articles/200289326-emptying-library-trash/) each library's trash. |
| `--optimize` | Optimize the server database (see Plex's [troubleshooting article](https://support.plex.tv/articles/226836308-help/)). |
| `--clean-bundles` | Remove unused metadata bundles. |
| `--wait` | Wait until the libraries stop scanning. |

With only maintenance options (`--empty-trash`, `--optimize`, `--clean-bundles`)
no scan is started. Scans run on the server, so the command returns quickly
unless `--wait` is used.
