# plex-seeDuplicates.py
_Still a work in progress_ See items with duplicate files (in the console) so you can manually fish for and delete them.  Did this due to avoid having to use the GUI to do this task.  Note that 'Matches' are where Plex's database has recorded a 'match' - eg, that the two files are the same movie.  Matches can be wrong, and can be manually made, these are all still matches as far as this output is concerned - that is, if Plex is wrong, this is wrong.  No other file naming intelligence is applied.

## Example:
```console
[user@server plexscripts]$ python3 ./seeDuplicates.py -T YOURTOKENGOESHERE
    1 TITLE-1
     - [0] /mnt/sdb1/<path>/Title-1 Dir Title 1080p/Title.Extended.Cut.2021.1080p.mkv  13 GB
     - [1] /mnt/sdf1/<path>/Title-1 Dir (2021)/Movie.Title.1.H264-ABC-AsRed.mkv  5 GB
    2 TITLE-2
     - [0] /mnt/sdc1/<path>/Title-2 Dir Title 1080p/Title.2002.1080p.BluRay.x264-GROUP.mkv  8 GB
     - [1] /mnt/sdd1/<path>/Title-2 Dir Title 1080p/Title.2002.1080p.BluRay.x264-GROUP.mkv  8 GB
    3 TITLE-3
     - [0] /mnt/sdd1/<path>/Title-3 Dir Title 1080p/m-title-1-t-a.avi  700 MB
     - [1] /mnt/sdd1/<path>/Title-3 Dir Title 1080p/m-title-1-t-b.avi  699 MB
    4 TITLE-7
     - [0] /mnt/sdc1/<path>/7 2009 1080p/7.m2ts  3 GB
     - [1] /mnt/sdb1/<path>/7 2009 720p/7.2009.720p.mkv  6 GB
```

### Example explanation:
1. Title 1: Example of match with different filenames
2. Title 2: Example of same filename, different directories (note the drive mount was different in this case)
3. Title 3: Example of the old way files were split, where two files followed on from eachother allowing them to be written to media of limited size.  Be careful of these - deleting one of those might result in deleting half your content.  See "Movies Split Across Multiple Files" topic at [this plex support article](https://support.plex.tv/articles/naming-and-organizing-your-movie-media-files/) on how to handle naming those in Plex.
4. Title 7: Example match where two completely different types of files are there in the database.

## Prerequisites
There are talented buggers out there on the internet, better instructions exist than I would do, for all of these:
1. Get yourself python installed.
2. You will need to install [Plex Python library](https://python-plexapi.readthedocs.io/en/latest/introduction.html)
3. You will need a [Plex Token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/) for authentication purposes in this version.

Regarding Tokens: There is a username/password method which I may implement later, however I have 2FA - I don't believe username/password method works with 2FA enabled.  Excellent additional info about this topic is [here](https://www.plexopedia.com/plex-media-server/general/plex-token/).

## Troubleshooting
There is little to go wrong.  It just requires a Plex Token to contact your Plex server:
```console
[user@server plexscripts]$ python3 ./seeDuplicates.py
    No PLEX TOKEN (-T XXXXXX) given

[user@server plexscripts]$ python3 ./seeDuplicates.py -T YOURTOKENGOESHERE
    ...<As above>...
```

## Links
[l3uddz/plex_dupefinder](https://github.com/l3uddz/plex_dupefinder) This looks like an excellent script, with more functionality than mine.  I chose the simpler route because I couldn't risk the automation deleting the wrong things.

## Suggestions
Comments, suggestions, improvements, etc welcome.

## Lastly [Disclaimer]:
- I don't expect that anything could go wrong using this script, it is simple, you can see the code for yourself!  That said, your mileage may vary, and while I have taken all care possible (I use it myself!) I make no guarantees - all responsibility is yours!
