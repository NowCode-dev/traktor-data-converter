"""Tests pour le parser Rekordbox XML."""

import os

from traktord.parsers.rekordbox import RekordboxParser

SAMPLE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "samples", "rekordbox_sample.xml"
)


def test_parse_collection():
    parser = RekordboxParser()
    collection = parser.parse(SAMPLE_PATH)
    assert len(collection.tracks) == 3
    assert collection.source_format == "rekordbox"


def test_parse_track_metadata():
    parser = RekordboxParser()
    collection = parser.parse(SAMPLE_PATH)
    track = collection.tracks[0]  # Strobe

    assert track.title == "Strobe"
    assert track.artist == "Deadmau5"
    assert track.album == "For Lack of a Better Name"
    assert track.genre == "Progressive House"
    assert track.bpm == 128.0
    assert track.key == "Am"
    assert track.rating == 5  # 255 / 51 = 5
    assert track.play_count == 12
    assert track.label == "Mau5trap"
    assert track.year == 2009
    assert track.date_added == "2024-01-15"


def test_parse_cue_points():
    parser = RekordboxParser()
    collection = parser.parse(SAMPLE_PATH)
    track = collection.tracks[0]  # Strobe

    assert len(track.cue_points) == 5

    # Premier cue : "Intro" hot cue A
    cue0 = track.cue_points[0]
    assert cue0.name == "Intro"
    assert cue0.type == "cue"
    assert cue0.position_ms == 500.0
    assert cue0.hotcue == 0
    assert cue0.green == 226

    # Loop
    loop = track.cue_points[3]
    assert loop.type == "loop"
    assert loop.position_ms == 240500.0
    assert loop.length_ms == 15000.0  # (255.5 - 240.5) * 1000
    assert loop.hotcue == 3

    # Memory cue (Num=-1)
    memory = track.cue_points[4]
    assert memory.hotcue == -1


def test_parse_beatgrid():
    parser = RekordboxParser()
    collection = parser.parse(SAMPLE_PATH)
    track = collection.tracks[0]  # Strobe

    assert track.grid_offset_ms == 35.0  # 0.035 * 1000


def test_parse_file_path():
    parser = RekordboxParser()
    collection = parser.parse(SAMPLE_PATH)

    # macOS path
    track1 = collection.tracks[0]
    assert track1.file_path == "/Users/lorys/Music/DJ/Deadmau5 - Strobe.mp3"
    assert track1.file_type == "mp3"

    # Windows path
    track3 = collection.tracks[2]
    assert track3.file_path == "C:/Users/lorys/Music/DJ/Energy 52 - Cafe Del Mar.flac"


def test_parse_playlists():
    parser = RekordboxParser()
    collection = parser.parse(SAMPLE_PATH)

    assert "Favorites" in collection.playlists
    assert len(collection.playlists["Favorites"]) == 2

    assert "Sets/Summer 2024" in collection.playlists
    assert len(collection.playlists["Sets/Summer 2024"]) == 3
