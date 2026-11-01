# plextool subs

Extracts the subtitle tracks embedded in MKV and MP4 files, for when subtitles
need adjusting in bulk.

## Tools

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

## Options

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
