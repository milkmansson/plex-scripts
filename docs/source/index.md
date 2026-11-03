# plextool

Maintenance helpers for a Plex Media Server: refresh and scan libraries, reorder Recently
Added, find duplicates and stale content, audit libraries, copy watched state, back up
playlists and manage subtitles.

Install with `pip install plextool`. New here? Start with the [Quickstart](quickstart). Every command also explains itself on
the command line:

```console
$ plextool --help
$ plextool recent --help
```

Commands that change anything do a dry run unless `--commit` is given.

```{toctree}
:maxdepth: 1

quickstart
```

```{toctree}
:maxdepth: 1
:caption: Commands

commands/auth
commands/token
commands/devices
commands/users
commands/server
commands/status
commands/info
commands/scan
commands/recent
commands/dupes
commands/stale
commands/audit
commands/watched
commands/resume
commands/playlists
commands/subs
```
