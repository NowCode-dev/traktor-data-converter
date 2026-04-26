# Changelog — Traktor Data Converter

> Historique des sessions de travail

---

## [2026-04-26] — v1.9.1 — Stats par source dans find_missing_artworks

### Resume

Apres test V1.9.0 par Lorys (5500 tracks, 690 trouves online), le label
GUI disait encore "Found via iTunes" alors que la majorite vient en
realite de Beatport / Discogs. Patch cosmetique :

- Renomme `Found via iTunes` -> `Found online` dans la GUI
- Ajoute la ventilation par source : Beatport / Discogs / MusicBrainz / iTunes
- `find_cover_cascade` retourne maintenant `tuple[bytes | None, source | None]`
  pour permettre le tracking par source
- `find_missing_artworks` retourne un nouveau champ `found_by_source`
  (dict {beatport, discogs, musicbrainz, itunes})

### Modifications

- `src/traktord/utils/artwork_search.py` :
  `find_cover_cascade` retourne `tuple[Optional[bytes], Optional[str]]`.
  Le 2e element est le nom de la source qui a matche.
- `src/traktord/merge_cues.py` :
  `find_missing_artworks` tracke `found_by_source` et l'ajoute aux stats.
- `src/traktord/gui.py` :
  Panel de l'option 7 affiche maintenant le breakdown par source.
- `tests/test_artwork_search.py` :
  Adaptation au nouveau type de retour (25 tests passent).

### Breaking change

L'API de `find_cover_cascade` change : retour `tuple` au lieu de `bytes`.
Code externe qui consomme directement la fonction doit etre mis a jour.
Pas de consommateurs externes connus a ce stade.

---

## [2026-04-26] — v1.9.0 — Find missing artworks : cascade multi-sources

### Resume

V1.8.0 cherchait uniquement sur iTunes. Sur la biblio underground techno
de Lorys (Beatport), iTunes ne match que ~3-4% des tracks (44/1240 lors
du run de test). V1.9.0 introduit une cascade ordonnee de 4 sources qui
visent specifiquement le catalogue electronique :

1. **Beatport via TrackID** extrait du filename (`(MM-YYYY)-(ID)_artist-title-mix-label`)
   — rapide et fiable pour les achats Beatport recents. Scrape passif
   du tag og:image sur la page produit (HD 1400x1400 directement).
2. **Discogs** via API publique (sans token, ou token user gratuit via
   env var `DISCOGS_TOKEN` pour rate limit 60 req/min au lieu de 25).
   Recherche release + fetch detail pour recuperer l'image primary.
3. **MusicBrainz + Cover Art Archive** : MBID release recupere via
   l'API MB (rate limit 1 req/s respecte), puis fetch CAA front-1200.
4. **iTunes** : fallback final pour la pop / commercial (logique V1.8.0
   preservee, factorisee dans `_search_itunes`).

Premier match >= seuil de confiance (0.7) gagne. Beatport TrackID
est pris sans fuzzy match (le TrackID est deterministe).

### Modifications

- `src/traktord/utils/artwork_search.py` :
  - `find_cover_cascade(artist, title, file_path=None, discogs_token=None)`
    nouvelle API publique
  - `_search_beatport_id(file_path)` extrait le TrackID via regex et
    fetch og:image
  - `_search_discogs(artist, title, token, threshold)` cherche release,
    fetch detail, prend image primary
  - `_search_musicbrainz(artist, title, threshold)` cherche recording,
    suit jusqu'a 3 releases, fetch CAA front
  - `_search_itunes(artist, title, threshold)` factorise la logique V1.8.0
  - `_mb_http_json` applique un rate limit 1 req/s pour MusicBrainz
  - `search_itunes_cover` conservee pour compat
- `src/traktord/merge_cues.py` :
  - `find_missing_artworks` utilise `find_cover_cascade` au lieu de
    `search_itunes_cover` et passe `file_path` pour permettre l'extraction
    Beatport TrackID
- `tests/test_artwork_search.py` (nouveau) : 25 tests sur regex Beatport,
  fuzzy match, ordre de cascade, court-circuit, resolution token

### Limitations

- **Beatport via recherche par nom** non implemente : la page de search
  est rendue cote client (CSR Next.js, pas dans le SSR), et l'API publique
  Beatport requiert OAuth. Fallback : pour les anciens fichiers sans
  TrackID dans le filename, on s'appuie sur Discogs et MusicBrainz.
- **Discogs sans token** = 25 req/min. Pour acceler sur 1000+ tracks,
  creer un token user (gratuit) sur `https://www.discogs.com/settings/developers`
  et le passer via env var `DISCOGS_TOKEN`.
- **Tracks tres recents (juillet 2025+)** souvent inconnus de Discogs
  et MusicBrainz. La source 1 (Beatport TrackID) couvre ce cas.

### Tests

- 153/153 passent (128 existants + 25 nouveaux dans test_artwork_search).
- Test live valide : Beatport TrackID `20629038` (DAETOR — No Hiding,
  Eastenderz) telecharge 152 KB d'image HD.

---

## [2026-04-26] — v1.8.0 — Find missing artworks online (iTunes Search API)

### Resume

Nouvelle commande pour les tracks dont le fichier audio n'a aucune cover
embedded (ni APIC ID3 ni covr MP4) : interroge l'iTunes Search API,
matche fuzzy sur artist + title, telecharge la cover HD (600x600) du
meilleur match si score >= 0.7, et l'injecte dans le fichier + cache
Traktor.

### Modifications

- `src/traktord/utils/artwork_search.py` (nouveau) :
  `search_itunes_cover(artist, title)` retourne les bytes JPEG ou None
- `src/traktord/utils/trmd.py` :
  `inject_external_cover(file_path, cover_bytes, coverart_dir)` ecrit
  une APIC ID3 (MP3/AIFF/WAV) ou un atom covr MP4 (M4A) puis appelle
  `inject_artwork` pour le pipeline standard (PRIV + cache)
- `src/traktord/merge_cues.py` :
  `find_missing_artworks(collection, nml_path)` parcourt la collection,
  filtre les tracks sans cover, query iTunes pour chaque, injecte si
  match suffisant, met a jour le NML
- `src/traktord/gui.py` : nouvelle option **7** dans le menu

### Limitations

- API iTunes uniquement pour V1 (sans cle, gratuite). Discogs / Beatport
  / MusicBrainz peuvent etre ajoutees en cascade plus tard.
- Threshold fuzzy match a 0.7 — tunable si trop strict ou trop laxiste.
- ToS iTunes Search API : usage zone grise pour utilisation commerciale
  via deck2deck.ch. A clarifier avant promotion massive.

### Tests

- 128/128 passent. Tests unitaires de `search_itunes_cover` non ajoutes
  (necessitent mocking HTTP, a faire si la feature stabilise).

---

## [2026-04-26] — v1.7.0 — Support M4A artwork (covr atom MP4)

### Resume

`inject_artwork` etend le support aux fichiers M4A/MP4/AAC en lisant
l'atom `covr` MP4 (different du tag ID3 APIC utilise par MP3/AIFF/WAV).
Apporte le cache Coverart Traktor pour les ~100 M4A typiques d'une biblio
DJ heritee d'iTunes.

### Modifications

- `src/traktord/utils/trmd.py` :
  - `_extract_cover_bytes()` (nouveau) : abstraction qui retourne les
    bytes de la cover + le container_type (`"ID3"` ou `"MP4"`)
  - `inject_artwork()` refactore : pour les MP3/AIFF/WAV (ID3) ecrit
    le PRIV:TRAKTOR4 dans le fichier comme avant. Pour les M4A (MP4),
    ecrit uniquement le cache Coverart (le format MP4 n'a pas
    d'equivalent PRIV ; Traktor lit le `covr` atom directement pour
    le deck et notre cache pour le browser thumbnail).
  - `SUPPORTED_AUDIO_EXTS` etendu : `.m4a`, `.mp4`, `.aac`

### Validation empirique

Test sur `01 Big Fun.m4a` (D.O.N.S, Dave Spoon Remix) du dossier Promo
& Divers de Lorys : injection reussie, `coverid="016/XVSRCTZ42B..."`,
cache files ecrits, COVERARTID disponible pour le NML au prochain
reinject-artworks.

### Tests

- 128/128 passent.

---

## [2026-04-26] — v1.6.1 — Apply AIFF/WAV support to all entry points

### Resume

v1.6.0 a etendu `inject_artwork` pour gerer AIFF/WAV, mais 3 callers
filtraient toujours `suffix == ".mp3"` AVANT d'appeler la fonction —
les AIFF/WAV etaient skippes silencieusement avant meme que le code
etendu n'ait sa chance.

Sur l'export reel de Lorys (5511 tracks) :
- v1.6.0 : 3729 injected, 1782 skipped (AIFF/M4A/WAV/etc.)
- v1.6.1 : devrait injecter ~530 AIFF supplementaires

### Modifications

- `src/traktord/utils/trmd.py` : nouvelle constante `SUPPORTED_AUDIO_EXTS`
  = `{".mp3", ".aiff", ".aif", ".wav"}`, exposee comme API publique
- `src/traktord/merge_cues.py` :
  - `update_coverart_ids` (option 4 / reinject-artworks)
  - `add_new_tracks` (option 5 / incremental import)
- `src/traktord/cli.py` `_inject_artworks_phase1` (commande `init`)
- `src/traktord/gui.py` `_run_phase1` (option 1 GUI)

### Note

`inject_full_metadata` (commande `convert` via `_inject_metadata`)
reste MP3-only pour l'instant — usage marginal, etendra plus tard
si besoin.

### Tests

- 128/128 passent.

---

## [2026-04-26] — v1.6.0 — Support AIFF and WAV in artwork injection

### Resume

`inject_artwork` etait limite aux MP3 (utilisait `mutagen.id3.ID3` direct).
Les AIFF et WAV avec tags ID3 embedded ne recevaient pas de cover dans
Traktor. Maintenant ces 3 formats sont traites uniformement via
`mutagen.File()` (detection auto du container) + `audio.save()` qui
preserve la structure du fichier.

### Cas concret

Lorys avait dans sa biblio plusieurs AIFF Booka Shade (achats Beatport
anciens 2013, doublons iTunes) avec 3 APICs chacun, mais Traktor
affichait "no artwork" car notre code skippait silencieusement les non-MP3.

### Modifications

- `src/traktord/utils/trmd.py` :
  - `_load_id3_container()` (nouveau) : ouvre via `mutagen.File()`,
    retourne `(tags, audio_obj)` ou `(None, None)` si non supporte
  - `inject_artwork()` refactore : prend `file_path: Path` (au lieu de
    `mp3_path`), accepte MP3/AIFF/WAV indistinctement, sauve via
    `audio.save()` qui preserve les chunks AIFF/RIFF WAV

### Limites encore presentes

- FLAC, Opus, OGG Vorbis, M4A : pas (encore) supportes, leur format
  d'artwork est different (METADATA_BLOCK_PICTURE, MP4 covr atom...).
  A faire au besoin.

### Tests

- 128/128 passent.

---

## [2026-04-26] — v1.5.1 — Fix slash in playlist names splitting hierarchy

### Resume

Bug fix : les playlists Rekordbox dont le nom contient un `/` (ex.
"Electronica / Downtempo", "Indie Dance / Nu Disco", "Minimal / Deep tech")
etaient incorrectement decoupees en plusieurs niveaux de hierarchie.
Resultat dans Traktor : un dossier "Electronica" contenant une playlist
"Downtempo", au lieu de la vraie playlist "Electronica / Downtempo".

### Cause

Le parser Rekordbox utilisait `/` comme separateur interne pour serialiser
les chemins de playlists hierarchises (`"Genres/Tech House"`). Or
Rekordbox autorise les `/` dans les noms de playlists, ce qui creait une
ambiguite. Le writer Traktor splittait alors a tort sur ces `/`.

### Fix

Constante `PLAYLIST_PATH_SEP = "\x00"` (NUL byte) introduite dans
`models/track.py` comme separateur interne. NUL ne peut pas apparaitre
dans un nom legitime, ce qui leve l'ambiguite. Parser et writer mis a
jour.

### Modifications

- `src/traktord/models/track.py` — exporte `PLAYLIST_PATH_SEP`
- `src/traktord/parsers/rekordbox.py` — utilise `PLAYLIST_PATH_SEP`
- `src/traktord/converters/traktor.py` — utilise `PLAYLIST_PATH_SEP` dans
  `_build_playlists` (split + join)
- `tests/test_rekordbox_parser.py` — assertion mise a jour

### Tests

- 128/128 passent.

---

## [2026-04-26] — v1.5.0 — Smart playlists multi-criteres (Genre OR, Artist, Comment)

### Resume

Detection des smart playlists etendue a 3 dimensions, avec multi-valeurs
en OR :
- **Genre OR** : top 1-3 genres distincts couvrant 95 % (au lieu d'un
  seul) — capture les playlists "Breaks" qui combinent "Breaks",
  "Breaks / Breakbeat / UK Bass", "Drum & Bass"
- **Artist OR** : top 1-3 artistes couvrant 95 % — capture
  "Sebastien Leger" avec les variantes featuring
- **Comment-tag** : 95 %+ des tracks ont un mot du nom playlist dans
  leur Comment — capture "Soft Track", "Hit Track", etc. (les playlists
  qui filtrent sur les tags Lorys ecrits dans Comments)

### Validation empirique

Sur l'export reel (5511 tracks, 136 playlists) :
- **V1.4** : 16 smart playlists detectees
- **V1.5** : 29 smart playlists detectees (+13)
  - 18 GENRE
  - 6 ARTIST
  - 5 COMMENT

Tous les patterns identifies par Lorys sont captures (Breaks, Dance,
Minimal/Deep tech, Sebastien Leger, Soft Track).

### Modifications

- `src/traktord/converters/traktor.py` :
  - `_detect_smart_match()` (refacto) — cascade GENRE -> ARTIST -> COMMENT,
    retourne `(field, values)` pour multi-valeurs
  - `_detect_dimension_match()` (nouveau) — accumulation top-N jusqu'a
    couverture 95 % avec garde-fou anti-faux-positif (au moins une valeur
    matche le nom de la playlist)
  - `_detect_comment_tag_match()` (nouveau) — recherche d'un token (>=3
    chars, hors stoplist) du nom playlist dans 95 %+ des Comments
  - `_build_smartlist_query()` accepte field + multi-values
- `src/traktord/cli.py` + `src/traktord/gui.py` — affichent la query
  complete dans le rapport (au lieu de juste le genre)
- `tests/test_smart_playlists.py` — etendu a 17 tests (les 3 strategies)

### Limites connues (V2 future)

V1.5 ne gere que des criteres OR sur une seule dimension. Pour les smart
playlists Rekordbox avec criteres AND/multi-dimension complexes
(genre AND BPM range AND rating), il faudra V2 = lecture de
`master.db` Rekordbox via `pyrekordbox`.

### Tests

- 128/128 passent (5 nouveaux + 12 mis a jour vs ancienne API).

---

## [2026-04-26] — v1.4.0 — Smart playlists "Genre = X" auto-detectees

### Resume

Les playlists Rekordbox du type "Genre = X" sont desormais converties en
**Traktor SMARTLIST** (avec `<SEARCH_EXPRESSION QUERY="$GENRE % ...">`)
au lieu de PLAYLIST statique. Couvre les playlists Genres typiques :
Techno, Tech House, Trance, Breaks, etc. Les autres playlists (statiques
ou non detectables) restent en LIST.

### Contexte

L'export XML Rekordbox aplatit toutes les smart playlists en listes
statiques (l'info des criteres est perdue avant qu'on lise). On detecte
donc heuristiquement les playlists "convention genre" :
- >=95 % des tracks de la playlist ont un genre qui contient le nom de
  la playlist (ou inversement), normalisation case-insensitive avec
  tirets/slashes -> espaces
- Capture les variantes : playlist "Techno" matche les genres "Techno",
  "Classic Techno", "Techno (Peak Time)", etc.

Sur l'export reel de Lorys (5511 tracks, 136 playlists) : 16 smart
playlists detectees automatiquement (Tech House, Techno, Trance, Breaks,
Deep House, etc.). Les 3 restantes ratent pour mismatch nommage
(playlist "Funky House" mais genres tracks = "Funk / Soul / Disco").

### Modifications

- `src/traktord/converters/traktor.py` :
  - `_detect_genre_smart_match()` (nouveau) — heuristique de detection
  - `_build_smartlist_query()` (nouveau) — construit la query avec
    variantes tiret/espace en OR
  - `_build_playlists()` ecrit `<NODE TYPE="SMARTLIST">` au lieu de
    `<NODE TYPE="PLAYLIST">` quand la convention match
  - `TraktorWriter.write()` accepte `smart_playlists` et `smart_detected`
- `src/traktord/cli.py` — flag `--smart-playlists/--no-smart-playlists`
  sur la commande `init` (default True). Affiche le rapport des smart
  detectees apres ecriture.
- `src/traktord/gui.py` — Phase 1 active smart_playlists par defaut +
  rapport (max 20 affichees, "+ N more" sinon)
- `tests/test_smart_playlists.py` — 11 tests unitaires

### Format Traktor SMARTLIST genere

```xml
<NODE TYPE="SMARTLIST" NAME="Tech House">
  <SMARTLIST UUID="...">
    <SEARCH_EXPRESSION VERSION="1"
      QUERY='$GENRE % "Tech House" | $GENRE % "Tech-House"'/>
  </SMARTLIST>
</NODE>
```

### Tests

- 123/123 passent (11 nouveaux).

---

## [2026-04-25] — v1.3.0 — RELEASE_DATE precise (jour) au lieu de juste l'annee

### Resume

Le champ `<INFO RELEASE_DATE="...">` du NML Traktor est maintenant rempli
avec la date precise au jour pres lue depuis le fichier audio (tag ID3
TDRL/TDOR), au lieu de l'annee seule transmise par Rekordbox. Cela permet
de trier la collection Traktor par date de release dans une colonne
browser, au jour pres.

### Modifications

- `src/traktord/utils/track_date.py` — nouveau module `get_release_date()`
  avec strategie en cascade :
    1. ID3 TDRL ou TDOR (Beatport remplit les deux) -> `YYYY/MM/DD`
    2. Filesystem birthtime (HFS+/APFS = date d'arrivee disque) -> `YYYY/MM/DD`
    3. ID3 TDRC + pattern `(MM-YYYY)` du filename -> `YYYY/MM`
    4. ID3 TDRC seul -> `YYYY`
    5. None -> fallback sur `track.year` Rekordbox
- `src/traktord/converters/traktor.py` — le writer NML appelle
  `get_release_date(track.file_path)` avant de tomber sur `track.year`
- `tests/test_track_date.py` — 8 tests unitaires (mock mutagen + birthtime)

### Validation empirique

8 MP3 Beatport (2013-2025) testes : tous renvoient une date complete
au jour pres via TDRL (Beatport remplit ce tag systematiquement).
Exemples : `2021/06/16`, `2025/01/24`, `2015/11/27`.

### Tests

- 112/112 passent (104 + 8 nouveaux).

---

## [2026-04-25] — v1.2.0 — Load cue (Q1 RB → Cue 8 Traktor) by default + visible on pad

### Resume

Le load cue (CUE_V2 TYPE=3) est maintenant ajoute par defaut a la position
du premier hotcue Rekordbox (Q1) et assigne au pad 8 Traktor (HOTCUE=7)
au lieu de l'invisible HOTCUE=-1. Comportement classique DJ : le track
demarre a Q1 au load et le pad 8 est utilisable pour rappeler la position.

### Modifications

- `src/traktord/merge_cues.py` — `_add_load_cue` cherche un pad libre dans
  l'ordre 7→0, fallback HOTCUE=-1 si tous occupes. Avant : toujours -1.
- `src/traktord/cli.py` — `--load-cue/--no-load-cue` default True (etait False)
- `src/traktord/gui.py` — Confirm Phase 2 default True (etait False)

### Migration

Les tracks deja convertis sans load cue (ou avec load cue invisible
HOTCUE=-1) ne sont pas modifies retroactivement. Pour les corriger :
relancer Phase 2 (merge-cues) sur l'export Rekordbox.

### Tests

- 104/104 passent.

---

## [2026-04-25] — v1.1.3 — Add progress bar to reinject-artworks

`update_coverart_ids` (commande `reinject-artworks` / GUI option 4) loop
silencieusement sur 5000+ tracks. Ajout d'une barre rich.Progress avec
spinner, count M/N, time elapsed et ETA.

### Modifications

- `src/traktord/merge_cues.py` — wrapping de la boucle d'injection avec
  `rich.progress.Progress`

### Tests

- 104/104 passent.

---

## [2026-04-25] — v1.1.2 — Fix broken import in merge_cues (reinject-artworks)

### Resume

Bug fix : `merge_cues.py` avait un import relatif casse `from .trmd
import inject_artwork` (ligne 257 et 355) qui pointait vers
`traktord.trmd` au lieu de `traktord.utils.trmd`. Resultat :
`reinject-artworks` et `update_coverart_ids` plantaient sur
`ModuleNotFoundError`.

### Modifications

- `src/traktord/merge_cues.py` — corrige les 2 imports :
  `from .trmd import inject_artwork` -> `from .utils.trmd import inject_artwork`

### Tests

- 104/104 passent.

---

## [2026-04-25] — v1.1.1 — Fix artwork color channels (RGBA -> BGRA)

### Resume

Bug fix : les artworks injectes dans le cache Coverart de Traktor 4
apparaissaient avec les channels rouge et bleu inverses (les bleus
devenaient orange et inversement). Cause : Traktor 4 lit les pixels en
BGRA, on ecrivait en RGBA. Le fix swappe R<->B au moment de l'ecriture
et de la lecture du cache.

### Modifications

- `src/traktord/utils/coverart.py` — `encode_coverart` swap RGBA->BGRA
  avant ecriture, `decode_coverart` swap BGRA->RGBA a la lecture. La
  representation interne `CoverArtImage.rgba_pixels` reste en RGBA
  (compatible PIL), seul le format on-disk change.

### Validation empirique

- Test discriminant sur le MacBook Pro : remplacement du fichier cache
  `145/H1ELPEJANINZSBKGEOPGXRNVCT1C000` (Cosmic Boys/AKKI - Dark Places)
  par une version avec R/B pre-swappes. Apres quit + relance Traktor,
  l'artwork est apparu en bleu correct (au lieu de l'orange precedent).
- Confirme via inspection de l'APIC du MP3 source : image bleue, donc
  c'etait bien notre encodage qui l'inversait.

### Suite cote utilisateur

Les caches deja generes par v1.1.0 ou avant sont en RGBA et continueront
a afficher avec channels inverses. Pour les regenerer : refaire la
Phase 1 `init` ou utiliser `reinject-artworks` apres mise a jour vers
v1.1.1.

### Tests

- 104/104 passent (les tests round-trip encode/decode restent valides
  car le swap est symetrique).

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
