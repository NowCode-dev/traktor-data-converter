# Handoff — Traktor Data Converter (session 2026-04-12)

> Ce fichier contient tout le contexte pour reprendre le travail dans
> une nouvelle session Claude Code. Lis-le en premier.

## Objectif

Migrer une bibliotheque Rekordbox (5510 tracks) vers Traktor Pro 4
en preservant TOUTES les metadonnees : cues, BPM, key, commentaires,
rating, artworks.

## Architecture Traktor 4 (decouverte cle)

**Traktor 4 ne lit plus le NML pour les metadonnees.** Tout est dans
une frame ID3 proprietaire `PRIV:TRAKTOR4` stockee dans chaque MP3.
Le NML v20 est secondaire — quand Traktor rescanne un fichier, il
lit le PRIV et ecrase le NML.

**Consequence : il faut injecter les metadonnees dans le PRIV de
chaque MP3, pas seulement dans le NML.**

## Ce qui est fait

### Serialiseur TRMD (complet)
`src/traktord/utils/trmd.py` :
- `Chunk` dataclass + `serialize()` recursif
- `parse_trmd()` / `parse_chunk()` — roundtrip bit-perfect verifie
- `build_artw_body()` / `parse_artw_body()` — artwork complet
- `generate_coverid()` — ID deterministe SHA-256 + NI Base32
- `build_minimal_trmd()` — TRMD avec HDR_ v3 + DATA v20 + ARTW
- `inject_artwork()` — injection PRIV:TRAKTOR4 + cache files
- `read_artwork()` — lecture PRIV existante

### Module coverart (complet)
`src/traktord/utils/coverart.py` :
- Base32 NI, encode/decode cache, 3 resolutions, write cache files

### Tests (49 verts)
- `tests/test_coverart.py` — 19 tests
- `tests/test_trmd.py` — 30 tests (dont roundtrip sur vrais Factory Sounds)

### NML Writer (complet)
`src/traktord/converters/traktor.py` — genere NML correct

### CLI + GUI
- `src/traktord/cli.py` — CLI Click avec `--artwork`
- `src/traktord/gui.py` — assistant terminal Rich + dialogues natifs macOS
- Publie sur GitHub : `NowCode-dev/traktor-data-converter` (public)
- Installe et teste sur MacBook Pro 2018 (Ventura 13.2.1)

### Validation
- Artworks affiches dans Traktor Pro 4 ✓ (confirme par screenshot)
- Mais metadonnees perdues au rescan (commentaires, rating, cues)

## Ce qui reste a faire (priorite haute)

### Enrichir le PRIV:TRAKTOR4 avec les metadonnees

Modifier `build_minimal_trmd()` → `build_full_trmd()` qui inclut :

| Chunk | Format | Source Rekordbox | Priorite |
|---|---|---|---|
| HBPM | float32 LE | track.bpm | Haute |
| BPMQ | float32 LE (100.0) | fixe | Haute |
| MKEY | int32 LE | track.key (converti) | Haute |
| TKEY | UTF-16 LE (strlen + data) | track.key (string) | Haute |
| CUEP | binaire variable | track.cue_points | Haute |
| TIT2 | UTF-16 LE (strlen + data) | track.title | Haute |
| TPE1 | UTF-16 LE (strlen + data) | track.artist | Haute |
| TALB | UTF-16 LE (strlen + data) | track.album | Moyenne |
| TLEN | int32 LE (ms) | track.duration | Moyenne |
| BITR | int32 LE | track.bitrate | Moyenne |
| FLGS | int32 LE | flags standard | Basse |
| IPDT | int32 LE (timestamp) | date import | Basse |

### Methode recommandee

1. **Analyser les chunks existants** des Factory Sounds pour comprendre
   le format exact de chaque chunk (surtout CUEP et les strings UTF-16)
2. **Coder les builders** pour chaque chunk
3. **Tester sur la copie** du disque externe (PAS les originaux)
4. **Verifier dans Traktor** que les metadonnees survivent au rescan

### Format des strings dans TRMD (observe)

Les chunks texte (TIT2, TPE1, TALB, TKEY, LMDT) utilisent :
```
bytes 0-3 : uint32 LE = longueur en caracteres
bytes 4-N : UTF-16 LE (strlen * 2 bytes)
```

### Format CUEP (a reverser)

Le chunk CUEP fait 52-396 bytes dans les Factory Sounds.
Il faut reverser le format exact (probablement une liste de cue points
avec type, position, longueur, nom, couleur).

## Donnees de reference

### Vrais fichiers avec PRIV:TRAKTOR4 complet
```
/Library/Application Support/Native Instruments/Traktor Pro 4/Factory Sounds/*.mp3
```
→ Contiennent tous les chunks (CUEP, HBPM, MKEY, etc.)
→ Utiliser pour reverser le format de chaque chunk

### Fichiers de test
- `data/inspection/mp3_works/` — 5 MP3 Beatport (PRIV injectee artwork only)
- `data/test_injection/` — copie de test
- `data/ExportRB_03.2026.xml` — export Rekordbox reel (5510 tracks)

### Bibliotheque MacBook
- **Originaux** : sur le MacBook + backup disque externe
- **NE PAS modifier les originaux** — travailler sur la copie
- Traktor 4.4.2 sur le MacBook

## Environnement

- Dev : Mac (disque externe EXT_MINI01), Python 3.9 dans .venv
- MacBook : MacBook Pro 2018, Ventura 13.2.1, Python 3.9 (Xcode CLT)
- tkinter CASSE sur le MacBook (Aqua theme + dark mode) → utiliser Rich
- GitHub : `NowCode-dev/traktor-data-converter` (public)

## Notes techniques

- DATA version = **20** (pas 19 comme dans le rapport initial)
- VRSN = 7 (format TRMD v7)
- TRMD root version = 2
- HDR_ version = 3
- 180 bytes de padding nul apres le TRMD dans le PRIV (ignorable)
- SYNC est un conteneur (3 enfants : LMDT, LOCK, MATY)
- `from __future__ import annotations` sur tous les .py (Python 3.9)
- `eval-type-backport` requis pour Pydantic sous 3.9
