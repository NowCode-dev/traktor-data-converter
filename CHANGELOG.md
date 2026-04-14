# Changelog — Traktor Data Converter

> Historique des sessions de travail

---

## [2026-04-14] — Approche 2 phases (init + merge-cues)

### Modifications
- `src/traktord/merge_cues.py` — Nouveau module : merge des cues Rekordbox dans la collection.nml Traktor apres son analyse
- `src/traktord/converters/traktor.py` — Parametre `include_cues` sur TraktorWriter.write() pour generer un NML sans cues
- `src/traktord/cli.py` — Nouvelles commandes `init` (Phase 1) et `merge-cues` (Phase 2)
- `src/traktord/gui.py` — Refonte en assistant 2 phases avec choix explicite
- `src/traktord/utils/trmd.py` — Ajout builders metadonnees (HBPM, MKEY, CUEP, TIT2, etc.) + `build_full_trmd()` et `inject_full_metadata()` (abandonne dans l'approche finale mais garde en library)
- `tests/test_trmd.py` — +10 tests (CUEP roundtrip, build_full_trmd)
- 59 tests verts au total

### Decisions
- **Abandon de l'injection PRIV:TRAKTOR4 complete** : apres test diagnostique (copie bit-perfect d'un vrai PRIV Factory Sounds dans un MP3 Beatport), Traktor rejette tout PRIV injecte. Il doit valider le PRIV contre l'audio du fichier. Impossible a reproduire sans reverse-engineer l'algorithme de hash audio.
- **Approche 2 phases adoptee** (suggestion de Lorys) :
  - Phase 1 : NML basique (sans cues) + artwork
  - Traktor analyse tout → genere des AUID/TRN3/CHKS valides lui-meme
  - Phase 2 : merge des cues Rekordbox dans la collection.nml analysee par Traktor
- FLGS=0x1C teste mais insuffisant pour empecher le rescan
- Les tags ID3 standard (COMM, POPM) sont toujours ecrits pour commentaires/rating
- GitHub repo rendu public pour distribution facile sur le MacBook de Lorys

### A faire (prochaine session)
- Terminer Phase 1 sur MacBook (Traktor analyse 5510 tracks, ~2-3h)
- Lancer Phase 2 (merge des cues)
- Verifier que les cues ne disparaissent plus au load dans les decks
- Si OK, valider aussi commentaires, rating, artworks
- Si OK, considerer le projet termine pour la migration Rekordbox → Traktor 4

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
