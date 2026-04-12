# Traktor Data Converter

Convertisseur multi-formats de bibliotheques DJ en ligne de commande.

Migrez vos collections entre **Traktor**, **Rekordbox**, **Serato** et **VirtualDJ** en preservant cue points, loops, beatgrids, BPM, tonalites et playlists.

## Installation

```bash
# Cloner le repo
git clone https://github.com/NowCode-dev/traktor-data-converter.git
cd traktor-data-converter

# Installer en mode dev
pip install -e ".[dev]"
```

## Utilisation

```bash
# Convertir une collection Traktor vers Rekordbox
traktor-convert convert collection.nml --to rekordbox -o output.xml

# Convertir Rekordbox vers VirtualDJ
traktor-convert convert rekordbox.xml --to virtualdj -o database.xml

# Afficher les infos d'une collection
traktor-convert info collection.nml
```

## Formats supportes

| Format | Lecture | Ecriture |
|--------|---------|----------|
| Traktor NML | Oui | Oui |
| Rekordbox XML | Oui | Oui |
| Serato | Prevu | Prevu |
| VirtualDJ | Prevu | Prevu |

## Developpement

```bash
pytest              # Tests
ruff check src/     # Linter
ruff format src/    # Formatter
mypy src/           # Type checking
```

## Licence

MIT - NowCode Sarl
