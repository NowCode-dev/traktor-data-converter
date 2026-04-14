# Handoff — Traktor Data Converter (fin session 2026-04-14)

> Ce fichier contient tout le contexte pour reprendre le travail dans
> une nouvelle session Claude Code. Lis-le en premier.

## Etat actuel

**Lorys a lance la Phase 1 sur son MacBook.** Traktor analyse sa
bibliotheque de 5510 tracks (~2-3h). La Phase 2 (merge des cues)
sera lancee a la prochaine session, demain (2026-04-15).

## Objectif final

Migrer la bibliotheque Rekordbox (5510 tracks) vers Traktor Pro 4
en preservant : artworks, cues, BPM, key, commentaires, rating.

## Approche retenue : 2 phases

### Phase 1 — Import initial (faite)
- Genere un NML avec metadonnees de base (titre, artiste, album, BPM,
  key, commentaire, rating) **sans cue points**
- Injecte le PRIV:TRAKTOR4 minimal (artwork seul) + cache Coverart
- Utilisateur ouvre Traktor → analyse complete automatique
- Traktor genere ses propres AUID/TRN3/CHKS valides

Commande : `traktor-convert init export.xml`

### Phase 2 — Merge des cues (a faire demain)
- Parse l'XML Rekordbox pour les cues
- Lit la collection.nml Traktor apres analyse
- Match par filename, ajoute les `CUE_V2` dans les entrees existantes
- **Garde le beatgrid de Traktor** (option `--keep-grid` par defaut)
- Ecrit la collection.nml mise a jour + backup automatique

Commande : `traktor-convert merge-cues export.xml`

## Commandes a faire demain

Sur le MacBook, une fois l'analyse Traktor terminee et Traktor ferme :

```bash
pip3 install --user --force-reinstall git+https://github.com/NowCode-dev/traktor-data-converter.git
python3 -m traktord.gui
# Choisir "2"
# Selectionner le meme export.xml
# Confirmer

# Ou en CLI directe :
traktor-convert merge-cues /chemin/vers/export.xml
```

Puis rouvrir Traktor et verifier :
- Les 4 cues Rekordbox apparaissent bien sur les pads A/B/C/D
- Le beatgrid est correct (celui de Traktor)
- Les commentaires, rating, artwork restent
- **Charger un track dans un deck** → les cues ne disparaissent plus

## Pourquoi cette approche

### Ce qu'on a essaye et qui echoue
1. **Injection PRIV:TRAKTOR4 minimal (artwork seul)** : artwork OK mais
   tout le reste du NML est efface au rescan
2. **Injection PRIV:TRAKTOR4 complet** (HBPM, CUEP, MKEY, etc.) : meme
   avec FLGS=0x1C, Traktor re-analyse et efface
3. **Copie bit-perfect d'un PRIV Factory Sounds reel** dans un MP3
   Beatport : Traktor ignore completement le PRIV, affiche les tags
   ID3 originaux du MP3. Traktor valide probablement le PRIV contre
   l'audio du fichier (hash/fingerprint).

### Ce qui fonctionne
Laisser Traktor faire son analyse (il genere lui-meme les AUID/TRN3/
CHKS valides) puis rajouter nos cues dans la NML qu'il gere. Les
cues sont des donnees "utilisateur" que Traktor n'ecrase pas au load.

## Repo GitHub

- `NowCode-dev/traktor-data-converter` (public)
- Derniere version : commit `24ddbbb` (2026-04-14)
- Installation : `pip3 install --user git+https://github.com/NowCode-dev/traktor-data-converter.git`

## Environnement

- **Mac Mini local** (EXT_MINI01) : dev + tests preliminaires uniquement
- **MacBook Pro 2018** (Ventura 13.2.1) : environnement reel avec
  Traktor Pro 4.4.2 + Rekordbox + bibliotheque MP3
- Backup complet de la bibliotheque sur disque externe (fait par Lorys)

## Code actuel

### Modules cles
- `src/traktord/parsers/rekordbox.py` — Parser XML Rekordbox → Collection
- `src/traktord/converters/traktor.py` — TraktorWriter avec `include_cues=False`
  pour Phase 1
- `src/traktord/merge_cues.py` — Phase 2 : merge dans collection.nml
- `src/traktord/utils/trmd.py` — Serialiseur TRMD complet (utilise pour
  l'artwork minimal en Phase 1 ; `build_full_trmd` garde en library mais
  non utilise dans le flux 2 phases)
- `src/traktord/cli.py` — Commandes `init` + `merge-cues` + `convert` + `info`
- `src/traktord/gui.py` — Assistant interactif 2 phases

### Tests
59 tests verts (19 coverart + 40 trmd dont 10 nouveaux CUEP/full_trmd)

## Notes techniques importantes

- DATA version = 20 pour Traktor Pro 4 (pas 19)
- VRSN = 7 (format TRMD v7)
- Position cues en **millisecondes** float64 LE
- MKEY index 0-23 : 0-11 majeurs, 12-23 mineurs ; Am = 21
- Rekordbox key peut etre en Camelot ("8A", "1B") ou classique ("Am")
- Traktor NML version="19" (meme pour Traktor Pro 4)
- Le grid est un CUE_V2 TYPE=4 avec HOTCUE=-1 ; les hotcues user ont HOTCUE=0-7

## Scenario de bascule si Phase 2 echoue

Si demain les cues ne s'ajoutent pas correctement :
1. Verifier que le backup collection.nml existe (cree par merge_cues)
2. Restaurer si besoin depuis `Traktor 4.4.2/Backup/`
3. Debug : verifier que le match par filename fonctionne
4. Fallback : utiliser les file_path complets au lieu du basename
