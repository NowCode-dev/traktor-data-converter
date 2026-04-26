"""Tests pour la cascade multi-sources de recherche d'artwork (V1.9.0)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from traktord.utils import artwork_search
from traktord.utils.artwork_search import (
    _BEATPORT_ID_RE,
    _normalize,
    _strip_mix_suffix,
    _string_similarity,
    find_cover_cascade,
)


# ---------------------------------------------------------------------------
# Regex extraction TrackID Beatport
# ---------------------------------------------------------------------------

class TestBeatportIdRegex:
    """Verifie l'extraction du TrackID depuis les noms de fichiers Beatport."""

    def test_extracts_id_from_recent_format(self):
        name = "(07-2025)-(20629038)_DAETOR-No_Hiding-Original_Mix-Eastenderz.mp3"
        m = _BEATPORT_ID_RE.search(name)
        assert m is not None
        assert m.group(1) == "20629038"

    def test_extracts_id_with_aiff(self):
        name = "(12-2024)-(12345)_Artist-Title-Mix-Label.aiff"
        m = _BEATPORT_ID_RE.search(name)
        assert m is not None
        assert m.group(1) == "12345"

    def test_no_match_on_legacy_filename(self):
        # Anciens fichiers Beatport sans TrackID dans le nom.
        assert _BEATPORT_ID_RE.search("Artist - Title (Original Mix).mp3") is None

    def test_no_match_on_partial_pattern(self):
        # Date sans TrackID.
        assert _BEATPORT_ID_RE.search("(07-2025)_DAETOR-Track.mp3") is None


# ---------------------------------------------------------------------------
# Utilitaires fuzzy match
# ---------------------------------------------------------------------------

class TestStripMixSuffix:
    def test_removes_original_mix(self):
        assert _strip_mix_suffix("Track Name (Original Mix)") == "Track Name"

    def test_removes_remix_brackets(self):
        assert _strip_mix_suffix("Track [Extended Mix]") == "Track"

    def test_keeps_text_without_suffix(self):
        assert _strip_mix_suffix("Just A Title") == "Just A Title"

    def test_case_insensitive(self):
        assert _strip_mix_suffix("Song (ORIGINAL MIX)") == "Song"


class TestNormalize:
    def test_lowercase(self):
        assert _normalize("HELLO WORLD") == "hello world"

    def test_strips_punctuation(self):
        assert _normalize("Hello, World!") == "hello world"

    def test_collapses_spaces(self):
        assert _normalize("a   b   c") == "a b c"


class TestStringSimilarity:
    def test_identical(self):
        assert _string_similarity("foo bar", "foo bar") == 1.0

    def test_disjoint(self):
        assert _string_similarity("foo", "bar") == 0.0

    def test_substring_bonus(self):
        # "bicep" est substring de "bicep glue mixed"
        score = _string_similarity("bicep", "bicep glue mixed")
        assert score >= 0.4  # jaccard 1/3 + 0.2 bonus

    def test_empty_returns_zero(self):
        assert _string_similarity("", "foo") == 0.0
        assert _string_similarity("foo", "") == 0.0


# ---------------------------------------------------------------------------
# Cascade : ordre et court-circuit
# ---------------------------------------------------------------------------

class TestCascadeOrder:
    """Verifie que la cascade s'arrete au premier match."""

    def test_beatport_id_short_circuits(self, tmp_path):
        """Si Beatport via TrackID matche, les autres sources ne sont pas appelees."""
        beatport_bytes = b"BEATPORT_COVER_BYTES"
        file_path = tmp_path / "(07-2025)-(20629038)_DAETOR-No_Hiding-Original_Mix-Eastenderz.mp3"
        file_path.touch()

        with patch.object(artwork_search, "_search_beatport_id", return_value=beatport_bytes) as mock_bp, \
             patch.object(artwork_search, "_search_discogs") as mock_dc, \
             patch.object(artwork_search, "_search_musicbrainz") as mock_mb, \
             patch.object(artwork_search, "_search_itunes") as mock_it:
            result = find_cover_cascade("DAETOR", "No Hiding", file_path=file_path)

        assert result == beatport_bytes
        mock_bp.assert_called_once()
        mock_dc.assert_not_called()
        mock_mb.assert_not_called()
        mock_it.assert_not_called()

    def test_falls_through_to_discogs_when_beatport_misses(self, tmp_path):
        discogs_bytes = b"DISCOGS_COVER_BYTES"
        file_path = tmp_path / "no-trackid.mp3"
        file_path.touch()

        with patch.object(artwork_search, "_search_beatport_id", return_value=None), \
             patch.object(artwork_search, "_search_discogs", return_value=discogs_bytes) as mock_dc, \
             patch.object(artwork_search, "_search_musicbrainz") as mock_mb, \
             patch.object(artwork_search, "_search_itunes") as mock_it:
            result = find_cover_cascade("Artist", "Title", file_path=file_path)

        assert result == discogs_bytes
        mock_dc.assert_called_once()
        mock_mb.assert_not_called()
        mock_it.assert_not_called()

    def test_falls_through_to_musicbrainz(self, tmp_path):
        mb_bytes = b"MUSICBRAINZ_COVER_BYTES"
        file_path = tmp_path / "no-trackid.mp3"
        file_path.touch()

        with patch.object(artwork_search, "_search_beatport_id", return_value=None), \
             patch.object(artwork_search, "_search_discogs", return_value=None), \
             patch.object(artwork_search, "_search_musicbrainz", return_value=mb_bytes) as mock_mb, \
             patch.object(artwork_search, "_search_itunes") as mock_it:
            result = find_cover_cascade("Artist", "Title", file_path=file_path)

        assert result == mb_bytes
        mock_mb.assert_called_once()
        mock_it.assert_not_called()

    def test_itunes_is_last_fallback(self, tmp_path):
        itunes_bytes = b"ITUNES_COVER_BYTES"
        file_path = tmp_path / "no-trackid.mp3"
        file_path.touch()

        with patch.object(artwork_search, "_search_beatport_id", return_value=None), \
             patch.object(artwork_search, "_search_discogs", return_value=None), \
             patch.object(artwork_search, "_search_musicbrainz", return_value=None), \
             patch.object(artwork_search, "_search_itunes", return_value=itunes_bytes) as mock_it:
            result = find_cover_cascade("Artist", "Title", file_path=file_path)

        assert result == itunes_bytes
        mock_it.assert_called_once()

    def test_returns_none_when_all_sources_miss(self, tmp_path):
        file_path = tmp_path / "no-trackid.mp3"
        file_path.touch()

        with patch.object(artwork_search, "_search_beatport_id", return_value=None), \
             patch.object(artwork_search, "_search_discogs", return_value=None), \
             patch.object(artwork_search, "_search_musicbrainz", return_value=None), \
             patch.object(artwork_search, "_search_itunes", return_value=None):
            result = find_cover_cascade("Artist", "Title", file_path=file_path)

        assert result is None

    def test_skips_beatport_id_when_no_file_path(self):
        """Sans file_path, on saute l'extraction TrackID."""
        with patch.object(artwork_search, "_search_beatport_id") as mock_bp, \
             patch.object(artwork_search, "_search_discogs", return_value=b"OK") as mock_dc, \
             patch.object(artwork_search, "_search_musicbrainz") as mock_mb, \
             patch.object(artwork_search, "_search_itunes") as mock_it:
            result = find_cover_cascade("Artist", "Title", file_path=None)

        assert result == b"OK"
        mock_bp.assert_not_called()
        mock_dc.assert_called_once()

    def test_returns_none_for_empty_artist_or_title(self):
        # Pas de query possible si artist ou title vide ET pas de file_path.
        assert find_cover_cascade("", "Title") is None
        assert find_cover_cascade("Artist", "") is None


# ---------------------------------------------------------------------------
# Discogs token resolution
# ---------------------------------------------------------------------------

class TestDiscogsTokenResolution:
    def test_uses_arg_token_over_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DISCOGS_TOKEN", "env_token")
        file_path = tmp_path / "no-trackid.mp3"
        file_path.touch()

        captured: dict[str, str] = {}

        def fake_discogs(artist, title, token, threshold):
            captured["token"] = token
            return None

        with patch.object(artwork_search, "_search_beatport_id", return_value=None), \
             patch.object(artwork_search, "_search_discogs", side_effect=fake_discogs), \
             patch.object(artwork_search, "_search_musicbrainz", return_value=None), \
             patch.object(artwork_search, "_search_itunes", return_value=None):
            find_cover_cascade(
                "Artist", "Title", file_path=file_path, discogs_token="arg_token"
            )

        assert captured["token"] == "arg_token"

    def test_falls_back_to_env_when_no_arg(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DISCOGS_TOKEN", "env_token")
        file_path = tmp_path / "no-trackid.mp3"
        file_path.touch()

        captured: dict[str, str] = {}

        def fake_discogs(artist, title, token, threshold):
            captured["token"] = token
            return None

        with patch.object(artwork_search, "_search_beatport_id", return_value=None), \
             patch.object(artwork_search, "_search_discogs", side_effect=fake_discogs), \
             patch.object(artwork_search, "_search_musicbrainz", return_value=None), \
             patch.object(artwork_search, "_search_itunes", return_value=None):
            find_cover_cascade("Artist", "Title", file_path=file_path)

        assert captured["token"] == "env_token"


# ---------------------------------------------------------------------------
# Backward compat : search_itunes_cover existante
# ---------------------------------------------------------------------------

def test_search_itunes_cover_still_exported():
    """L'API V1.8.0 reste disponible pour les tests existants."""
    from traktord.utils.artwork_search import search_itunes_cover
    assert callable(search_itunes_cover)
