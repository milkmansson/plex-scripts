# plex-scripts

Command line tools for Plex library maintenance, built on
[python-plexapi](https://python-plexapi.readthedocs.io/). They talk to the
server through its API. Nothing here touches the Plex database file, which is
too risky to edit by hand.

| Command | What it does |
| --- | --- |
| [`plextool status`](docs/status.md) | Server version, library sizes, who is watching what. |
| [`plextool scan`](docs/scan.md) | Scan libraries or a single folder, refresh metadata, empty trash, optimize. |
| [`plextool recent`](docs/recent.md) | Change "added at" dates to reorder Recently Added. Works on movies, shows, seasons and episodes. |
| [`plextool dupes`](docs/dupes.md) | List movies and episodes that have more than one file, and optionally delete the extras. |
| [`plextool stale`](docs/stale.md) | Find large, unwatched or long-idle content to free up space. |
| [`plextool audit`](docs/audit.md) | Find unmatched items, missing files, missing posters or summaries, low resolution, missing subtitle or audio languages. |
| [`plextool watched`](docs/watched.md) | Copy watched state between users, back it up and restore it, or mark a show or movie watched. |
| [`plextool resume`](docs/resume.md) | List or clear stuck Continue Watching entries. |
| [`plextool playlists`](docs/playlists.md) | Back up and restore video playlists. |
| [`extract-all-subs.sh`](extract-all-subs/README.md) | Extract every subtitle track from a folder of MKV files. |

The `plextool` commands that change anything do a dry run unless you pass
`--commit`. Deleting files (`dupes --keep`) also asks you to type `DELETE`.
`extract-all-subs.sh` writes files unless you pass `--dry-run`.

## Install

Python 3.9 or later.

```console
$ pip install .            # installs the `plextool` command
$ plextool --help
```

To run from a checkout without installing, `pip install -r requirements.txt`
and use `python3 -m plextool ...` instead.

## Connecting

You need a [Plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).
Set it once in your shell so it stays out of the command line and your history:

```console
$ export PLEX_TOKEN=xxxxxxxxxxxxxxxxxxxx
$ export PLEX_URL=http://myserver:32400     # optional, default http://localhost:32400
```

`--token` and `--base-url` override these on any command.

## Upgrading from the old scripts

The three Python scripts are now subcommands of `plextool`, and flags are
lower-case:

| Old | New |
| --- | --- |
| `modify-recently-added.py -T tok -n 3 -r -y` | `plextool recent --recent 3 --release --commit` |
| `see-duplicates.py -T tok` | `plextool dupes` |
| `plex-copy-watched.py --src-user a --src-pass p ...` | `plextool watched copy --from a --to b` (no passwords) |

`-T`, `-b`, `-l`, `-t`, `-g`, `-r`, `-N`, `-d` and `-y` still work.
`recent` now also locks the date it sets, so a rescan can't undo it. The token
now comes from `PLEX_TOKEN` rather than the old `PLEX-TOKEN`.

## Development

```console
$ pip install -e '.[dev]'
$ pytest
```

## Disclaimer

These tools only use the documented plexapi calls, but they do write to your
server when you pass `--commit`. Check the dry run first. Use at your own risk.
