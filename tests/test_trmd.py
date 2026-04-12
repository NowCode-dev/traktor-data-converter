"""Tests pour le module trmd (serialiseur/deserialiseur PRIV:TRAKTOR4)."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from traktord.utils.coverart import CoverArtImage
from traktord.utils.trmd import (
    CHUNK_HEADER_SIZE,
    DATA_VERSION,
    HDR_VERSION,
    PRIV_OWNER,
    TRMD_VERSION,
    VRSN_VALUE,
    Chunk,
    build_artw_body,
    build_minimal_trmd,
    find_chunk,
    generate_coverid,
    parse_artw_body,
    parse_chunk,
    parse_trmd,
)

# Chemin vers les MP3 Factory Sounds Traktor Pro 4 (pour roundtrip test)
FACTORY_SOUNDS = Path(
    "/Library/Application Support/Native Instruments/Traktor Pro 4/Factory Sounds"
)


# ----------------------------------------------------------------------------
# Chunk serialisation
# ----------------------------------------------------------------------------

class TestChunk:
    """Serialisation/deserialisation de chunks generiques."""

    def test_leaf_chunk_size(self) -> None:
        """Un chunk feuille = 12 bytes header + len(data)."""
        c = Chunk("TEST", version=0, data=b"\x01\x02\x03\x04")
        blob = c.serialize()
        assert len(blob) == CHUNK_HEADER_SIZE + 4
        assert c.total_size == CHUNK_HEADER_SIZE + 4

    def test_fourcc_reversed_on_disk(self) -> None:
        """Le 4CC est byte-reversed dans le blob."""
        c = Chunk("TRMD", data=b"")
        blob = c.serialize()
        assert blob[:4] == b"DMRT"

    def test_length_and_version_le(self) -> None:
        """Length et version sont en little-endian."""
        c = Chunk("TEST", version=42, data=b"\x00" * 100)
        blob = c.serialize()
        length, version = struct.unpack("<II", blob[4:12])
        assert length == 100
        assert version == 42

    def test_container_chunk(self) -> None:
        """Un chunk conteneur serialise ses enfants dans le body."""
        parent = Chunk("PRNT", version=1, children=[
            Chunk("CH_A", data=b"\x01\x02"),
            Chunk("CH_B", data=b"\x03\x04\x05"),
        ])
        blob = parent.serialize()
        # Parent header (12) + child A (12+2) + child B (12+3) = 41
        assert len(blob) == 12 + (12 + 2) + (12 + 3)
        assert parent.total_size == len(blob)

    def test_nested_containers(self) -> None:
        """Conteneurs imbriques sur 3 niveaux."""
        root = Chunk("ROOT", children=[
            Chunk("MID_", children=[
                Chunk("LEAF", data=b"\xff"),
            ]),
        ])
        blob = root.serialize()
        assert len(blob) == 12 + 12 + 12 + 1  # 37

    def test_empty_leaf(self) -> None:
        """Un chunk feuille sans donnees."""
        c = Chunk("EMPT", data=b"")
        blob = c.serialize()
        assert len(blob) == 12
        length = struct.unpack("<I", blob[4:8])[0]
        assert length == 0


# ----------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------

class TestParsing:
    """Parsing de blobs TRMD."""

    def test_parse_leaf(self) -> None:
        c = Chunk("TEST", version=5, data=b"\xAA\xBB")
        blob = c.serialize()
        parsed, end = parse_chunk(blob, 0)
        assert parsed.fourcc == "TEST"
        assert parsed.version == 5
        assert parsed.data == b"\xAA\xBB"
        assert end == len(blob)

    def test_parse_trmd_minimal(self) -> None:
        """Parse un TRMD minimal (HDR_ + DATA vide)."""
        root = Chunk("TRMD", version=2, children=[
            Chunk(" HDR", version=3, children=[
                Chunk("CHKS", data=b"\x00" * 4),
                Chunk("FMOD", data=b"\x00" * 4),
                Chunk("VRSN", data=b"\x00" * 4),
            ]),
            Chunk("DATA", version=20, children=[
                Chunk("ANDB", data=b"\x00" * 4),
            ]),
        ])
        blob = root.serialize()
        parsed = parse_trmd(blob)
        assert parsed.fourcc == "TRMD"
        assert parsed.version == 2
        assert len(parsed.children) == 2
        assert parsed.children[0].fourcc == " HDR"
        assert parsed.children[1].fourcc == "DATA"

    def test_roundtrip_serialise_parse(self) -> None:
        """Serialize -> parse -> re-serialize = identique."""
        root = Chunk("TRMD", version=2, children=[
            Chunk(" HDR", version=3, children=[
                Chunk("CHKS", data=b"\x37\xEC\x84\x00"),
                Chunk("FMOD", data=b"\x0B\x02\xEA\x07"),
                Chunk("VRSN", data=b"\x07\x00\x00\x00"),
            ]),
            Chunk("DATA", version=20, children=[
                Chunk("ANDB", data=b"\x00" * 4),
                Chunk("BITR", data=b"\x36\x77\x04\x00"),
            ]),
        ])
        blob1 = root.serialize()
        parsed = parse_trmd(blob1)
        blob2 = parsed.serialize()
        assert blob1 == blob2

    def test_parse_invalid_root(self) -> None:
        """Erreur si le chunk racine n'est pas TRMD."""
        c = Chunk("NOPE", data=b"hello")
        with pytest.raises(ValueError, match="TRMD"):
            parse_trmd(c.serialize())

    def test_parse_truncated(self) -> None:
        """Erreur si le buffer est tronque."""
        with pytest.raises(ValueError):
            parse_chunk(b"\x00" * 5, 0)

    def test_parse_with_trailing_padding(self) -> None:
        """Le padding apres TRMD est ignore."""
        root = Chunk("TRMD", version=2, children=[
            Chunk(" HDR", version=3, children=[
                Chunk("CHKS", data=b"\x00" * 4),
            ]),
        ])
        blob = root.serialize() + b"\x00" * 180
        parsed = parse_trmd(blob)
        assert parsed.fourcc == "TRMD"


# ----------------------------------------------------------------------------
# find_chunk
# ----------------------------------------------------------------------------

class TestFindChunk:
    def test_find_direct_child(self) -> None:
        root = Chunk("TRMD", children=[
            Chunk("DATA", data=b"hello"),
        ])
        assert find_chunk(root, "DATA") is not None
        assert find_chunk(root, "DATA").data == b"hello"

    def test_find_nested(self) -> None:
        root = Chunk("TRMD", children=[
            Chunk("DATA", children=[
                Chunk("ARTW", data=b"art"),
            ]),
        ])
        result = find_chunk(root, "DATA/ARTW")
        assert result is not None
        assert result.data == b"art"

    def test_find_missing(self) -> None:
        root = Chunk("TRMD", children=[])
        assert find_chunk(root, "DATA/ARTW") is None


# ----------------------------------------------------------------------------
# ARTW body
# ----------------------------------------------------------------------------

class TestArtwBody:
    """Construction et parsing du body ARTW."""

    def test_build_parse_roundtrip(self) -> None:
        """Roundtrip build -> parse."""
        pixels = bytes(range(256)) * 40  # 10240 bytes > 10000
        pixels = pixels[:50 * 50 * 4]  # Exactement 10000 bytes
        image = CoverArtImage(50, 50, pixels)
        coverid = "042/ABCDEFGHIJKLMNOPQRSTUVWXYZ01"

        body = build_artw_body(coverid, image)
        parsed_id, parsed_img = parse_artw_body(body)

        assert parsed_id == coverid
        assert parsed_img.width == 50
        assert parsed_img.height == 50
        assert parsed_img.rgba_pixels == pixels

    def test_artw_body_structure(self) -> None:
        """Verifie la structure binaire exacte du body ARTW."""
        pixels = b"\xFF" * (10 * 10 * 4)
        image = CoverArtImage(10, 10, pixels)
        coverid = "059/1BXRENA13QCHFADF55SXAOJ3IERA"

        body = build_artw_body(coverid, image)

        # Marker
        assert body[0] == 0x08
        # Width 10 LE
        assert struct.unpack("<H", body[1:3])[0] == 10
        # Padding
        assert body[3:5] == b"\x00\x00"
        # Height 10 LE
        assert struct.unpack("<H", body[5:7])[0] == 10
        # Padding
        assert body[7:9] == b"\x00\x00"
        # COVERARTID string length = 32 (PPP/28CHARS)
        assert struct.unpack("<I", body[9:13])[0] == 32
        # COVERARTID UTF-16 LE
        assert body[13 : 13 + 64].decode("utf-16-le") == coverid
        # RGBA bitmap
        assert body[13 + 64 :] == pixels

    def test_artw_body_too_short(self) -> None:
        with pytest.raises(ValueError, match="trop court"):
            parse_artw_body(b"\x08\x00")

    def test_artw_bad_marker(self) -> None:
        body = b"\x07" + b"\x00" * 20
        with pytest.raises(ValueError, match="marker"):
            parse_artw_body(body)


# ----------------------------------------------------------------------------
# generate_coverid
# ----------------------------------------------------------------------------

class TestGenerateCoverId:
    def test_format(self) -> None:
        """Le COVERARTID a le bon format PPP/28CHARS."""
        cid = generate_coverid(b"test image data")
        assert len(cid) == 32  # 3 + 1 + 28
        prefix, name = cid.split("/")
        assert len(prefix) == 3
        assert prefix.isdigit()
        assert len(name) == 28

    def test_deterministic(self) -> None:
        """Meme input = meme output."""
        cid1 = generate_coverid(b"identical data")
        cid2 = generate_coverid(b"identical data")
        assert cid1 == cid2

    def test_different_input_different_id(self) -> None:
        cid1 = generate_coverid(b"image A")
        cid2 = generate_coverid(b"image B")
        assert cid1 != cid2

    def test_valid_ni_alphabet(self) -> None:
        """Tous les caracteres du nom sont dans l'alphabet NI."""
        from traktord.utils.coverart import NI_ALPHABET
        cid = generate_coverid(b"some data")
        _, name = cid.split("/")
        for c in name:
            assert c in NI_ALPHABET, f"Caractere {c!r} pas dans l'alphabet NI"


# ----------------------------------------------------------------------------
# build_minimal_trmd
# ----------------------------------------------------------------------------

class TestBuildMinimalTrmd:
    def test_parseable(self) -> None:
        """Le TRMD minimal est parseable."""
        pixels = bytes(125 * 125 * 4)
        image = CoverArtImage(125, 125, pixels)
        coverid = "042/ABCDEFGHIJKLMNOPQRSTUVWXYZ01"

        blob = build_minimal_trmd(coverid, image)
        root = parse_trmd(blob)

        assert root.fourcc == "TRMD"
        assert root.version == TRMD_VERSION
        assert len(root.children) == 2

        hdr = root.children[0]
        assert hdr.fourcc == " HDR"
        assert hdr.version == HDR_VERSION

        data = root.children[1]
        assert data.fourcc == "DATA"
        assert data.version == DATA_VERSION

    def test_artw_extractable(self) -> None:
        """L'ARTW est lisible dans le TRMD minimal."""
        pixels = bytes(125 * 125 * 4)
        image = CoverArtImage(125, 125, pixels)
        coverid = "042/ABCDEFGHIJKLMNOPQRSTUVWXYZ01"

        blob = build_minimal_trmd(coverid, image)
        root = parse_trmd(blob)
        artw = find_chunk(root, "DATA/ARTW")
        assert artw is not None

        parsed_id, parsed_img = parse_artw_body(artw.data)
        assert parsed_id == coverid
        assert parsed_img.width == 125
        assert parsed_img.height == 125
        assert parsed_img.rgba_pixels == pixels

    def test_vrsn_is_7(self) -> None:
        """VRSN contient la valeur 7 (format v7)."""
        pixels = bytes(10 * 10 * 4)
        image = CoverArtImage(10, 10, pixels)
        blob = build_minimal_trmd("001/AAAAAAAAAAAAAAAAAAAAAAAAAAAA", image)
        root = parse_trmd(blob)
        vrsn = find_chunk(root, " HDR/VRSN")
        assert vrsn is not None
        assert struct.unpack("<I", vrsn.data)[0] == VRSN_VALUE


# ----------------------------------------------------------------------------
# Roundtrip sur de vrais fichiers Traktor Pro 4 (Factory Sounds)
# ----------------------------------------------------------------------------

class TestRealFiles:
    """Tests sur les vrais fichiers Factory Sounds (skip si non disponibles)."""

    @pytest.fixture
    def factory_priv_data(self) -> bytes:
        """Recupere les donnees PRIV:TRAKTOR4 du premier MP3 Factory."""
        if not FACTORY_SOUNDS.exists():
            pytest.skip("Traktor Pro 4 Factory Sounds non disponibles")

        from mutagen.id3 import ID3

        for mp3 in sorted(FACTORY_SOUNDS.glob("*.mp3")):
            tags = ID3(str(mp3))
            for frame in tags.values():
                if frame.FrameID == "PRIV" and getattr(frame, "owner", "") == PRIV_OWNER:
                    return frame.data
            break

        pytest.skip("Pas de frame PRIV:TRAKTOR4 dans les Factory Sounds")

    def test_parse_real_trmd(self, factory_priv_data: bytes) -> None:
        """Parse un vrai TRMD et verifie la structure."""
        root = parse_trmd(factory_priv_data)
        assert root.fourcc == "TRMD"
        assert root.version == TRMD_VERSION
        assert len(root.children) == 2

    def test_roundtrip_real_trmd(self, factory_priv_data: bytes) -> None:
        """Roundtrip bit-perfect sur un vrai TRMD."""
        root = parse_trmd(factory_priv_data)
        reserialized = root.serialize()
        # Comparer uniquement la partie TRMD (sans padding)
        original_trmd = factory_priv_data[: root.total_size]
        assert reserialized == original_trmd

    def test_read_real_artw(self, factory_priv_data: bytes) -> None:
        """Lit l'ARTW d'un vrai fichier."""
        root = parse_trmd(factory_priv_data)
        artw = find_chunk(root, "DATA/ARTW")
        assert artw is not None

        coverid, image = parse_artw_body(artw.data)
        assert image.width == 125
        assert image.height == 125
        assert "/" in coverid
        assert len(coverid) == 32

    def test_real_vrsn_value(self, factory_priv_data: bytes) -> None:
        """VRSN contient la bonne valeur dans le fichier reel."""
        root = parse_trmd(factory_priv_data)
        vrsn = find_chunk(root, " HDR/VRSN")
        assert vrsn is not None
        val = struct.unpack("<I", vrsn.data)[0]
        assert val == VRSN_VALUE
