# Handoff — Traktor Data Converter

## ✅ Encoder delay compensation — release v1.1.0 (2026-04-25)

Le fix WIP du 20/04 a ete valide empiriquement le 25/04 sur 8 MP3 Beatport
(2013-2025). `_ENCODER_DELAY_SIGN = 1` est le bon signe : cues alignes au
ms pres avec Rekordbox apres import dans Traktor Pro 4.

Decouverte terrain : les MP3 Beatport tombent **tous** sur le fallback 1152
samples (pas de header Xing/LAME), donc compensation uniforme = 26.122 ms
a 44.1 kHz. Le cas "header LAME present" reste theorique pour la biblio
de Lorys.

Cf. `CHANGELOG.md` entry `[2026-04-25] — v1.1.0` pour le detail complet
et la procedure de validation utilisee (`scripts/diag_encoder_delay.py`).

Probleme separe **non resolu** (a attaquer plus tard) : divergence d'analyse
Traktor vs Rekordbox sur le beatgrid de certains tracks. Independant de
l'encoder delay.

---

# Handoff — Traktor Data Converter (fin session 2026-04-16)

> Ce fichier contient tout le contexte pour reprendre le travail dans
> une nouvelle session Claude Code. Lis-le en premier.

## Etat actuel

Le projet est **fonctionnel**. L'approche 2 phases a ete validee en
conditions reelles sur la bibliotheque complete de Lorys (5510 tracks).
Tous les bugs identifies ont ete corriges :

- Duplicatas NML (VOLUME="Mac HD")
- DISPL_ORDER conflictuel
- Artworks dans le browser (COVERARTID dans INFO)
- Selection de la bonne APIC (Cover Front)

**Lorys va refaire une procedure complete depuis zero** la prochaine
session pour valider que tout marche du premier coup sans commandes
de correction intermediaires.

## Objectif

Migrer une bibliotheque Rekordbox vers Traktor Pro 4 en preservant
artworks, cues, BPM, key, commentaires, rating, playlists.

## Procedure validee (2 phases)

### Phase 1 — Import initial
```bash
python3 -m traktord.gui  # Option 1
```
- Ecrit collection.nml Traktor avec metadonnees de base (sans cues)
- Injecte les artworks (PRIV:TRAKTOR4 ARTW + cache Coverart)
- Ecrit COVERARTID dans INFO du NML pour affichage browser

### Analyse Traktor
- Ouvrir Traktor Pro 4 → analyse auto (2-3h pour 5510 tracks)
- Traktor genere AUID/TRN3/beatgrid valides

### Phase 2 — Merge des cues
```bash
python3 -m traktord.gui  # Option 2
```
- Lit collection.nml analysee par Traktor
- Ajoute les cue_points Rekordbox dans chaque ENTRY
- Preserve AUDIO_ID, AutoGrid, LOUDNESS de l'analyse Traktor

### Options supplementaires
- Option 3 : `cleanup` — purger les doublons si necessaire
- Option 4 : `reinject-artworks` — re-injecter les artworks sans
  re-analyse Traktor (si fix APIC applique apres Phase 2)

## Bugs resolus et leurs solutions

| Bug | Cause | Fix |
|-----|-------|-----|
| Cues n'apparaissent pas | Duplicatas ENTRY (VOLUME different) | paths.py : VOLUME="Mac HD" |
| Cues cachees sur les pads | DISPL_ORDER=0 conflit AutoGrid | merge_cues.py : start after AutoGrid |
| Artwork uniquement visible au load | COVERARTID manquant dans NML | converters/traktor.py : ecrit COVERARTID |
| Artwork "pourri" (waveform aleatoire) | Premiere APIC != Cover Front | trmd.py : `_select_apic()` |
| Ranking/playlists perdus apres cleanup | cleanup cassait les references | OK maintenant (cleanup + merge_cues cooperent) |

## Architecture cle

### Pourquoi la 2 phases ?
Traktor 4 utilise `PRIV:TRAKTOR4` dans les MP3 comme source de verite
pour l'analyse (BPM/key/grid/transients/AUID). Si on injecte un PRIV
incomplet, Traktor rejette ou ecrase nos metadonnees au load. Meme la
copie bit-perfect d'un PRIV Factory Sounds reel est rejetee (validation
contre l'audio).

La solution : laisser Traktor analyser d'abord (il genere AUID valide),
puis augmenter le NML avec nos cues Rekordbox. Les cues sont des donnees
utilisateur que Traktor ne touche pas au rescan.

### Modules principaux
- `parsers/rekordbox.py` — XML Rekordbox → Collection
- `converters/traktor.py` — Collection → NML (avec include_cues=False pour Phase 1)
- `utils/trmd.py` — Serialiseur PRIV:TRAKTOR4 (artwork) + `_select_apic()`
- `utils/coverart.py` — Format cache Coverart (125x125 RGBA)
- `merge_cues.py` — Phase 2 : merge dans NML + cleanup + reinject-artworks
- `cli.py` — Commandes : init, merge-cues, cleanup, reinject-artworks, convert, info
- `gui.py` — Assistant terminal 2 phases + options

### Tests
59 tests verts (19 coverart + 40 trmd dont CUEP, build_full_trmd, roundtrip Factory Sounds)

## Repo GitHub

- `NowCode-dev/traktor-data-converter` (public)
- Derniere version : commit `54fefd8` (2026-04-16)
- Installation : `pip3 install --user git+https://github.com/NowCode-dev/traktor-data-converter.git`

## Environnement

- **Mac Mini local** (EXT_MINI01) : dev + tests preliminaires
- **MacBook Pro 2018** (Ventura 13.2.1) : environnement reel avec
  Traktor Pro 4.4.2 + Rekordbox + bibliotheque MP3 (5510 tracks)
- Backup complet de la bibliotheque sur disque externe

## Notes techniques

- VOLUME Traktor = "Mac HD" (pas "Macintosh HD" meme si c'est le nom systeme)
- DATA version = 20 pour Traktor Pro 4
- VRSN = 7, TRMD version = 2, HDR_ version = 3
- Position cues en millisecondes float64 LE
- MKEY index 0-23 : 0-11 majeurs, 12-23 mineurs
- COVERARTID format "PPP/28CHARS" via SHA-256 + NI Base32
- APIC type=3 = Cover Front (a prendre en priorite)

## Scenarios de reprise

**Si la prochaine procedure marche du premier coup :** projet termine.
Mettre a jour le README avec screenshots et consolider la doc.

**Si un probleme reste :** utiliser les commandes de correction :
- `cleanup` pour doublons
- `reinject-artworks` pour artworks
- `merge-cues` re-jouable sans souci (backup auto a chaque fois)
