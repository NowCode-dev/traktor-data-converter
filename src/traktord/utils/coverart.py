"""Encodeur/decodeur du cache d'artwork Traktor (Native Instruments).

Format binaire reverse-engineere depuis Traktor 3.11 et 4.4.2.

Structure d'un fichier cache (sans extension) :

    Offset  Size  Description
    ------  ----  -----------------------------------------------
    0       1     marker = 0x08 (probablement "8 bits par canal")
    1       2     width  (uint16 little-endian)
    3       2     0x0000
    5       2     height (uint16 little-endian)
    7       2     0x0000
    9       w*h*4 pixel data RGBA (4 bytes par pixel)

Trois resolutions sont stockees pour chaque artwork, suffixees au
nom de fichier :

    XXX/<NAME>000  -> resolution principale (Traktor 3 = ratio
                      d'origine, Traktor 4 = 125x125 carre force)
    XXX/<NAME>001  -> 75x75 carre
    XXX/<NAME>002  -> 56x56 carre

Le nom de fichier complet est de la forme `<prefix>/<name>` ou :
    - prefix : 3 chiffres decimaux ("003", "059", ...)
    - name   : 28 caracteres en Base32 custom NI (140 bits utiles)

L'alphabet Base32 NI utilise 32 caracteres differents du Base32
standard (RFC 4648) : 6 chiffres (0-5) + 26 lettres majuscules.
Les chiffres 6-9 sont absents.

L'algorithme exact qui transforme une image source en COVERARTID
est en cours de reverse-engineering. Ce module fournit l'encodage
binaire du cache, le decodeur Base32 NI, et la generation des 3
resolutions a partir d'une image PIL.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

# ----------------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------------

#: Marker du header (probablement "8 bits par canal")
HEADER_MARKER = 0x08

#: Taille du header en bytes
HEADER_SIZE = 9

#: Resolutions stockees par Traktor 4 (carre force)
T4_RESOLUTIONS = (125, 75, 56)

#: Resolutions stockees par Traktor 3 :
#: - 000 conserve le ratio d'origine (longueur max ~125-200 px)
#: - 001 et 002 sont carres
T3_RESOLUTION_001 = 75
T3_RESOLUTION_002 = 56

#: Alphabet Base32 custom Native Instruments.
#: 32 caracteres : 6 chiffres (0-5) puis 26 lettres majuscules.
#: Les chiffres 6, 7, 8, 9 sont absents.
NI_ALPHABET = "012345ABCDEFGHIJKLMNOPQRSTUVWXYZ"

#: Index inverse pour le decodage
_NI_DECODE = {c: i for i, c in enumerate(NI_ALPHABET)}


# ----------------------------------------------------------------------------
# Encodage / decodage du nom de fichier (Base32 NI custom)
# ----------------------------------------------------------------------------

def encode_ni_b32(data: bytes, length: int = 28) -> str:
    """Encode des bytes en Base32 NI custom (140 bits = 28 caracteres).

    Args:
        data: Bytes a encoder. Au moins 18 bytes (140 bits) sont consommes.
        length: Nombre de caracteres en sortie (default 28 = 140 bits).

    Returns:
        Chaine de `length` caracteres dans l'alphabet NI.
    """
    bits = 0
    nbits = 0
    out = []
    for b in data:
        bits = (bits << 8) | b
        nbits += 8
        while nbits >= 5 and len(out) < length:
            nbits -= 5
            out.append(NI_ALPHABET[(bits >> nbits) & 0x1F])
        if len(out) >= length:
            break
    # Si pas assez de bytes pour remplir, completer avec des zeros
    while len(out) < length:
        if nbits > 0:
            shift = 5 - nbits
            out.append(NI_ALPHABET[(bits << shift) & 0x1F])
            nbits = 0
        else:
            out.append(NI_ALPHABET[0])
    return "".join(out)


def decode_ni_b32(s: str) -> bytes:
    """Decode une chaine Base32 NI custom en bytes.

    Args:
        s: Chaine dans l'alphabet NI (typiquement 28 caracteres).

    Returns:
        Bytes decodes. Pour 28 chars en entree (140 bits), retourne
        18 bytes (le dernier byte n'a que 4 bits significatifs).

    Raises:
        ValueError: si un caractere n'est pas dans l'alphabet NI.
    """
    bits = 0
    nbits = 0
    out = bytearray()
    for c in s:
        if c not in _NI_DECODE:
            raise ValueError(f"Caractere invalide dans l'alphabet NI : {c!r}")
        bits = (bits << 5) | _NI_DECODE[c]
        nbits += 5
        while nbits >= 8:
            nbits -= 8
            out.append((bits >> nbits) & 0xFF)
    if nbits > 0:
        out.append((bits << (8 - nbits)) & 0xFF)
    return bytes(out)


# ----------------------------------------------------------------------------
# Format binaire du fichier cache
# ----------------------------------------------------------------------------

@dataclass
class CoverArtImage:
    """Une image dans le cache Traktor."""

    width: int
    height: int
    rgba_pixels: bytes  # width * height * 4 bytes RGBA

    def __post_init__(self) -> None:
        expected = self.width * self.height * 4
        if len(self.rgba_pixels) != expected:
            raise ValueError(
                f"Taille pixel data incoherente : {len(self.rgba_pixels)} "
                f"vs attendu {expected} ({self.width}x{self.height} RGBA)"
            )

    @property
    def encoded_size(self) -> int:
        """Taille du fichier cache encode en bytes."""
        return HEADER_SIZE + len(self.rgba_pixels)


def _swap_rb_channels(rgba: bytes) -> bytes:
    """Swap les channels R et B (RGBA <-> BGRA).

    Le format pixel sur disque attendu par Traktor 4 est BGRA. Notre representation
    en memoire est RGBA (cf. PIL). On swap au moment de l'ecriture/lecture du cache
    pour rester coherent en interne tout en produisant un cache lisible par Traktor.
    """
    ba = bytearray(rgba)
    for i in range(0, len(ba), 4):
        ba[i], ba[i + 2] = ba[i + 2], ba[i]
    return bytes(ba)


def encode_coverart(image: CoverArtImage) -> bytes:
    """Encode une image dans le format binaire du cache Traktor.

    L'image est stockee sur disque en BGRA (ordre attendu par Traktor 4).
    Notre representation interne `rgba_pixels` est en RGBA, on swap R<->B
    avant l'ecriture.

    Args:
        image: L'image source avec ses pixels RGBA en memoire.

    Returns:
        Bytes du fichier cache (header 9 bytes + pixels BGRA).
    """
    header = struct.pack(
        "<BHHHH",
        HEADER_MARKER,
        image.width,
        0x0000,
        image.height,
        0x0000,
    )
    return header + _swap_rb_channels(image.rgba_pixels)


def decode_coverart(data: bytes) -> CoverArtImage:
    """Decode un fichier cache Traktor en image RGBA.

    Le cache sur disque est en BGRA, on swap R<->B au decodage pour
    fournir des pixels RGBA en memoire (compatibles PIL).

    Args:
        data: Bytes du fichier cache.

    Returns:
        CoverArtImage avec width, height, et pixels RGBA en memoire.

    Raises:
        ValueError: si le format est invalide.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError(f"Fichier trop court : {len(data)} bytes")
    marker, width, pad1, height, pad2 = struct.unpack("<BHHHH", data[:HEADER_SIZE])
    if marker != HEADER_MARKER:
        raise ValueError(f"Marker invalide : 0x{marker:02x} (attendu 0x{HEADER_MARKER:02x})")
    if pad1 != 0 or pad2 != 0:
        raise ValueError(f"Padding non nul : pad1=0x{pad1:04x} pad2=0x{pad2:04x}")
    expected = HEADER_SIZE + width * height * 4
    if len(data) != expected:
        raise ValueError(
            f"Taille incoherente : {len(data)} bytes pour {width}x{height} "
            f"(attendu {expected})"
        )
    return CoverArtImage(
        width=width,
        height=height,
        rgba_pixels=_swap_rb_channels(data[HEADER_SIZE:]),
    )


# ----------------------------------------------------------------------------
# Generation des 3 resolutions a partir d'une image source
# ----------------------------------------------------------------------------

def generate_coverart_resolutions_t4(
    source_image_bytes: bytes,
) -> tuple[CoverArtImage, CoverArtImage, CoverArtImage]:
    """Genere les 3 resolutions Traktor 4 (toutes carrees) depuis une image source.

    Args:
        source_image_bytes: Bytes de l'image source (JPEG, PNG, etc.) — typiquement
            le contenu d'une frame APIC ID3.

    Returns:
        Tuple de 3 CoverArtImage (125x125, 75x75, 56x56) en RGBA.

    Raises:
        ImportError: si Pillow n'est pas installe.
        ValueError: si l'image source est illisible.
    """
    try:
        from PIL import Image
    except ImportError as e:
        raise ImportError("Pillow est requis pour generer les resolutions") from e

    src = Image.open(BytesIO(source_image_bytes)).convert("RGBA")
    out = []
    for size in T4_RESOLUTIONS:
        img = src.resize((size, size), Image.LANCZOS)
        out.append(CoverArtImage(width=size, height=size, rgba_pixels=img.tobytes()))
    return tuple(out)  # type: ignore[return-value]


def generate_coverart_resolutions_t3(
    source_image_bytes: bytes,
    primary_max_dimension: int = 125,
) -> tuple[CoverArtImage, CoverArtImage, CoverArtImage]:
    """Genere les 3 resolutions Traktor 3 depuis une image source.

    Comme Traktor 3, la resolution principale (000) preserve le ratio
    d'origine, redimensionnee pour que sa plus grande dimension soit
    `primary_max_dimension`. Les deux autres resolutions sont des carres.

    Args:
        source_image_bytes: Bytes de l'image source (JPEG, PNG, etc.).
        primary_max_dimension: Dimension max (largeur ou hauteur) pour
            la resolution 000. Default 125.

    Returns:
        Tuple de 3 CoverArtImage : (000=ratio preserve, 001=75x75, 002=56x56).
    """
    try:
        from PIL import Image
    except ImportError as e:
        raise ImportError("Pillow est requis pour generer les resolutions") from e

    src = Image.open(BytesIO(source_image_bytes)).convert("RGBA")
    w, h = src.size

    # 000 : ratio d'origine, plus grande dimension = primary_max_dimension
    if w >= h:
        new_w = primary_max_dimension
        new_h = max(1, round(h * primary_max_dimension / w))
    else:
        new_h = primary_max_dimension
        new_w = max(1, round(w * primary_max_dimension / h))
    img_000 = src.resize((new_w, new_h), Image.LANCZOS)

    img_001 = src.resize((T3_RESOLUTION_001, T3_RESOLUTION_001), Image.LANCZOS)
    img_002 = src.resize((T3_RESOLUTION_002, T3_RESOLUTION_002), Image.LANCZOS)

    return (
        CoverArtImage(new_w, new_h, img_000.tobytes()),
        CoverArtImage(T3_RESOLUTION_001, T3_RESOLUTION_001, img_001.tobytes()),
        CoverArtImage(T3_RESOLUTION_002, T3_RESOLUTION_002, img_002.tobytes()),
    )


# ----------------------------------------------------------------------------
# Helpers d'ecriture vers le dossier Coverart
# ----------------------------------------------------------------------------

def write_coverart_files(
    coverart_dir: Path,
    coverid: str,
    resolutions: tuple[CoverArtImage, CoverArtImage, CoverArtImage],
) -> tuple[Path, Path, Path]:
    """Ecrit les 3 fichiers cache pour un COVERARTID dans le dossier Coverart.

    Args:
        coverart_dir: Dossier `Coverart/` racine de Traktor.
        coverid: Identifiant complet `<prefix>/<name>` (ex `059/1BXRENA13...`).
        resolutions: Tuple des 3 CoverArtImage (000, 001, 002).

    Returns:
        Tuple des 3 chemins crees.
    """
    if "/" not in coverid:
        raise ValueError(f"COVERARTID invalide (manque le prefix) : {coverid!r}")
    prefix, name = coverid.split("/", 1)

    sub = coverart_dir / prefix
    sub.mkdir(parents=True, exist_ok=True)

    paths = []
    for i, image in enumerate(resolutions):
        path = sub / f"{name}{i:03d}"
        path.write_bytes(encode_coverart(image))
        paths.append(path)
    return tuple(paths)  # type: ignore[return-value]


def parse_coverid(coverid: str) -> tuple[str, str]:
    """Parse un COVERARTID `<prefix>/<name>` en (prefix, name).

    Raises:
        ValueError: si le format est invalide.
    """
    if "/" not in coverid:
        raise ValueError(f"COVERARTID invalide : {coverid!r}")
    prefix, name = coverid.split("/", 1)
    if len(prefix) != 3 or not prefix.isdigit():
        raise ValueError(f"Prefix invalide (3 chiffres requis) : {prefix!r}")
    if len(name) != 28:
        raise ValueError(f"Name invalide (28 chars requis) : {name!r} ({len(name)} chars)")
    for c in name:
        if c not in _NI_DECODE:
            raise ValueError(f"Caractere invalide dans le name : {c!r}")
    return prefix, name
