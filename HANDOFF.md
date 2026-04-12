# Handoff — Traktor Data Converter (session 2026-04-12)

> Ce fichier contient tout le contexte pour reprendre le travail dans
> une nouvelle session Claude Code. Lis-le en premier.

## Problème à résoudre

Les artworks (pochettes) ne s'affichent pas dans Traktor 4 après
conversion Rekordbox → Traktor via NML. Les MP3 ont leurs APIC ID3
intactes (vérifié sur 5 fichiers). Le converter génère un NML correct
pour cues/BPM/beatgrids/playlists, mais Traktor 4 ne lit pas les
artworks depuis le NML ni depuis les APIC des MP3.

## Cause root identifiée

Traktor 4 a déplacé TOUTES ses métadonnées (artworks inclus) dans
une frame ID3 propriétaire `PRIV:TRAKTOR4` stockée directement dans
chaque fichier MP3. Le NML v20 ne contient plus aucun attribut
COVERARTID (contrairement à Traktor 3).

Sans cette frame PRIV, Traktor 4 n'a pas d'artwork à afficher.

## Architecture de la solution

### Format PRIV:TRAKTOR4 (reverse-engineeré)

Structure chunked custom "TRMD" avec 4CC byte-reversed (little-endian) :

```
TRMD (root, raw bytes "DMRT")
├── HDR_ (header v3, 48 bytes)
│   ├── CHKS (checksum, 4 bytes)
│   ├── FMOD (file modification, 4 bytes)
│   └── VRSN (version, 4 bytes)
└── DATA (v19, contient tout)
    ├── ANDB (4 bytes)
    ├── ARTW (artwork : header + COVERARTID + bitmap RGBA)
    ├── AUID (audio fingerprint, 260 bytes)
    ├── BITR (bitrate, 4 bytes)
    ├── BPMQ (BPM quality, 4 bytes)
    ├── CUEP (cue points, variable)
    ├── FLGS (flags, 4 bytes)
    ├── HBPM (BPM, 4 bytes)
    ├── IPDT (import date, 4 bytes)
    ├── MKEY (musical key, 4 bytes)
    ├── PCDB (peak DB, 4 bytes)
    ├── PKDB (perceived DB, 4 bytes)
    ├── SYNC (sync info, contient LMDT/LOCK/MATY)
    ├── TALB (album, variable)
    ├── TIT2 (title, variable)
    ├── TKEY (key string, variable)
    ├── TLEN (length, 4 bytes)
    ├── TPE1 (artist, variable)
    └── TRN3 (transient data, ~13 KB)
```

Chunk header : `4CC_reversed(4) + length_LE(4) + version_LE(4) = 12 bytes`

### Format du chunk ARTW

```
byte 0       : marker 0x08
bytes 1-2    : width uint16 LE
bytes 3-4    : 0x0000 padding
bytes 5-6    : height uint16 LE
bytes 7-8    : 0x0000 padding
bytes 9-12   : uint32 LE = longueur du COVERARTID en caractères
bytes 13-X   : COVERARTID en UTF-16 LE (format "PPP/28CHARS")
bytes X-end  : Raw RGBA bitmap (width * height * 4 bytes)
```

### Format des fichiers cache Coverart

```
~/Documents/Native Instruments/Traktor 4.X.X/Coverart/<prefix>/<name>{000,001,002}
```

Même format binaire que le debut du chunk ARTW (header 9 bytes + RGBA) mais SANS le COVERARTID inline.

3 résolutions : 000=125x125, 001=75x75, 002=56x56

### Alphabet Base32 NI custom

`012345ABCDEFGHIJKLMNOPQRSTUVWXYZ` (32 chars, manque 6,7,8,9)

COVERARTID = `<prefix_3digits>/<name_28chars>` (140 bits)

Le COVERARTID est ARBITRAIRE — on le génère nous-mêmes (pas besoin
de reverse un hash). On peut hasher l'APIC JPEG ou utiliser un UUID.

## Code existant

### Module coverart.py (COMPLET, 19 tests verts)
`src/traktord/utils/coverart.py` :
- `encode_ni_b32 / decode_ni_b32` — Base32 NI custom
- `encode_coverart / decode_coverart` — format binaire cache
- `parse_coverid` — validation format `PPP/28CHARS`
- `generate_coverart_resolutions_t4` — 3 résolutions carrées depuis APIC
- `generate_coverart_resolutions_t3` — ratio préservé en 000
- `write_coverart_files` — écrit les 3 fichiers dans Coverart/
- `CoverArtImage` — dataclass (width, height, rgba_pixels)

### Tests
`tests/test_coverart.py` — 19 tests : roundtrip bit-perfect vérifié sur 36 vrais fichiers cache Traktor

### Scripts
`scripts/inspect_traktor.py` — diagnostic multi-commandes (scan, monitor, analyze, reverse-coverid, db-dump)

## Fait (session 2026-04-12)

### 1. Sérialiseur TRMD — DONE
`src/traktord/utils/trmd.py` (~280 lignes) :
- `Chunk` dataclass + `serialize()` récursif
- `parse_trmd()` / `parse_chunk()` — roundtrip bit-perfect vérifié sur Factory Sounds NI
- `build_artw_body()` / `parse_artw_body()` — format ARTW complet
- `generate_coverid()` — ID déterministe via SHA-256 + NI Base32
- `build_minimal_trmd()` — TRMD minimal (HDR_ v3 + DATA v20 + ARTW)
- `inject_artwork()` — injection PRIV:TRAKTOR4 + cache files
- `read_artwork()` — lecture depuis PRIV existante

Correction importante vs le rapport initial : DATA version = **20** (pas 19) pour Traktor Pro 4.

### 2. Test validation — DONE
- Injection sur 5 MP3 Beatport → artwork affiché dans Traktor Pro 4 ✓
- Frame PRIV + 3 fichiers cache (125x125, 75x75, 56x56) par track

### 3. Intégration CLI — DONE
`src/traktord/cli.py` :
- Option `--artwork` sur la commande `convert`
- Détection auto du dossier Coverart Traktor 4
- Progress bar Rich, skip silencieux si fichier absent ou sans APIC
- Usage : `traktor-convert convert export.xml --to traktor --artwork`

### Tests
`tests/test_trmd.py` — 30 tests (+ 19 tests coverart existants = 49 total)

## Ce qui reste à faire

### Problème Python 3.9 vs 3.11
Le venv utilise Python 3.9.6 mais `pyproject.toml` exige `>=3.11`.
Plusieurs modules (`track.py`, `keys.py`, `paths.py`) utilisent `int | None`
sans `from __future__ import annotations` → crash à l'import sous 3.9.
Soit upgrader le venv, soit ajouter le `from __future__` partout.

### Test de conversion complète
Lancer `traktor-convert convert data/ExportRB_03.2026.xml --to traktor --artwork`
sur la vraie collection de 5510 tracks pour valider à grande échelle.

### Amélirations possibles
- Préserver les chunks existants (AUID, CUEP, etc.) si un PRIV:TRAKTOR4 existe déjà
- Support FLAC/AIFF (pas que MP3)
- Option `--coverart-only` pour injecter les artworks sans regénérer le NML

## Fichiers de données disponibles

- `data/inspection/mp3_works/` — 5 MP3 Beatport avec APIC (+ PRIV injectées)
- `data/test_injection/` — copie de test utilisée pour la validation Traktor
- `data/inspection/coverart_sample/` — 6 sous-dossiers cache T4 + real collection.nml
- `data/Exemple/Traktor 4.4.2/` — structure complète Traktor 4 (depuis MacBook)
- `inspection_dump/` — scan complet MacBook (NMLs, DBs, caches T3+T4)
- `traktor_coverart_investigation/` — rapports reverse-engineering
- `data/ExportRB_03.2026.xml` — export Rekordbox réel (5510 tracks)
- `data/output/collection.nml` — NML généré par le converter (sans artworks)
