# Changelog — Traktor Data Converter

> Historique des sessions de travail

---

## [2026-04-12] — Serialiseur TRMD, artworks fonctionnels, GUI, publication GitHub

### Modifications
- `src/traktord/utils/trmd.py` — Nouveau module : serialiseur/deserialiseur du format PRIV:TRAKTOR4 (Chunk, parse_trmd, build_artw_body, generate_coverid, build_minimal_trmd, inject_artwork, read_artwork)
- `src/traktord/utils/coverart.py` — Inchange (19 tests existants toujours verts)
- `src/traktord/cli.py` — Ajout option `--artwork` + fonction `_inject_artworks` avec progress bar Rich
- `src/traktord/gui.py` — Nouveau : assistant terminal interactif Rich + dialogues natifs macOS (osascript)
- `src/traktord/logo.png` — Logo NowCode integre au package
- `tests/test_trmd.py` — 30 tests (roundtrip bit-perfect sur vrais Factory Sounds NI)
- `pyproject.toml` — Ajout mutagen, Pillow, eval-type-backport ; requires-python abaisse a >=3.9 ; package-data pour le logo
- `.gitignore` — Exclusion des donnees lourdes (MP3, exports, dumps)
- `from __future__ import annotations` ajoute sur 6 fichiers pour compat Python 3.9
- Publie sur GitHub : NowCode-dev/traktor-data-converter (public)
- Installe et teste sur MacBook Pro 2018 (Ventura 13.2.1)

### Decisions
- DATA version = 20 (pas 19) pour Traktor Pro 4 — corrige par rapport au rapport initial
- tkinter abandonne (Aqua theme casse sur Ventura + dark mode) → Rich terminal + osascript
- customtkinter aussi teste et abandonne (meme probleme de rendu)
- COVERARTID genere de maniere deterministe via SHA-256 de l'APIC
- Repo GitHub passe en public (produit a distribuer/vendre)
- Compte lo-marrocco supprime, tout sur NowCode-dev

### Probleme decouvert
- Traktor 4 utilise PRIV:TRAKTOR4 comme source de verite, PAS le NML
- Le NML est ecrase au rescan → les metadonnees (cues, BPM, comments, rating) sont perdues
- Seuls les artworks survivent car ils sont dans le PRIV

### A faire
- Enrichir le PRIV:TRAKTOR4 avec toutes les metadonnees (HBPM, MKEY, CUEP, TIT2, TPE1, TALB, TLEN, BITR)
- Reverser le format CUEP (cue points) depuis les Factory Sounds
- Tester sur la copie disque externe (PAS les originaux du MacBook)
- Verifier que les metadonnees survivent au rescan de Traktor

---

## [2026-03-30] — Diagnostic du problème d'artworks

### Modifications
- Aucune modification de code (session d'analyse uniquement)

### Decisions
- Identification du problème : les pochettes/artworks ne s'affichent pas après conversion Rekordbox → Traktor
- Cause identifiée : le modèle `Track` n'a pas de champ artwork, le parser Rekordbox ignore `ArtworkPath`, le writer Traktor n'écrit rien pour l'artwork

### A faire
- Ajouter un champ `artwork_path: str = ""` au modèle `Track`
- Parser l'attribut `ArtworkPath` dans le parser Rekordbox
- Gérer l'artwork dans le writer Traktor (référence ou intégration ID3)
- Clarifier avec Lorys : artwork intégré dans les tags ID3 ou images séparées ?
