"""Tests pour l'extraction de la date de release."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from traktord.utils.track_date import get_release_date


def test_missing_file_returns_none(tmp_path: Path) -> None:
    """Fichier inexistant -> None sans exception."""
    assert get_release_date(tmp_path / "does_not_exist.mp3") is None


def test_tdrl_full_iso_date(tmp_path: Path) -> None:
    """TDRL avec date complete YYYY-MM-DD -> format Traktor YYYY/MM/DD."""
    mp3 = tmp_path / "(06-2021)-(15306058)_Cosmic_Boys-Dark_Places.mp3"
    mp3.write_bytes(b"\x00")

    fake_tags = {"TDRL": MagicMock(text=["2021-06-16"])}
    fake_tags_obj = MagicMock()
    fake_tags_obj.get = lambda k: fake_tags.get(k)

    with patch("mutagen.id3.ID3", return_value=fake_tags_obj):
        assert get_release_date(mp3) == "2021/06/16"


def test_tdor_fallback_when_tdrl_missing(tmp_path: Path) -> None:
    """TDRL absent mais TDOR present -> on lit TDOR."""
    mp3 = tmp_path / "track.mp3"
    mp3.write_bytes(b"\x00")

    fake_tags = {"TDOR": MagicMock(text=["2015-11-27"])}
    fake_tags_obj = MagicMock()
    fake_tags_obj.get = lambda k: fake_tags.get(k)

    with patch("mutagen.id3.ID3", return_value=fake_tags_obj):
        assert get_release_date(mp3) == "2015/11/27"


def test_filename_month_with_tdrc_year(tmp_path: Path) -> None:
    """Pas de TDRL/TDOR, mais filename `(MM-YYYY)` + TDRC year -> YYYY/MM."""
    mp3 = tmp_path / "(11-2015)-(7235392)_Alec_Troniq-Old_Tortures.mp3"
    mp3.write_bytes(b"\x00")

    fake_tags = {"TDRC": MagicMock(text=["2015"])}
    fake_tags_obj = MagicMock()
    fake_tags_obj.get = lambda k: fake_tags.get(k)

    # On patch aussi le birthtime pour simuler qu'il n'est pas dispo
    # (sinon il prendrait le birthtime avant de retomber sur TDRC).
    with patch("mutagen.id3.ID3", return_value=fake_tags_obj), \
         patch("traktord.utils.track_date._filesystem_birthtime", return_value=None):
        assert get_release_date(mp3) == "2015/11"


def test_year_only_no_filename_pattern(tmp_path: Path) -> None:
    """Pas de TDRL/TDOR, pas de filename pattern, mais TDRC year -> YYYY."""
    mp3 = tmp_path / "track.mp3"
    mp3.write_bytes(b"\x00")

    fake_tags = {"TDRC": MagicMock(text=["1998"])}
    fake_tags_obj = MagicMock()
    fake_tags_obj.get = lambda k: fake_tags.get(k)

    with patch("mutagen.id3.ID3", return_value=fake_tags_obj), \
         patch("traktord.utils.track_date._filesystem_birthtime", return_value=None):
        assert get_release_date(mp3) == "1998"


def test_no_tags_no_pattern_returns_none(tmp_path: Path) -> None:
    """Aucune source -> None."""
    mp3 = tmp_path / "untagged.mp3"
    mp3.write_bytes(b"\x00")

    fake_tags_obj = MagicMock()
    fake_tags_obj.get = lambda k: None

    with patch("mutagen.id3.ID3", return_value=fake_tags_obj), \
         patch("traktord.utils.track_date._filesystem_birthtime", return_value=None):
        assert get_release_date(mp3) is None


def test_birthtime_fallback_for_non_mp3(tmp_path: Path) -> None:
    """Pour un FLAC sans tags ID3, on tombe sur le birthtime du fichier."""
    flac = tmp_path / "track.flac"
    flac.write_bytes(b"\x00")

    with patch(
        "traktord.utils.track_date._filesystem_birthtime",
        return_value="2020/03/15",
    ):
        assert get_release_date(flac) == "2020/03/15"


def test_invalid_tdrl_format_falls_through(tmp_path: Path) -> None:
    """TDRL avec format invalide (ex: juste annee) -> on tombe sur TDOR ou autre."""
    mp3 = tmp_path / "(05-2019)-(123)_Track.mp3"
    mp3.write_bytes(b"\x00")

    fake_tags = {
        "TDRL": MagicMock(text=["2019"]),  # pas YYYY-MM-DD, ignore
        "TDRC": MagicMock(text=["2019"]),
    }
    fake_tags_obj = MagicMock()
    fake_tags_obj.get = lambda k: fake_tags.get(k)

    with patch("mutagen.id3.ID3", return_value=fake_tags_obj), \
         patch("traktord.utils.track_date._filesystem_birthtime", return_value=None):
        assert get_release_date(mp3) == "2019/05"
