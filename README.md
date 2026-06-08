# plex-scripts

The python scripts in this repo are for Plex database content maintenance.
Considering the capabilities in the `plexapi` package, solutions involving
taking the database offline and messing with the content feel needlessly risky.
Therefore, through a combination of reverse engineering, vibe-coding and
trial-and-error, the following scripts were born.

## modify-recently-added
Plex lacks the capability of tuning the contents of the 'recently added' lists
for the relevant media.  [`modify-recently-added`](./modify-recently-added/README.md)
modifies the 'added at' dates on content, bringing individual titles to the
front or sending them to the back.  Useful if, for example:
- Database was recreated, and the actual latest content needs to be brought to
the front
- Content files are reorganised in the filesystem, and plex recognises them as
if they were new

## see-duplicates



## copy-watched
