# Changelog — Traktor Data Converter

> Historique des sessions de travail

---

## [2026-04-25] — v1.1.0 — Fix encoder delay sur cues et beatgrid

### Resume

Bug fix : les positions de cues et le beatgrid arrivaient decales d'environ
26 ms dans Traktor par rapport a Rekordbox sur les MP3. Cause : encoder
delay (silence de padding en debut de fichier) traite differemment selon
les formats. Cette release applique automatiquement la compensation au
moment de l'ecriture du NML — les cues sont desormais frame-accurate.

### Modifications

- `src/traktord/utils/encoder_delay.py` — nouveau module : lecture de
  l'encoder delay depuis les fichiers audio
  - MP3 → frame Xing/LAME via mutagen (fallback 1152 samples si absent)
  - M4A/AAC → atom iTunSMPB champ [1] en hex
  - Opus → header pre-skip (48 kHz)
  - FLAC/WAV/AIFF/OGG Vorbis → 0.0 (pas de padding)
- `src/traktord/converters/traktor.py` — le writer applique la compensation
  sur `grid_offset_ms` et chaque `cue.position_ms` lors de l'ecriture
  du NML. Constante `_ENCODER_DELAY_SIGN = 1`.
- `scripts/diag_encoder_delay.py` — script de diagnostic empirique :
  scanne des MP3 reels, croise avec un export Rekordbox, calcule les
  positions NML pour les 3 valeurs candidates de SIGN, genere un mini
  NML de test
- `tests/test_encoder_delay.py` — 11 tests unitaires (mock mutagen,
  fallbacks, tous les formats)
- `tests/test_traktor_writer.py` — fix chemin fixture (`traktord-data` →
  `data`, bug pre-existant, debloquait 13 tests)

### Validation empirique

- 8 MP3 Beatport (2013-2025) testes sur MacBook Pro avec Traktor Pro 4.4.2
  + Rekordbox 6.8.6
- Verification au sample pres via grep direct du collection.nml de Traktor
  apres import : positions ecrites = positions calculees (137.122 ms vs
  111 ms RB brut sur Old Tortures par ex.)
- A l'oreille et en cue play : alignement Traktor vs Rekordbox confirme
- Decouverte cote terrain : les MP3 Beatport tombent **tous** sur le
  fallback 1152 samples (pas de header Xing/LAME), le fix s'applique
  donc uniformement = 26.122 ms a 44.1 kHz

### Decisions

- Approche dispatch par format avec valeur autoritaire du fichier (pas
  d'heuristique), fallback 1152 samples pour les MP3 sans header Xing/LAME
- Fix silencieux : aucun flag CLI, correction automatique a chaque export
- Bump 0.1.0 → 1.1.0 (alignement avec le tag GitHub v1.0.0 du 19/04)

### Reste connu (pour suite)

Probleme separe non couvert ici : divergence d'analyse Traktor vs Rekordbox
sur le beatgrid (les deux softs detectent un BPM/grid_offset legerement
different sur certains tracks). C'est independant de l'encoder delay et
sera traite ulterieurement.

### Tests

- 104/104 passent

---

## [2026-04-19] — Release GitHub v1.0.0 + fix lien de telechargement

### Modifications
- Creation du tag `v1.0.0` et release GitHub avec notes completes (installation, usage, pricing)
- Le lien "Download" de deck2deck.ch pointe vers la page releases qui etait vide → maintenant fonctionnel

### Decisions
- Release GitHub plutot que changer les liens (plus propre, page avec instructions)

---

## [2026-04-18] — Systeme de licence freemium + lancement commercial

### Modifications
- `src/traktord/license.py` — Nouveau module : generation/validation cle, limite 25 tracks, fichier ~/.deck2deck-license
- `src/traktord/gui.py` — Verification licence en Phase 1 et 2, option "6" activation licence, banniere avec statut licence

### Decisions
- Cle universelle (meme pour tous les acheteurs) — suffisant pour $20, pas d'anti-piraterie
- Gumroad pour la vente (pas Odoo) — overkill pour un produit a $20
- Limite 25 tracks en mode gratuit

---

## [2026-04-17] — Import incremental + validation procedure complete

### Modifications
- `src/traktord/merge_cues.py` — Nouvelle fonction `add_new_tracks()` : import incremental qui n'ajoute que les tracks absentes de la collection Traktor existante
- `src/traktord/cli.py` — Nouvelle commande `add` pour l'import incremental
- `src/traktord/gui.py` — Option "5" (import incremental) dans le menu interactif

### Decisions
- Import incremental pour eviter le rescan de 2-3h a chaque ajout de tracks
- Match par filename entre Rekordbox XML et NML Traktor existant

### Validation
- Procedure complete A a Z validee par Lorys : Phase 1 → analyse Traktor → Phase 2. Tout fonctionne (cues, BPM, key, comments, rating, artworks)

---

## [2026-04-15 → 2026-04-16] — Debug complet procedure 2 phases, fix artworks, procedure stabilisee

### Modifications

**Fix duplicatas et DISPL_ORDER (2026-04-15) :**
- `src/traktord/utils/paths.py` — VOLUME="Mac HD" par defaut sur macOS (au lieu de "Macintosh HD") pour matcher ce que Traktor 4 utilise
- `src/traktord/merge_cues.py` — DISPL_ORDER commence apres les AutoGrids existants ; priorite aux entries avec AUDIO_ID quand doublons ; nouvelle fonction `cleanup_duplicates()` pour purger les entries sans AUDIO_ID
- `src/traktord/cli.py` — Nouvelle commande `cleanup`
- `src/traktord/gui.py` — Option "3" (cleanup) dans le menu

**Fix affichage artwork browser (2026-04-15) :**
- `src/traktord/converters/traktor.py` — Ecrit `COVERARTID` dans `INFO` si `track.extra["coverartid"]` defini (pour afficher l'artwork dans le browser sans loader le track)
- `src/traktord/cli.py` + `src/traktord/gui.py` — Phase 1 fait l'injection artwork AVANT l'ecriture du NML pour collecter les coverids
- `README.md` — Procedure complete A a Z avec reset, Phase 1, analyse Traktor, Phase 2, verification, restauration backup

**Fix selection APIC (2026-04-16) :**
- `src/traktord/utils/trmd.py` — Nouvelle fonction `_select_apic()` qui prend l'APIC type=3 (Cover Front) en priorite au lieu de la premiere APIC du MP3. Fallback sur type=0 (Other), 17 (Illustration), 18 (Artist logo), puis premiere disponible
- Applique a `inject_artwork()` et `inject_full_metadata()`

**Nouvelle commande non-destructive (2026-04-16) :**
- `src/traktord/merge_cues.py` — `update_coverart_ids()` : re-injecte artworks + update COVERARTID dans NML sans toucher aux cues/analyse
- `src/traktord/cli.py` — Commande `reinject-artworks`
- `src/traktord/gui.py` — Option "4" (reinject-artworks) dans le menu

### Decisions

- **VOLUME="Mac HD"** : nom interne utilise par Traktor Pro 4 meme quand le volume systeme macOS s'appelle "Macintosh HD". Sans ce fix, Traktor creait des doublons a chaque import et les playlists se retrouvaient vides
- **DISPL_ORDER apres AutoGrid** : l'AutoGrid de Traktor utilise DISPL_ORDER=0. Si nos hotcues partent aussi a 0, conflit silencieux et cues non affichees dans les pads
- **COVERARTID dans INFO** : Traktor utilise cet attribut pour afficher l'artwork dans le browser. Sans lui, il faut loader chaque track dans un deck pour que l'artwork apparaisse
- **Injection artwork AVANT ecriture NML** : pour collecter les COVERARTID et les ecrire dans le NML. Ordre critique
- **Selection APIC par type** : les MP3 Beatport/Rekordbox peuvent avoir plusieurs frames APIC (front cover, back, artist logo, voire waveform). Prendre la premiere etait faux et donnait des artworks aleatoires
- **Procedure 2 phases validee en conditions reelles** : Phase 1 → analyse Traktor → Phase 2. Les cues, BPM, key, commentaires, rating, artworks sont tous preserves. Au rechargement d'un track dans un deck, rien ne disparait

### Validation

- Cues Rekordbox correctement affiches sur les pads A/B/C/D apres Phase 2
- BPM, key, commentaires, rating preserves apres Traktor rescan
- Artworks affiches dans deck et (avec fix Cover Front) dans le browser
- 59 tests verts

### A faire (prochaine session)

- Lorys refait une procedure complete depuis zero (reset + Phase 1 + analyse + Phase 2) avec la derniere version du tool integrant tous les fixes
- Valider que tout fonctionne du premier coup sans commande `cleanup` ou `reinject-artworks`
- Si OK, le projet peut etre considere comme termine pour la migration Rekordbox → Traktor 4

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
