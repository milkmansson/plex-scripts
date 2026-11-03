# plextool settings

Lists, searches and changes the Plex server's own settings, which the web app spreads over many pages
(Settings, then the server's pages for General, Network, Transcoder and so on).

- `settings list` shows the settings, grouped, with the value and the default where they differ.
- `settings get` shows one setting with its explanation and choices.
- `settings set` changes one setting.

Handy when:
- A setting is known by name or half-remembered, and searching is quicker than opening each page.
- The server is misbehaving, and the settings changed from their defaults are the first thing to check (`--changed`).
- The same setting needs changing on several servers, from a script.
- A settings list is wanted as text or JSON, for notes or a comparison between two servers.

```console
$ plextool settings list --search transcode
$ plextool settings list --changed
$ plextool settings get FriendlyName
$ plextool settings set TranscoderTempDirectory /fast/disk            # preview
$ plextool settings set TranscoderTempDirectory /fast/disk --commit
```

## settings list

| Option | Meaning |
| --- | --- |
| `--search TEXT` | Only settings whose ID, label, description or group contains `TEXT`. |
| `--group NAME` | Only one group, as the list shows it. |
| `--changed` | Only settings that differ from their default. |
| `--hidden` | Include settings the web app does not show. |
| `--json` | Print JSON instead of text. |

Settings Plex marks as secure are listed as `(hidden)` and their values are never printed.

## settings set

The value must suit the setting's type: `true` or `false` (also `yes`, `no`, `on`, `off`, `1`, `0`) for a switch, a
number for a number, any text for text. A setting with a list of choices accepts only those choices. A wrong value
is refused before anything is sent. A setting that already has the value is left alone.

Like the other commands that change things, `set` is a dry run unless `--commit` is passed. The preview shows the
old and new value. Some settings only take effect after the server restarts, and the server decides which.
The text `settings get` shows for each setting is Plex's own description of it.
