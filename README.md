# plex-scripts

> [!WARNING]
> Still in development/testing... please raise an issue if you find one!

Command line tools for Plex library maintenance, built on
[python-plexapi](https://python-plexapi.readthedocs.io/). They talk to the
server through its API. Nothing here touches the Plex database file, which is
too risky to edit by hand.

| Command | What it does |
| --- | --- |
| [`plextool auth`](plextool/auth.md) | Sign in to Plex with a link or QR code, get a short-lived token, and wipe the saved login and keys. |
| [`plextool status`](plextool/status.md) | Server version, library sizes, who is watching what. |
| [`plextool scan`](plextool/scan.md) | Scan libraries or a single folder, refresh metadata, empty trash, optimize. |
| [`plextool recent`](plextool/recent.md) | Change "added at" dates to reorder Recently Added. Works on movies, shows, seasons and episodes. |
| [`plextool dupes`](plextool/dupes.md) | List movies and episodes that have more than one file, and optionally delete the extras. |
| [`plextool stale`](plextool/stale.md) | Find large, unwatched or long-idle content to free up space. |
| [`plextool audit`](plextool/audit.md) | Find unmatched items, missing files, missing posters or summaries, low resolution, missing subtitle or audio languages. |
| [`plextool watched`](plextool/watched.md) | Copy watched state between users, back it up and restore it, or mark a show or movie watched. |
| [`plextool resume`](plextool/resume.md) | List or clear stuck Continue Watching entries. |
| [`plextool playlists`](plextool/playlists.md) | Back up and restore video playlists. |
| [`plextool subs`](plextool/subs.md) | Extract subtitles from MKV and MP4 files, save Plex's on-demand downloaded subtitles next to the video, or search for new ones and pick which to download. Files are named for Plex, forced and SDH included. |

The `plextool` commands that change anything do a dry run unless you pass
`--commit`. Deleting files (`dupes --keep`) also asks you to type `DELETE`.

## Getting help

Every command explains itself, with options and examples:

```console
$ plextool --help
$ plextool recent --help
$ plextool watched copy --help
```

A fuller page for each command sits beside its code, in `plextool/<command>.md`
(linked in the table above).

## Install

Python 3.9 or later. `plextool subs` also needs MKVToolNix (`mkvmerge`,
`mkvextract`) for MKV files and FFmpeg (`ffmpeg`, `ffprobe`) for MP4 files. You
only need the ones for the file types you use.

```console
$ pip install .            # installs the `plextool` command
$ plextool --help
```

To run from a checkout without installing, `pip install -r requirements.txt`
and use `python3 -m plextool ...` instead.

## Connecting

Sign in once. This prints a link (and a QR code, if `segno` is installed) to
approve in a browser:

```console
$ plextool auth login
$ export PLEX_URL=http://myserver:32400     # optional, default http://localhost:32400
```

That saves a short-lived token, and the signing key that renews it, in
`~/.config/plextool/` (readable only by you). [`plextool auth`](plextool/auth.md)
explains exactly what is kept, how to wipe it with `plextool auth wipe`, and the
`--type token` alternative.

If you would rather supply your own [Plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/),
plextool looks for one in this order: `--token`, `--token-file FILE` (`-` for
standard input), `$PLEX_TOKEN`, the output of `$PLEX_TOKEN_CMD`, then the saved
login. Prefer `--token-file` or the environment to `--token`, which leaves the
token in your shell history.

## Upgrading from the old scripts

The three Python scripts are now subcommands of `plextool`, and flags are
lower-case:

| Old | New |
| --- | --- |
| `modify-recently-added.py -T tok -n 3 -r -y` | `plextool recent --recent 3 --release --commit` |
| `see-duplicates.py -T tok` | `plextool dupes` |
| `plex-copy-watched.py --src-user a --src-pass p ...` | `plextool watched copy --from a --to b` (no passwords) |
| `extract-all-subs.sh --dry-run DIR` | `plextool subs extract DIR` (preview by default; add `--commit` to write) |

`-T`, `-b`, `-l`, `-t`, `-g`, `-r`, `-N`, `-d` and `-y` still work.
`recent` now also locks the date it sets, so a rescan can't undo it. The token
now comes from `PLEX_TOKEN` rather than the old `PLEX-TOKEN`, or from `plextool auth login`.

## Development

```console
$ pip install -e '.[dev]'
$ pytest
```

## Disclaimer

These tools only use the documented plexapi calls, but they do write to your
server when you pass `--commit`. Check the dry run first. Use at your own risk.
