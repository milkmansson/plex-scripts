# plextool watched

Copy, back up, restore and bulk-set watched state for movies and TV episodes.
`--token` must be the server owner's token. Where a command takes a user, the
owner can be named too, and leaving `--user` off means the owner.

Only the watched flag moves. View counts, last-watched dates and resume
positions do not. Watchlists live on plex.tv, not on the server, so they are
not covered.

All commands that change anything are dry runs unless you pass `--commit`.

## copy

Copy one user's watched state to another. Useful when a shared account is being
split up, or someone closes and reopens their Plex account.

```console
$ plextool watched copy --from alice --to bob            # dry run
$ plextool watched copy --from alice --to bob --commit
```

Users can be a username, email or Home user name. `--movies` or `--shows`
limits it to one kind.

## export and import

Save a user's watched state to a file, for a backup before a database rebuild
or to move it to another server, and restore it later.

```console
$ plextool watched export alice-watched.json --user alice
$ plextool watched import alice-watched.json --user alice --commit
```

Use `-` as the file to write to standard output or read from standard input,
so the data can go straight through a pipe. The "Wrote N items" message then
goes to standard error and stays out of the data:

```console
$ plextool watched export - --user alice | gzip > alice-watched.json.gz
$ plextool watched export - --user alice | plextool watched import - --user bob --commit
```

Import marks matching unwatched items as watched. It never marks anything
unwatched.

## mark

Mark everything matching a title watched or unwatched, such as a whole series
or season.

```console
$ plextool watched mark -l "TV Shows" -t "Some Show" --commit
$ plextool watched mark -l "TV Shows" -t "Some Show" --level season --unwatched
```

| Option | Meaning |
| --- | --- |
| `-t`, `--title` | Title to match (substring). Required. |
| `-l`, `--library` | Library to search. Default is all movie and TV libraries. |
| `--level` | `movie`, `show`, `season` or `episode`. |
| `--unwatched` | Mark unwatched instead of watched. |
| `--user` | Whose watched state to change. |

## How matching works

The owner's account fetches an access token for each other user, so no user
passwords are needed. Items are matched by Plex GUID, so both users must have
access to the same libraries on this server. If a user can't be found, or no
token comes back, check that the server is shared with them.
