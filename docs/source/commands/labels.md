# plextool labels

Adds, removes and counts labels on movies and shows in bulk. Plex's web app can edit labels one item at a time,
or through a bulk edit by selection.

- `labels list` shows each library's labels and how many items have each.
- `labels add` and `labels remove` change every item matching the options given.

Handy when:
- A user's access is limited by label (see [`plextool users`](users.md)), and a whole genre or collection needs the label.
- A label was added to a hundred items by mistake and needs taking off.
- It is unclear which labels exist, or which are no longer used.
- A label should go on everything matching a search that the web app cannot express in one step.

```console
$ plextool labels list
$ plextool labels add kids --genre Animation                      # preview
$ plextool labels add kids -l Movies --collection "Pixar" --commit
$ plextool labels remove kids --title Saw --commit
```

## add and remove

Items are chosen with at least one of these options, or with `--all-items`. Options combine with AND.

| Option | Selects |
| --- | --- |
| `--title TEXT` | Titles containing `TEXT`. |
| `--genre NAME` | Items with this genre. |
| `--collection NAME` | Items in this collection. |
| `--year YEAR` | Items released in this year. |
| `--with-label OTHER` | Items that already have another label. |
| `--unwatched` | Items not yet watched by the token's user. |
| `--all-items` | Everything in the chosen libraries. |
| `-l NAME` | A library (repeat for several). The default is every movie and TV library. |

The server is asked only for items that need the change: `add` skips items that already have the label, and `remove`
only looks at items that have it. The preview lists the first 15 items and the total. Like the other commands that
change things, both are a dry run unless `--commit` is passed.

In TV libraries, labels go on shows, which is where Plex applies label restrictions. Plex's article on
[restricting access with labels](https://support.plex.tv/articles/204232573-restricting-the-shares/) explains how
a label limits what a shared user sees, and `plextool users invite --movies-label` sets that up.
