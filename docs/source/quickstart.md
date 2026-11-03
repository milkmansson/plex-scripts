# Quickstart

This goes from nothing to running the first commands: install plextool, sign in to
Plex, choose a server, then start using it.

## 1. Install

This needs `python` (3.9 or later; 3.12 is what plextool is tested on).

```console
$ python3 -m venv .venv && source .venv/bin/activate   # optional: keeps plextool's packages separate
$ pip install 'plextool[qr]'
$ plextool --help
```

To install from the source instead (this also needs `git`):

```console
$ git clone https://github.com/milkmansson/plextool.git
$ cd plextool
$ pip install '.[qr]'
```

`[qr]` adds a QR code to the sign-in. Leave it off if no QR code is wanted.

`plextool subs` also needs MKVToolNix (`mkvmerge`, `mkvextract`) for MKV files and
FFmpeg (`ffmpeg`, `ffprobe`) for MP4 files. Only the ones for the file types in use are needed.

## 2. Sign in

```console
$ plextool auth login
```

This prints a link (and a QR code, if `segno` is installed). Open it in a browser and
approve. plextool saves a Plex token in `~/.config/plextool/`, readable only by the current user.
See [`plextool auth`](commands/auth) for what is kept and how to wipe it.

plextool looks for a
[Plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)
in this order: `--token`, `--token-file FILE` (`-` for standard
input), `$PLEX_TOKEN`, the output of `$PLEX_TOKEN_CMD`, then the saved login. Prefer
`--token-file` or the environment to `--token`, which leaves the token in the shell history.

## 3. Choose a server

```console
$ plextool server find              # servers on the Plex account and on the network
$ plextool server use "My Server"   # one of the names from the list
```

If the server is on the same machine as the terminal, skip this step: plextool tries
`http://localhost:32400` by default. Without internet access, see
[working offline](commands/server.md#working-offline-or-directly-against-the-server).

## 4. Look around

```console
$ plextool status
```

This shows the libraries and who is watching what right now. It ends with what is playing:

```console
Now playing (1 session, 0 transcoding)
  alice: Some Movie (2020) [playing] on Living Room TV
```

## 5. Start doing things

Commands that change anything do a dry run unless `--commit` is given. Deleting files
(`dupes --keep`) also asks for `DELETE` to be typed. Check the dry run first.

Every command explains itself, with options and examples:

```console
$ plextool --help
$ plextool recent --help
$ plextool watched copy --help
```

If a command is slow and its progress is wanted, add `-v` (`--verbose`). It prints each
request sent to Plex, with the time, then a line for the reply (status, number of records,
size and how long it took), and when each slow step starts and finishes, on standard error. The token is hidden. After about 10 seconds of silence, plextool also prints
`still reading ...` notices every 20 seconds even without `-v`. A command that takes more than 5 seconds also ends with
`Finished in 2m 14s`.

For example, to get Swedish subtitles for a movie from the subtitle providers Plex searches:

```console
$ plextool subs fetch -t "Some Movie" --lang sv --list               # see what is available; nothing is downloaded
$ plextool subs fetch -t "Some Movie" --lang sv --choose --commit    # pick one; Plex downloads it
$ plextool subs fetch -t "Some Movie" --lang sv --choose --export --commit   # same, and also save a file beside the video
```

When Plex downloads a subtitle from a provider, it keeps the copy in its own database and
does not put a file next to the video, so only Plex can show it. `--export` copies Plex's
stored copy out and saves it beside the video (`<video name>.sv.srt`), where any player can
use it. The [`subs` page](commands/subs.md#where-each-subtitle-comes-from) explains where each kind of
subtitle comes from, and how `--map` helps if the media is under a different path on the
machine plextool runs on.

For a TV show, `-t "Some Show"` covers every episode, which is a search for each one, so
start with `--list`.

## Next

Pick a command from the list on the left, or see the table in the
[README](https://github.com/milkmansson/plextool#commands).
