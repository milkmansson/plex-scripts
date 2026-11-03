# plextool

> [!WARNING]
> Still in development/testing... please raise an issue if you find one!

Command line tool for Plex library maintenance, built on
[python-plexapi](https://python-plexapi.readthedocs.io/). It talks to the
server through its API. No access is made to the Plex database file, which is
too risky to edit by hand.

## What it is useful for

plextool is a command line toolkit for looking after a Plex Media Server: fixing
things Plex's web interface can't, and finding problems across a large library.
Typical jobs:

- **Fix the Recently Added order.** This is what it was first built for. Plex has no way to
  edit the Recently Added lists, so after you rebuild the database, delete
  duplicate files and rescan, or reorganise files on disk, everything shows up as
  "new" and the real newest content is buried. [`plextool recent`](https://plextool.readthedocs.io/en/latest/commands/recent.html)
  changes the "added at" date of movies, shows, seasons and episodes: set each
  item back to its own release or air date, shift dates by an offset, or set one date for a
  whole batch. The date is locked so a rescan can't undo it.
  ```console
  $ plextool recent --recent 20 --release              # preview: put the 20 newest back to their release dates
  $ plextool recent --title "Some Show" --shift=-30d --commit
  ```
- **Find and remove duplicate movies and episodes.** [`plextool dupes`](https://plextool.readthedocs.io/en/latest/commands/dupes.html)
  lists every item Plex holds more than one file for, and can delete the extras you don't want.
- **Free up disk space.** [`plextool stale`](https://plextool.readthedocs.io/en/latest/commands/stale.html) finds large, never-watched or
  long-idle movies and shows.
- **Audit a library.** [`plextool audit`](https://plextool.readthedocs.io/en/latest/commands/audit.html) reports unmatched items, missing files,
  missing posters or summaries, low-resolution video, and missing subtitle or audio languages.
- **Copy, back up and restore watched status.** [`plextool watched`](https://plextool.readthedocs.io/en/latest/commands/watched.html) moves watched
  state between users (for example when a shared account is split), saves it to a file, and
  restores it after a rebuild or when someone closes and reopens their Plex account.
- **Clear a stuck Continue Watching list.** [`plextool resume`](https://plextool.readthedocs.io/en/latest/commands/resume.html) lists and removes
  entries that won't go away.
- **Back up and restore playlists.** [`plextool playlists`](https://plextool.readthedocs.io/en/latest/commands/playlists.html) saves video playlists
  to a file and recreates them on the same or another server.
- **Get subtitles.** [`plextool subs`](https://plextool.readthedocs.io/en/latest/commands/subs.html) extracts the subtitle tracks inside MKV and MP4
  files, searches Plex's subtitle providers for a language and downloads one, and, with
  `--export`, copies the subtitle Plex downloaded out of its database into a file beside
  the video so it works outside Plex too. Plex itself never writes that file.
- **Script Plex.** Reports can print JSON, and exports can go through a pipe, so the output
  feeds other tools.

Everything that changes the server is a preview until you pass `--commit`. plextool uses Plex's API and
never edits the Plex database file. It signs in through your browser with
[`plextool auth`](https://plextool.readthedocs.io/en/latest/commands/auth.html), and works against a server on the same machine, across the
internet, or directly with no internet access ([`plextool server`](https://plextool.readthedocs.io/en/latest/commands/server.html)).

## Commands

| Command | What it does |
| --- | --- |
| [`plextool auth`](https://plextool.readthedocs.io/en/latest/commands/auth.html) | Sign in to Plex with a link or QR code, list and remove old sign-ins from your account, and wipe the saved login and keys. |
| [`plextool server`](https://plextool.readthedocs.io/en/latest/commands/server.html) | Find servers on your account or network and choose the one to use. Covers working offline or directly against the server. |
| [`plextool status`](https://plextool.readthedocs.io/en/latest/commands/status.html) | Server version, library sizes, who is watching what. |
| [`plextool scan`](https://plextool.readthedocs.io/en/latest/commands/scan.html) | Scan libraries or a single folder, refresh metadata, empty trash, optimize. |
| [`plextool recent`](https://plextool.readthedocs.io/en/latest/commands/recent.html) | Change "added at" dates to reorder Recently Added. Works on movies, shows, seasons and episodes. |
| [`plextool dupes`](https://plextool.readthedocs.io/en/latest/commands/dupes.html) | List movies and episodes that have more than one file, and optionally delete the extras. |
| [`plextool stale`](https://plextool.readthedocs.io/en/latest/commands/stale.html) | Find large, unwatched or long-idle content to free up space. |
| [`plextool audit`](https://plextool.readthedocs.io/en/latest/commands/audit.html) | Find unmatched items, missing files, missing posters or summaries, low resolution, missing subtitle or audio languages. |
| [`plextool watched`](https://plextool.readthedocs.io/en/latest/commands/watched.html) | Copy watched state between users, back it up and restore it, or mark a show or movie watched. |
| [`plextool resume`](https://plextool.readthedocs.io/en/latest/commands/resume.html) | List or clear stuck Continue Watching entries. |
| [`plextool playlists`](https://plextool.readthedocs.io/en/latest/commands/playlists.html) | Back up and restore video playlists. |
| [`plextool subs`](https://plextool.readthedocs.io/en/latest/commands/subs.html) | Extract subtitles from MKV and MP4 files, search Plex's subtitle providers for new ones and pick which to download, and copy subtitles Plex downloaded (kept in its database, not beside the video) out as files next to the video. Files are named for Plex, forced and SDH included. |

The `plextool` commands that change anything do a dry run unless you pass
`--commit`. Deleting files (`dupes --keep`) also asks you to type `DELETE`.

## Quick start

Install it from PyPI. This needs `python` installed as a prerequisite:

```console
$ python3 -m venv .venv && source .venv/bin/activate   # optional: keeps plextool's packages separate
$ pip install 'plextool[qr]'        # '[qr]' adds a QR code to the sign-in; leave it off if you don't want one
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

**Where the subtitle ends up.** When Plex downloads a subtitle from a provider, it keeps
the copy in its own database. It does not put a file next to the video, so only Plex can
show it: another player, or another Plex server, never sees it. The first two commands stop
there, and you pick the subtitle from the player's subtitle menu.

**`--export` gets around that.** Once Plex has downloaded the subtitle, plextool copies
Plex's stored copy out of the server and saves it as an ordinary file beside the video
(`<video name>.sv.srt`), which any player can use. It doesn't read the video file, so the
MKV or MP4 is never opened, and it doesn't contact the subtitle provider. (Subtitle
tracks that are already inside an MKV or MP4 are a different job, for `plextool subs extract`.)
For `--export`, the machine you run it on must be able to read the media files. If it sees
them under a different path than Plex does, use `--map`. The
[`subs` page](https://plextool.readthedocs.io/en/latest/commands/subs.html#where-each-subtitle-comes-from) sets out where each kind of subtitle comes from.

For a TV show, `-t "Some Show"` covers every episode, which is a search for each one,
so start with `--list`.

If the server is on the machine you are typing on, skip `server find` and `server use`:
plextool tries `http://localhost:32400` by default. Without internet access, see
[working offline](https://plextool.readthedocs.io/en/latest/commands/server.html#working-offline-or-directly-against-the-server).

## Getting help

Every command explains itself, with options and examples:

```console
$ plextool --help
$ plextool recent --help
$ plextool watched copy --help
```

To see what plextool is doing, add `-v` (`--verbose`) to any command. It prints each request sent
to Plex, with the time, on standard error, followed by a line for the reply: the status, how many
records were in it (and where that page sits in the whole list), its size and how long it took.
It also prints when each slow step starts and finishes. Your token
is hidden in that output.

```console
$ plextool stale --all-users -v
```

When a command takes more than 5 seconds, plextool prints `Finished in 2m 14s` on standard error at the end
(with `-v`, always).

Reading a big library can take minutes. After about 10 seconds of silence, plextool prints
`still reading <library>...` to standard error, and again every 20 seconds, so you can tell it has not
stopped. `--json` output is not affected.

A fuller page for each command is on [Read the Docs](https://plextool.readthedocs.io/)
(linked in the table above); its source is in `docs/source/commands/`.

## Install

plextool is tested on Python 3.12. It declares Python 3.9 or later, so pip will
install it on older versions. If something doesn't work on one, please
[open an issue](https://github.com/milkmansson/plextool/issues) with your Python
version.

`plextool subs` also needs MKVToolNix (`mkvmerge`, `mkvextract`) for MKV files and
FFmpeg (`ffmpeg`, `ffprobe`) for MP4 files. You only need the ones for the file types
you use.

```console
$ pip install plextool     # installs the `plextool` command
$ plextool --help
```

To install from a checkout instead (this needs `git`):

```console
$ git clone https://github.com/milkmansson/plextool.git
$ cd plextool
$ pip install .
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
or `--base-url` if given. [`plextool server`](https://plextool.readthedocs.io/en/latest/commands/server.html) explains the
options, including working with no internet or directly on the server's machine.

That saves a Plex token in `~/.config/plextool/` (readable only by you).
[`plextool auth`](https://plextool.readthedocs.io/en/latest/commands/auth.html) explains exactly what is kept, how to wipe it
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
