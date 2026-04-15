# Traktor Data Converter

Migrer votre bibliotheque **Rekordbox** vers **Traktor Pro 4** en preservant :

- Artworks (pochettes)
- Cue points et hotcues
- BPM et tonalite
- Commentaires et rating
- Playlists

## Pourquoi en 2 phases ?

Traktor Pro 4 ne lit plus les cues et metadonnees depuis le NML directement —
il utilise sa propre base interne alimentee par son analyse audio. Si vous
injectez des donnees dans le NML et laissez Traktor analyser apres, Traktor
ecrase tout.

La solution : **laisser Traktor analyser d'abord** (Phase 1), puis **ajouter
les cues Rekordbox** dans la collection.nml qu'il a deja analysee (Phase 2).
Les cues sont des donnees utilisateur que Traktor ne touche pas au load.

## Installation (macOS)

```bash
# Avec pip (recommande)
pip3 install --user git+https://github.com/NowCode-dev/traktor-data-converter.git

# Verification
python3 -m traktord.gui
```

Pre-requis :
- macOS 12+ (Ventura recommande)
- Python 3.9+
- Traktor Pro 4 installe et lance au moins une fois
- Export XML Rekordbox (File → Export Collection in xml format)

## Procedure complete A a Z

### 1. Preparer une collection Traktor vide (optionnel, recommande)

Si vous voulez partir d'une collection Traktor propre :

```bash
# Fermer Traktor
# Sauvegarder l'ancienne collection (au cas ou)
mv ~/Documents/Native\ Instruments/Traktor\ 4.4.2/collection.nml \
   ~/Documents/Native\ Instruments/Traktor\ 4.4.2/collection_avant.nml.bak

# Vider le cache Coverart (si vous voulez refaire les artworks proprement)
rm -rf ~/Documents/Native\ Instruments/Traktor\ 4.4.2/Coverart
```

### 2. Phase 1 — Import initial

```bash
python3 -m traktord.gui
# Choisir "1"
# Selectionner votre export Rekordbox (.xml)
```

Ce qui se passe :
- Parse de l'XML Rekordbox
- Injection des artworks (pochettes) dans les MP3 + cache Coverart
- Generation du `collection.nml` Traktor avec toutes les metadonnees
  (titre, artiste, BPM, key, commentaires, rating) **sans cues**

Les artworks s'afficheront dans le browser Traktor des l'ouverture.

### 3. Attendre l'analyse Traktor

Ouvrir Traktor Pro 4. Il va :
- Importer votre collection
- Analyser chaque track (BPM, key, beatgrid, transients)
- Generer son empreinte audio interne (AUID)

Ca peut prendre **2-3 heures pour 5000 tracks**. La status bar en bas de Traktor
montre "Scanning..." pendant l'analyse.

**Ne fermez pas Traktor tant que l'analyse n'est pas finie.**

### 4. Phase 2 — Merger les cues Rekordbox

Une fois l'analyse completement terminee :

```bash
# Fermer Traktor
python3 -m traktord.gui
# Choisir "2"
# Selectionner le meme export Rekordbox
```

Ce qui se passe :
- Lecture de la `collection.nml` Traktor (analysee)
- Ajout des cue points Rekordbox dans chaque entree
- Backup automatique avant modification

### 5. Verifier

Rouvrir Traktor. Charger un track dans un deck. Vous devriez voir :
- Les 4 hotcues Rekordbox sur les pads A/B/C/D
- Le BPM et la key analyses par Traktor
- L'artwork
- Le commentaire et le rating

Les cues **ne disparaissent plus** au rechargement ou au rescan.

## Commandes supplementaires

```bash
# Cleanup : supprimer les doublons dans la collection.nml
python3 -m traktord.gui
# Choisir "3"

# Afficher les infos d'un export Rekordbox
traktor-convert info export.xml

# Conversion CLI directe
traktor-convert init export.xml
# attendre analyse Traktor
traktor-convert merge-cues export.xml
```

## En cas de probleme

**Les cues ne s'affichent pas :**
- Verifier que l'analyse Traktor s'est bien terminee avant la Phase 2
- Verifier qu'il n'y a pas de doublons : `traktor-convert cleanup`
- Fermer Traktor avant de lancer Phase 2

**Les artworks ne s'affichent pas dans le browser :**
- Les tracks doivent etre charges au moins une fois dans un deck
- Ou re-faire la Phase 1 (qui ecrit le COVERARTID dans le NML)

**Restaurer un backup :**

Chaque phase cree un backup dans `~/Documents/Native Instruments/Traktor 4.4.2/Backup/`
avec un timestamp. Pour restaurer :

```bash
cp ~/Documents/Native\ Instruments/Traktor\ 4.4.2/Backup/collection_XXXXXXXX_XXXXXX.nml \
   ~/Documents/Native\ Instruments/Traktor\ 4.4.2/collection.nml
```

## Formats supportes

| Format | Lecture | Ecriture |
|--------|---------|----------|
| Rekordbox XML | Oui | - |
| Traktor NML | Oui | Oui |
| Serato | Prevu | Prevu |
| VirtualDJ | Prevu | Prevu |

## Developpement

```bash
git clone https://github.com/NowCode-dev/traktor-data-converter.git
cd traktor-data-converter
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest                  # 59 tests
ruff check src/         # Linter
```

## Licence

MIT — NowCode Sarl (nowcode.ch)
