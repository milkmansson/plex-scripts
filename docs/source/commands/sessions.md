# plextool sessions

Shows what is playing on the server and stops streams.

- `sessions list` shows every stream: who is watching, what, on which device, whether it is playing or paused,
  how far in, where from (`lan` or `wan`) and whether the video is direct or transcoded.
- `sessions stop` ends streams chosen by number, by user, or all of them, and shows the viewer a message.

Handy when:
- The server is about to be restarted, and the people watching should be told and stopped first.
- The server is slow, and it is unclear which stream is transcoding.
- A stream from an unknown device or user needs ending.
- A script needs to know whether anyone is watching before it scans or reboots (`--json`).

```console
$ plextool sessions list
$ plextool sessions stop 12 --reason "Restarting the server in 5 minutes"             # preview
$ plextool sessions stop --user alice --commit
$ plextool sessions stop --all --commit
```

## sessions stop

At least one of the stream numbers (from `sessions list`), `--user NAME` or `--all` is required, and the choices
combine. Like the other commands that change things, `stop` is a dry run unless `--commit` is passed. The preview
lists each stream that would be stopped.

| Option | Meaning |
| --- | --- |
| `--user NAME` | Every stream of this user. |
| `--all` | Every stream. |
| `--reason TEXT` | The message the viewer sees. The default says playback was stopped by the server administrator. |
| `--commit` | Actually stop them. |

Plex ends a stream by its session ID. A stream for which Plex gives none is reported and skipped, and a stream Plex
refuses to stop is reported with Plex's reason. Either makes the exit code 1. Plex's article on the
[status and dashboard](https://support.plex.tv/articles/200871837-status-and-dashboard/) covers the web app's view of
the same streams.
