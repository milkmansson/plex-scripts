# plextool resume

Lists, and optionally clears, entries stuck in Continue Watching. Works on the
token owner's list.

```console
$ plextool resume                              # list partly-watched items
$ plextool resume --idle 90 --clear watched    # preview
$ plextool resume --idle 90 --clear watched --commit
```

| Option | Meaning |
| --- | --- |
| `--idle DAYS` | Only items not played in the last DAYS days. |
| `--clear watched` | Mark the listed items watched. They leave Continue Watching and keep a watched tick. |
| `--clear unwatched` | Mark them unwatched. Be aware this also resets any earlier view count on that item. |
| `-y`, `--commit` | Apply. Without it, `--clear` is only a preview. |

Only partly-watched items are listed. Items Plex offers as "next up" are left alone.
