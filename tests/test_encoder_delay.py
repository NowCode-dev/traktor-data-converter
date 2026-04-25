"""Tests pour la lecture de l'encoder delay."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from traktord.utils.encoder_delay import get_encoder_delay_ms


def test_missing_file_returns_zero(tmp_path: Path) -> None:
    """Un fichier inexistant retourne 0.0 sans exception."""
    assert get_encoder_delay_ms(tmp_path / "does_not_exist.mp3") == 0.0


def test_wav_returns_zero(tmp_path: Path) -> None:
    """Les formats PCM bruts (WAV/AIFF) n'ont pas d'encoder delay."""
    wav = tmp_path / "track.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 100)
    assert get_encoder_delay_ms(wav) == 0.0


def test_flac_returns_zero(tmp_path: Path) -> None:
    """FLAC est lossless sans padding — retourne 0."""
    flac = tmp_path / "track.flac"
    flac.write_bytes(b"fLaC" + b"\x00" * 100)
    assert get_encoder_delay_ms(flac) == 0.0


def test_unsupported_extension_returns_zero(tmp_path: Path) -> None:
    """Extension inconnue → 0.0."""
    unknown = tmp_path / "track.xyz"
    unknown.write_bytes(b"\x00" * 100)
    assert get_encoder_delay_ms(unknown) == 0.0


def test_mp3_with_lame_delay_is_computed(tmp_path: Path) -> None:
    """MP3 avec encoder_delay exposé par mutagen → conversion samples → ms."""
    mp3 = tmp_path / "track.mp3"
    mp3.write_bytes(b"\x00" * 100)

    fake_info = MagicMock()
    fake_info.sample_rate = 44100
    fake_info.encoder_delay = 1152  # valeur LAME typique

    fake_audio = MagicMock()
    fake_audio.info = fake_info

    with patch("mutagen.mp3.MP3", return_value=fake_audio):
        delay = get_encoder_delay_ms(mp3)

    # 1152 / 44100 * 1000 ≈ 26.122 ms
    assert 26.0 < delay < 26.3


def test_mp3_without_lame_header_fallback(tmp_path: Path) -> None:
    """MP3 sans header Xing/LAME → fallback 1152 samples (1 frame MPEG)."""
    mp3 = tmp_path / "track.mp3"
    mp3.write_bytes(b"\x00" * 100)

    fake_info = MagicMock()
    fake_info.sample_rate = 44100
    fake_info.encoder_delay = 0  # absent ou zero

    fake_audio = MagicMock()
    fake_audio.info = fake_info

    with patch("mutagen.mp3.MP3", return_value=fake_audio):
        delay = get_encoder_delay_ms(mp3)

    # Fallback : 1152 / 44100 * 1000 ≈ 26.122 ms (cas 6% biblio DJ)
    assert 26.0 < delay < 26.3


def test_mp3_48khz_adjusts_for_sample_rate(tmp_path: Path) -> None:
    """Le delay en ms depend du sample rate du fichier, pas d'une constante."""
    mp3 = tmp_path / "track.mp3"
    mp3.write_bytes(b"\x00" * 100)

    fake_info = MagicMock()
    fake_info.sample_rate = 48000
    fake_info.encoder_delay = 1152

    fake_audio = MagicMock()
    fake_audio.info = fake_info

    with patch("mutagen.mp3.MP3", return_value=fake_audio):
        delay = get_encoder_delay_ms(mp3)

    # 1152 / 48000 * 1000 = 24.0 ms
    assert 23.9 < delay < 24.1


def test_mp3_mutagen_exception_returns_zero(tmp_path: Path) -> None:
    """Si mutagen leve une exception (fichier corrompu), retourne 0 sans crash."""
    mp3 = tmp_path / "broken.mp3"
    mp3.write_bytes(b"\x00" * 10)

    with patch("mutagen.mp3.MP3", side_effect=RuntimeError("corrupt")):
        assert get_encoder_delay_ms(mp3) == 0.0


def test_m4a_itunsmpb_parsed(tmp_path: Path) -> None:
    """M4A avec atom iTunSMPB → champ [1] en hex = delay samples."""
    m4a = tmp_path / "track.m4a"
    m4a.write_bytes(b"\x00" * 100)

    # Champ [1] = 0x0840 = 2112 samples (valeur typique AAC)
    itunsmpb = b" 00000000 00000840 000001C0 000000000043B400 "

    fake_info = MagicMock()
    fake_info.sample_rate = 44100

    fake_audio = MagicMock()
    fake_audio.info = fake_info
    fake_audio.tags = {"----:com.apple.iTunes:iTunSMPB": [itunsmpb]}

    with patch("mutagen.mp4.MP4", return_value=fake_audio):
        delay = get_encoder_delay_ms(m4a)

    # 2112 / 44100 * 1000 ≈ 47.89 ms
    assert 47.8 < delay < 48.0


def test_m4a_without_itunsmpb_returns_zero(tmp_path: Path) -> None:
    """M4A sans atom iTunSMPB → 0.0 (pas de valeur autoritaire disponible)."""
    m4a = tmp_path / "track.m4a"
    m4a.write_bytes(b"\x00" * 100)

    fake_info = MagicMock()
    fake_info.sample_rate = 44100

    fake_audio = MagicMock()
    fake_audio.info = fake_info
    fake_audio.tags = {}

    with patch("mutagen.mp4.MP4", return_value=fake_audio):
        assert get_encoder_delay_ms(m4a) == 0.0


def test_opus_pre_skip_is_48khz(tmp_path: Path) -> None:
    """Opus travaille a 48 kHz en interne peu importe le sample rate source."""
    opus = tmp_path / "track.opus"
    opus.write_bytes(b"\x00" * 100)

    fake_info = MagicMock()
    fake_info.pre_skip = 3840  # valeur Opus typique

    fake_audio = MagicMock()
    fake_audio.info = fake_info

    with patch("mutagen.oggopus.OggOpus", return_value=fake_audio):
        delay = get_encoder_delay_ms(opus)

    # 3840 / 48000 * 1000 = 80.0 ms
    assert 79.9 < delay < 80.1
