"""Auto-detection du format d'un fichier de collection DJ."""

from __future__ import annotations


def detect_format(file_path: str) -> str | None:
    """Detecter le format d'un fichier en lisant les premiers octets.

    Retourne : "rekordbox", "traktor", "virtualdj" ou None.
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(4096).decode("utf-8", errors="ignore")
    except OSError:
        return None

    if "<DJ_PLAYLISTS" in header:
        return "rekordbox"
    if "<NML " in header or "<NML>" in header:
        return "traktor"
    if "<VirtualDJ_Database" in header:
        return "virtualdj"

    return None
