# plextool recent

Plex has no way to edit the Recently Added lists. This command changes the
"added at" date on items, which moves them forward or back in those lists.

Handy when:
- You recreated the database and the real newest content needs to be at the front.
- You deleted duplicate files, Plex rescanned, and everything came back as "new".
- You reorganised files on disk and Plex treated them as new additions.

```console
$ plextool recent (--title T | --guid ID | --recent N) (--date D | --release | --now | --shift OFFSET) [options]
```

Without `--commit` it only prints what it would do.

## Choosing items

Exactly one of:

| Option | Meaning |
| --- | --- |
| `-t`, `--title TEXT` | Titles containing TEXT. The year is not part of the title; Plex stores it separately. |
| `-g`, `--guid ID` | One item by Plex ID (`plex://movie/...`) or agent ID (`imdb://tt...`, `tmdb://...`, `tvdb://...`). Also `-p`/`--plex-id`. |
| `-n`, `--recent N` | The N most recently added items, per library. |

Narrow it down with:

| Option | Meaning |
| --- | --- |
| `-l`, `--library NAME` | Library to use. Repeat for several. Default is every movie and TV library. |
| `--level` | `movie`, `show`, `season` or `episode`. Default is `movie` in movie libraries and `show` in TV libraries. |
| `--cascade` | When changing a show or season, change its seasons and episodes too. |

## Choosing the new date

Exactly one of:

| Option | Meaning |
| --- | --- |
| `-d`, `--date DATE` | Use this date: `YYYY-MM-DD` or `"YYYY-MM-DD HH:MM:SS"`. |
| `-r`, `--release` | Use each item's own release or air date. Items with no release date are skipped. |
| `-N`, `--now` | Use the current time. |
| `-s`, `--shift OFFSET` | Move each item's current date by an offset: a number plus `min`, `h`, `d` or `w`. Write negatives with an equals sign: `--shift=-30d`. |

Future dates work. They put the item at the front until that date passes.

## Writing

`-y`, `--commit` (also `--confirm`) applies the changes.

By default the new date is **locked** in Plex, the same as editing the date in
the web UI, so a later rescan or metadata refresh leaves it alone. Pass
`--no-lock` to write the date without locking it.

## TV shows

Plex builds the TV Recently Added list from **episodes**, so changing only the
show usually changes nothing visible. To reorder a series, use `--cascade`, or
work on episodes directly with `--level episode`.

## Examples

Preview the last 3 movies added:

```console
$ plextool recent -l Movies -n 3 --release
```

Send one movie back to its release date, by Plex ID:

```console
$ plextool recent -g plex://movie/62343531cf31d465454ccb34afad --release --commit
```

Set a whole series, every season and every episode, to each episode's air date:

```console
$ plextool recent -l "TV Shows" -t "Some Show" --cascade --release --commit
```

Push the 20 newest episodes back a week:

```console
$ plextool recent -l "TV Shows" --level episode -n 20 --shift=-7d --commit
```

## Notes

- Dates you give are read as local time.
- A title search matches substrings, so "Lord" finds "Lord of the Rings",
  "Lord of the Flies" and "Sealord". Review the dry run, then select the one
  you want by `--guid`.
- Searching by agent ID (`imdb://`, etc.) checks each item's IDs locally, which
  is slower on big libraries than a Plex ID lookup.
