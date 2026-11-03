# plextool playlists

Back up and restore the token owner's video playlists.

Handy when:
- You are about to rebuild the server, or move to a new one, and want to keep your playlists.
- Playlists went missing after a library was removed and added again.
- You want to copy playlists to another server that has the same items.

```console
$ plextool playlists list
$ plextool playlists export playlists.json
$ plextool playlists export playlists.json --name "Christmas" --name "Kids"
$ plextool playlists import playlists.json            # preview
$ plextool playlists import playlists.json --commit
```

Use `-` as the file to write to standard output or read from standard input.
The "Wrote N playlists" message then goes to standard error, so it stays out of
the data:

```console
$ plextool playlists export - | plextool playlists import - --commit
```

- Items are matched by Plex GUID, so you can restore onto the same server after
  a rebuild, or onto another server that has the same content matched.
- Items not found on the target server are skipped and counted.
- A playlist that already exists is skipped unless you pass `--replace`, which
  deletes it and recreates it.
- Smart playlists and music/photo playlists are listed, but not exported or
  recreated.
