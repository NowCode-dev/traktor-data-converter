"""Tests pour la conversion des chemins de fichiers."""

from traktord.utils.paths import (
    file_path_to_traktor_location,
    rekordbox_uri_to_file_path,
    traktor_location_to_file_path,
)


def test_rekordbox_uri_macos():
    uri = "file://localhost/Users/lorys/Music/DJ/track.mp3"
    assert rekordbox_uri_to_file_path(uri) == "/Users/lorys/Music/DJ/track.mp3"


def test_rekordbox_uri_windows():
    uri = "file://localhost/C:/Users/lorys/Music/track.mp3"
    assert rekordbox_uri_to_file_path(uri) == "C:/Users/lorys/Music/track.mp3"


def test_rekordbox_uri_encoded():
    uri = "file://localhost/Users/lorys/Music/Caf%C3%A9%20Del%20Mar.mp3"
    assert rekordbox_uri_to_file_path(uri) == "/Users/lorys/Music/Café Del Mar.mp3"


def test_traktor_location_macos():
    loc = file_path_to_traktor_location("/Users/lorys/Music/DJ/track.mp3")
    assert loc["DIR"] == "/:Users/:lorys/:Music/:DJ/:"
    assert loc["FILE"] == "track.mp3"


def test_traktor_location_windows():
    loc = file_path_to_traktor_location("C:/Users/lorys/Music/track.mp3")
    assert loc["VOLUME"] == "C:"
    assert loc["DIR"] == "/:Users/:lorys/:Music/:"
    assert loc["FILE"] == "track.mp3"


def test_traktor_location_roundtrip():
    original = "/Users/lorys/Music/DJ/track.mp3"
    loc = file_path_to_traktor_location(original)
    restored = traktor_location_to_file_path(loc["VOLUME"], loc["DIR"], loc["FILE"])
    assert restored == original


def test_traktor_location_roundtrip_windows():
    original = "C:/Users/lorys/Music/track.mp3"
    loc = file_path_to_traktor_location(original)
    restored = traktor_location_to_file_path(loc["VOLUME"], loc["DIR"], loc["FILE"])
    assert restored == original
