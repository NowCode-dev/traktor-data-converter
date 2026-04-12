# Traktor Data Converter

## Description

Convertisseur multi-formats de bibliotheques DJ en ligne de commande.
Permet de migrer ses collections entre Traktor (Native Instruments), Rekordbox (Pioneer DJ), Serato DJ et VirtualDJ en preservant les metadonnees critiques : cue points, loops, beatgrids, BPM, key, playlists.

## Stack technique

- **Langage** : Python 3.11+
- **CLI** : Click 8.x
- **Parsing XML** : lxml
- **Modeles de donnees** : Pydantic 2.x
- **Affichage** : Rich (tableaux, progress bars, couleurs)
- **Linter/Formatter** : Ruff
- **Tests** : pytest + pytest-cov
- **Typage** : mypy (mode strict)
- **Build** : pyproject.toml (setuptools)

## Structure du projet

```
Traktor-data-Converter/
├── CLAUDE.md              # Ce fichier
├── README.md              # Documentation utilisateur
├── pyproject.toml         # Config projet, dependances, scripts
├── .gitignore
├── src/traktord/
│   ├── __init__.py        # Version
│   ├── cli.py             # Point d'entree CLI (Click)
│   ├── models/
│   │   ├── __init__.py
│   │   └── track.py       # Modele unifie Track/Collection/CuePoint
│   ├── parsers/           # Lecteurs de formats (NML, XML, etc.)
│   │   ├── __init__.py
│   │   ├── traktor.py     # Parser Traktor NML
│   │   ├── rekordbox.py   # Parser Rekordbox XML
│   │   ├── serato.py      # Parser Serato (DatabaseV2 + GEOB tags)
│   │   └── virtualdj.py   # Parser VirtualDJ database.xml
│   ├── converters/        # Ecrivains de formats
│   │   ├── __init__.py
│   │   ├── traktor.py     # Writer Traktor NML
│   │   ├── rekordbox.py   # Writer Rekordbox XML
│   │   ├── serato.py      # Writer Serato
│   │   └── virtualdj.py   # Writer VirtualDJ
│   └── utils/
│       ├── __init__.py
│       ├── detect.py      # Auto-detection du format source
│       ├── keys.py        # Conversion des notations musicales (Open Key, Camelot, classique)
│       └── paths.py       # Normalisation des chemins fichiers (Win/Mac/Linux)
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_traktor_parser.py
│   └── test_keys.py
├── data/
│   ├── samples/           # Fichiers NML/XML de test
│   └── output/            # Fichiers generes (gitignore)
├── docs/                  # Documentation technique
└── config/                # Fichiers de config (mappings de champs, etc.)
```

## Architecture : pattern Parser/Writer via modele intermediaire

```
[Traktor NML] ──► TraktorParser ──►┐
[Rekordbox XML] ► RekordboxParser ►├──► Collection(Track[]) ──►┬── TraktorWriter ──► [NML]
[Serato DB] ────► SeratoParser ───►│                           ├── RekordboxWriter ► [XML]
[VirtualDJ XML] ► VDJParser ──────►┘                           └── VDJWriter ──────► [XML]
```

Chaque parser convertit le format natif vers le modele `Track` unifie.
Chaque writer convertit depuis le modele `Track` vers le format cible.

## Formats supportes — details techniques

### Traktor NML (Native Instruments)
- **Fichier** : `collection.nml` (XML)
- **Elements cles** : `<ENTRY>` (morceau), `<LOCATION>` (chemin fichier), `<TEMPO>` (BPM), `<CUE_V2>` (cue points), `<MUSICAL_KEY>`, `<INFO>`, `<LOUDNESS>`
- **Cue types** : TYPE=0 (cue), TYPE=1 (fade-in), TYPE=2 (fade-out), TYPE=3 (load), TYPE=4 (grid)
- **Position cue** : en millisecondes (attribut START)
- **BPM** : attribut BPM sur element TEMPO, BPM_QUALITY en pourcentage
- **Key** : valeur entiere 1-12 sur MUSICAL_KEY

### Rekordbox XML (Pioneer DJ)
- **Fichier** : export XML via Rekordbox
- **Elements cles** : `<TRACK>` (morceau), `<POSITION_MARK>` (cue points), `<TEMPO>` (beatgrid)
- **Lib Python** : pyrekordbox peut lire le master.db (SQLCipher) et le XML
- **Position cue** : en secondes (attribut Start)
- **BPM** : attribut AverageBpm sur TRACK

### Serato DJ
- **Fichiers** : `_Serato_/database V2` (binaire), `.crate` (binaire)
- **Format binaire** : records concatenes (4-byte tag ASCII + 4-byte length big-endian + data)
- **Tags patterns** : `o*` (nested records), `t*` (UTF-16 BE text), `p*` (paths), `u*` (uint32 BE)
- **Cue points** : stockes dans les tags ID3 GEOB des fichiers audio (Markers_, Markers2, BeatGrid)
- **Complexite** : format non documente, reverse-engineere par la communaute (Mixxx, Holzhaus/serato-tags)
- **Important** : les cues voyagent AVEC les fichiers audio (tags GEOB), pas dans la DB — conversion Serato necessite mutagen pour lire/ecrire les tags ID3

### VirtualDJ
- **Fichier** : `database.xml`
- **Elements cles** : `<Song>` (morceau), `<Tags>` (metadata), `<Infos>` (stats), `<Scan>` (analyse), `<Poi>` (cue points)
- **BPM** : attention, Scan.Bpm stocke le temps entre 2 beats en secondes → BPM = 60 / Scan.Bpm
- **Poi types** : cue, loop, beatgrid avec attributs Pos, Type, Name, Num, Color

## Conventions de code

- **Nommage** : snake_case pour fonctions/variables, PascalCase pour classes
- **Imports** : tries par isort (integre dans Ruff)
- **Docstrings** : en francais, format Google style
- **Type hints** : obligatoires partout (mypy strict)
- **Largeur** : 100 caracteres max par ligne
- **Erreurs** : exceptions custom heritant de `TraktordError`

## Commandes utiles

```bash
# Installation en mode dev
pip install -e ".[dev]"

# Lancer le CLI
traktor-convert convert collection.nml --to rekordbox -o output.xml
traktor-convert info collection.nml

# Tests
pytest
pytest --cov=traktord

# Linter + formatter
ruff check src/
ruff format src/

# Type checking
mypy src/
```

## Regles importantes

- **Jamais de perte de donnees** : en cas de champ non mappable, le stocker dans `Track.extra` pour preservation
- **Chemins fichiers** : normaliser entre Windows (volume:\path) et Unix (/path) — Traktor utilise un format specifique avec VOLUME + DIR + FILE
- **Conversion BPM** : attention aux arrondis, conserver la precision maximale
- **Conversion Key** : supporter Open Key, Camelot et notation classique (Am, Cm, etc.)
- **Cue points** : les positions sont en ms (Traktor) vs secondes (Rekordbox) — toujours convertir
- **Serato** : format binaire complexe, commencer par read-only, ecriture dans un second temps
- **Backups** : toujours recommander a l'utilisateur de sauvegarder sa collection avant conversion
