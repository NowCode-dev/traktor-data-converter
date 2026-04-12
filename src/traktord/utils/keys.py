"""Mapping des tonalites musicales entre formats DJ.

Traktor : entier 0-23 (MUSICAL_KEY VALUE)
Rekordbox : notation classique ("Am", "Db", "F#m")
Camelot : "8A", "11B"
Open Key : "1m", "4d"
"""

from __future__ import annotations

# Mapping complet : index = MUSICAL_KEY VALUE (0-23)
# (classique, camelot, open_key)
KEY_TABLE: list[tuple[str, str, str]] = [
    # Majeurs (0-11)
    ("C", "8B", "1d"),
    ("Db", "3B", "8d"),
    ("D", "10B", "3d"),
    ("Eb", "5B", "10d"),
    ("E", "12B", "5d"),
    ("F", "7B", "12d"),
    ("F#", "2B", "7d"),
    ("G", "9B", "2d"),
    ("Ab", "4B", "9d"),
    ("A", "11B", "4d"),
    ("Bb", "6B", "11d"),
    ("B", "1B", "6d"),
    # Mineurs (12-23)
    ("Cm", "5A", "10m"),
    ("C#m", "12A", "5m"),
    ("Dm", "7A", "12m"),
    ("Ebm", "2A", "7m"),
    ("Em", "9A", "2m"),
    ("Fm", "4A", "9m"),
    ("F#m", "11A", "4m"),
    ("Gm", "6A", "11m"),
    ("G#m", "1A", "6m"),
    ("Am", "8A", "1m"),
    ("Bbm", "3A", "8m"),
    ("Bm", "10A", "3m"),
]

# Variantes enharmoniques : diese ↔ bemol
_ENHARMONIC: dict[str, str] = {
    "C#": "Db",
    "D#": "Eb",
    "Fb": "E",
    "E#": "F",
    "Gb": "F#",
    "G#": "Ab",
    "A#": "Bb",
    "Cb": "B",
    "Dbm": "C#m",
    "D#m": "Ebm",
    "Gbm": "F#m",
    "Abm": "G#m",
    "A#m": "Bbm",
}

# Construire les lookups inverses
_CLASSICAL_TO_INT: dict[str, int] = {}
_CAMELOT_TO_INT: dict[str, int] = {}
_OPENKEY_TO_INT: dict[str, int] = {}

for i, (classical, camelot, openkey) in enumerate(KEY_TABLE):
    _CLASSICAL_TO_INT[classical] = i
    _CAMELOT_TO_INT[camelot] = i
    _OPENKEY_TO_INT[openkey] = i

# Ajouter les variantes enharmoniques
for variant, canonical in _ENHARMONIC.items():
    if canonical in _CLASSICAL_TO_INT:
        _CLASSICAL_TO_INT[variant] = _CLASSICAL_TO_INT[canonical]


def classical_to_traktor_key(tonality: str) -> int | None:
    """Convertir une notation classique (Am, Db, F#m) vers un entier Traktor 0-23."""
    if not tonality:
        return None
    tonality = tonality.strip()
    # Essayer notation classique directe
    if tonality in _CLASSICAL_TO_INT:
        return _CLASSICAL_TO_INT[tonality]
    # Essayer Camelot (Mixed In Key ecrit parfois dans le champ Tonality)
    if tonality.upper() in _CAMELOT_TO_INT:
        return _CAMELOT_TO_INT[tonality.upper()]
    # Essayer Open Key
    if tonality.lower() in _OPENKEY_TO_INT:
        return _OPENKEY_TO_INT[tonality.lower()]
    return None


def traktor_key_to_classical(value: int) -> str:
    """Convertir un entier Traktor 0-23 vers la notation classique."""
    if 0 <= value < len(KEY_TABLE):
        return KEY_TABLE[value][0]
    return ""


def traktor_key_to_camelot(value: int) -> str:
    """Convertir un entier Traktor 0-23 vers la notation Camelot."""
    if 0 <= value < len(KEY_TABLE):
        return KEY_TABLE[value][1]
    return ""
