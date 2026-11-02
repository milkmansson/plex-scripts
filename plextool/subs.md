# plextool subs

Three actions for subtitles:

| Action | What it does |
| --- | --- |
| [`extract`](#extract) | Pull the subtitle tracks embedded in MKV and MP4 files out as separate files. |
| [`export`](#export) | Copy subtitles that Plex downloaded out of its database and save them next to the video. |
| [`fetch`](#fetch) | Search Plex's subtitle providers for a language and download one, with a chance to choose. |

All three name files the same way (see [Naming](#naming)) and are a preview
unless you pass `--commit`.

## Tools for extract

You only need the tools for the file types you use:

| Files | Needs |
| --- | --- |
| `.mkv` | `mkvmerge` and `mkvextract` from MKVToolNix |
| `.mp4`, `.m4v` | `ffmpeg` and `ffprobe` from FFmpeg |

If one set is missing, files of that type are skipped with a note saying what to
install, and the rest are processed as normal. It only stops with an error if
none of the files found can be handled. Use `--types mkv` or `--types mp4` to
limit the run to one kind.

## extract

```console
$ plextool subs extract /mnt/media/Movies            # preview
$ plextool subs extract /mnt/media/Movies --commit
$ plextool subs extract /mnt/media/Movies --commit --scan Movies
```

Every video under the directory (default: the current one), including all
subfolders, is checked. Each subtitle track is saved beside its video.

## Naming

These rules apply to all three actions.

Names follow Plex's rules for external subtitles: the language code, then
`.forced` or `.sdh` if the track is flagged that way, then the extension.

| Track | File |
| --- | --- |
| English | `Movie.en.srt` |
| English, forced | `Movie.en.forced.srt` |
| English, SDH (hearing impaired) | `Movie.en.sdh.srt` |
| Spanish | `Movie.es.srt` |
| French image subtitles (PGS) | `Movie.fr.sup` |
| A second, otherwise identical English track | `Movie.2.en.srt` |
| A second English SDH track | `Movie.2.en.sdh.srt` |

- A track counts as forced or SDH if the file marks it so, or if its name says
  so, such as "English (SDH)", "Hearing Impaired", "Closed Captions" or "Forced".
- A number is added only when two tracks would otherwise get the same name, so
  flagged tracks don't get one. The first of a kind has no number, and later
  ones are 2, 3 and so on. The number goes in front of the language because
  Plex reads the language from the end of the name.
- Language codes are short (`en`, `fr`, `pt`). Languages with no short code
  stay three letters, and tracks with no language are `und`.
- The extension follows the format: `srt`, `ass`, `vtt`, `sup` (PGS), or `sub`
  (VobSub, which also writes an `.idx`). In MP4 files text tracks (usually
  `mov_text`) become `srt`.
- Image-based subtitles inside MP4 files can't be turned into usable files.
  They are listed as skipped.

## Options for extract

| Option | Meaning |
| --- | --- |
| `DIRECTORY` | Where to search. Default is the current directory. |
| `--types LIST` | File types to process: `mkv`, `mp4`, or `mkv,mp4` (default). |
| `-y`, `--commit` | Write the files. Without it you get a preview. |
| `-f`, `--force` | Overwrite subtitle files that already exist. By default they are skipped. |
| `--scan LIBRARY` | After extracting, ask Plex to scan this library so the files appear. |
| `--scan-path PATH` | Folder to scan, as the Plex server sees it. Default is the directory you searched. Set this if the server mounts your media at a different path. |

Only `--scan` needs a Plex connection (`--token`, `--base-url`). The rest works
without a server.

## export

When you use Plex's "Search for subtitles", the result is stored in Plex's
database, not beside the video, and can't be reused elsewhere. `export` saves
those subtitles as ordinary files next to the video.

```console
$ plextool subs export -t "Some Show"                   # preview
$ plextool subs export --all --lang eng --commit --scan
$ plextool subs export -l Movies -n 20 --map /data/media=/mnt/media --commit
```

Choose what to look at with one of `-t/--title` (a movie, or a show, which means
all its episodes), `-g/--guid`, `-n/--recent N`, or `--all`.

| Option | Meaning |
| --- | --- |
| `-l`, `--library NAME` | Library to use. Repeat for several. Default is every movie and TV library. |
| `--lang LANG` | Only this language, eg `en` or `eng`. |
| `--all-external` | Also include subtitle files that were already beside the video. Normally only ones downloaded from a provider are exported. |
| `--map SERVER=LOCAL` | Translate a path as Plex sees it into one on this machine, eg `/data/media=/mnt/media`. Repeat for several. |
| `-f`, `--force` | Overwrite files that already exist. By default they are skipped. |
| `--scan` | Afterwards, ask Plex to scan the folders that got new files. |
| `-y`, `--commit` | Write the files. |

This command has to be able to reach the video files. If you run it on another
machine, or Plex sees your media under a different path, use `--map`. A folder
that can't be found is reported rather than created.

Each item is loaded from the server to read its subtitle list, so `--all` is
slow on big libraries. Narrow it with `-l`, `-t` or `-n` when you can.

## fetch

Searches Plex's subtitle providers for movies and episodes that have no subtitle
in a language, and downloads one into Plex.

Plex keeps what it downloads in its own database and does not write a file next to
the video, so only Plex can use it. Add `--export` to also save it as a file beside
the video, which other players and servers can use. That needs this machine to be
able to read the media files (see `--map`).

```console
$ plextool subs fetch -t "Some Movie" --lang en --list         # just look
$ plextool subs fetch -t "Some Show" --lang fr --choose --commit
$ plextool subs fetch -n 20 --lang en --sdh prefer --export --commit
```

### Choosing which subtitle

The most popular result isn't always the right one, so there are three ways to
work:

| Mode | What happens |
| --- | --- |
| `--list` | Shows the candidates for each item and stops. Nothing is downloaded. |
| `--choose` | Shows the candidates for each item and asks you which to download. Enter takes #1, a number takes that one, `s` skips the item, `q` stops. |
| (neither) | Downloads the top-ranked candidate automatically. |

Candidates are ranked with perfect matches first, then by download count
(score). Each line shows the number, a `*` for a perfect match, the score, the
provider, the format, forced/SDH flags, and the subtitle's own title (often the
release name, which helps you match it to your file).

```
  1 * score 20      OpenSubtitles    srt                Some.Movie.2020.1080p.BluRay
  2   score 5230    OpenSubtitles    srt                Some.Movie.2020.WEB-DL
  3   score 880     OpenSubtitles    srt    sdh         Some.Movie.2020.1080p.BluRay.SDH
```

### Options

| Option | Meaning |
| --- | --- |
| `--lang LANG` | Language to look for, eg `en` or `eng`. Required. |
| `-t`, `-g`, `-n`, `--all`, `-l` | Which items, as for `export`. |
| `--sdh prefer\|only\|exclude` | What to do about SDH (hearing impaired) subtitles. |
| `--forced prefer\|only\|exclude` | What to do about forced subtitles. |
| `--min-score N` | Ignore candidates with a lower download count. Perfect matches are always kept. |
| `--candidates N` | Show at most N candidates per item (default 10). |
| `--include-present` | Also search items that already have a subtitle in this language. |
| `--export` | After downloading, save the new subtitle beside the video. |
| `--wait SECONDS` | With `--export`, how long to wait for each download to arrive (default 30). |
| `--map`, `-f`, `--scan`, `-y/--commit` | As for `export`. |

Plex downloads in the background. Without `--export` the command returns once
the downloads are requested. With it, the command waits for each new subtitle to
show up and then saves it. If one hasn't arrived in time, run `subs export`
afterwards.

Every item checked means a search against the subtitle provider, so start with
`-t` or `-n` before trying `--all`.
