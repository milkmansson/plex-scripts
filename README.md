# plex-scripts
The python scripts in this repo are for Plex database content maintenance.
Considering the capabilities in the `plexapi` package, solutions involving
taking the database offline and messing with the content feel needlessly risky.
Therefore, through a combination of reverse engineering, vibe-coding and
trial-and-error, the following scripts were born.

## Plex-Related

### modify-recently-added
Plex lacks the capability of tuning the contents of the 'recently added' lists
for the relevant media.  [`modify-recently-added`](./modify-recently-added/README.md)
modifies the 'added at' dates on content, bringing individual titles to the
front or sending them to the back.  Useful if, for example:
- Database was recreated, and the actual latest content needs to be brought to
the front.
- Content files are reorganised in the filesystem, and plex mistakenly
recognises them as if they were new.

### see-duplicates
Report items with duplicate files (in the console) so you can manually fish for
and delete them.  Using Plex's GUI to do this task is painful, especially where
spaces or non ANSI alphabet characters are in filenames.
**Note:** 'Matches' are where Plex's database has recorded a 'match' - eg, that
the two files are the same movie, for example.  Matches can be wrong, and can be
manually made.  These would all still be duplicates as far as this output is
concerned - that is, if Plex is wrong, this script will also be wrong.  No other
file naming intelligence is applied.

### copy-watched
Used for where the 'watched' content of one user account needs to be copied to
another distinct user account.  Useful if a shared account needs to be
separated, or where a user closes/reopens their account etc.  Copies the watched
information stored on one target server.  Does not copy Watchlist data - whilst
a script for this could be possible, this script works against a target server,
where Watchlist data is maintained on Plex's systems.

## General
General scripts for other manipulations useful on a Plex server, but not
specific to plex.
