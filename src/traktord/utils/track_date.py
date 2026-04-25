"""Extraction de la meilleure date de release/creation d'un fichier audio.

L'objectif est d'enrichir le champ `RELEASE_DATE` du NML Traktor avec une
date au jour pres (au lieu de juste l'annee transmise par Rekordbox), pour
permettre un tri precis dans le browser.

Priorite (du plus au moins precis) :
    1. Tags ID3 TDRL ou TDOR (date officielle de release, format YYYY-MM-DD)
       — Beatport remplit ces deux tags identiquement.
    2. Filesystem birthtime (HFS+/APFS) — date d'arrivee du fichier sur le
       disque, soit la date d'achat dans la majorite des cas.
    3. Tag ID3 TDRC + pattern `(MM-YYYY)` du filename Beatport — annee tag
       + mois extrait du nom de fichier.
    4. Tag ID3 TDRC seul (annee uniquement).
    5. None si rien n'est exploitable.

Le format de retour est compatible avec Traktor `<INFO RELEASE_DATE="...">` :
    - `YYYY/MM/DD` si jour connu
    - `YYYY/MM` si seulement mois + annee
    - `YYYY` si seulement annee
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

#: Pattern Beatport `(MM-YYYY)` au debut du filename.
_BEATPORT_DATE_RE = re.compile(r"^\((\d{2})-(\d{4})\)")


def get_release_date(file_path: str | os.PathLike[str]) -> str | None:
    """Retourne la meilleure date au format Traktor.

    Ne leve jamais d'exception : retourne None si rien n'est lisible.
    """
    try:
        path = Path(file_path)
        if not path.is_file():
            return None

        ext = path.suffix.lower()

        # 1. Tags ID3 TDRL/TDOR (date complete YYYY-MM-DD)
        if ext == ".mp3":
            iso = _read_id3_release_date(path)
            if iso:
                return iso.replace("-", "/")

        # 2. Filesystem birthtime (HFS+/APFS sur Mac, ext4 disponible aussi)
        btime_str = _filesystem_birthtime(path)
        if btime_str:
            return btime_str

        # 3 & 4. ID3 TDRC + filename Beatport
        if ext == ".mp3":
            year = _read_id3_year(path)
            month_year = _filename_month_year(path)
            if month_year:
                month, fname_year = month_year
                use_year = year or fname_year
                return f"{use_year}/{month}"
            if year:
                return year

        return None
    except Exception:
        return None


def _read_id3_release_date(path: Path) -> str | None:
    """Retourne TDRL ou TDOR (priorite TDRL) au format YYYY-MM-DD si valide."""
    try:
        from mutagen.id3 import ID3
    except ImportError:
        return None

    try:
        tags = ID3(str(path))
    except Exception:
        return None

    for key in ("TDRL", "TDOR"):
        frame = tags.get(key)
        if not frame or not getattr(frame, "text", None):
            continue
        raw = str(frame.text[0])[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
            return raw
    return None


def _read_id3_year(path: Path) -> str | None:
    """Retourne l'annee depuis TDRC ou TYER si valide (4 chiffres)."""
    try:
        from mutagen.id3 import ID3
    except ImportError:
        return None

    try:
        tags = ID3(str(path))
    except Exception:
        return None

    for key in ("TDRC", "TYER"):
        frame = tags.get(key)
        if not frame or not getattr(frame, "text", None):
            continue
        raw = str(frame.text[0])[:4]
        if raw.isdigit() and len(raw) == 4:
            return raw
    return None


def _filename_month_year(path: Path) -> tuple[str, str] | None:
    """Retourne (mois, annee) extraits du pattern `(MM-YYYY)` du filename."""
    m = _BEATPORT_DATE_RE.match(path.name)
    if not m:
        return None
    return m.group(1), m.group(2)


def _filesystem_birthtime(path: Path) -> str | None:
    """Retourne le birthtime au format `YYYY/MM/DD` si dispo (HFS+/APFS)."""
    try:
        st = path.stat()
        bt = getattr(st, "st_birthtime", None)
        if bt is None:
            return None
        return datetime.fromtimestamp(bt).strftime("%Y/%m/%d")
    except Exception:
        return None
