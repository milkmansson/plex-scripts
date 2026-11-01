import json
from argparse import ArgumentTypeError, Namespace
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from plextool import subs
from plextool.common import PlexToolError


def test_lang_code():
    assert subs.lang_code("pt-BR", "por") == "pt"
    assert subs.lang_code("en", "eng") == "en"
    assert subs.lang_code(None, "eng") == "en"
    assert subs.lang_code("und", "fre") == "fr"
    assert subs.lang_code(None, "tha") == "tha"
    assert subs.lang_code(None, None) == "und"
    assert subs.lang_code("", "und") == "und"


def test_codec_ext():
    assert subs.codec_ext("S_TEXT/UTF8") == "srt"
    assert subs.codec_ext("S_HDMV/PGS") == "sup"
    assert subs.codec_ext("S_SOMETHING/NEW") == "sub"


def test_flags_for():
    assert subs.flags_for(None, False, False) == (False, False)
    assert subs.flags_for("English (SDH)", False, False) == (False, True)
    assert subs.flags_for("English [Hearing Impaired]", False, False) == (False, True)
    assert subs.flags_for("Forced", False, False) == (True, False)
    assert subs.flags_for("Full", True, True) == (True, True)
    # words merely containing the letters don't count
    assert subs.flags_for("Enforced rule, accent", False, False) == (False, False)


def mkv_track(tid, codec, **props):
    return {"id": tid, "type": "subtitles", "properties": {"codec_id": codec, **props}}


IDENTIFY = {"tracks": [
    {"id": 0, "type": "video", "properties": {}},
    mkv_track(2, "S_TEXT/UTF8", language="eng"),
    mkv_track(3, "S_TEXT/ASS", language_ietf="en"),
    mkv_track(4, "S_HDMV/PGS", language="fre"),
    mkv_track(5, "S_TEXT/UTF8", language="eng", forced_track=True),
    mkv_track(6, "S_TEXT/UTF8", language="eng", track_name="English SDH"),
    mkv_track(7, "S_TEXT/UTF8", language="eng", flag_hearing_impaired=True),
]}


def test_mkv_names_use_number_only_when_same_name(tmp_path):
    tracks = subs.mkv_tracks(IDENTIFY)
    assert [t["id"] for t in tracks] == [2, 3, 4, 5, 6, 7]
    names = [p.name for p in subs.output_names(tmp_path / "Movie.mkv", tracks)]
    assert names == [
        "Movie.en.srt",          # plain English
        "Movie.2.en.ass",        # second plain English: same name, so numbered
        "Movie.fr.sup",
        "Movie.en.forced.srt",   # flagged: its own name, no number
        "Movie.en.sdh.srt",      # flagged by name
        "Movie.2.en.sdh.srt",    # second SDH track
    ]


def test_forced_and_sdh_together(tmp_path):
    track = {"lang": "en", "forced": True, "sdh": True, "ext": "srt"}
    assert subs.output_names(tmp_path / "M.mkv", [track])[0].name == "M.en.forced.sdh.srt"


PROBE = {"streams": [
    {"index": 1, "codec_type": "subtitle", "codec_name": "mov_text",
     "tags": {"language": "eng"}, "disposition": {"forced": 0, "hearing_impaired": 0}},
    {"index": 2, "codec_type": "subtitle", "codec_name": "mov_text",
     "tags": {"language": "eng", "title": "English (SDH)"}, "disposition": {}},
    {"index": 3, "codec_type": "subtitle", "codec_name": "mov_text",
     "tags": {"language": "spa"}, "disposition": {"forced": 1}},
    {"index": 4, "codec_type": "subtitle", "codec_name": "dvd_subtitle", "tags": {"language": "eng"}},
    {"index": 0, "codec_type": "video"},
]}


def test_mp4_tracks(tmp_path):
    tracks = subs.mp4_tracks(PROBE)
    assert [t["id"] for t in tracks] == [1, 2, 3, 4]
    assert tracks[3]["ext"] is None                      # image-based: not extractable
    assert tracks[2]["forced"] and tracks[1]["sdh"]
    names = [p.name for p in subs.output_names(tmp_path / "M.mp4", tracks[:3])]
    assert names == ["M.en.srt", "M.en.sdh.srt", "M.es.forced.srt"]


def test_find_videos_groups_by_kind(tmp_path):
    (tmp_path / "a").mkdir()
    for name in ("a/One.MKV", "Two.mkv", "Three.mp4", "Four.M4V", "Five.avi", "a/notes.txt"):
        (tmp_path / name).touch()
    found = subs.find_videos(tmp_path, ["mkv", "mp4"])
    assert sorted(p.name for p in found["mkv"]) == ["One.MKV", "Two.mkv"]
    assert sorted(p.name for p in found["mp4"]) == ["Four.M4V", "Three.mp4"]
    assert subs.find_videos(tmp_path, ["mp4"]).keys() == {"mp4"}


def test_parse_types():
    assert subs.parse_types("MKV, mp4") == ["mkv", "mp4"]
    with pytest.raises(ArgumentTypeError):
        subs.parse_types("avi")


@pytest.fixture
def fake_tools(monkeypatch):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "mkvmerge":
            return NS(returncode=0, stdout=json.dumps(IDENTIFY), stderr="")
        if cmd[0] == "ffprobe":
            return NS(returncode=0, stdout=json.dumps(PROBE), stderr="")
        return NS(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subs.subprocess, "run", run)
    monkeypatch.setattr(subs.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    return calls


def test_extract_dry_run_writes_nothing(tmp_path, fake_tools):
    mkv = tmp_path / "Movie.mkv"
    mkv.touch()
    assert subs.extract_file("mkv", mkv, commit=False, force=False) == 6
    assert [c[0] for c in fake_tools] == ["mkvmerge"]


def test_extract_mkv_commit_skips_existing(tmp_path, fake_tools):
    mkv = tmp_path / "Movie.mkv"
    mkv.touch()
    (tmp_path / "Movie.en.srt").touch()
    assert subs.extract_file("mkv", mkv, commit=True, force=False) == 5
    extracts = [c for c in fake_tools if c[0] == "mkvextract"]
    assert extracts[0][3] == f"3:{tmp_path / 'Movie.2.en.ass'}"
    assert subs.extract_file("mkv", mkv, commit=True, force=True) == 6


def test_extract_mp4_uses_ffmpeg_and_skips_image_tracks(tmp_path, fake_tools, capsys):
    mp4 = tmp_path / "Movie.mp4"
    mp4.touch()
    assert subs.extract_file("mp4", mp4, commit=True, force=False) == 3
    ffmpeg = [c for c in fake_tools if c[0] == "ffmpeg"]
    assert len(ffmpeg) == 3
    assert ffmpeg[0][-5:] == ["-map", "0:1", "-c:s", "srt", str(tmp_path / "Movie.en.srt")]
    assert "can't be extracted" in capsys.readouterr().out


def test_extract_reports_tool_failure(tmp_path, monkeypatch, capsys):
    def run(cmd, **kw):
        if cmd[0] == "ffprobe":
            return NS(returncode=0, stdout=json.dumps(PROBE), stderr="")
        return NS(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(subs.subprocess, "run", run)
    mp4 = tmp_path / "M.mp4"
    mp4.touch()
    assert subs.extract_file("mp4", mp4, commit=True, force=False) == 0
    assert "boom" in capsys.readouterr().out


def _args(tmp_path, **kw):
    base = {"directory": str(tmp_path), "types": ["mkv", "mp4"], "force": False, "commit": False,
            "scan": None, "scan_path": None}
    return Namespace(**{**base, **kw})


def test_missing_ffmpeg_still_does_mkv(tmp_path, monkeypatch, fake_tools, capsys):
    (tmp_path / "A.mkv").touch()
    (tmp_path / "B.mp4").touch()
    monkeypatch.setattr(subs.shutil, "which",
                        lambda tool: None if tool in ("ffmpeg", "ffprobe") else "/x")
    assert subs.run_extract(_args(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "A.mkv" in out and "B.mp4" not in out.split("!")[0]
    assert "1 mp4 file skipped: ffmpeg and ffprobe not found" in out


def test_missing_mkvtoolnix_still_does_mp4(tmp_path, monkeypatch, fake_tools, capsys):
    (tmp_path / "A.mkv").touch()
    (tmp_path / "B.mp4").touch()
    monkeypatch.setattr(subs.shutil, "which",
                        lambda tool: None if tool.startswith("mkv") else "/x")
    assert subs.run_extract(_args(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "B.mp4" in out and "mkvmerge and mkvextract not found" in out


def test_error_only_when_nothing_can_run(tmp_path, monkeypatch):
    (tmp_path / "A.mkv").touch()
    monkeypatch.setattr(subs.shutil, "which", lambda tool: None)
    with pytest.raises(PlexToolError, match="None of the video files"):
        subs.run_extract(_args(tmp_path))


def test_no_files_needs_no_tools(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(subs.shutil, "which", lambda tool: None)
    assert subs.run_extract(_args(tmp_path)) == 0
    assert "No mkv/mp4 files" in capsys.readouterr().out


def test_bad_directory():
    with pytest.raises(PlexToolError, match="Not a directory"):
        subs.run_extract(_args(Path("/nonexistent/dir")))
