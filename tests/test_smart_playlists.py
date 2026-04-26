"""Tests pour la detection des smart playlists (convention Genre = X)."""

from __future__ import annotations

from traktord.converters.traktor import (
    _build_smartlist_query,
    _detect_genre_smart_match,
)
from traktord.models.track import Track


def _track(path: str, genre: str) -> Track:
    return Track(title="t", artist="a", file_path=path, genre=genre)


def test_detect_simple_match() -> None:
    """100 % meme genre + nom playlist = genre -> match."""
    paths = ["a.mp3", "b.mp3", "c.mp3"]
    p2t = {p: _track(p, "Tech House") for p in paths}
    assert _detect_genre_smart_match("Tech House", paths, p2t) == "Tech House"


def test_detect_genre_contains_playlist_name() -> None:
    """Genre contient le nom playlist (cas Techno -> Classic Techno)."""
    paths = ["a.mp3", "b.mp3"]
    p2t = {
        "a.mp3": _track("a.mp3", "Classic Techno"),
        "b.mp3": _track("b.mp3", "Techno (Peak Time)"),
    }
    assert _detect_genre_smart_match("Techno", paths, p2t) == "Techno"


def test_detect_playlist_name_contains_genre() -> None:
    """Nom playlist contient le genre (cas inverse)."""
    paths = ["a.mp3"]
    p2t = {"a.mp3": _track("a.mp3", "House")}
    assert _detect_genre_smart_match("Deep House", paths, p2t) == "Deep House"


def test_detect_normalize_dash_slash() -> None:
    """Tirets et slashes normalises en espaces."""
    paths = ["a.mp3", "b.mp3"]
    p2t = {p: _track(p, "Tech-House") for p in paths}
    assert _detect_genre_smart_match("Tech House", paths, p2t) == "Tech House"


def test_detect_below_threshold_returns_none() -> None:
    """Ratio < 95 % -> pas smart."""
    paths = ["a.mp3", "b.mp3", "c.mp3", "d.mp3", "e.mp3"]
    p2t = {
        "a.mp3": _track("a.mp3", "Tech House"),
        "b.mp3": _track("b.mp3", "Tech House"),
        "c.mp3": _track("c.mp3", "Tech House"),
        "d.mp3": _track("d.mp3", "Disco"),
        "e.mp3": _track("e.mp3", "Funk"),
    }
    # 3/5 = 60 % < 95 %
    assert _detect_genre_smart_match("Tech House", paths, p2t) is None


def test_detect_no_genre_match_returns_none() -> None:
    """Aucun match nom <-> genre -> None."""
    paths = ["a.mp3"]
    p2t = {"a.mp3": _track("a.mp3", "Funk / Soul / Disco")}
    assert _detect_genre_smart_match("Funky House", paths, p2t) is None


def test_detect_empty_playlist_returns_none() -> None:
    """Playlist sans tracks -> None."""
    assert _detect_genre_smart_match("Whatever", [], {}) is None


def test_detect_tracks_without_genre_returns_none() -> None:
    """Toutes les tracks sans genre -> None (pas de tracks comptables)."""
    paths = ["a.mp3"]
    p2t = {"a.mp3": _track("a.mp3", "")}
    assert _detect_genre_smart_match("Tech House", paths, p2t) is None


def test_query_simple_no_variant() -> None:
    """Genre sans tiret/espace -> 1 seul terme."""
    assert _build_smartlist_query("Techno") == '$GENRE % "Techno"'


def test_query_with_dash_variant() -> None:
    """Genre avec tiret -> 2 variantes."""
    q = _build_smartlist_query("Tech-House")
    assert q == '$GENRE % "Tech-House" | $GENRE % "Tech House"'


def test_query_with_space_variant() -> None:
    """Genre avec espace -> 2 variantes."""
    q = _build_smartlist_query("Tech House")
    assert q == '$GENRE % "Tech House" | $GENRE % "Tech-House"'
