# plextool dupes

Lists movies and episodes for which Plex holds more than one file, so that
what to delete can be decided. It is read-only unless `--keep` is used. Using the Plex web UI for this is slow,
and awkward with spaces or non-Latin characters in file names.

Handy when:
- A title appears twice, or a folder holds two versions of the same movie or episode.
- Files were re-encoded or upgraded and the old copies are still there.
- Disk space is needed and the duplicates that would free the most should come first (`--sort size`).

```console
$ plextool dupes [-l NAME ...] [-n LIMIT] [--sort title|size] [--json] [--keep POLICY [--commit]]
```

| Option | Meaning |
| --- | --- |
| `-l`, `--library NAME` | Library to scan. Repeat for several. Default is every movie and TV library. |
| `-n`, `--limit N` | Show at most N items per library. |
| `--sort` | `title` (default), or `size` for the most reclaimable space first. |
| `--json` | Print JSON instead of text, for scripts. |
| `--keep POLICY` | Delete the other versions of every duplicate. See below. |
| `-y`, `--commit` | With `--keep`: actually delete. |
| `--assume-yes` | With `--commit`: skip the typed confirmation. |

TV libraries are checked per episode.

## Example

```console
$ plextool dupes -l Movies
== Movies: 4 items with duplicates ==
    1 Title One (2021)
     - [0] /mnt/sdb1/Title One 1080p/Title.Extended.Cut.2021.1080p.mkv  13.0 GB  [1080 h264]
     - [1] /mnt/sdf1/Title One (2021)/Movie.Title.1.H264-ABC.mkv  5.0 GB  [1080 h264]
    2 Title Two (2002)
     - [0] /mnt/sdc1/Title Two/Title.2002.1080p.BluRay.x264-GROUP.mkv  8.0 GB  [1080 h264]
     - [1] /mnt/sdd1/Title Two/Title.2002.1080p.BluRay.x264-GROUP.mkv  8.0 GB  [1080 h264]
    3 Title Three (1999)
     - [0] 2 parts, 700.0 MB total
         /mnt/sdd1/Title Three/m-title-1-t-a.avi  350.0 MB
         /mnt/sdd1/Title Three/m-title-1-t-b.avi  350.0 MB
         (multi-part version: these files play as one item; deleting one part breaks it)
     - [1] /mnt/sdd1/Title Three/title3.mkv  600.0 MB  [720 h264]
    4 Title Seven (2009)
     - [0] /mnt/sdc1/7 2009 1080p/7.m2ts  3.0 GB  [1080 h264]
     - [1] /mnt/sdb1/7 2009 720p/7.2009.720p.mkv  6.0 GB  [720 h264]

4 items with duplicates; 16.6 GB could be freed by keeping only the largest version of each.
```

1. Same movie, different file names and sizes.
2. Same file name in two directories (here, on different drives).
3. A movie split across several files, listed as one version. Deleting one part
   breaks it. See "Movies Split Across Multiple Files" in
   [Plex's naming guide](https://support.plex.tv/articles/naming-and-organizing-your-movie-media-files/).
4. Two different encodes of the same title.

"Reclaimable" counts everything except the largest version. It is a guide to
size, not a recommendation about which copy to keep.

## Deleting duplicates

`--keep` keeps one version of each duplicate and deletes the rest:

| Policy | Keeps |
| --- | --- |
| `largest` | The biggest file. |
| `smallest` | The smallest file. |
| `best-resolution` | The highest resolution, then the biggest. |

```console
$ plextool dupes -l Movies --keep best-resolution            # preview
$ plextool dupes -l Movies --keep best-resolution --commit   # asks for DELETE to be typed
```

This **permanently deletes files from disk**. It is a preview unless `--commit` is
passed, and then `DELETE` must be typed to continue (`--assume-yes` skips
that for scripts). Items with a multi-part version are skipped, since deleting
one part would break the item. Plex must have "Allow media deletion" turned on
(Settings > Library), or the server refuses.

Because the duplicates are whatever Plex has matched together, read the
preview before committing. A wrong match means a wrong deletion. Use `--limit`
to work in small batches.

## Caveat

A duplicate here means Plex has matched both files to the same item. Matches
can be wrong, or made by hand, and no file name analysis is applied. If Plex is
wrong, so is this list.

## See also

[l3uddz/plex_dupefinder](https://github.com/l3uddz/plex_dupefinder) does more,
including more elaborate rules for choosing what to delete.
