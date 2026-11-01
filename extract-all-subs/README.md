# extract-all-subs.sh

Extracts every subtitle track from a folder tree of MKV files, for when
subtitles need adjusting in bulk. Each track is saved next to its video, named
so Plex picks it up:

```
Movie.en.srt          first English track
Movie.2.en.srt        second English track
```

```console
$ ./extract-all-subs.sh --dry-run /mnt/media/Movies    # preview
$ ./extract-all-subs.sh /mnt/media/Movies
```

| Option | Meaning |
| --- | --- |
| `DIRECTORY` | Where to search. Default is the current directory. |
| `-n`, `--dry-run` | Show what would be extracted without writing files. |
| `-f`, `--force` | Overwrite existing subtitle files. By default they are skipped. |

Needs `mkvmerge` and `mkvextract` (from MKVToolNix) and `jq`.
