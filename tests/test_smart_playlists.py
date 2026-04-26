"""Tests pour la detection des smart playlists (Genre / Artist / Comment)."""

from __future__ import annotations

from traktord.converters.traktor import (
    _build_smartlist_query,
    _detect_smart_match,
)
from traktord.models.track import Track


def _track(path: str, genre: str = "", artist: str = "", comment: str = "") -> Track:
    return Track(title="t", artist=artist, file_path=path, genre=genre, comment=comment)


# -----------------------------------------------------------------------------
# Strategie 1 : Genre OR
# -----------------------------------------------------------------------------

def test_single_genre_exact_match() -> None:
    paths = [f"{i}.mp3" for i in range(3)]
    p2t = {p: _track(p, genre="Tech House") for p in paths}
    field, values = _detect_smart_match("Tech House", paths, p2t)
    assert field == "GENRE"
    assert values == ["Tech House"]


def test_genre_contains_playlist_name() -> None:
    """playlist 'Techno' matche les genres 'Classic Techno', 'Techno Peak Time'."""
    paths = ["a.mp3", "b.mp3"]
    p2t = {
        "a.mp3": _track("a.mp3", genre="Classic Techno"),
        "b.mp3": _track("b.mp3", genre="Techno (Peak Time)"),
    }
    field, values = _detect_smart_match("Techno", paths, p2t)
    assert field == "GENRE"
    assert "Classic Techno" in values or "Techno (Peak Time)" in values


def test_multi_genre_or_breaks_pattern() -> None:
    """Cas Lorys 'Breaks' : 19 / 5 / 1 sur 3 genres distincts."""
    paths = [f"{i}.mp3" for i in range(25)]
    p2t = {}
    for i, p in enumerate(paths):
        if i < 19:
            p2t[p] = _track(p, genre="Breaks / Breakbeat / UK Bass")
        elif i < 24:
            p2t[p] = _track(p, genre="Breaks")
        else:
            p2t[p] = _track(p, genre="Drum & Bass")
    field, values = _detect_smart_match("Breaks", paths, p2t)
    assert field == "GENRE"
    # Top 2 genres atteint deja 96 %, le 3eme n'est pas necessairement inclus
    assert "Breaks / Breakbeat / UK Bass" in values
    assert "Breaks" in values


def test_genre_below_threshold_falls_through() -> None:
    """Genre top fournit 60 %, on ne s'arrete pas la (cherche autre dimension)."""
    paths = [f"{i}.mp3" for i in range(10)]
    p2t = {}
    for i, p in enumerate(paths):
        # 6 tracks "Tech House", 4 "Disco" — mais nom playlist matche pas non plus
        if i < 6:
            p2t[p] = _track(p, genre="Tech House", artist="DJ Random")
        else:
            p2t[p] = _track(p, genre="Disco", artist="DJ Random")
    # Nom playlist sans rapport avec genre / artist
    assert _detect_smart_match("Foobar", paths, p2t) is None


def test_genre_anti_false_positive() -> None:
    """Si les top genres ne matchent pas le nom de la playlist, pas de smart."""
    paths = ["a.mp3", "b.mp3", "c.mp3"]
    p2t = {p: _track(p, genre="Funk / Soul / Disco") for p in paths}
    # Nom playlist "Funky House" n'est pas substring de "Funk / Soul / Disco"
    assert _detect_smart_match("Funky House", paths, p2t) is None


# -----------------------------------------------------------------------------
# Strategie 2 : Artist OR
# -----------------------------------------------------------------------------

def test_single_artist_match() -> None:
    paths = [f"{i}.mp3" for i in range(5)]
    p2t = {p: _track(p, artist="Sebastien Leger") for p in paths}
    field, values = _detect_smart_match("Sebastien Leger", paths, p2t)
    assert field == "ARTIST"
    assert "Sebastien Leger" in values


def test_artist_partial_match_collab() -> None:
    """Cas Lorys : '=Sebastien Leger' OR 'contient Sebastien Leger' (avec featuring)."""
    paths = ["a.mp3", "b.mp3", "c.mp3"]
    p2t = {
        "a.mp3": _track("a.mp3", artist="Sebastien Leger"),
        "b.mp3": _track("b.mp3", artist="Sebastien Leger"),
        "c.mp3": _track("c.mp3", artist="Sebastien Leger, Sian Evans, Cypherpunx"),
    }
    field, values = _detect_smart_match("Sebastien Leger", paths, p2t)
    assert field == "ARTIST"


# -----------------------------------------------------------------------------
# Strategie 3 : Comment-tag
# -----------------------------------------------------------------------------

def test_comment_tag_match() -> None:
    """Cas Lorys 'Soft Track' : >=95 % des tracks ont 'Soft' dans Comment."""
    paths = [f"{i}.mp3" for i in range(5)]
    p2t = {
        paths[0]: _track(paths[0], comment="Energy 6 /* Soft / Voc.L */"),
        paths[1]: _track(paths[1], comment="Soft / Hold-S Sounds"),
        paths[2]: _track(paths[2], comment="Soft / Trancy"),
        paths[3]: _track(paths[3], comment="Soft / Massive"),
        paths[4]: _track(paths[4], comment="Soft / Spacey"),
    }
    field, values = _detect_smart_match("Soft Track", paths, p2t)
    assert field == "COMMENT"
    assert values == ["Soft"]


def test_comment_tag_skips_stoplist() -> None:
    """'Track' est dans la stoplist, on ne match pas dessus."""
    paths = ["a.mp3", "b.mp3"]
    p2t = {
        "a.mp3": _track("a.mp3", comment="Best track ever"),
        "b.mp3": _track("b.mp3", comment="A great track"),
    }
    # Nom = "Track" → tous les comments contiennent "track" mais c'est en stoplist
    assert _detect_smart_match("Track", paths, p2t) is None


# -----------------------------------------------------------------------------
# Cas no-match
# -----------------------------------------------------------------------------

def test_empty_playlist_returns_none() -> None:
    assert _detect_smart_match("Whatever", [], {}) is None


def test_no_genre_no_artist_no_comment_returns_none() -> None:
    paths = ["a.mp3"]
    p2t = {"a.mp3": _track("a.mp3")}
    assert _detect_smart_match("Whatever", paths, p2t) is None


# -----------------------------------------------------------------------------
# Build query
# -----------------------------------------------------------------------------

def test_query_genre_single() -> None:
    assert _build_smartlist_query("GENRE", ["Techno"]) == '$GENRE % "Techno"'


def test_query_genre_with_dash_variant() -> None:
    q = _build_smartlist_query("GENRE", ["Tech-House"])
    assert q == '$GENRE % "Tech-House" | $GENRE % "Tech House"'


def test_query_genre_multi_or() -> None:
    q = _build_smartlist_query("GENRE", ["Breaks", "Drum & Bass"])
    # "Drum & Bass" a un espace, donc une variante tiret est ajoutee
    assert q == (
        '$GENRE % "Breaks" | $GENRE % "Drum & Bass" | $GENRE % "Drum-&-Bass"'
    )


def test_query_artist_no_variant() -> None:
    """Pour ARTIST on ne genere pas de variantes tiret/espace."""
    q = _build_smartlist_query("ARTIST", ["Sebastien-Leger"])
    assert q == '$ARTIST % "Sebastien-Leger"'


def test_query_comment() -> None:
    assert _build_smartlist_query("COMMENT", ["Soft"]) == '$COMMENT % "Soft"'
