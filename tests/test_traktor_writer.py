"""Tests pour le writer Traktor NML — valide contre le format reel."""

import os
import tempfile

from lxml import etree

from traktord.converters.traktor import TraktorWriter
from traktord.parsers.rekordbox import RekordboxParser

SAMPLE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "traktord-data", "samples", "rekordbox_sample.xml"
)


def _parse_and_write() -> etree._Element:
    """Helper : parser le sample RB, ecrire en NML, retourner le XML parse."""
    parser = RekordboxParser()
    collection = parser.parse(SAMPLE_PATH)

    writer = TraktorWriter()
    with tempfile.NamedTemporaryFile(suffix=".nml", delete=False) as f:
        output_path = f.name

    try:
        writer.write(collection, output_path)
        tree = etree.parse(output_path)
        return tree.getroot()
    finally:
        os.unlink(output_path)


def test_nml_root_structure():
    root = _parse_and_write()
    assert root.tag == "NML"
    assert root.get("VERSION") == "19"
    assert root.find("HEAD") is not None
    assert root.find("COLLECTION") is not None
    assert root.find("SETS") is not None


def test_nml_head():
    root = _parse_and_write()
    head = root.find("HEAD")
    assert head.get("COMPANY") == "www.native-instruments.com"
    assert head.get("PROGRAM") == "Traktor"


def test_nml_sets():
    root = _parse_and_write()
    sets = root.find("SETS")
    assert sets.get("ENTRIES") == "0"


def test_nml_collection_count():
    root = _parse_and_write()
    collection = root.find("COLLECTION")
    assert collection.get("ENTRIES") == "3"
    entries = collection.findall("ENTRY")
    assert len(entries) == 3


def test_nml_entry_metadata():
    root = _parse_and_write()
    entry = root.find("COLLECTION/ENTRY")
    assert entry.get("TITLE") == "Strobe"
    assert entry.get("ARTIST") == "Deadmau5"


def test_nml_modification_info():
    root = _parse_and_write()
    mod_info = root.find("COLLECTION/ENTRY/MODIFICATION_INFO")
    assert mod_info is not None
    assert mod_info.get("AUTHOR_TYPE") == "user"


def test_nml_location():
    root = _parse_and_write()
    loc = root.find("COLLECTION/ENTRY/LOCATION")
    assert loc is not None
    assert loc.get("FILE") == "Deadmau5 - Strobe.mp3"
    assert "/:Users/:lorys/:Music/:DJ/:" in loc.get("DIR", "")


def test_nml_tempo():
    root = _parse_and_write()
    tempo = root.find("COLLECTION/ENTRY/TEMPO")
    assert tempo is not None
    assert tempo.get("BPM") == "128.000000"
    assert tempo.get("BPM_QUALITY") == "100.000000"


def test_nml_musical_key():
    root = _parse_and_write()
    key = root.find("COLLECTION/ENTRY/MUSICAL_KEY")
    assert key is not None
    assert key.get("VALUE") == "21"  # Am = 21


def test_nml_cue_points():
    root = _parse_and_write()
    entry = root.find("COLLECTION/ENTRY")
    cues = entry.findall("CUE_V2")
    # 5 cue points + 1 AutoGrid = 6
    assert len(cues) >= 5

    # AutoGrid (TYPE=4)
    autogrid = [c for c in cues if c.get("TYPE") == "4"]
    assert len(autogrid) == 1
    assert autogrid[0].get("NAME") == "AutoGrid"
    assert float(autogrid[0].get("START", "0")) == 35.0

    # Hot cue
    hotcues = [c for c in cues if c.get("TYPE") == "0" and c.get("HOTCUE") == "0"]
    assert len(hotcues) >= 1

    # Loop (TYPE=5)
    loops = [c for c in cues if c.get("TYPE") == "5"]
    assert len(loops) == 1
    assert float(loops[0].get("LEN", "0")) == 15000.0


def test_nml_info_element():
    root = _parse_and_write()
    info = root.find("COLLECTION/ENTRY/INFO")
    assert info is not None
    assert info.get("GENRE") == "Progressive House"
    assert info.get("LABEL") == "Mau5trap"
    assert info.get("COMMENT") == "Classic track"
    # Bitrate en bps
    assert info.get("BITRATE") == "320000"
    # FILESIZE en KB (15432000 bytes / 1024 = 15070)
    assert info.get("FILESIZE") == "15070"
    assert info.get("FLAGS") == "8"


def test_nml_playlist_structure():
    """Verifier la structure NODE > PLAYLIST conforme au format Traktor."""
    root = _parse_and_write()
    playlists = root.find("PLAYLISTS")
    assert playlists is not None

    # Racine $ROOT
    root_node = playlists.find("NODE")
    assert root_node.get("TYPE") == "FOLDER"
    assert root_node.get("NAME") == "$ROOT"

    # SUBNODES
    subnodes = root_node.find("SUBNODES")
    assert subnodes is not None
    count = int(subnodes.get("COUNT", "0"))
    assert count > 0

    # Trouver une playlist
    playlist_nodes = subnodes.findall(".//NODE[@TYPE='PLAYLIST']")
    assert len(playlist_nodes) > 0

    # Verifier la structure NODE TYPE="PLAYLIST" > PLAYLIST TYPE="LIST"
    pnode = playlist_nodes[0]
    assert pnode.get("TYPE") == "PLAYLIST"
    assert pnode.get("NAME") != ""

    playlist_inner = pnode.find("PLAYLIST")
    assert playlist_inner is not None
    assert playlist_inner.get("TYPE") == "LIST"
    assert playlist_inner.get("UUID") is not None
    assert len(playlist_inner.get("UUID", "")) == 32

    entries = playlist_inner.findall("ENTRY")
    assert int(playlist_inner.get("ENTRIES", "0")) == len(entries)

    # Verifier PRIMARYKEY
    pk = entries[0].find("PRIMARYKEY")
    assert pk.get("TYPE") == "TRACK"
    assert pk.get("KEY") != ""


def test_nml_folder_grouping():
    """Verifier que les playlists dans un meme dossier sont groupees."""
    root = _parse_and_write()
    subnodes = root.find("PLAYLISTS/NODE/SUBNODES")

    # On doit avoir "Favorites" (playlist) et "Sets" (dossier), pas de doublons
    nodes = subnodes.findall("NODE")
    names = [n.get("NAME") for n in nodes]
    assert len(names) == len(set(names)), f"Doublons detectes : {names}"
