"""Modele de donnees unifie pour representer un morceau DJ."""

from __future__ import annotations

from pydantic import BaseModel


class CuePoint(BaseModel):
    """Point cue (hot cue, memory cue, loop)."""

    name: str = ""
    type: str = "cue"  # cue, fade_in, fade_out, load, grid, loop
    position_ms: float = 0.0
    length_ms: float = 0.0  # pour les loops
    hotcue: int = -1  # -1 = memory cue, 0-7 = pads A-H
    red: int = 0
    green: int = 0
    blue: int = 0


class Track(BaseModel):
    """Representation unifiee d'un morceau DJ.

    Ce modele sert de format intermediaire entre tous les formats supportes.
    Chaque parser convertit vers ce modele, chaque writer convertit depuis ce modele.
    """

    # Identite
    title: str = ""
    artist: str = ""
    album: str = ""
    genre: str = ""
    comment: str = ""
    label: str = ""
    key: str = ""  # notation classique : "Am", "Db", "F#m"
    track_number: int | None = None
    disc_number: int | None = None
    year: int | None = None
    composer: str = ""
    grouping: str = ""
    remixer: str = ""
    mix: str = ""

    # Fichier
    file_path: str = ""
    file_size: int | None = None
    file_type: str = ""  # mp3, wav, flac, aiff...

    # Audio
    bitrate: int | None = None  # kbps
    sample_rate: int | None = None  # Hz
    duration: float | None = None  # secondes

    # DJ metadata
    bpm: float | None = None
    rating: int | None = None  # 0-5
    color: str | None = None
    play_count: int = 0
    last_played: str | None = None  # ISO date yyyy-mm-dd
    date_added: str | None = None  # ISO date yyyy-mm-dd

    # Cue points et loops
    cue_points: list[CuePoint] = []

    # Grille rythmique
    grid_offset_ms: float | None = None

    # Metadonnees du format source (pour preservation)
    source_format: str = ""
    extra: dict = {}


class Collection(BaseModel):
    """Une collection complete de morceaux DJ."""

    tracks: list[Track] = []
    playlists: dict[str, list[str]] = {}  # nom -> liste de file_paths
    source_format: str = ""
    source_file: str = ""
