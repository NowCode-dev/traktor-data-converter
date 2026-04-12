"""Tests pour le module coverart (encodage/decodage du cache Traktor)."""

import pytest

from traktord.utils.coverart import (
    HEADER_MARKER,
    HEADER_SIZE,
    NI_ALPHABET,
    CoverArtImage,
    decode_coverart,
    decode_ni_b32,
    encode_coverart,
    encode_ni_b32,
    parse_coverid,
)


# ----------------------------------------------------------------------------
# Base32 NI custom
# ----------------------------------------------------------------------------

class TestNIBase32:
    """Encodage/decodage de l'alphabet Base32 NI custom."""

    def test_alphabet_has_32_chars(self) -> None:
        assert len(NI_ALPHABET) == 32

    def test_alphabet_no_678_9(self) -> None:
        # Specificite NI : pas de 6, 7, 8, 9
        assert "6" not in NI_ALPHABET
        assert "7" not in NI_ALPHABET
        assert "8" not in NI_ALPHABET
        assert "9" not in NI_ALPHABET

    def test_alphabet_chars(self) -> None:
        # 6 chiffres + 26 lettres
        digits = [c for c in NI_ALPHABET if c.isdigit()]
        letters = [c for c in NI_ALPHABET if c.isalpha()]
        assert len(digits) == 6
        assert len(letters) == 26

    def test_decode_known_value(self) -> None:
        # Valeur observee dans un vrai NML Traktor 3
        result = decode_ni_b32("1BXRENA13QCHFADF55SXAOJ3IERA")
        assert result.hex() == "09fb754cc11d90d5992b2971d351e372ae60"

    def test_encode_decode_roundtrip(self) -> None:
        for s in [
            "1BXRENA13QCHFADF55SXAOJ3IERA",
            "DY5TP3AVEDNTED41UT5UAHRJTS4D",
            "GMH14EBOZODSEAIUGNRQD2AOZ3RC",
        ]:
            decoded = decode_ni_b32(s)
            re_encoded = encode_ni_b32(decoded, length=28)
            assert re_encoded == s, f"Roundtrip failed for {s}"

    def test_decode_invalid_char_raises(self) -> None:
        # Le 6 n'est pas dans l'alphabet
        with pytest.raises(ValueError, match="invalide"):
            decode_ni_b32("6BXRENA13QCHFADF55SXAOJ3IERA")


# ----------------------------------------------------------------------------
# Format binaire du fichier cache
# ----------------------------------------------------------------------------

class TestCoverArtBinary:
    """Encodage/decodage du format binaire du cache."""

    def test_header_constants(self) -> None:
        assert HEADER_MARKER == 0x08
        assert HEADER_SIZE == 9

    def test_encode_125x125(self) -> None:
        # Image vide 125x125 RGBA -> 62509 bytes
        pixels = bytes(125 * 125 * 4)
        img = CoverArtImage(125, 125, pixels)
        encoded = encode_coverart(img)
        assert len(encoded) == 62509
        # Header
        assert encoded[0] == 0x08
        # width LE
        assert encoded[1] == 0x7D and encoded[2] == 0x00
        # padding
        assert encoded[3:5] == b"\x00\x00"
        # height LE
        assert encoded[5] == 0x7D and encoded[6] == 0x00
        assert encoded[7:9] == b"\x00\x00"

    def test_decode_known_size(self) -> None:
        # Tailles attendues pour les 3 resolutions Traktor 4
        for w, h, expected_size in [(125, 125, 62509), (75, 75, 22509), (56, 56, 12553)]:
            pixels = bytes(w * h * 4)
            img = CoverArtImage(w, h, pixels)
            assert img.encoded_size == expected_size
            data = encode_coverart(img)
            decoded = decode_coverart(data)
            assert decoded.width == w
            assert decoded.height == h
            assert decoded.rgba_pixels == pixels

    def test_decode_rectangular(self) -> None:
        # Traktor 3 stocke des images rectangulaires (159x125 par exemple)
        pixels = bytes(159 * 125 * 4)
        img = CoverArtImage(159, 125, pixels)
        data = encode_coverart(img)
        assert len(data) == 9 + 159 * 125 * 4
        decoded = decode_coverart(data)
        assert decoded.width == 159
        assert decoded.height == 125

    def test_decode_invalid_marker(self) -> None:
        bad_data = bytes([0x07]) + bytes(8) + bytes(125 * 125 * 4)
        with pytest.raises(ValueError, match="Marker"):
            decode_coverart(bad_data)

    def test_decode_size_mismatch(self) -> None:
        # Header dit 125x125 mais on donne moins de pixels
        header = bytes([0x08, 0x7D, 0x00, 0x00, 0x00, 0x7D, 0x00, 0x00, 0x00])
        bad = header + bytes(100)  # pas assez
        with pytest.raises(ValueError, match="incoherente"):
            decode_coverart(bad)

    def test_decode_too_short(self) -> None:
        with pytest.raises(ValueError, match="trop court"):
            decode_coverart(b"\x08\x00")


# ----------------------------------------------------------------------------
# Parsing du COVERARTID
# ----------------------------------------------------------------------------

class TestParseCoverID:
    def test_valid_coverid(self) -> None:
        prefix, name = parse_coverid("059/1BXRENA13QCHFADF55SXAOJ3IERA")
        assert prefix == "059"
        assert name == "1BXRENA13QCHFADF55SXAOJ3IERA"

    def test_missing_slash(self) -> None:
        with pytest.raises(ValueError, match="invalide"):
            parse_coverid("0591BXRENA13QCHFADF55SXAOJ3IERA")

    def test_wrong_prefix_length(self) -> None:
        with pytest.raises(ValueError, match="Prefix"):
            parse_coverid("59/1BXRENA13QCHFADF55SXAOJ3IERA")

    def test_non_digit_prefix(self) -> None:
        with pytest.raises(ValueError, match="Prefix"):
            parse_coverid("ABC/1BXRENA13QCHFADF55SXAOJ3IERA")

    def test_wrong_name_length(self) -> None:
        with pytest.raises(ValueError, match="Name"):
            parse_coverid("059/SHORT")

    def test_invalid_char_in_name(self) -> None:
        # Le 6 n'est pas dans l'alphabet
        with pytest.raises(ValueError, match="invalide"):
            parse_coverid("059/6BXRENA13QCHFADF55SXAOJ3IERA")
