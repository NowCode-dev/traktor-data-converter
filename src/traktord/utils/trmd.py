"""Serialiseur/deserialiseur du format TRMD (frame ID3 PRIV:TRAKTOR4).

Format chunked proprietaire Native Instruments stocke dans une frame
ID3v2 PRIV avec owner="TRAKTOR4" dans chaque fichier MP3.

Structure sur disque d'un chunk :

    Offset  Size  Description
    ------  ----  -----------
    0       4     FourCC byte-reversed (ex: "TRMD" -> b"DMRT")
    4       4     Longueur du body en uint32 LE
    8       4     Version en uint32 LE
    12      N     Body (sous-chunks concatenes OU donnees brutes)

Arbre typique d'une frame PRIV:TRAKTOR4 complete :

    TRMD (v2)
    +-- HDR_ (v3) : CHKS, FMOD, VRSN
    +-- DATA (v20) : ANDB, ARTW, AUID, BITR, BPMQ, CUEP, FLGS,
                     HBPM, IPDT, MKEY, PCDB, PKDB, SYNC, TALB,
                     TIT2, TKEY, TLEN, TPE1, TRN3
"""

from __future__ import annotations

import hashlib
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from datetime import datetime
from typing import TYPE_CHECKING

from .coverart import (
    CoverArtImage,
    encode_ni_b32,
    generate_coverart_resolutions_t4,
    write_coverart_files,
)

if TYPE_CHECKING:
    from ..models.track import CuePoint, Track

# ----------------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------------

#: Taille du header de chunk (4CC + length + version)
CHUNK_HEADER_SIZE = 12

#: Owner de la frame PRIV dans les tags ID3
PRIV_OWNER = "TRAKTOR4"

#: Versions observees dans Traktor Pro 4.4.2
TRMD_VERSION = 2
HDR_VERSION = 3
DATA_VERSION = 20
VRSN_VALUE = 7  # Format TRMD version 7


# ----------------------------------------------------------------------------
# Chunk generique
# ----------------------------------------------------------------------------

@dataclass
class Chunk:
    """Un chunk TRMD (conteneur ou feuille).

    Attributes:
        fourcc: Identifiant logique sur 4 caracteres (ex: "TRMD", " HDR").
        version: Entier stocke dans le header du chunk.
        data: Donnees brutes pour un chunk feuille (vide si conteneur).
        children: Sous-chunks pour un chunk conteneur (vide si feuille).
    """

    fourcc: str
    version: int = 0
    data: bytes = b""
    children: list[Chunk] = field(default_factory=list)

    def serialize(self) -> bytes:
        """Serialise le chunk en bytes (header + body, recursif)."""
        body = b"".join(c.serialize() for c in self.children) if self.children else self.data
        return _pack_header(self.fourcc, len(body), self.version) + body

    @property
    def total_size(self) -> int:
        """Taille totale serialisee (header + body)."""
        body_len = sum(c.total_size for c in self.children) if self.children else len(self.data)
        return CHUNK_HEADER_SIZE + body_len


def _pack_header(fourcc: str, body_length: int, version: int) -> bytes:
    """Pack un header de chunk : 4CC reversed + length LE + version LE."""
    return fourcc.encode("ascii")[::-1] + struct.pack("<II", body_length, version)


# ----------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------

#: Chunks connus comme conteneurs (ont des sous-chunks, pas des donnees)
_CONTAINER_FOURCCS = {"TRMD", " HDR", "DATA", "SYNC"}


def parse_chunk(data: bytes, offset: int = 0) -> tuple[Chunk, int]:
    """Parse un chunk a partir d'un offset dans un buffer.

    Returns:
        Tuple (chunk, offset_apres_chunk).
    """
    if offset + CHUNK_HEADER_SIZE > len(data):
        raise ValueError(f"Pas assez de bytes pour un header a l'offset {offset}")

    fourcc_raw = data[offset : offset + 4]
    fourcc = fourcc_raw[::-1].decode("ascii")
    body_len, version = struct.unpack("<II", data[offset + 4 : offset + 12])
    body_start = offset + CHUNK_HEADER_SIZE
    body_end = body_start + body_len

    if body_end > len(data):
        raise ValueError(
            f"Chunk {fourcc!r} a l'offset {offset} : body_len={body_len} "
            f"depasse la fin du buffer ({len(data)})"
        )

    chunk = Chunk(fourcc=fourcc, version=version)

    if fourcc in _CONTAINER_FOURCCS:
        pos = body_start
        while pos < body_end:
            child, pos = parse_chunk(data, pos)
            chunk.children.append(child)
    else:
        chunk.data = data[body_start:body_end]

    return chunk, body_end


def parse_trmd(data: bytes) -> Chunk:
    """Parse un blob TRMD complet en arbre de chunks.

    Args:
        data: Bytes bruts de la frame PRIV (peut contenir du padding
              apres le TRMD — il est ignore).

    Returns:
        Le chunk racine TRMD.

    Raises:
        ValueError: si le format est invalide.
    """
    chunk, _ = parse_chunk(data, 0)
    if chunk.fourcc != "TRMD":
        raise ValueError(f"Chunk racine attendu TRMD, trouve {chunk.fourcc!r}")
    return chunk


# ----------------------------------------------------------------------------
# Helpers : recherche de chunk dans l'arbre
# ----------------------------------------------------------------------------

def find_chunk(root: Chunk, path: str) -> Optional[Chunk]:
    """Trouve un chunk par chemin (ex: "DATA/ARTW").

    Args:
        root: Chunk racine.
        path: Chemin separe par "/" (ex: "DATA/ARTW", " HDR/VRSN").

    Returns:
        Le chunk trouve ou None.
    """
    parts = path.split("/")
    current = root
    for part in parts:
        found = None
        for child in current.children:
            if child.fourcc == part:
                found = child
                break
        if found is None:
            return None
        current = found
    return current


# ----------------------------------------------------------------------------
# Construction du body ARTW
# ----------------------------------------------------------------------------

def build_artw_body(coverid: str, image: CoverArtImage) -> bytes:
    """Construit le body d'un chunk ARTW.

    Format :
        byte 0       : marker 0x08
        bytes 1-2    : width uint16 LE
        bytes 3-4    : 0x0000 padding
        bytes 5-6    : height uint16 LE
        bytes 7-8    : 0x0000 padding
        bytes 9-12   : uint32 LE = longueur du COVERARTID en caracteres
        bytes 13-X   : COVERARTID en UTF-16 LE
        bytes X-end  : Raw RGBA bitmap (width * height * 4 bytes)

    Args:
        coverid: Identifiant complet "PPP/28CHARS" (32 caracteres).
        image: Image RGBA source (typiquement 125x125).

    Returns:
        Bytes du body ARTW.
    """
    header = struct.pack("<BHHHH", 0x08, image.width, 0, image.height, 0)
    coverid_utf16 = coverid.encode("utf-16-le")
    coverid_len = len(coverid)
    return header + struct.pack("<I", coverid_len) + coverid_utf16 + image.rgba_pixels


def parse_artw_body(data: bytes) -> tuple[str, CoverArtImage]:
    """Parse le body d'un chunk ARTW.

    Returns:
        Tuple (coverid, CoverArtImage).
    """
    if len(data) < 13:
        raise ValueError(f"ARTW body trop court : {len(data)} bytes")

    marker, width, pad1, height, pad2 = struct.unpack("<BHHHH", data[:9])
    if marker != 0x08:
        raise ValueError(f"ARTW marker invalide : 0x{marker:02x}")

    strlen = struct.unpack("<I", data[9:13])[0]
    coverid_end = 13 + strlen * 2
    if coverid_end > len(data):
        raise ValueError(f"ARTW coverid depasse le body (strlen={strlen})")

    coverid = data[13:coverid_end].decode("utf-16-le")
    rgba = data[coverid_end:]
    expected_rgba = width * height * 4
    if len(rgba) != expected_rgba:
        raise ValueError(
            f"ARTW bitmap size mismatch : {len(rgba)} vs {expected_rgba} "
            f"({width}x{height} RGBA)"
        )

    return coverid, CoverArtImage(width=width, height=height, rgba_pixels=rgba)


# ----------------------------------------------------------------------------
# Generation de COVERARTID
# ----------------------------------------------------------------------------

def generate_coverid(image_data: bytes) -> str:
    """Genere un COVERARTID deterministe a partir des donnees d'une image.

    Le COVERARTID est de la forme "PPP/28CHARS" ou :
    - PPP : 3 chiffres decimaux derives du hash
    - 28CHARS : nom en Base32 NI custom (140 bits)

    L'ID est arbitraire — on utilise SHA-256 de l'image source pour
    generer un ID stable et sans collision.

    Args:
        image_data: Bytes de l'image source (JPEG/PNG, typiquement APIC).

    Returns:
        COVERARTID au format "PPP/28CHARS".
    """
    digest = hashlib.sha256(image_data).digest()
    # Prefixe : 3 chiffres decimaux (0-255, zero-padded)
    prefix = f"{digest[0]:03d}"
    # Nom : 28 caracteres en Base32 NI depuis les bytes 1-18 du hash
    name = encode_ni_b32(digest[1:], length=28)
    return f"{prefix}/{name}"


# ----------------------------------------------------------------------------
# Helpers d'encodage des chunks
# ----------------------------------------------------------------------------

def _utf16_str(s: str) -> bytes:
    """Encode une string en format Traktor : uint32 strlen + UTF-16 LE."""
    return struct.pack("<I", len(s)) + s.encode("utf-16-le")


def _parse_utf16_str(data: bytes) -> str:
    """Decode une string Traktor (uint32 strlen + UTF-16 LE)."""
    strlen = struct.unpack("<I", data[:4])[0]
    return data[4:4 + strlen * 2].decode("utf-16-le")


def _pack_ipdt(dt: Optional[datetime] = None) -> bytes:
    """Encode une date au format IPDT : YYYY*65536 + MM*256 + DD."""
    if dt is None:
        dt = datetime.now()
    return struct.pack("<I", (dt.year << 16) | (dt.month << 8) | dt.day)


# ----------------------------------------------------------------------------
# Mapping des types de cue NML -> TRMD
# ----------------------------------------------------------------------------

_CUE_TYPE_TO_INT = {
    "cue": 0,
    "fade_in": 1,
    "fade_out": 2,
    "load": 3,
    "grid": 4,
    "loop": 5,
}


# ----------------------------------------------------------------------------
# Builders des chunks de metadonnees
# ----------------------------------------------------------------------------

def build_cuep_body(
    cue_points: "list[CuePoint]",
    grid_offset_ms: Optional[float] = None,
) -> bytes:
    """Construit le body du chunk CUEP.

    Format :
        uint32 num_cues
        pour chaque cue (40 + strlen*2 bytes) :
            uint32 ver = 1
            uint32 strlen
            UTF-16 LE name[strlen]
            uint32 unknown = 0
            uint32 type         (0=cue, 1=fade_in, 2=fade_out, 3=load, 4=grid, 5=loop)
            float64 position_ms
            float64 length_ms
            uint32 color = 0xFFFFFFFF
            int32 hotcue        (0-7 ou -1 pour grid/memory)

    Args:
        cue_points: Liste des cue points du morceau.
        grid_offset_ms: Si defini, ajoute un cue "AutoGrid" (type=4) en premier.

    Returns:
        Body du chunk CUEP.
    """
    cues = []

    # Beatgrid en premier si defini
    if grid_offset_ms is not None:
        cues.append(("AutoGrid", 4, float(grid_offset_ms), 0.0, -1))

    # Cues utilisateur
    for c in cue_points:
        cue_type = _CUE_TYPE_TO_INT.get(c.type, 0)
        cues.append((c.name or "", cue_type, c.position_ms, c.length_ms, c.hotcue))

    parts = [struct.pack("<I", len(cues))]
    for name, cue_type, pos, length, hotcue in cues:
        parts.append(struct.pack("<I", 1))  # ver
        parts.append(_utf16_str(name))
        parts.append(struct.pack("<I", 0))  # unknown
        parts.append(struct.pack("<I", cue_type))
        parts.append(struct.pack("<d", pos))
        parts.append(struct.pack("<d", length))
        parts.append(struct.pack("<I", 0xFFFFFFFF))  # color default
        parts.append(struct.pack("<i", hotcue))  # signed pour -1

    return b"".join(parts)


def parse_cuep_body(data: bytes) -> list[dict]:
    """Parse le body d'un chunk CUEP en liste de dicts."""
    num_cues = struct.unpack("<I", data[:4])[0]
    off = 4
    cues = []
    for _ in range(num_cues):
        ver = struct.unpack("<I", data[off:off + 4])[0]
        off += 4
        strlen = struct.unpack("<I", data[off:off + 4])[0]
        off += 4
        name = data[off:off + strlen * 2].decode("utf-16-le")
        off += strlen * 2
        _unknown = struct.unpack("<I", data[off:off + 4])[0]
        off += 4
        cue_type = struct.unpack("<I", data[off:off + 4])[0]
        off += 4
        pos = struct.unpack("<d", data[off:off + 8])[0]
        off += 8
        length = struct.unpack("<d", data[off:off + 8])[0]
        off += 8
        color = struct.unpack("<I", data[off:off + 4])[0]
        off += 4
        hotcue = struct.unpack("<i", data[off:off + 4])[0]
        off += 4
        cues.append({
            "ver": ver, "name": name, "type": cue_type,
            "position_ms": pos, "length_ms": length,
            "color": color, "hotcue": hotcue,
        })
    return cues


def build_sync_chunk(dt: Optional[datetime] = None) -> Chunk:
    """Construit le chunk SYNC (container avec LMDT/LOCK/MATY)."""
    if dt is None:
        dt = datetime.now()
    # LMDT : datetime string "YYYY-MM-DDTHH:MM:SS" en UTF-16
    lmdt_str = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return Chunk("SYNC", version=3, children=[
        Chunk("LMDT", data=_utf16_str(lmdt_str)),
        Chunk("LOCK", data=struct.pack("<I", 1)),
        Chunk("MATY", data=struct.pack("<I", 3)),
    ])


# ----------------------------------------------------------------------------
# Construction TRMD minimal (artwork seul)
# ----------------------------------------------------------------------------

def build_minimal_trmd(coverid: str, image: CoverArtImage) -> bytes:
    """Construit un blob TRMD minimal contenant uniquement l'artwork.

    Structure :
        TRMD (v2)
        +-- HDR_ (v3) : CHKS=0, FMOD=timestamp, VRSN=7
        +-- DATA (v20) : ANDB=0, ARTW=image

    Args:
        coverid: COVERARTID au format "PPP/28CHARS".
        image: Image RGBA (typiquement 125x125).

    Returns:
        Bytes du blob TRMD complet (pret a injecter dans PRIV).
    """
    artw_body = build_artw_body(coverid, image)

    # Timestamp FMOD : secondes depuis epoch en uint32 LE
    fmod_val = int(time.time())

    hdr = Chunk(" HDR", version=HDR_VERSION, children=[
        Chunk("CHKS", data=b"\x00\x00\x00\x00"),
        Chunk("FMOD", data=struct.pack("<I", fmod_val)),
        Chunk("VRSN", data=struct.pack("<I", VRSN_VALUE)),
    ])

    data_chunk = Chunk("DATA", version=DATA_VERSION, children=[
        Chunk("ANDB", data=b"\x00\x00\x00\x00"),
        Chunk("ARTW", data=artw_body),
    ])

    root = Chunk("TRMD", version=TRMD_VERSION, children=[hdr, data_chunk])
    return root.serialize()


# ----------------------------------------------------------------------------
# TRMD complet avec metadonnees (build_full_trmd)
# ----------------------------------------------------------------------------

def build_full_trmd(
    track: "Track",
    artwork_image: Optional[CoverArtImage] = None,
    artwork_coverid: Optional[str] = None,
) -> bytes:
    """Construit un blob TRMD complet avec toutes les metadonnees.

    Inclut tous les chunks necessaires pour que Traktor ne perde pas les
    metadonnees au rescan : BPM, cues, key, title, artist, album, duree,
    bitrate, artwork, etc.

    Args:
        track: Modele Track avec les metadonnees.
        artwork_image: Image 125x125 RGBA (si None, pas de chunk ARTW).
        artwork_coverid: COVERARTID correspondant (requis si artwork_image).

    Returns:
        Bytes du blob TRMD complet.
    """
    from .keys import classical_to_traktor_key

    # Chunks de DATA en ordre alphabetique (comme Traktor les ecrit)
    data_children = []

    # ANDB - analysis DB (zeros = pas analyse)
    data_children.append(Chunk("ANDB", data=b"\x00" * 4))

    # ARTW - artwork (optionnel)
    if artwork_image is not None and artwork_coverid is not None:
        artw_body = build_artw_body(artwork_coverid, artwork_image)
        data_children.append(Chunk("ARTW", data=artw_body))

    # BITR - bitrate en bps (kbps * 1000)
    bitrate_bps = (track.bitrate or 0) * 1000
    data_children.append(Chunk("BITR", data=struct.pack("<I", bitrate_bps)))

    # BPMQ - BPM quality (1.0 = 100%)
    data_children.append(Chunk("BPMQ", data=struct.pack("<f", 1.0)))

    # CUEP - cue points + beatgrid
    cuep_body = build_cuep_body(track.cue_points, track.grid_offset_ms)
    data_children.append(Chunk("CUEP", data=cuep_body))

    # AUID - audio fingerprint (260 bytes zeros = placeholder "analyse faite")
    data_children.append(Chunk("AUID", data=b"\x00" * 260))

    # FLGS - flags 0x1C = bits d'analyse (observe dans Factory Sounds)
    # Sans ca, Traktor refait l'analyse et ecrase nos metadonnees au rescan
    data_children.append(Chunk("FLGS", data=struct.pack("<I", 0x1C)))

    # HBPM - BPM en float32
    bpm = float(track.bpm or 0.0)
    data_children.append(Chunk("HBPM", data=struct.pack("<f", bpm)))

    # IPDT - import date (today)
    data_children.append(Chunk("IPDT", data=_pack_ipdt()))

    # LABL - label (optionnel)
    if track.label:
        data_children.append(Chunk("LABL", data=_utf16_str(track.label)))

    # MKEY - musical key index (0-23)
    key_index = classical_to_traktor_key(track.key) if track.key else None
    if key_index is not None:
        data_children.append(Chunk("MKEY", data=struct.pack("<I", key_index)))

    # PCDB, PKDB - peak DB (zeros)
    data_children.append(Chunk("PCDB", data=b"\x00" * 4))
    data_children.append(Chunk("PKDB", data=b"\x00" * 4))

    # SYNC - metadonnees de sync (current datetime)
    data_children.append(build_sync_chunk())

    # TALB - album
    if track.album:
        data_children.append(Chunk("TALB", data=_utf16_str(track.album)))

    # TIT2 - title
    if track.title:
        data_children.append(Chunk("TIT2", data=_utf16_str(track.title)))

    # TKEY - key string
    if track.key:
        data_children.append(Chunk("TKEY", data=_utf16_str(track.key)))

    # TLEN - length in seconds (uint32)
    duration_sec = int(track.duration or 0)
    data_children.append(Chunk("TLEN", data=struct.pack("<I", duration_sec)))

    # TPE1 - artist
    if track.artist:
        data_children.append(Chunk("TPE1", data=_utf16_str(track.artist)))

    # TRN3 - transient data (minimal = 4 bytes count=0 ; evite le re-analyse audio)
    data_children.append(Chunk("TRN3", data=b"\x00" * 4))

    # HDR_
    fmod_val = int(datetime.now().timestamp())
    hdr = Chunk(" HDR", version=HDR_VERSION, children=[
        Chunk("CHKS", data=b"\x00\x00\x00\x00"),
        Chunk("FMOD", data=struct.pack("<I", fmod_val)),
        Chunk("VRSN", data=struct.pack("<I", VRSN_VALUE)),
    ])

    # DATA
    data_chunk = Chunk("DATA", version=DATA_VERSION, children=data_children)

    # TRMD root
    root = Chunk("TRMD", version=TRMD_VERSION, children=[hdr, data_chunk])
    return root.serialize()


# ----------------------------------------------------------------------------
# Injection dans un MP3
# ----------------------------------------------------------------------------

def inject_artwork(
    mp3_path: Path,
    coverart_dir: Optional[Path] = None,
    coverid: Optional[str] = None,
) -> Optional[str]:
    """Injecte l'artwork dans un MP3 via PRIV:TRAKTOR4 + fichiers cache.

    Lit la frame APIC du MP3, genere les resolutions Traktor 4,
    construit le TRMD minimal, et ecrit :
    1. La frame PRIV:TRAKTOR4 dans le MP3
    2. Les 3 fichiers cache dans coverart_dir (si fourni)

    Args:
        mp3_path: Chemin vers le fichier MP3.
        coverart_dir: Dossier Coverart/ de Traktor. Si None, seule la
            frame PRIV est ecrite (pas de cache files).
        coverid: COVERARTID a utiliser. Si None, genere automatiquement
            depuis l'APIC.

    Returns:
        Le COVERARTID utilise, ou None si aucune APIC trouvee.
    """
    try:
        from mutagen.id3 import ID3, PRIV
    except ImportError as e:
        raise ImportError("mutagen est requis pour l'injection PRIV") from e

    tags = ID3(str(mp3_path))

    # Chercher la frame APIC (artwork embarque)
    apic_data = None
    for frame in tags.values():
        if frame.FrameID == "APIC":
            apic_data = frame.data
            break

    if apic_data is None:
        return None

    # Generer le COVERARTID si pas fourni
    if coverid is None:
        coverid = generate_coverid(apic_data)

    # Generer les 3 resolutions Traktor 4
    res_125, res_75, res_56 = generate_coverart_resolutions_t4(apic_data)

    # Construire le blob TRMD avec l'image principale (125x125)
    trmd_blob = build_minimal_trmd(coverid, res_125)

    # Supprimer l'ancienne frame PRIV:TRAKTOR4 si presente
    to_remove = []
    for key, frame in tags.items():
        if frame.FrameID == "PRIV" and getattr(frame, "owner", "") == PRIV_OWNER:
            to_remove.append(key)
    for key in to_remove:
        del tags[key]

    # Ajouter la nouvelle frame PRIV
    tags.add(PRIV(owner=PRIV_OWNER, data=trmd_blob))
    tags.save(str(mp3_path), v2_version=4)

    # Ecrire les fichiers cache si le dossier est fourni
    if coverart_dir is not None:
        write_coverart_files(coverart_dir, coverid, (res_125, res_75, res_56))

    return coverid


def inject_full_metadata(
    mp3_path: Path,
    track: "Track",
    coverart_dir: Optional[Path] = None,
    include_artwork: bool = True,
) -> Optional[str]:
    """Injecte un TRMD complet (metadonnees + artwork) dans un MP3.

    Cette fonction remplace `inject_artwork` quand on veut preserver
    TOUTES les metadonnees (BPM, cues, key, title, etc.) au rescan Traktor.

    Args:
        mp3_path: Chemin vers le fichier MP3.
        track: Modele Track avec toutes les metadonnees.
        coverart_dir: Dossier Coverart/ de Traktor (si None, pas de cache files).
        include_artwork: Si True, lit l'APIC du MP3 et inclut l'artwork.

    Returns:
        Le COVERARTID si artwork inclus, "NO_ARTWORK" si pas d'artwork,
        None si erreur.
    """
    try:
        from mutagen.id3 import ID3, PRIV, COMM, POPM
    except ImportError as e:
        raise ImportError("mutagen est requis pour l'injection PRIV") from e

    tags = ID3(str(mp3_path))

    # Generer artwork si demande
    artwork_image = None
    coverid = None
    if include_artwork:
        apic_data = None
        for frame in tags.values():
            if frame.FrameID == "APIC":
                apic_data = frame.data
                break

        if apic_data is not None:
            coverid = generate_coverid(apic_data)
            res_125, res_75, res_56 = generate_coverart_resolutions_t4(apic_data)
            artwork_image = res_125

            # Ecrire les fichiers cache
            if coverart_dir is not None:
                write_coverart_files(coverart_dir, coverid, (res_125, res_75, res_56))

    # Construire le TRMD complet
    trmd_blob = build_full_trmd(track, artwork_image, coverid)

    # Supprimer l'ancienne frame PRIV:TRAKTOR4 si presente
    to_remove = []
    for key, frame in tags.items():
        if frame.FrameID == "PRIV" and getattr(frame, "owner", "") == PRIV_OWNER:
            to_remove.append(key)
    for key in to_remove:
        del tags[key]

    # Injecter PRIV:TRAKTOR4
    tags.add(PRIV(owner=PRIV_OWNER, data=trmd_blob))

    # COMM - commentaire (tag ID3 standard, Traktor le lit)
    if track.comment:
        # Supprimer les anciens COMM
        for key in list(tags.keys()):
            if key.startswith("COMM"):
                del tags[key]
        tags.add(COMM(encoding=3, lang="eng", desc="", text=track.comment))

    # POPM - rating 0-5 etoiles → 0-255 (standard ID3)
    # Mapping Traktor : 0=0, 1=51, 2=102, 3=153, 4=204, 5=255
    if track.rating is not None and 0 <= track.rating <= 5:
        # Supprimer les anciens POPM
        for key in list(tags.keys()):
            if key.startswith("POPM"):
                del tags[key]
        popm_rating = [0, 51, 102, 153, 204, 255][track.rating]
        tags.add(POPM(email="no@email", rating=popm_rating, count=0))

    tags.save(str(mp3_path), v2_version=4)

    return coverid or "NO_ARTWORK"


def read_artwork(mp3_path: Path) -> Optional[tuple[str, CoverArtImage]]:
    """Lit l'artwork depuis la frame PRIV:TRAKTOR4 d'un MP3.

    Returns:
        Tuple (coverid, CoverArtImage) ou None si pas de PRIV:TRAKTOR4.
    """
    try:
        from mutagen.id3 import ID3
    except ImportError as e:
        raise ImportError("mutagen est requis pour lire PRIV") from e

    tags = ID3(str(mp3_path))
    for frame in tags.values():
        if frame.FrameID == "PRIV" and getattr(frame, "owner", "") == PRIV_OWNER:
            root = parse_trmd(frame.data)
            artw = find_chunk(root, "DATA/ARTW")
            if artw is None:
                return None
            return parse_artw_body(artw.data)
    return None
