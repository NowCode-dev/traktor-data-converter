"""Conversion des chemins de fichiers entre formats DJ.

Rekordbox : file://localhost/Users/foo/Music/track.mp3
Traktor : VOLUME="Macintosh HD" DIR="/:Users/:foo/:Music/:" FILE="track.mp3"
"""

from __future__ import annotations

import platform
from urllib.parse import unquote, urlparse


def rekordbox_uri_to_file_path(uri: str) -> str:
    """Convertir un URI Rekordbox en chemin fichier local."""
    parsed = urlparse(uri)
    path = unquote(parsed.path)
    # Sur Windows, le path commence par /C:/ — retirer le / initial
    if len(path) > 2 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path


def file_path_to_traktor_location(file_path: str, volume_name: str | None = None) -> dict[str, str]:
    """Convertir un chemin fichier en LOCATION Traktor (VOLUME, DIR, FILE, VOLUMEID).

    Exemples :
        /Users/foo/Music/track.mp3
        → VOLUME="Macintosh HD", DIR="/:Users/:foo/:Music/:", FILE="track.mp3"

        C:/Users/foo/Music/track.mp3
        → VOLUME="C:", DIR="/:Users/:foo/:Music/:", FILE="track.mp3"

        /home/foo/Music/track.mp3
        → VOLUME="", DIR="/:home/:foo/:Music/:", FILE="track.mp3"
    """
    # Normaliser les separateurs
    path = file_path.replace("\\", "/")

    # Detecter le volume
    volume = ""
    volumeid = ""

    if len(path) > 1 and path[1] == ":":
        # Windows : C:/Users/...
        volume = path[:2]  # "C:"
        volumeid = path[:2]
        path = path[2:]  # /Users/...
    elif path.startswith("/Volumes/"):
        # macOS volume externe : /Volumes/USB_DJ/Music/...
        parts = path.split("/")
        volume = parts[2]  # "USB_DJ"
        volumeid = volume
        path = "/" + "/".join(parts[3:])  # /Music/...
    elif platform.system() == "Darwin" or path.startswith("/Users/"):
        volume = volume_name or "Macintosh HD"
        volumeid = volume
    else:
        # Linux ou autre
        volume = ""
        volumeid = ""

    # Separer le fichier du repertoire
    if "/" in path:
        last_slash = path.rfind("/")
        dir_part = path[:last_slash + 1]
        file_part = path[last_slash + 1:]
    else:
        dir_part = "/"
        file_part = path

    # Encoder en format Traktor : chaque segment prefixe par /:
    segments = [s for s in dir_part.split("/") if s]
    traktor_dir = "/:" + "/:".join(segments) + "/:" if segments else "/:"

    return {
        "VOLUME": volume,
        "DIR": traktor_dir,
        "FILE": file_part,
        "VOLUMEID": volumeid,
    }


def rekordbox_uri_to_traktor_location(uri: str) -> dict[str, str]:
    """Convertir directement un URI Rekordbox en LOCATION Traktor."""
    file_path = rekordbox_uri_to_file_path(uri)
    return file_path_to_traktor_location(file_path)


def traktor_location_to_file_path(volume: str, dir_path: str, file_name: str) -> str:
    """Reconstruire un chemin fichier depuis une LOCATION Traktor.

    Exemple :
        VOLUME="Macintosh HD", DIR="/:Users/:foo/:Music/:", FILE="track.mp3"
        → /Users/foo/Music/track.mp3
    """
    # Decoder le DIR Traktor : retirer les /: et reconstruire
    segments = [s for s in dir_path.split("/:") if s]
    path = "/".join(segments)

    # Ajouter le volume si Windows
    if volume and len(volume) == 2 and volume[1] == ":":
        return f"{volume}/{path}/{file_name}" if path else f"{volume}/{file_name}"

    # Sinon chemin Unix
    return f"/{path}/{file_name}" if path else f"/{file_name}"
