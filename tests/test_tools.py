import io
import json
import shutil
import subprocess
import sys
from argparse import ArgumentTypeError
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

import pytest
from plexapi.exceptions import NotFound

from plextool import (
    audit,
    common,
    completion,
    devices,
    dupes,
    info,
    playlists,
    resume,
    stale,
    tokens,
    users,
    watched,
)
from plextool.cli import build_parser
from plextool.common import PlexToolError, confirm_typed, item_size, read_json, working, write_json

NOW = datetime(2025, 6, 1)


def part(path="/a.mkv", size=100, exists=True):
    return NS(file=path, size=size, exists=exists,
              subtitleStreams=list, audioStreams=list)


def episode(show, n, size=100, views=0, added=None, last=None):
    return NS(type="episode", title=f"E{n}", grandparentTitle=show, seasonNumber=1, episodeNumber=n,
              guid=f"plex://episode/{show}{n}", media=[NS(parts=[part(size=size)])],
              viewCount=views, addedAt=added, lastViewedAt=last)


# --- info ----------------------------------------------------------------

def stream_part(video=(), audio=(), subs=(), file="/m/a.mkv", size=100):
    return NS(file=file, size=size, container="mkv", videoStreams=lambda: list(video),
              audioStreams=lambda: list(audio), subtitleStreams=lambda: list(subs))


def media_version(part, **kw):
    base = {"container": "mkv", "duration": 9720000, "bitrate": 5000, "aspectRatio": 1.78, "parts": [part],
            "videoCodec": "hevc", "videoProfile": "main 10", "width": 1920, "height": 1080,
            "videoFrameRate": "24p"}
    return NS(**{**base, **kw})


def movie_item(title, year, version, key=1):
    return NS(title=title, year=year, type="movie", ratingKey=key, librarySectionTitle="Movies",
              media=[version], duration=9720000, guids=[NS(id="imdb://tt1")], guid=f"plex://movie/{key}")


def test_fmt_duration():
    assert info.fmt_duration(9720000) == "2h 42m"
    assert info.fmt_duration(2710000) == "45m 10s"
    assert info.fmt_duration(None) is None


def test_hdr_label():
    assert info.hdr_label(NS(DOVIPresent=True, DOVIProfile=8)) == "Dolby Vision (profile 8)"
    assert info.hdr_label(NS(DOVIPresent=False, colorTrc="smpte2084")) == "HDR10"
    assert info.hdr_label(NS(colorTrc="arib-std-b67")) == "HLG"
    assert info.hdr_label(NS(colorTrc="bt709")) is None


def test_version_info_reads_streams():
    video = NS(codec="hevc", profile="main 10", width=1920, height=1080, bitDepth=10, frameRate=23.976,
               bitrate=4000, colorSpace="bt2020nc", colorTrc="smpte2084")
    audio = NS(language="English", languageCode="eng", codec="dca", channels=6, audioChannelLayout="5.1",
               bitrate=1509, title="DTS", default=True)
    sub_file = NS(language="English", languageCode="eng", format="srt", forced=False, hearingImpaired=True,
                  title=None, key="/library/streams/9", providerTitle="OpenSubtitles")
    sub_in = NS(language="Japanese", languageCode="jpn", format="pgs", forced=True, hearingImpaired=False,
                title=None, key=None, providerTitle=None)
    version = info.version_info(media_version(stream_part([video], [audio], [sub_file, sub_in], size=44)))
    assert version["video"]["resolution"] == "1920x1080" and version["video"]["hdr"] == "HDR10"
    assert version["audio"][0]["codec"] == "dca" and version["audio"][0]["default"] is True
    assert [s["source"] for s in version["subtitles"]] == ["external", "embedded"]
    assert version["subtitles"][0]["sdh"] and version["subtitles"][1]["forced"]
    assert version["size"] == 44 and version["files"][0]["path"] == "/m/a.mkv"


def test_version_info_without_streams_falls_back_to_the_version():
    version = info.version_info(media_version(stream_part()))
    assert version["video"]["codec"] == "hevc" and version["video"]["resolution"] == "1920x1080"
    assert version["audio"] == [] and version["subtitles"] == []
    assert version["analysed"] is False


def test_unanalysed_file_is_labelled_not_left_blank(capsys):
    unanalysed = info.version_info(media_version(stream_part()))
    info.print_version(1, 1, unanalysed)
    out = capsys.readouterr().out
    assert "Plex has not analysed this file yet" in out
    assert "audio      not analysed" in out and "subtitles  not analysed" in out
    columns = info.comparison_columns([info.item_info(movie_item("Ran", 1985, media_version(stream_part())))])
    row = columns[0][1]
    assert row["audio"] == "not analysed" and row["subtitles"] == "not analysed"
    assert row["hdr"] == "not analysed" and row["bit depth"] == "not analysed"


def test_analysed_file_with_no_tracks_says_none(capsys):
    video = NS(codec="h264", profile="high", width=1280, height=720, bitDepth=8, frameRate=25,
               bitrate=2000, colorSpace=None, colorTrc=None)
    version = info.version_info(media_version(stream_part([video])))
    assert version["analysed"] is True
    info.print_version(1, 1, version)
    out = capsys.readouterr().out
    assert "audio (0)  none" in out and "subtitles (0)  none" in out
    row = info.comparison_columns([info.item_info(movie_item("X", 2000, media_version(stream_part([video]))))])[0][1]
    assert row["audio"] == "none" and row["subtitles"] == "none" and row["hdr"] is None


def test_choose_one():
    ran, remaster = NS(title="Ran", ratingKey=1, year=1985, type="movie", librarySectionTitle="M"), \
        NS(title="Ran (Remastered)", ratingKey=2, year=2020, type="movie", librarySectionTitle="M")
    assert info.choose_one("ran", [ran, remaster]) is ran           # an exact title wins
    assert info.choose_one("Ran", [ran]) is ran
    with pytest.raises(PlexToolError, match="matches 2 items") as raised:
        info.choose_one("Ra", [ran, remaster])
    assert "-k 1" in str(raised.value) and "-k 2" in str(raised.value)
    with pytest.raises(PlexToolError, match="Nothing matches"):
        info.choose_one("Zed", [])


def test_comparison_marks_what_differs():
    first = movie_item("Ran", 1985, media_version(stream_part(size=44, file="/m/a.mkv")), key=1)
    second = movie_item("Ran", 2020, media_version(stream_part(size=22, file="/m/b.mkv"), videoCodec="h264"), key=2)
    infos = [info.item_info(first), info.item_info(second)]
    columns = info.comparison_columns(infos)
    assert [h for h, _ in columns] == ["Ran (1985)", "Ran (2020)"]
    assert columns[0][1]["size"] != columns[1][1]["size"]
    assert columns[0][1]["container"] == columns[1][1]["container"]


def test_comparison_splits_an_items_versions():
    item = movie_item("Ran", 1985, media_version(stream_part(file="/m/a.mkv")))
    item.media.append(media_version(stream_part(file="/m/b.mp4"), container="mp4"))
    headings = [h for h, _ in info.comparison_columns([info.item_info(item)])]
    assert headings == ["Ran (1985) [v1]", "Ran (1985) [v2]"]


def test_print_comparison_flags_differing_rows(capsys):
    info.print_comparison([("A", {"size": "1 GB", "container": "mkv"}), ("B", {"size": "2 GB", "container": "mkv"})])
    out = capsys.readouterr().out
    assert "size *" in out and "container *" not in out and "* differs" in out


def test_parse_groups():
    assert info.parse_groups("tech, people") == ("tech", "people")
    with pytest.raises(ArgumentTypeError):
        info.parse_groups("tech,bogus")


def test_info_needs_an_item(monkeypatch):
    args = build_parser().parse_args(["info"])
    with pytest.raises(PlexToolError, match="Say which item"):
        info.run(args)


# --- token ---------------------------------------------------------------

def token_args(*argv):
    return build_parser().parse_args(["token", *argv])


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("PLEXTOOL_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("PLEX_URL", raising=False)
    return tmp_path


def test_token_new_requires_access_and_destination(capsys):
    for argv in ([], ["new"], ["new", "--rw", "--name", "x"], ["new", "--file", "f"], ["new", "--print"],
                 ["new", "--rw", "--ro", "--print"], ["new", "--rw", "--print", "--file", "f"]):
        with pytest.raises(SystemExit):
            token_args(*argv)
        capsys.readouterr()


def test_token_new_rw_needs_a_name_and_no_user():
    with pytest.raises(PlexToolError, match="--rw needs --name"):
        tokens.run(token_args("new", "--rw", "--print"))
    with pytest.raises(PlexToolError, match="--user goes with --ro"):
        tokens.run(token_args("new", "--rw", "--name", "x", "--user", "alice", "--print"))


def test_token_new_ro_needs_a_user():
    with pytest.raises(PlexToolError, match="--ro needs --user"):
        tokens.run(token_args("new", "--ro", "--print"))


def test_env_text_and_private_file(tmp_path):
    text = tokens.env_text("read/write", "http://nas:32400", "SECRET", "mcp")
    assert "PLEX_URL=http://nas:32400\nPLEX_TOKEN=SECRET\n" in text and text.startswith("# Made by plextool on ")
    assert "PLEX_URL" not in tokens.env_text("read/write", None, "SECRET", "mcp")
    path = tmp_path / "sub" / "plex.env"
    tokens.deliver(token_args("new", "--rw", "--name", "x", "--file", str(path)), "SECRET", text)
    assert path.read_text() == text and (path.stat().st_mode & 0o777) == 0o600
    with pytest.raises(PlexToolError, match="already exists"):
        tokens.deliver(token_args("new", "--rw", "--name", "x", "--file", str(path)), "SECRET", text)
    tokens.deliver(token_args("new", "--rw", "--name", "x", "--file", str(path), "--force"), "NEW", "NEW\n")
    assert path.read_text() == "NEW\n"


def test_token_new_rw_makes_a_named_device_and_records_it(monkeypatch, config, capsys):
    seen = {}

    def fake_request(timeout, device_name=None, file=None):
        seen.update(timeout=timeout, device=device_name)
        return "RWTOKEN", "abcdef12-0000"
    monkeypatch.setattr(tokens.auth, "request_token", fake_request)
    monkeypatch.setattr("plextool.server.load_saved", lambda: {"kind": "account", "last_url": "http://nas:32400"})
    assert tokens.run(token_args("new", "--rw", "--name", "mcp", "--print")) == 0
    captured = capsys.readouterr()
    assert captured.out == "RWTOKEN\n"                         # only the token on standard output
    assert seen["device"] == "plextool/mcp"
    assert "same power as the Plex account" in captured.err and "token revoke mcp" in captured.err
    out = config / "e.env"
    tokens.run(token_args("new", "--rw", "--name", "other", "--file", str(out)))
    assert "PLEX_URL=http://nas:32400" in out.read_text() and "PLEX_TOKEN=RWTOKEN" in out.read_text()
    record = {e["name"]: e for e in tokens.load_record()}
    assert record["mcp"]["device_id"] == "abcdef12-0000" and record["mcp"]["file"] is None
    assert record["other"]["file"] == str(out.resolve())
    assert "RWTOKEN" not in tokens.record_path().read_text()    # no secrets in the record


def test_token_new_ro_uses_the_users_token(monkeypatch, config, capsys):
    admin = NS(_baseurl="http://nas:32400", machineIdentifier="machine1")
    monkeypatch.setattr(tokens, "connect", lambda args: admin)
    monkeypatch.setattr(tokens, "user_access_token", lambda args, plex, name: "ALICETOKEN")
    shown = NS(library=NS(sections=lambda: [NS(title="Movies"), NS(title="TV Shows")]))
    monkeypatch.setattr(tokens, "PlexServer", lambda url, token, timeout=None: shown)
    out = config / "ro.env"
    assert tokens.run(token_args("new", "--ro", "--user", "alice", "--file", str(out))) == 0
    assert "PLEX_TOKEN=ALICETOKEN" in out.read_text() and "PLEX_URL=http://nas:32400" in out.read_text()
    err = capsys.readouterr().err
    assert "Movies, TV Shows" in err and "no truly read-only token" in err and "delete media" in err
    entry = tokens.load_record()[0]
    assert entry["access"] == "ro" and entry["user"] == "alice" and entry["machine_id"] == "machine1"


def test_token_new_ro_refuses_the_owner(monkeypatch):
    monkeypatch.setattr(tokens, "connect", lambda args: NS(_baseurl="http://nas:32400"))
    monkeypatch.setattr(tokens, "user_access_token", lambda args, plex, name: None)
    with pytest.raises(PlexToolError, match="owner of this server"):
        tokens.run(token_args("new", "--ro", "--user", "me", "--print"))


def test_token_new_ro_reports_a_rejected_token(monkeypatch):
    from plexapi.exceptions import Unauthorized
    monkeypatch.setattr(tokens, "connect", lambda args: NS(_baseurl="http://nas:32400"))
    monkeypatch.setattr(tokens, "user_access_token", lambda args, plex, name: "T")

    def reject(*a, **kw):
        raise Unauthorized("no")
    monkeypatch.setattr(tokens, "PlexServer", reject)
    with pytest.raises(PlexToolError, match="did not accept"):
        tokens.run(token_args("new", "--ro", "--user", "alice", "--print"))


class FakeDevice:
    def __init__(self, name, client_id, product="plextool"):
        self.name, self.clientIdentifier, self.product = name, client_id, product
        self.createdAt = self.lastSeenAt = datetime(2026, 11, 3, 10, 0)
        self.deleted = False

    def delete(self):
        self.deleted = True


def fake_account(monkeypatch, devices, shares=()):
    monkeypatch.setattr(tokens, "resolve_token", lambda args: ("tok", "test"))
    monkeypatch.setattr(tokens.auth, "account_devices", lambda token, everything=False: devices)
    monkeypatch.setattr(tokens, "connect", lambda args: NS(machineIdentifier="machine1"))
    users = [NS(title=t, username=t, email=None, restricted="0", home=False,
                servers=[NS(machineIdentifier="machine1", pending=False, allLibraries=False, numLibraries=2)])
             for t in shares]
    monkeypatch.setattr(tokens, "plex_account", lambda args: NS(users=lambda: users))


def test_token_list_shows_tokens_users_and_gone_entries(monkeypatch, config, capsys):
    mcp = FakeDevice("plextool/mcp", "aaaaaaaa-1111")
    login = FakeDevice("plextool on host", "bbbbbbbb-2222")
    tv = FakeDevice("Living Room TV", "cccccccc-3333", product="Plex for LG")
    fake_account(monkeypatch, [mcp, login, tv], shares=["alice", "bob"])
    tokens.save_record([
        {"name": "mcp", "access": "rw", "device_id": "aaaaaaaa-1111", "created": "2026-11-03", "file": "/h/mcp.env"},
        {"name": "old", "access": "rw", "device_id": "dddddddd-4444", "created": "2026-10-01", "file": None},
        {"name": "alice", "access": "ro", "user": "alice", "created": "2026-11-02", "file": None,
         "machine_id": "machine1"},
        {"name": "carol", "access": "ro", "user": "carol", "created": "2026-11-02", "file": None,
         "machine_id": "machine1"}])
    assert tokens.run(token_args("list")) == 0
    out = capsys.readouterr().out
    assert "Apps and devices authorised on the Plex account" in out
    assert "Living Room TV" in out and "Plex for LG" in out        # other apps are listed by default
    assert "token for another tool: mcp" in out and "plextool sign-in" in out
    assert "mcp" in out and "/h/mcp.env" in out and "active" in out
    assert "old" in out and "no longer on the account" in out
    assert "user still has access" in out and "user no longer has access" in out
    assert "Users with access to this server" in out and "bob" in out and "2 libraries" in out
    assert "temporary tokens" in out


def test_token_list_plextool_only(monkeypatch, config, capsys):
    mcp, tv = FakeDevice("plextool/mcp", "aaaaaaaa-1111"), FakeDevice("Living Room TV", "cccccccc-3333", "Plex for LG")
    fake_account(monkeypatch, [mcp, tv])
    assert tokens.run(token_args("list", "--plextool", "--no-users")) == 0
    out = capsys.readouterr().out
    assert "plextool's only" in out and "Living Room TV" not in out and "mcp" in out


def test_token_list_without_users(monkeypatch, config, capsys):
    fake_account(monkeypatch, [], shares=["alice"])
    assert tokens.run(token_args("list", "--no-users")) == 0
    out = capsys.readouterr().out
    assert "Users with access" not in out and "none" in out


def test_token_revoke_is_a_dry_run_until_committed(monkeypatch, config, capsys):
    mcp, login = FakeDevice("plextool/mcp", "aaaaaaaa-1111"), FakeDevice("plextool on host", "bbbbbbbb-2222")
    fake_account(monkeypatch, [mcp, login])
    env = config / "mcp.env"
    env.write_text("PLEX_TOKEN=x\n")
    tokens.save_record([{"name": "mcp", "access": "rw", "device_id": "aaaaaaaa-1111", "file": str(env)}])
    assert tokens.run(token_args("revoke", "mcp", "--delete-file")) == 0
    assert "Would remove" in capsys.readouterr().out and not mcp.deleted and env.exists()
    assert tokens.run(token_args("revoke", "mcp", "--delete-file", "--commit")) == 0
    assert mcp.deleted and not login.deleted and not env.exists()
    assert tokens.load_record() == []


def test_token_revoke_by_id_prefix_and_unknown(monkeypatch, config):
    mcp = FakeDevice("plextool/mcp", "aaaaaaaa-1111")
    fake_account(monkeypatch, [mcp])
    tokens.run(token_args("revoke", "aaaa", "--commit"))
    assert mcp.deleted
    with pytest.raises(PlexToolError, match="No token named or starting 'nope'"):
        tokens.run(token_args("revoke", "nope"))


def test_token_revoke_never_touches_plain_logins(monkeypatch, config):
    login = FakeDevice("plextool on host", "bbbbbbbb-2222")
    web = FakeDevice("Chrome", "m6t825jf0abc", product="Plex Web")
    fake_account(monkeypatch, [login, web])
    with pytest.raises(PlexToolError, match="plain plextool sign-in.*auth revoke bbbbbbbb"):
        tokens.run(token_args("revoke", "bbbbbbbb", "--commit"))
    with pytest.raises(PlexToolError, match="'Chrome' \\(Plex Web\\).*did not make"):
        tokens.run(token_args("revoke", "m6t825jf", "--commit"))
    with pytest.raises(PlexToolError, match="No token named or starting 'zzz'"):
        tokens.run(token_args("revoke", "zzz", "--commit"))
    assert not login.deleted and not web.deleted


def test_token_revoke_ro_explains_and_can_forget(monkeypatch, config, capsys):
    fake_account(monkeypatch, [])
    tokens.save_record([{"name": "alice", "access": "ro", "user": "alice"}])
    assert tokens.run(token_args("revoke", "alice", "--commit")) == 0
    assert "no device of its own" in capsys.readouterr().out and len(tokens.load_record()) == 1
    tokens.run(token_args("revoke", "alice", "--forget", "--commit"))
    assert tokens.load_record() == []


def test_auth_revoke_unused_for_picks_only_old_plain_sign_ins(monkeypatch, config, capsys):
    from datetime import timedelta

    from plextool import auth
    now = datetime.now()
    fresh, stale_, never, current, named = (FakeDevice("plextool on mms-p2", "aaaaaaaa-1"),
                                            FakeDevice("plextool on old", "bbbbbbbb-2"),
                                            FakeDevice("plextool on never", "cccccccc-3"),
                                            FakeDevice("plextool on here", "dddddddd-4"),
                                            FakeDevice("plextool/mcp", "eeeeeeee-5"))
    fresh.lastSeenAt = now - timedelta(days=1)
    stale_.lastSeenAt = now - timedelta(days=30)
    never.lastSeenAt = None
    current.lastSeenAt = now - timedelta(days=90)
    named.lastSeenAt = now - timedelta(days=90)
    monkeypatch.setattr(auth, "resolve_token", lambda args: ("tok", "test"))
    monkeypatch.setattr(auth, "account_devices", lambda token, everything=False: [fresh, stale_, never, current, named])
    monkeypatch.setattr(auth, "load_state", lambda: {"client_id": "dddddddd-4"})
    auth.revoke_devices(NS(ids=[], others=False, this=False, unused_for=7, commit=False))
    assert not any(d.deleted for d in (fresh, stale_, never, current, named))        # a dry run
    auth.revoke_devices(NS(ids=[], others=False, this=False, unused_for=7, commit=True))
    assert stale_.deleted and never.deleted
    assert not (fresh.deleted or current.deleted or named.deleted)
    with pytest.raises(PlexToolError, match="at least 1 day"):
        auth.revoke_devices(NS(ids=[], others=False, this=False, unused_for=0, commit=True))


def test_auth_revoke_says_when_an_id_belongs_to_another_app(monkeypatch, config):
    from plextool import auth
    login, web = FakeDevice("plextool on host", "bbbbbbbb-2222"), FakeDevice("Chrome", "m6t825jf0abc", "Plex Web")
    monkeypatch.setattr(auth, "resolve_token", lambda args: ("tok", "test"))
    monkeypatch.setattr(auth, "account_devices", lambda token, everything=False:
                        [login, web] if everything else [login])
    monkeypatch.setattr(auth, "load_state", lambda: {"client_id": "bbbbbbbb-2222"})
    args = {"others": False, "this": False, "unused_for": None, "commit": True}
    with pytest.raises(PlexToolError, match="'Chrome' \\(Plex Web\\).*did not make"):
        auth.revoke_devices(NS(ids=["m6t825jf"], **args))
    with pytest.raises(PlexToolError, match="No device on the account starts with 'zzz'"):
        auth.revoke_devices(NS(ids=["zzz"], **args))
    assert not web.deleted


def test_auth_revoke_others_keeps_tokens_made_for_other_tools(monkeypatch, config, capsys):
    from plextool import auth
    mcp, login, old = (FakeDevice("plextool/mcp", "aaaaaaaa-1111"), FakeDevice("plextool on host", "bbbbbbbb-2222"),
                       FakeDevice("plextool on laptop", "cccccccc-3333"))
    monkeypatch.setattr(auth, "resolve_token", lambda args: ("tok", "test"))
    monkeypatch.setattr(auth, "account_devices", lambda token, everything=False: [mcp, login, old])
    monkeypatch.setattr(auth, "load_state", lambda: {"client_id": "bbbbbbbb-2222"})
    auth.revoke_devices(NS(ids=[], others=True, this=False, unused_for=None, commit=True))
    assert old.deleted and not mcp.deleted and not login.deleted
    assert "Keeping 1 token" in capsys.readouterr().out


def test_token_names_get_the_plextool_prefix(monkeypatch, config):
    from plextool import auth
    seen = []
    monkeypatch.setattr(tokens.auth, "request_token", lambda timeout, device_name=None, file=None:
                        (seen.append(device_name), ("T", "id-1"))[1])
    for given in ("mcp", "plextool/mcp", "  mcp  "):
        tokens.run(token_args("new", "--rw", "--name", given, "--print"))
    assert seen == ["plextool/mcp"] * 3
    with pytest.raises(PlexToolError, match="cannot be empty"):
        tokens.run(token_args("new", "--rw", "--name", "plextool/", "--print"))
    assert auth.is_named_token(NS(name="plextool/mcp")) and auth.is_named_token(NS(name="plextool: old"))
    assert not auth.is_named_token(NS(name="plextool on host"))
    assert auth.token_label("plextool/mcp") == "mcp" and auth.token_label("plextool: old") == "old"


# --- devices -------------------------------------------------------------

def make_devices(monkeypatch, current="bbbbbbbb-2222"):
    now = datetime.now()
    from datetime import timedelta
    fleet = {
        "web_old": FakeDevice("Chrome", "m6t825jf0abc", "Plex Web"),
        "web_new": FakeDevice("Firefox", "n7u936kg1def", "Plex Web"),
        "tv": FakeDevice("Living Room TV", "cccccccc-3333", "Plex for LG"),
        "login": FakeDevice("plextool on host", "bbbbbbbb-2222"),
        "named": FakeDevice("plextool/mcp", "aaaaaaaa-1111"),
        "server": FakeDevice("mms-p2", "eeeeeeee-5555", "Plex Media Server"),
    }
    fleet["web_old"].lastSeenAt = now - timedelta(days=400)
    fleet["web_new"].lastSeenAt = now - timedelta(days=1)
    fleet["tv"].lastSeenAt = now - timedelta(days=200)
    fleet["login"].lastSeenAt = now - timedelta(days=300)
    fleet["named"].lastSeenAt = now - timedelta(days=300)
    fleet["server"].lastSeenAt = now - timedelta(days=500)
    monkeypatch.setattr(devices, "resolve_token", lambda args: ("tok", "test"))
    monkeypatch.setattr(devices.auth, "account_devices", lambda token, everything=False: list(fleet.values()))
    monkeypatch.setattr(devices.auth, "load_state", lambda: {"client_id": current})
    monkeypatch.setattr(devices, "plex_account", lambda args: NS(resources=lambda: [
        NS(clientIdentifier="eeeeeeee-5555", provides="server"),
        NS(clientIdentifier="ffffffff-6666", provides="client,player")]))
    return fleet


def deleted(fleet):
    return sorted(k for k, d in fleet.items() if d.deleted)


def test_is_server_by_product_or_provides():
    assert common and devices.auth.is_server(NS(product="Plex Media Server", provides="server"))
    assert devices.auth.is_server(NS(product="Something", provides="client,server"))
    assert not devices.auth.is_server(NS(product="Plex Web", provides="client,player"))
    assert not devices.auth.is_server(NS(product="Plex Web"))


def test_devices_list_filters(monkeypatch, capsys):
    make_devices(monkeypatch)
    devices.run(build_parser().parse_args(["devices", "list", "--product", "plex web"]))
    out = capsys.readouterr().out
    assert "Chrome" in out and "Firefox" in out and "Living Room TV" not in out
    devices.run(build_parser().parse_args(["devices", "list", "--unused-for", "100"]))
    out = capsys.readouterr().out
    assert "Chrome" in out and "Living Room TV" in out and "Firefox" not in out
    assert "Plex Media Server (not removable with plextool)" in out


def test_devices_remove_needs_a_selection():
    with pytest.raises(PlexToolError, match="Say what to remove"):
        devices.run(build_parser().parse_args(["devices", "remove"]))


def test_devices_remove_filters_skip_servers_the_login_and_named_tokens(monkeypatch, capsys):
    fleet = make_devices(monkeypatch)
    args = build_parser().parse_args(["devices", "remove", "--unused-for", "100"])
    assert devices.run(args) == 0
    out = capsys.readouterr().out
    assert deleted(fleet) == [] and "Dry run only" in out and "signed out" in out
    assert "Not selecting 3 matching devices" in out
    devices.run(build_parser().parse_args(["devices", "remove", "--unused-for", "100", "--commit"]))
    assert deleted(fleet) == ["tv", "web_old"]


def test_devices_remove_filters_combine(monkeypatch):
    fleet = make_devices(monkeypatch)
    devices.run(build_parser().parse_args(
        ["devices", "remove", "--product", "Plex Web", "--unused-for", "100", "--commit"]))
    assert deleted(fleet) == ["web_old"]
    fleet2 = make_devices(monkeypatch)
    devices.run(build_parser().parse_args(["devices", "remove", "--name", "living", "--commit"]))
    assert deleted(fleet2) == ["tv"]


def test_devices_remove_by_id_and_refusals(monkeypatch, capsys):
    fleet = make_devices(monkeypatch)
    devices.run(build_parser().parse_args(["devices", "remove", "m6t825jf", "--commit"]))
    assert deleted(fleet) == ["web_old"]
    with pytest.raises(PlexToolError, match="is a Plex Media Server.*does not remove servers"):
        devices.run(build_parser().parse_args(["devices", "remove", "eeeeeeee", "--commit"]))
    with pytest.raises(PlexToolError, match="No device on the account starts with 'zzz'"):
        devices.run(build_parser().parse_args(["devices", "remove", "zzz"]))
    assert "server" not in deleted(fleet)


def test_devices_remove_can_name_the_login_and_a_named_token(monkeypatch, capsys):
    fleet = make_devices(monkeypatch)
    devices.run(build_parser().parse_args(["devices", "remove", "bbbbbbbb", "aaaaaaaa", "--commit"]))
    assert deleted(fleet) == ["login", "named"]
    assert "saved login" in capsys.readouterr().out


def test_servers_survive_any_age_filter(monkeypatch):
    fleet = make_devices(monkeypatch)
    devices.run(build_parser().parse_args(["devices", "remove", "--unused-for", "365", "--commit"]))
    assert "server" not in deleted(fleet) and deleted(fleet) == ["web_old"]    # the server is 500 days old


def test_a_server_the_product_name_misses_is_caught_by_plex_tv(monkeypatch):
    fleet = make_devices(monkeypatch)
    fleet["server"].product, fleet["server"].provides = "Mystery Product", None   # not recognisable by name
    devices.run(build_parser().parse_args(["devices", "remove", "--unused-for", "365", "--commit"]))
    assert "server" not in deleted(fleet)
    with pytest.raises(PlexToolError, match="is a Plex Media Server"):
        devices.run(build_parser().parse_args(["devices", "remove", "eeeeeeee", "--commit"]))
    assert "server" not in deleted(fleet)


def test_nothing_is_removed_if_plex_tv_cannot_confirm_the_servers(monkeypatch):
    from requests.exceptions import ConnectionError as RequestsConnectionError
    fleet = make_devices(monkeypatch)

    def fail(args):
        raise RequestsConnectionError("down")
    monkeypatch.setattr(devices, "plex_account", fail)
    for argv in (["--unused-for", "365", "--commit"], ["m6t825jf", "--commit"]):
        with pytest.raises(PlexToolError, match="nothing was removed"):
            devices.run(build_parser().parse_args(["devices", "remove", *argv]))
    assert deleted(fleet) == []
    devices.run(build_parser().parse_args(["devices", "list"]))        # listing still works


def test_devices_remove_rejects_a_bad_age(monkeypatch):
    make_devices(monkeypatch)
    with pytest.raises(PlexToolError, match="at least 1 day"):
        devices.run(build_parser().parse_args(["devices", "remove", "--unused-for", "0"]))


# --- users ---------------------------------------------------------------

class FakeAccount:
    """Records what plextool asks Plex to do, and does nothing."""

    username, email, title = "owner", "owner@example.com", "Owner"

    FRIENDINVITE = "https://plex.tv/api/servers/{machineId}/shared_servers"

    def __init__(self, people=(), invites=(), shared_xml=None):
        self.people, self.invites, self.calls = list(people), list(invites), []
        self.shared_xml, self.queried = shared_xml, []

    def query(self, url):
        import xml.etree.ElementTree as ET
        self.queried.append(url)
        if isinstance(self.shared_xml, Exception):
            raise self.shared_xml
        return ET.fromstring(self.shared_xml or "<MediaContainer/>")

    def users(self):
        return self.people

    def user(self, name):
        from plexapi.exceptions import NotFound
        for p in self.people:
            if name.lower() in {p.title.lower(), p.username.lower(), p.email.lower()}:
                return p
        raise NotFound(name)

    def pendingInvites(self, includeSent=True, includeReceived=True):
        return self.invites

    def inviteFriend(self, who, server, **kwargs):
        self.calls.append(("invite", who, kwargs))

    def updateFriend(self, user, server, **kwargs):
        self.calls.append(("update", user.title, kwargs))

    def removeFriend(self, user):
        self.calls.append(("removeFriend", user.title))

    def cancelInvite(self, invite):
        self.calls.append(("cancel", invite.email))


def share_for(machine="machine1", libs=2, all_libs=False, pending=False):
    return NS(machineIdentifier=machine, pending=pending, allLibraries=all_libs, numLibraries=libs,
              sections=lambda: [NS(title="Movies", shared=True), NS(title="TV Shows", shared=False)])


def person(name, shares=(), home=False, restricted="0"):
    return NS(title=name, username=name.lower(), email=f"{name.lower()}@example.com", servers=list(shares),
              home=home, restricted=restricted, allowSync=True, allowCameraUpload=False, allowChannels=False,
              filterMovies="contentRating=G", filterTelevision="", filterMusic="")


def users_setup(monkeypatch, config, account):
    plex = NS(machineIdentifier="machine1", friendlyName="Fake", library=NS(sections=lambda: [
        NS(title="Movies"), NS(title="TV Shows"), NS(title="Music")]))
    monkeypatch.setattr(users, "connect", lambda args: plex)
    monkeypatch.setattr(users, "plex_account", lambda args: account)
    monkeypatch.setattr(users, "resolve_token", lambda args: ("tok", "test"))
    return plex


def run_users(*argv):
    return users.run(build_parser().parse_args(["users", *argv]))


def test_users_restriction_parsing():
    assert users.restriction("G,PG,!R", "kids,!scary") == {
        "contentRating": ["G", "PG"], "contentRating!": ["R"], "label": ["kids"], "label!": ["scary"]}
    assert users.restriction(None, "") is None


def test_users_invite_requires_libraries(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["users", "invite", "a@example.com"])
    capsys.readouterr()


def test_users_invite_is_a_preview_until_committed(monkeypatch, config, capsys):
    account = FakeAccount()
    users_setup(monkeypatch, config, account)
    assert run_users("invite", "alice@example.com", "--libraries", "Movies,tv shows",
                     "--movies-rating", "G,!R", "--downloads", "yes") == 0
    out = capsys.readouterr().out
    assert account.calls == []
    assert "Would invite alice@example.com to Fake" in out and "libraries: Movies, TV Shows" in out
    assert "movies restrictions: contentRating G; contentRating not R" in out
    assert "downloads: allowed" in out and "camera upload: not allowed" in out
    assert "sends them an email" in out and "Dry run only" in out
    run_users("invite", "alice@example.com", "--libraries", "Movies,tv shows",
              "--movies-rating", "G,!R", "--downloads", "yes", "--commit")
    kind, who, kwargs = account.calls[0]
    assert (kind, who) == ("invite", "alice@example.com")
    assert kwargs["sections"] == ["Movies", "TV Shows"]
    assert kwargs["allowSync"] is True and kwargs["allowCameraUpload"] is False and kwargs["allowChannels"] is False
    assert kwargs["filterMovies"] == {"contentRating": ["G"], "contentRating!": ["R"]}
    assert "filterTelevision" not in kwargs


def test_users_invite_all_libraries_and_unknown_library(monkeypatch, config):
    account = FakeAccount()
    users_setup(monkeypatch, config, account)
    run_users("invite", "a@example.com", "--libraries", "all", "--commit")
    assert account.calls[0][2]["sections"] == ["Movies", "TV Shows", "Music"]
    with pytest.raises(PlexToolError, match="No library called 'Films'.*Use --libraries all"):
        run_users("invite", "a@example.com", "--libraries", "Films", "--commit")


def test_users_invite_refuses_existing_access_pending_invites_and_the_owner(monkeypatch, config):
    account = FakeAccount(people=[person("Alice", [share_for()])],
                          invites=[NS(email="bob@example.com", username="", friendlyName="")])
    users_setup(monkeypatch, config, account)
    with pytest.raises(PlexToolError, match="already has access.*users share"):
        run_users("invite", "alice@example.com", "--libraries", "all", "--commit")
    with pytest.raises(PlexToolError, match="already waiting.*users cancel"):
        run_users("invite", "bob@example.com", "--libraries", "all", "--commit")
    with pytest.raises(PlexToolError, match="owns this server"):
        run_users("invite", "owner@example.com", "--libraries", "all", "--commit")
    assert account.calls == []


def test_users_invite_reports_plex_refusals(monkeypatch, config):
    from plexapi.exceptions import BadRequest

    class Refusing(FakeAccount):
        def inviteFriend(self, who, server, **kwargs):
            raise BadRequest("(400) nope")
    users_setup(monkeypatch, config, Refusing())
    with pytest.raises(PlexToolError, match="did not accept that.*Plex Pass"):
        run_users("invite", "a@example.com", "--libraries", "all", "--movies-rating", "G", "--commit")


def test_users_share_changes_only_what_is_named(monkeypatch, config, capsys):
    account = FakeAccount(people=[person("Alice", [share_for()])])
    users_setup(monkeypatch, config, account)
    with pytest.raises(PlexToolError, match="Say what to change"):
        run_users("share", "alice")
    run_users("share", "alice", "--downloads", "no")
    assert account.calls == [] and "Would change what Alice can do" in capsys.readouterr().out
    run_users("share", "alice", "--downloads", "no", "--tv-label", "!scary", "--commit")
    _, _, kwargs = account.calls[0]
    assert kwargs == {"sections": None, "allowSync": False, "filterTelevision": {"label!": ["scary"]}}
    run_users("share", "alice", "--clear-restrictions", "--libraries", "Movies", "--commit")
    assert account.calls[1][2] == {"sections": ["Movies"], "filterMovies": {}, "filterTelevision": {},
                                   "filterMusic": {}}
    with pytest.raises(PlexToolError, match="cannot be combined"):
        run_users("share", "alice", "--clear-restrictions", "--movies-rating", "G")


def test_users_share_without_access_needs_libraries(monkeypatch, config, capsys):
    account = FakeAccount(people=[person("Carol")])
    users_setup(monkeypatch, config, account)
    with pytest.raises(PlexToolError, match="no access to this server yet"):
        run_users("share", "carol", "--downloads", "yes")
    run_users("share", "carol", "--libraries", "Movies")
    assert "grants it" in capsys.readouterr().out
    with pytest.raises(PlexToolError, match="not a user on this account"):
        run_users("share", "nobody", "--downloads", "yes")
    with pytest.raises(PlexToolError, match="owns this server"):
        run_users("share", "owner", "--downloads", "yes")


def test_users_remove_needs_a_choice_and_previews(monkeypatch, config, capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["users", "remove", "alice"])
    capsys.readouterr()
    account = FakeAccount(people=[person("Alice", [share_for(libs=3)])])
    users_setup(monkeypatch, config, account)
    tokens.save_record([{"name": "alice-reader", "access": "ro", "user": "Alice"}])
    run_users("remove", "alice", "--server-access")
    out = capsys.readouterr().out
    assert account.calls == [] and "stay a friend" in out and "loses: 3 libraries" in out
    assert "alice-reader" in out and "stop working" in out
    run_users("remove", "alice", "--server-access", "--commit")
    kind, _, kwargs = account.calls[0]
    assert kind == "update" and kwargs == {"sections": ["Movies"], "removeSections": True}   # a non-empty list is needed
    run_users("remove", "alice", "--friend", "--commit")
    assert account.calls[1] == ("removeFriend", "Alice")


def test_users_remove_refusals(monkeypatch, config):
    account = FakeAccount(people=[person("Alice", [share_for()]), person("Kid", [share_for()], home=True),
                                  person("Dave")])
    users_setup(monkeypatch, config, account)
    with pytest.raises(PlexToolError, match="owns this server"):
        run_users("remove", "owner", "--friend", "--commit")
    with pytest.raises(PlexToolError, match="Plex Home"):
        run_users("remove", "kid", "--friend", "--commit")
    with pytest.raises(PlexToolError, match="no access to Fake"):
        run_users("remove", "dave", "--server-access", "--commit")
    assert account.calls == []


def pending_invite(email="bob@example.com"):
    """An invitation shaped like Plex's reply: the server name and a library count, nothing more."""
    import xml.etree.ElementTree as ET
    from datetime import datetime
    element = ET.fromstring(f'<Invite id="{email}" createdAt="1793720895" friend="0" home="0" server="1" '
                            f'username="" email="{email}" friendlyName="{email}"><Server name="Fake" numLibraries="2"/></Invite>')
    return NS(email=email, username="", friendlyName=email, server=True, home=False,
              createdAt=datetime(2026, 11, 3), _data=element,
              servers=[NS(name="Fake", numLibraries=2, allLibraries=False)])


def test_users_invites_show_the_count_and_what_plextool_recorded(monkeypatch, config, capsys):
    account = FakeAccount()
    users_setup(monkeypatch, config, account)
    run_users("invite", "bob@example.com", "--libraries", "Movies,TV Shows", "--tv-rating", "TV-Y",
              "--downloads", "yes", "--commit")
    capsys.readouterr()
    account.invites = [pending_invite("bob@example.com"), pending_invite("other@example.com")]
    run_users("invites")
    out = capsys.readouterr().out
    assert out.count("Fake: 2 libraries") == 2
    assert "libraries: Movies, TV Shows  (as recorded when invited)" in out
    assert "TV restrictions: contentRating TV-Y  (as recorded when invited)" in out
    assert "downloads: allowed" in out
    assert "Plex does not say which libraries or settings" in out            # the invitation plextool did not send
    assert "TOKEN" not in users.auth.config_dir().joinpath("invites.json").read_text()


SHARED_LIST = (
    '<MediaContainer><SharedServer id="9" invitedEmail="bob@example.com" accessToken="SECRETTOKEN" '
    'allowSync="1" allowChannels="0" allowCameraUpload="0" filterMovies="contentRating=G,PG">'
    '<Section id="1" key="1" title="Movies" type="movie" shared="1"/>'
    '<Section id="2" key="2" title="TV Shows" type="show" shared="0"/>'
    '<Section id="3" key="3" title="Music" type="artist" shared="1"/></SharedServer>'
    '<SharedServer id="8" invitedEmail="someone@else.com" accessToken="OTHERSECRET"/></MediaContainer>')


def test_users_invites_use_plexs_shared_list_when_it_has_the_details(monkeypatch, config, capsys):
    account = FakeAccount(invites=[pending_invite("bob@example.com")], shared_xml=SHARED_LIST)
    users_setup(monkeypatch, config, account)
    run_users("invites")
    out = capsys.readouterr().out
    assert account.queried == ["https://plex.tv/api/servers/machine1/shared_servers"]
    assert "libraries: Movies, Music  (from Plex)" in out and "TV Shows" not in out
    assert "features: downloads  (from Plex)" in out
    assert "restrictions: movies: contentRating=G,PG  (from Plex)" in out
    assert "as recorded" not in out and "SECRET" not in out


def test_plexs_list_wins_over_the_local_record(monkeypatch, config, capsys):
    account = FakeAccount(shared_xml=SHARED_LIST)
    users_setup(monkeypatch, config, account)
    run_users("invite", "bob@example.com", "--libraries", "TV Shows", "--commit")
    account.invites = [pending_invite("bob@example.com")]
    capsys.readouterr()
    run_users("invites")
    out = capsys.readouterr().out
    assert "libraries: Movies, Music  (from Plex)" in out and "as recorded" not in out


def test_users_invites_raw_shows_the_matching_entry_without_secrets(monkeypatch, config, capsys):
    account = FakeAccount(invites=[pending_invite("bob@example.com"), pending_invite("none@example.com")],
                          shared_xml=SHARED_LIST)
    users_setup(monkeypatch, config, account)
    run_users("invites", "--raw")
    out = capsys.readouterr().out
    assert 'invitedEmail="bob@example.com"' in out and 'title="Movies"' in out
    assert "SECRETTOKEN" not in out and "OTHERSECRET" not in out and "accessToken" not in out
    assert "has nothing for this invitation" in out


def test_users_invites_fall_back_when_plex_will_not_give_the_list(monkeypatch, config, capsys):
    from plexapi.exceptions import BadRequest
    account = FakeAccount(invites=[pending_invite()], shared_xml=BadRequest("(400) no"))
    users_setup(monkeypatch, config, account)
    run_users("invites")
    out = capsys.readouterr().out
    assert "Fake: 2 libraries" in out and "Plex does not say which libraries" in out


def test_users_invites_still_work_if_the_server_cannot_be_reached(monkeypatch, config, capsys):
    account = FakeAccount(invites=[pending_invite()])
    users_setup(monkeypatch, config, account)

    def unreachable(args):
        raise PlexToolError("down")
    monkeypatch.setattr(users, "connect", unreachable)
    run_users("invites")
    captured = capsys.readouterr()
    assert "Fake: 2 libraries" in captured.out and "Could not reach the server" in captured.err
    assert account.queried == []


def test_users_invites_forget_what_is_no_longer_pending(monkeypatch, config, capsys):
    account = FakeAccount()
    users_setup(monkeypatch, config, account)
    run_users("invite", "bob@example.com", "--libraries", "Movies", "--commit")
    account.invites = []                                  # accepted, or cancelled elsewhere
    run_users("invites")
    assert "none" in capsys.readouterr().out and users.load_invites() == []


def test_users_cancel_forgets_the_record(monkeypatch, config):
    account = FakeAccount()
    users_setup(monkeypatch, config, account)
    run_users("invite", "bob@example.com", "--libraries", "Movies", "--commit")
    account.invites = [pending_invite("bob@example.com")]
    assert len(users.load_invites()) == 1
    run_users("cancel", "bob@example.com", "--commit")
    assert users.load_invites() == []


def test_users_invites_raw_is_plexs_reply(monkeypatch, config, capsys):
    users_setup(monkeypatch, config, FakeAccount(invites=[pending_invite()]))
    run_users("invites", "--raw")
    raw = capsys.readouterr().out
    assert raw.startswith("<Invite") and 'numLibraries="2"' in raw


def test_users_list_invites_and_cancel(monkeypatch, config, capsys):
    from datetime import datetime
    invite = NS(email="bob@example.com", username="bob", friendlyName="Bob", server=True, home=False,
                createdAt=datetime(2026, 11, 3))
    account = FakeAccount(people=[person("Alice", [share_for(all_libs=True)]), person("Dave")], invites=[invite])
    users_setup(monkeypatch, config, account)
    run_users("list", "--detail")
    out = capsys.readouterr().out
    assert "Alice" in out and "all libraries" in out and "Dave" not in out
    assert "features: downloads" in out and "restrictions: movies: contentRating=G" in out
    assert "shared: Movies" in out and "1 invitation waiting" in out
    run_users("invites")
    assert "bob@example.com" in capsys.readouterr().out
    run_users("cancel", "BOB@example.com")
    assert account.calls == [] and "Would cancel" in capsys.readouterr().out
    run_users("cancel", "bob", "--commit")
    assert account.calls == [("cancel", "bob@example.com")]
    with pytest.raises(PlexToolError, match="No waiting invitation"):
        run_users("cancel", "zed")


# --- completion ----------------------------------------------------------

def test_completion_walks_every_command_and_option():
    found = completion.walk(build_parser())
    assert {"auth", "token", "users", "completion"} <= set(found[()]["subs"])
    assert found[("token",)]["subs"] == ["new", "list", "revoke"]
    new = found[("token", "new")]
    assert "--rw" in new["opts"] and "--rw" not in new["value_opts"]            # a switch takes no value
    assert "--file" in new["value_opts"] and "--name" in new["value_opts"]
    assert found[("auth", "login")]["choices"]["--type"] == ["jwt", "token"]
    assert found[("users", "invite")]["choices"]["--downloads"] == ["yes", "no"]


def test_completion_script_for_each_shell(capsys):
    assert completion.run(NS(shell="zsh")) == 0
    out = capsys.readouterr().out
    assert "bashcompinit" in out and "complete -o default -F _plextool plextool" in out
    bash = completion.script("bash", build_parser())
    assert "bashcompinit" not in bash and '"token") echo "new list revoke"' in bash


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_completion_works_in_bash(tmp_path):
    script = tmp_path / "plextool.bash"
    script.write_text(completion.script("bash", build_parser()))
    driver = tmp_path / "try.sh"
    driver.write_text(f'''source {script}
try() {{ COMP_WORDS=("$@"); COMP_CWORD=$(( $# - 1 )); COMPREPLY=(); _plextool; echo "${{COMPREPLY[*]}}"; }}
try plextool to
try plextool token ""
try plextool token new --r
try plextool token new --rw --file ""
try plextool auth login --type ""
try plextool stale --library Movies --un
''')
    done = subprocess.run(["bash", str(driver)], capture_output=True, text=True, check=True)
    assert done.stdout.splitlines() == ["token", "new list revoke", "--rw --ro", "", "jwt token", "--unwatched"]


# --- progress ------------------------------------------------------------

def test_working_is_silent_when_quick(capsys):
    with working("reading TV"):
        pass
    assert capsys.readouterr().err == ""


def test_working_reports_when_slow(monkeypatch, capsys):
    import time
    monkeypatch.setattr(common, "FIRST_NOTICE", 0.05)
    monkeypatch.setattr(common, "NOTICE_EVERY", 0.05)
    with working("checking no-subs") as progress:
        progress.detail = "3 of 9 items"
        time.sleep(0.2)
    err = capsys.readouterr().err
    assert "still checking no-subs..." in err and "(3 of 9 items)" in err


def test_verbose_hides_tokens(monkeypatch, capsys):
    import logging
    monkeypatch.setattr(common, "VERBOSE", False)
    monkeypatch.setattr(common, "_SECRETS", {"s3cret"})
    logger = logging.getLogger("plexapi")
    old_handlers, old_level, old_prop = list(logger.handlers), logger.level, logger.propagate
    try:
        common.enable_verbose()
        logger.debug("GET http://x:32400/library/sections/1/all?type=4&X-Plex-Token=abc123&a=b")
        logger.debug("token is s3cret here")
    finally:
        logger.handlers[:], logger.level, logger.propagate = old_handlers, old_level, old_prop
    err = capsys.readouterr().err
    assert "GET http://x:32400/library/sections/1/all?type=4&X-Plex-Token=HIDDEN&a=b" in err
    assert "abc123" not in err and "s3cret" not in err and "token is HIDDEN here" in err


def test_verbose_flag_is_accepted_before_and_after_the_command():
    parser = build_parser()
    assert parser.parse_args(["-v", "stale"]).verbose_first is True
    assert parser.parse_args(["stale", "-v"]).verbose is True
    assert parser.parse_args(["stale"]).verbose is False


def test_working_prints_start_and_finish_when_verbose(monkeypatch, capsys):
    monkeypatch.setattr(common, "VERBOSE", True)
    with working("reading TV"):
        pass
    err = capsys.readouterr().err
    assert "reading TV..." in err and "finished reading TV in" in err


def test_scan_can_turn_off_autoreload():
    items = [NS(_autoReload=True), NS(_autoReload=True)]
    section = NS(title="Movies", search=lambda **kw: items)
    assert common.scan(section, autoreload=False, libtype="movie") is items
    assert [i._autoReload for i in items] == [False, False]
    other = [NS(_autoReload=True)]
    common.scan(NS(title="TV", search=lambda **kw: other), libtype="show")
    assert other[0]._autoReload is True


def test_format_duration():
    assert common.format_duration(4.24) == "4.2s"
    assert common.format_duration(75) == "1m 15s"
    assert common.format_duration(3700) == "1h 1m 40s"


def test_total_time_shown_when_slow_or_verbose(monkeypatch, capsys):
    from plextool import cli
    monkeypatch.setattr(stale, "run", lambda args: 0)
    monkeypatch.setattr(cli, "SHOW_TIME_AFTER", 0)
    assert cli.main(["stale"]) == 0
    assert "Finished in " in capsys.readouterr().err
    monkeypatch.setattr(cli, "SHOW_TIME_AFTER", 3600)
    cli.main(["stale"])
    assert capsys.readouterr().err == ""
    cli.main(["stale", "-v"])
    assert "Finished in " in capsys.readouterr().err


def test_plural():
    assert common.plural(1, "match") == "1 match"
    assert common.plural(0, "match") == "0 matches"
    assert common.plural(4039, "match") == "4039 matches"
    assert common.plural(2, "file") == "2 files"
    assert common.plural(2, "subtitle file") == "2 subtitle files"
    assert common.plural(3, "box") == "3 boxes"


def _connect_failing(monkeypatch, error, saved=None, url=None):
    monkeypatch.setattr(common, "resolve_token", lambda args: ("tok", "test"))
    monkeypatch.setattr("plextool.server.load_saved", lambda: saved)

    def refuse(*a, **kw):
        raise error
    monkeypatch.setattr(common, "PlexServer", refuse)
    args = NS(base_url=url, token=None, token_file=None)
    with pytest.raises(PlexToolError) as raised:
        common.connect(args)
    return str(raised.value)


def test_connect_without_a_chosen_server_says_so(monkeypatch):
    import requests
    monkeypatch.delenv("PLEX_URL", raising=False)
    message = _connect_failing(monkeypatch, requests.exceptions.ConnectTimeout("Connection to localhost timed out"))
    assert message.startswith("Could not reach http://localhost:32400: no answer (timed out).")
    assert "No server is chosen" in message and "plextool server use" in message
    assert "HTTPConnectionPool" not in message


def test_connect_with_an_explicit_url_does_not_blame_the_default(monkeypatch):
    import requests
    monkeypatch.delenv("PLEX_URL", raising=False)
    error = requests.exceptions.ConnectionError("Failed to establish a new connection: [Errno 111] Connection refused")
    message = _connect_failing(monkeypatch, error, url="http://nas:32400")
    assert message == "Could not reach http://nas:32400: connection refused (nothing is listening there)."


def test_default_connect_uses_a_short_timeout(monkeypatch):
    monkeypatch.delenv("PLEX_URL", raising=False)
    monkeypatch.setattr(common, "resolve_token", lambda args: ("tok", "test"))
    monkeypatch.setattr("plextool.server.load_saved", lambda: None)
    seen = {}

    def fake(url, token, timeout=None):
        seen.update(url=url, timeout=timeout)
        return NS(_baseurl=url)
    monkeypatch.setattr(common, "PlexServer", fake)
    common.connect(NS(base_url=None, token=None, token_file=None))
    assert seen == {"url": "http://localhost:32400", "timeout": common.DEFAULT_TIMEOUT}


def test_describe_reply():
    page = b'<?xml version="1.0"?><MediaContainer size="100" totalSize="5400" offset="200"><Video/></MediaContainer>'
    assert common.describe_reply(200, page, 0.824) == "  <- 200, 100 records (201-300 of 5400), 103 B, 0.82s"
    last = b'<MediaContainer size="1" totalSize="201" offset="200">'
    assert "1 record (201-201 of 201)" in common.describe_reply(200, last, 0.1)
    assert "(of 5)" in common.describe_reply(200, b'<MediaContainer size="0" totalSize="5">', 0.1)
    assert common.describe_reply(200, b'<MediaContainer size="7">', 0.1).count("(") == 0
    assert common.describe_reply(401, b"nope", 0.01) == "  <- 401, 4 B, 0.01s"


# --- stale ---------------------------------------------------------------

def test_item_size_sums_all_versions():
    item = NS(media=[NS(parts=[part(size=5), part(size=6)]), NS(parts=[part(size=7)])])
    assert item_size(item) == 18


def test_build_rows_groups_episodes_by_show():
    old, new = datetime(2020, 1, 1), datetime(2024, 1, 1)
    items = [episode("Show", 1, 100, views=1, added=new, last=old),
             episode("Show", 2, 200, views=2, added=old, last=new),
             episode("Other", 1, 50)]
    rows = {r["name"]: r for r in stale.build_rows(items, "show")}
    assert rows["Show"] == {"name": "Show", "size": 300, "added": old, "last_viewed": new,
                            "views": 3, "count": 2, "watchers": {"owner": new}}
    assert rows["Other"]["last_viewed"] is None


def test_add_user_views_counts_other_users():
    old, mid, new = datetime(2020, 1, 1), datetime(2022, 1, 1), datetime(2024, 1, 1)
    rows = stale.build_rows([episode("Show", 1, 100, views=1, last=old),
                             episode("Quiet", 1, 50), episode("Mine", 1, 70)], "show")
    theirs = [episode("Show", 1, views=2, last=new), episode("Quiet", 1, views=1, last=mid),
              episode("Hidden", 1, views=4, last=new), episode("Mine", 1, views=0)]
    stale.add_user_views(rows, theirs, "show", "alice")
    by_name = {r["name"]: r for r in rows}
    assert by_name["Show"]["views"] == 3
    assert by_name["Show"]["last_viewed"] == new
    assert by_name["Show"]["watchers"] == {"owner": old, "alice": new}
    assert stale.latest_watcher(by_name["Show"]) == "alice"
    assert by_name["Quiet"]["views"] == 1 and by_name["Quiet"]["watchers"] == {"alice": mid}
    assert by_name["Mine"]["views"] == 0 and by_name["Mine"]["watchers"] == {}
    assert "Hidden" not in by_name
    kept = stale.filter_rows(rows, NOW, unwatched=True)
    assert [r["name"] for r in kept] == ["Mine"]


def test_note_watcher_keeps_latest_and_handles_missing_dates():
    row = {"watchers": {}}
    stale.note_watcher(row, "bob", None)
    assert row["watchers"] == {"bob": None} and stale.latest_watcher(row) is None
    stale.note_watcher(row, "bob", datetime(2024, 1, 1))
    stale.note_watcher(row, "bob", datetime(2023, 1, 1))
    assert row["watchers"]["bob"] == datetime(2024, 1, 1)


class FakeServer:
    """Just enough of a PlexServer for stale.run(): sections of items by library title."""

    def __init__(self, items_by_title):
        self.items_by_title = items_by_title
        self.library = self

    def section(self, title):
        if title not in self.items_by_title:
            raise NotFound(title)
        items = self.items_by_title[title]
        return NS(title=title, TYPE="show", search=lambda **kw: items)


def test_stale_run_counts_other_users(monkeypatch, capsys):
    when = datetime(2024, 1, 1)
    owner_items = [episode("Show", 1, 100), episode("Other", 1, 50)]
    owner = FakeServer({"TV": owner_items})
    alice = FakeServer({"TV": [episode("Show", 1, views=1, last=when)]})
    bob = FakeServer({})  # TV is not shared with bob
    section = NS(title="TV", TYPE="show", search=lambda **kw: owner_items)
    monkeypatch.setattr(stale, "connect", lambda args: owner)
    monkeypatch.setattr(stale, "pick_sections", lambda plex, names: [section])
    monkeypatch.setattr(stale, "shared_users", lambda args, plex: ["alice", "bob"])
    monkeypatch.setattr(stale, "user_server",
                        lambda args, plex, name: {"alice": alice, "bob": bob, "me": owner}[name])
    args = build_parser().parse_args(["stale", "--unwatched", "--all-users", "--user", "me", "--json"])
    assert stale.run(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["name"] for r in out["TV"]] == ["Other"]
    args = build_parser().parse_args(["stale", "--all-users", "--json"])
    assert stale.run(args) == 0
    shown = {r["name"]: r for r in json.loads(capsys.readouterr().out)["TV"]}
    assert shown["Show"]["watchers"] == {"alice": when.isoformat()}


def test_filter_rows():
    rows = [
        {"name": "never", "size": 10, "added": NOW - timedelta(days=400), "last_viewed": None, "views": 0},
        {"name": "recent", "size": 10, "added": NOW - timedelta(days=400),
         "last_viewed": NOW - timedelta(days=5), "views": 3},
        {"name": "stale", "size": 10, "added": NOW - timedelta(days=400),
         "last_viewed": NOW - timedelta(days=300), "views": 1},
        {"name": "new", "size": 10, "added": NOW - timedelta(days=2), "last_viewed": None, "views": 0},
        {"name": "tiny", "size": 1, "added": NOW - timedelta(days=400), "last_viewed": None, "views": 0},
    ]
    names = lambda **kw: [r["name"] for r in stale.filter_rows(rows, NOW, **kw)]
    assert names(unwatched=True) == ["never", "new", "tiny"]
    assert names(idle_days=100) == ["never", "stale", "new", "tiny"]
    assert names(age_days=30) == ["never", "recent", "stale", "tiny"]
    assert names(min_size=5, unwatched=True, age_days=30) == ["never"]


def test_parse_size():
    assert stale.parse_size("2GB") == 2 * 1024**3
    assert stale.parse_size("1.5mb") == int(1.5 * 1024**2)
    assert stale.parse_size("100") == 100
    with pytest.raises(ArgumentTypeError):
        stale.parse_size("lots")


# --- audit ---------------------------------------------------------------

def test_audit_basic_checks():
    assert audit.check_unmatched(NS(guid="local://123"), None)
    assert audit.check_unmatched(NS(guid="plex://movie/1"), None) is None
    assert audit.check_no_poster(NS(thumb=None), None)
    assert audit.check_no_summary(NS(summary=""), None)
    assert audit.check_no_summary(NS(summary="x"), None) is None


def test_audit_missing_files_and_low_res():
    gone = NS(media=[NS(parts=[part("/x.mkv", exists=False), part("/y.mkv")])])
    assert "/x.mkv" in audit.check_missing_files(gone, None)
    assert audit.check_missing_files(NS(media=[NS(parts=[part()])]), None) is None
    assert audit.check_low_res(NS(media=[NS(videoResolution="480")]), None)
    assert audit.check_low_res(NS(media=[NS(videoResolution="480"), NS(videoResolution="1080")]), None) is None
    assert audit.check_low_res(NS(media=[NS(videoResolution=None)]), None) is None


def test_audit_language_checks():
    sub = NS(languageCode="eng")
    p = NS(subtitleStreams=lambda: [sub], audioStreams=list)
    item = NS(media=[NS(parts=[p])])
    assert audit.check_no_subs(item, "eng") is None
    assert audit.check_no_subs(item, "fra")
    assert audit.check_no_audio(item, "eng")


def test_run_check_reloads_only_when_needed():
    reloads = []
    item = NS(type="movie", title="T", year=None, guid="local://1", thumb="x",
              reload=lambda: reloads.append(1), media=[NS(parts=[part()])])
    assert audit.run_check("unmatched", [item], None)[0]["reason"].startswith("not matched")
    assert reloads == []
    audit.run_check("no-subs", [item], "eng")
    assert reloads == [1]


# --- resume --------------------------------------------------------------

def test_resume_select_and_percent():
    a = NS(viewOffset=500, duration=1000, lastViewedAt=NOW - timedelta(days=60))
    b = NS(viewOffset=100, duration=1000, lastViewedAt=NOW - timedelta(days=1))
    c = NS(viewOffset=None, duration=1000, lastViewedAt=None)
    assert resume.percent(a) == 50
    assert resume.percent(c) == 0
    assert resume.select([a, b, c], NOW) == [a, b]
    assert resume.select([a, b, c], NOW, idle_days=30) == [a]


# --- dupes ---------------------------------------------------------------

def entry(*versions):
    return {"title": "T", "versions": [
        {"index": i, "size": s, "height": h, "parts": [{"file": f"/{i}"}] * n}
        for i, (s, h, n) in enumerate(versions)]}


def test_choose_deletions():
    e = entry((500, 1080, 1), (900, 720, 1), (100, 480, 1))
    assert dupes.choose_deletions(e, "largest") == ([0, 2], None)
    assert dupes.choose_deletions(e, "smallest") == ([0, 1], None)
    assert dupes.choose_deletions(e, "best-resolution") == ([1, 2], None)


def test_choose_deletions_skips_multipart():
    indices, reason = dupes.choose_deletions(entry((500, 1080, 2), (900, 720, 1)), "largest")
    assert indices == [] and "multi-part" in reason


def test_dupes_commit_requires_keep():
    args = build_parser().parse_args(["dupes", "-T", "x", "--commit"])
    with pytest.raises(PlexToolError):
        args.run(args)


def test_confirm_typed(monkeypatch):
    confirm_typed("DELETE", "msg", assume_yes=True)
    monkeypatch.setattr("sys.stdin", NS(isatty=lambda: False))
    with pytest.raises(PlexToolError):
        confirm_typed("DELETE", "msg")
    monkeypatch.setattr("sys.stdin", NS(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda _: "no")
    with pytest.raises(PlexToolError):
        confirm_typed("DELETE", "msg")
    monkeypatch.setattr("builtins.input", lambda _: "DELETE")
    confirm_typed("DELETE", "msg")


# --- watched / playlists ---------------------------------------------------

def test_watched_file_round_trip():
    data = watched.to_file_data("alice", {"movies": {"g1": "One"}, "episodes": {"g2": "Two"}})
    assert data["user"] == "alice"
    assert watched.from_file_data(data) == {"movies": {"g1": "One"}, "episodes": {"g2": "Two"}}
    with pytest.raises(PlexToolError):
        watched.from_file_data({"version": 99})


def test_watched_kind_flags():
    parser = build_parser()
    both = parser.parse_args(["watched", "export", "f.json"])
    assert [k[0] for k in watched.wanted_kinds(both)] == ["movies", "episodes"]
    shows = parser.parse_args(["watched", "export", "f.json", "--shows"])
    assert [k[0] for k in watched.wanted_kinds(shows)] == ["episodes"]


def test_playlist_data():
    items = [NS(guid="plex://movie/1", type="movie", title="One", year=2000)]
    pl = NS(title="Faves", playlistType="video", smart=False, items=lambda: items)
    assert playlists.playlist_data(pl) == {
        "title": "Faves", "type": "video", "smart": False,
        "items": [{"guid": "plex://movie/1", "title": "One (2000)", "type": "movie"}]}
    smart = NS(title="S", playlistType="video", smart=True, items=lambda: 1 / 0)
    assert playlists.playlist_data(smart)["items"] == []


def test_cli_parses_new_commands():
    parser = build_parser()
    assert parser.parse_args(["scan", "--path", "/m", "-l", "Movies", "--wait"]).path == "/m"
    assert parser.parse_args(["stale", "--idle", "365", "--min-size", "1GB"]).min_size == 1024**3
    assert parser.parse_args(["audit", "-c", "no-subs", "--lang", "eng"]).check == ["no-subs"]
    assert parser.parse_args(["resume", "--clear", "watched", "-y"]).commit
    assert parser.parse_args(["playlists", "export", "f.json"]).file == "f.json"
    assert parser.parse_args(["watched", "mark", "-t", "X", "--unwatched"]).unwatched


def test_audit_requires_lang():
    args = build_parser().parse_args(["audit", "-T", "x", "-c", "no-subs"])
    with pytest.raises(PlexToolError):
        args.run(args)


def test_write_json_to_stdout_keeps_messages_out_of_the_data(capsys):
    stream = write_json("-", {"a": 1})
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"a": 1}
    assert stream is sys.stderr


def test_write_and_read_json_file(tmp_path, capsys):
    path = str(tmp_path / "x.json")
    assert write_json(path, {"b": "é"}) is sys.stdout
    assert read_json(path) == {"b": "é"}


def test_read_json_from_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"c": 2}'))
    assert read_json("-") == {"c": 2}


def test_read_json_errors(tmp_path, monkeypatch):
    with pytest.raises(PlexToolError, match="Could not read"):
        read_json(str(tmp_path / "missing.json"))
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    with pytest.raises(PlexToolError, match="standard input"):
        read_json("-")
