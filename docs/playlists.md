# plextool playlists

Back up and restore the token owner's video playlists.

```console
$ plextool playlists list
$ plextool playlists export playlists.json
$ plextool playlists export playlists.json --name "Christmas" --name "Kids"
$ plextool playlists import playlists.json            # preview
$ plextool playlists import playlists.json --commit
```

- Items are matched by Plex GUID, so you can restore onto the same server after
  a rebuild, or onto another server that has the same content matched.
- Items not found on the target server are skipped and counted.
- A playlist that already exists is skipped unless you pass `--replace`, which
  deletes it and recreates it.
- Smart playlists and music/photo playlists are listed, but not exported or
  recreated.
