"""Tests pour le mapping des tonalites."""

from traktord.utils.keys import (
    classical_to_traktor_key,
    traktor_key_to_camelot,
    traktor_key_to_classical,
)


def test_major_keys():
    assert classical_to_traktor_key("C") == 0
    assert classical_to_traktor_key("D") == 2
    assert classical_to_traktor_key("F#") == 6
    assert classical_to_traktor_key("B") == 11


def test_minor_keys():
    assert classical_to_traktor_key("Am") == 21
    assert classical_to_traktor_key("Cm") == 12
    assert classical_to_traktor_key("F#m") == 18
    assert classical_to_traktor_key("Bm") == 23


def test_enharmonic_variants():
    assert classical_to_traktor_key("Db") == 1
    assert classical_to_traktor_key("C#") == 1
    assert classical_to_traktor_key("Gb") == classical_to_traktor_key("F#")
    assert classical_to_traktor_key("Bbm") == 22
    assert classical_to_traktor_key("A#m") == 22


def test_camelot_notation():
    assert classical_to_traktor_key("8A") == 21  # Am
    assert classical_to_traktor_key("8B") == 0  # C
    assert classical_to_traktor_key("11A") == 18  # F#m


def test_reverse_classical():
    assert traktor_key_to_classical(0) == "C"
    assert traktor_key_to_classical(21) == "Am"
    assert traktor_key_to_classical(6) == "F#"


def test_reverse_camelot():
    assert traktor_key_to_camelot(0) == "8B"
    assert traktor_key_to_camelot(21) == "8A"


def test_empty_and_invalid():
    assert classical_to_traktor_key("") is None
    assert classical_to_traktor_key("XYZ") is None
    assert traktor_key_to_classical(99) == ""


def test_all_24_keys_roundtrip():
    """Verifier que chaque cle 0-23 fait un aller-retour."""
    for i in range(24):
        classical = traktor_key_to_classical(i)
        assert classical != ""
        result = classical_to_traktor_key(classical)
        assert result == i, f"Roundtrip echoue pour {i} -> {classical} -> {result}"
