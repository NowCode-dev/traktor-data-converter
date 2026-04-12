# Inspection Traktor — script de diagnostic

> Note pour l'agent qui execute ce script : tu lis ceci parce que Lorys
> a lance Claude Code sur son MacBook pour t'aider a finaliser le projet
> **Traktor Data Converter**. Le travail principal se fait sur le Mac mini
> avec une autre session, mais on a besoin d'infos qui ne sont accessibles
> que depuis ce MacBook (la vraie installation Traktor 4 et les fichiers
> de Lorys). Une fois ce script execute, tu transmettras les resultats
> a Lorys, qui les ramenera dans la session principale pour finaliser le
> code.

## Pourquoi ce script existe

Le converter convertit correctement Rekordbox -> Traktor pour les CUE,
BPM, beatgrids, playlists, mais **les artworks ne s'affichent pas dans
Traktor 4 apres import du NML**. On a deja determine que :

1. Les MP3 ont leurs frames APIC ID3 intactes (donc l'artwork EST present)
2. Le format binaire des fichiers cache Traktor a ete reverse-engineere
   (RGBA brut + header 9 bytes — a documenter dans le code final)
3. Le NML Traktor 4 (version 20) ne contient PLUS d'attribut COVERARTID
   — le mapping audio -> cache file est ailleurs

**Ce qui manque** pour terminer le code :
- Localiser la base interne ou Traktor 4 stocke le mapping
- Connaitre l'algorithme qui transforme un MP3 en nom de fichier cache
- Savoir si on peut forcer Traktor a regenerer le cache lui-meme

## Comment proceder (ordre recommande)

### NOUVEAU — Etape 0 : Reverse-engineering automatique du COVERARTID

L'etape la plus importante. Cette commande va automatiquement chercher
l'algorithme de hash que Traktor utilise pour generer les noms de
fichiers cache. Si elle reussit, le projet est debloque.

```bash
python3 scripts/inspect_traktor.py reverse-coverid
```

Le script va :
1. Trouver automatiquement le NML Traktor 3 (sous `~/Documents/Native
   Instruments/Traktor 3.X.X/collection.nml`)
2. Parser les entries qui ont un attribut COVERARTID
3. Pour chacune, retrouver le MP3 source sur le disque (typiquement dans
   `/Library/Application Support/Native Instruments/Traktor Pro 3/Factory Sounds/`)
4. Extraire la frame APIC ID3 du MP3 (le JPEG embarque, source des artworks)
5. Tester ~80 hashs candidats par entry (md5, sha1, sha256, blake2,
   xxhash, ripemd160 sur l'APIC original / re-encode JPEG / bitmap RGBA)
6. Comparer avec les bytes decodes du COVERARTID via l'alphabet Base32
   custom NI (`012345ABCDEFGHIJKLMNOPQRSTUVWXYZ`)
7. Quand un algo matche sur PLUSIEURS entries -> jackpot

A la fin, deux scenarios :

**Si l'algo est trouve** : le rapport `reverse_coverid_report.json` indique
clairement le hash gagnant (ex: `apic_full__sha1__alphabet_v1`). Donne
ce nom a Lorys, c'est suffisant pour finaliser le code.

**Si aucun algo ne matche** : le script sauvegarde quelques fichiers JPEG
APIC dans `./reverse_coverid_dump/` que Lorys ramenera dans la session
principale pour analyse plus poussee.

Donne donc dans tous les cas a Lorys :
- `reverse_coverid_report.json`
- Le contenu de `reverse_coverid_dump/` s'il existe

### Etape 1 — Inspection passive (pas d'interaction Traktor requise)

```bash
cd /chemin/vers/Traktor_data_converter
python3 scripts/inspect_traktor.py scan
```

Le script va :
- Detecter automatiquement les installations Traktor sous
  `~/Documents/Native Instruments/`
- Chercher les fichiers SQLite/realm/db dans
  `~/Library/Application Support/Native Instruments/`
- Echantillonner le dossier `Coverart/`
- Copier le tout dans `./inspection_dump/`
- Generer `inspection_dump/scan_report.json`

A la fin, **ZIPPE le dossier `inspection_dump/`** et donne-le a Lorys.

### Etape 2 — Capturer un mapping connu (Traktor doit etre ouvert)

```bash
python3 scripts/inspect_traktor.py monitor
```

Le script surveille `Coverart/` en temps reel. Pendant qu'il tourne :

1. Lorys ouvre Traktor
2. Lorys charge un track sur un deck (idealement un track qui n'a
   PAS son artwork affiche dans la liste — donc un track issu de la
   conversion Rekordbox)
3. Le script affiche en direct chaque fichier cache cree/modifie
4. **Lorys note dans un .txt** : track charge -> nom du fichier cache
5. Repete pour 3-5 tracks differents
6. Ctrl+C pour arreter

Si **aucun fichier n'est cree** apres avoir charge un track : Traktor
ne regenere pas son cache au "load on deck". C'est une mauvaise
nouvelle, mais c'est une info cruciale.

Si des fichiers SONT crees : super, on a notre mapping et la solution
est probablement automatisable.

### Etape 3 — Reverse du hash (avec un mapping en main)

Pour chaque track dont on a le mapping :

```bash
python3 scripts/inspect_traktor.py analyze /chemin/vers/track.mp3
```

Le script va :
- Lire l'APIC du MP3
- Generer une trentaine de hashes candidats (md5/sha1/sha256
  sur le path / l'APIC / les bytes audio, en hex/base32/base64)
- Chercher dans le Coverart un fichier dont le nom matche un de ces hashes

Si on trouve un match -> on connait l'algo, le projet peut etre finalise.

### Etape 4 — Si une DB SQLite a ete trouvee a l'etape 1

```bash
python3 scripts/inspect_traktor.py db-dump /chemin/de/la/db.sqlite
```

Dump le schema et un echantillon de chaque table. On y trouvera
peut-etre directement la table de mapping cover.

## Ce qu'il faut renvoyer a Lorys

A la fin de la session sur le MacBook, donne-lui :

1. Le ZIP de `inspection_dump/` (etape 1)
2. Le fichier `monitor_log.json` + son .txt manuel (etape 2)
3. Les fichiers `analyze_*.json` generes (etape 3)
4. Les fichiers `db_dump_*.json` generes (etape 4)

Lorys ramenera tout ca dans la session principale ou on finalisera le
module `src/traktord/utils/coverart.py` et son integration dans le
writer Traktor.
