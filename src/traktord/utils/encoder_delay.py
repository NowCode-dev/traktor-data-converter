"""Lecture de l'encoder delay depuis les fichiers audio.

Certains formats audio introduisent un silence de padding en debut de fichier
(encoder delay). Les softs DJ compensent differemment ce decalage, ce qui
provoque un shift typique de ~26 ms (1152 samples @ 44.1 kHz = 1 frame MPEG)
sur les cues et le beatgrid lors d'une conversion Rekordbox → Traktor.

Ce module expose une fonction unique `get_encoder_delay_ms` qui lit la valeur
autoritaire stockee dans le fichier (Xing/LAME pour MP3, iTunSMPB pour M4A,
pre-skip pour Opus) et retourne un offset en millisecondes. Retourne 0.0 si
le format ne contient pas de delay (FLAC/WAV/AIFF) ou si la valeur n'est pas
lisible.
"""

from __future__ import annotations

import os
from pathlib import Path


def get_encoder_delay_ms(file_path: str | os.PathLike[str]) -> float:
    """Retourne l'encoder delay d'un fichier audio en millisecondes.

    Dispatch par extension :
        - .mp3             → frame Xing/LAME
        - .m4a / .mp4 / .aac → atom iTunSMPB
        - .opus            → header pre-skip
        - autres (flac/wav/aiff/ogg vorbis) → 0.0

    Ne leve jamais d'exception : si le fichier est manquant, corrompu, ou que
    mutagen echoue, retourne 0.0.
    """
    try:
        path = Path(file_path)
        if not path.is_file():
            return 0.0

        ext = path.suffix.lower()
        if ext == ".mp3":
            return _mp3_delay_ms(path)
        if ext in {".m4a", ".mp4", ".aac"}:
            return _m4a_delay_ms(path)
        if ext == ".opus":
            return _opus_delay_ms(path)
        return 0.0
    except Exception:
        return 0.0


def _mp3_delay_ms(path: Path) -> float:
    """Lire l'encoder delay d'un MP3 via la frame Xing/LAME.

    Fallback : si la frame existe sans champ `encoder_delay` explicite, ou si
    elle n'existe pas du tout, retourne la valeur par defaut d'un frame MPEG
    (1152 samples @ sample_rate du fichier), qui correspond au comportement
    assume par la plupart des decodeurs pour les MP3 non taggues.
    """
    try:
        from mutagen.mp3 import MP3
    except ImportError:
        return 0.0

    audio = MP3(str(path))
    info = audio.info
    sample_rate = getattr(info, "sample_rate", 44100) or 44100

    # mutagen >= 1.45 expose encoder_delay (samples) sur MPEGInfo si
    # la frame Xing/LAME est presente et valide.
    delay_samples = getattr(info, "encoder_delay", None)
    if delay_samples is None or delay_samples <= 0:
        # Fallback : 1 frame MPEG de padding (default assume par les decodeurs
        # pour les MP3 sans header Xing/LAME — typiquement 6% d'une biblio DJ).
        delay_samples = 1152

    return (delay_samples / sample_rate) * 1000.0


def _m4a_delay_ms(path: Path) -> float:
    """Lire l'encoder delay d'un M4A/AAC via l'atom iTunSMPB.

    Format iTunSMPB : chaine ASCII de 12 valeurs hex separees par espaces.
        " 00000000 00000840 000001C0 000000000043B400 ... "
    Champ [1] = encoder_delay en samples, [2] = padding.
    """
    try:
        from mutagen.mp4 import MP4
    except ImportError:
        return 0.0

    audio = MP4(str(path))
    tags = audio.tags or {}
    sample_rate = getattr(audio.info, "sample_rate", 44100) or 44100

    # Atom stocke sous forme freeform par iTunes
    raw = tags.get("----:com.apple.iTunes:iTunSMPB")
    if not raw:
        return 0.0

    # mutagen retourne une liste de MP4FreeForm (bytes-like)
    value = raw[0]
    if isinstance(value, bytes):
        text = value.decode("ascii", errors="ignore")
    else:
        text = str(value)

    parts = text.strip().split()
    if len(parts) < 2:
        return 0.0

    delay_samples = int(parts[1], 16)
    return (delay_samples / sample_rate) * 1000.0


def _opus_delay_ms(path: Path) -> float:
    """Lire le pre-skip d'un fichier Opus.

    Opus stocke le pre-skip en samples dans le header, toujours a 48 kHz
    (Opus travaille en interne a 48 kHz peu importe le sample rate source).
    """
    try:
        from mutagen.oggopus import OggOpus
    except ImportError:
        return 0.0

    audio = OggOpus(str(path))
    pre_skip = getattr(audio.info, "pre_skip", 0) or 0
    return (pre_skip / 48000.0) * 1000.0
