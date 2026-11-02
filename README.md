# plextool

> [!WARNING]
> Still in development/testing... please raise an issue if you find one!

Command line tools for Plex library maintenance, built on
[python-plexapi](https://python-plexapi.readthedocs.io/). They talk to the
server through its API. Nothing here touches the Plex database file, which is
too risky to edit by hand.

## What it is useful for

plextool is a command line toolkit for looking after a Plex Media Server: fixing
things Plex's web interface can't, and finding problems across a large library.
Typical jobs:

- **Fix the Recently Added order.** This is what it was first built for. Plex has no way to
  edit the Recently Added lists, so after you rebuild the database, delete
  duplicate files and rescan, or reorganise files on disk, everything shows up as
  "new" and the real newest content is buried. [`plextool recent`](https://github.com/milkmansson/plextool/blob/main/plextool/recent.md)
  changes the "added at" date of movies, shows, seasons and episodes: set each
  item back to its own release or air date, shift dates by an offset, or set one date for a
  whole batch. The date is locked so a rescan can't undo it.
  ```console
  $ plextool recent --recent 20 --release              # preview: put the 20 newest back to their release dates
  $ plextool recent --title "Some Show" --shift=-30d --commit
  ```
- **Find and remove duplicate movies and episodes.** [`plextool dupes`](https://github.com/milkmansson/plextool/blob/main/plextool/dupes.md)
  lists every item Plex holds more than one file for, and can delete the extras you don't want.
- **Free up disk space.** [`plextool stale`](https://github.com/milkmansson/plextool/blob/main/plextool/stale.md) finds large, never-watched or
  long-idle movies and shows.
- **Audit a library.** [`plextool audit`](https://github.com/milkmansson/plextool/blob/main/plextool/audit.md) reports unmatched items, missing files,
  missing posters or summaries, low-resolution video, and missing subtitle or audio languages.
- **Copy, back up and restore watched status.** [`plextool watched`](https://github.com/milkmansson/plextool/blob/main/plextool/watched.md) moves watched
  state between users (for example when a shared account is split), saves it to a file, and
  restores it after a rebuild or when someone closes and reopens their Plex account.
- **Clear a stuck Continue Watching list.** [`plextool resume`](https://github.com/milkmansson/plextool/blob/main/plextool/resume.md) lists and removes
  entries that won't go away.
- **Back up and restore playlists.** [`plextool playlists`](https://github.com/milkmansson/plextool/blob/main/plextool/playlists.md) saves video playlists
  to a file and recreates them on the same or another server.
- **Get subtitles.** [`plextool subs`](https://github.com/milkmansson/plextool/blob/main/plextool/subs.md) extracts the subtitle tracks inside MKV and MP4
  files, searches Plex's subtitle providers for a language and downloads one, and copies
  subtitles Plex downloaded out of its database into files beside the video. Plex itself
  never writes them there.
- **Script Plex.** Reports can print JSON, and exports can go through a pipe, so the output
  feeds other tools.

Everything that changes the server is a preview until you pass `--commit`. plextool uses Plex's API and
never edits the Plex database file. It signs in through your browser with
[`plextool auth`](https://github.com/milkmansson/plextool/blob/main/plextool/auth.md), and works against a server on the same machine, across the
internet, or directly with no internet access ([`plextool server`](https://github.com/milkmansson/plextool/blob/main/plextool/server.md)).

## Commands

| Command | What it does |
| --- | --- |
| [`plextool auth`](https://github.com/milkmansson/plextool/blob/main/plextool/auth.md) | Sign in to Plex with a link or QR code, list and remove old sign-ins from your account, and wipe the saved login and keys. |
| [`plextool server`](https://github.com/milkmansson/plextool/blob/main/plextool/server.md) | Find servers on your account or network and choose the one to use. Covers working offline or directly against the server. |
| [`plextool status`](https://github.com/milkmansson/plextool/blob/main/plextool/status.md) | Server version, library sizes, who is watching what. |
| [`plextool scan`](https://github.com/milkmansson/plextool/blob/main/plextool/scan.md) | Scan libraries or a single folder, refresh metadata, empty trash, optimize. |
| [`plextool recent`](https://github.com/milkmansson/plextool/blob/main/plextool/recent.md) | Change "added at" dates to reorder Recently Added. Works on movies, shows, seasons and episodes. |
| [`plextool dupes`](https://github.com/milkmansson/plextool/blob/main/plextool/dupes.md) | List movies and episodes that have more than one file, and optionally delete the extras. |
| [`plextool stale`](https://github.com/milkmansson/plextool/blob/main/plextool/stale.md) | Find large, unwatched or long-idle content to free up space. |
| [`plextool audit`](https://github.com/milkmansson/plextool/blob/main/plextool/audit.md) | Find unmatched items, missing files, missing posters or summaries, low resolution, missing subtitle or audio languages. |
| [`plextool watched`](https://github.com/milkmansson/plextool/blob/main/plextool/watched.md) | Copy watched state between users, back it up and restore it, or mark a show or movie watched. |
| [`plextool resume`](https://github.com/milkmansson/plextool/blob/main/plextool/resume.md) | List or clear stuck Continue Watching entries. |
| [`plextool playlists`](https://github.com/milkmansson/plextool/blob/main/plextool/playlists.md) | Back up and restore video playlists. |
| [`plextool subs`](https://github.com/milkmansson/plextool/blob/main/plextool/subs.md) | Extract subtitles from MKV and MP4 files, search Plex's subtitle providers for new ones and pick which to download, and copy subtitles Plex downloaded (kept in its database, not beside the video) out as files next to the video. Files are named for Plex, forced and SDH included. |

The `plextool` commands that change anything do a dry run unless you pass
`--commit`. Deleting files (`dupes --keep`) also asks you to type `DELETE`.

## Quick start

Download the code and install it. This needs `git` and `python` installed as a prerequisite:

```console
$ git clone https://github.com/milkmansson/plextool.git
$ cd plextool
$ python3 -m venv .venv && source .venv/bin/activate   # optional: keeps plextool's packages separate
$ pip install '.[qr]'               # '[qr]' adds a QR code to the sign-in; leave it off if you don't want one
$ plextool auth login               # open the link it prints (or scan the QR code) and approve
$ plextool server find              # servers on your Plex account and on your network
$ plextool server use "My Server"   # one of the names from the list
$ plextool status                   # libraries, and who is watching what right now
```

`status` ends with what is playing:

```console
Now playing (1 session, 0 transcoding)
  alice: Some Movie (2020) [playing] on Living Room TV
```

To get, say, Swedish subtitles for that movie from the subtitle providers Plex searches:

```console
$ plextool subs fetch -t "Some Movie" --lang sv --list               # see what is available; nothing is downloaded
$ plextool subs fetch -t "Some Movie" --lang sv --choose --commit    # pick one; Plex downloads it
$ plextool subs fetch -t "Some Movie" --lang sv --choose --export --commit   # same, and also save a file beside the video
```

Plex keeps a subtitle it downloads from a provider in its own database. It does not
write a file next to the video, meaning, only Plex can use the subtitles it downloads. The first two commands stop
there: pick the subtitle from the player's subtitle menu.

The third command, with `--export`, also gives an ordinary subtitle file
(`<video name>.sv.srt`, which other players and servers can use): plextool copies the
subtitle out of Plex and saves it beside the video. For that, the machine you run it on
must be able to read the media files. If it sees them under a different path than Plex
does, use `--map`. The [`subs` page](https://github.com/milkmansson/plextool/blob/main/plextool/subs.md#where-each-subtitle-comes-from)
sets out where each kind of subtitle comes from.

For a TV show, `-t "Some Show"` covers every episode, which is a search for each one,
so start with `--list`.

If the server is on the machine you are typing on, skip `server find` and `server use`:
plextool tries `http://localhost:32400` by default. Without internet access, see
[working offline](https://github.com/milkmansson/plextool/blob/main/plextool/server.md#working-offline-or-directly-against-the-server).

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

plextool is tested on Python 3.12. It declares Python 3.9 or later, so pip will
install it on older versions. If something doesn't work on one, please
[open an issue](https://github.com/milkmansson/plextool/issues) with your Python
version.

`plextool subs` also needs MKVToolNix (`mkvmerge`, `mkvextract`) for MKV files and
FFmpeg (`ffmpeg`, `ffprobe`) for MP4 files. You only need the ones for the file types
you use.

```console
$ git clone https://github.com/milkmansson/plextool.git     # skip if you already have the code
$ cd plextool
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
$ plextool server find                       # skip if the server is on this machine
$ plextool server use "My Server"            # or: server use http://myserver:32400
```

Without a saved choice, plextool uses `http://localhost:32400`, or `$PLEX_URL`
or `--base-url` if given. [`plextool server`](https://github.com/milkmansson/plextool/blob/main/plextool/server.md) explains the
options, including working with no internet or directly on the server's machine.

That saves a Plex token in `~/.config/plextool/` (readable only by you).
[`plextool auth`](https://github.com/milkmansson/plextool/blob/main/plextool/auth.md) explains exactly what is kept, how to wipe it
with `plextool auth wipe`, and `--type jwt`, a short-lived token that plex.tv
accepts but Plex Media Server doesn't yet.

If you would rather supply your own [Plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/),
plextool looks for one in this order: `--token`, `--token-file FILE` (`-` for
standard input), `$PLEX_TOKEN`, the output of `$PLEX_TOKEN_CMD`, then the saved
login. Prefer `--token-file` or the environment to `--token`, which leaves the
token in your shell history.

## Development

```console
$ pip install -e '.[dev]'
$ pytest
```

## Disclaimer

These tools only use the documented plexapi calls, but they do write to your
server when you pass `--commit`. Check the dry run first. Use at your own risk.
