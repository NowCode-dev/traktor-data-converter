# Travail en cours — Traktor Data Converter

**Derniere mise a jour** : 2026-04-25 fin de journee — Session bug bash livre, en attente retours tests Lorys

## Contexte

Bibliotheque DJ Lorys (Beatport, 5511 tracks) avec workflow Rekordbox → Traktor Pro 4. Resolution de plusieurs bugs accumules + ajout de 2 features.

## Etat

**v1.3.0 publiee + release GitHub** : https://github.com/NowCode-dev/traktor-data-converter/releases/tag/v1.3.0

6 versions livrees aujourd'hui :

| Version | Sujet |
|---|---|
| v1.1.0 | Fix encoder delay sur cues/beatgrid (~26 ms) |
| v1.1.1 | Fix channels artwork RGBA→BGRA |
| v1.1.2 | Fix import casse merge_cues |
| v1.1.3 | Progress bar reinject-artworks |
| v1.2.0 | Load cue Q1 RB → pad 8 Traktor par defaut |
| v1.3.0 | RELEASE_DATE precise au jour (TDRL/TDOR) |

Tests : 112/112 verts.

## Derniere action

Release v1.3.0 publiee sur GitHub avec notes consolidees.

## Prochaine etape

Lorys teste sur sa biblio reelle (MBP) depuis sa session du soir. Procedure recommandee a executer cote MBP :

```bash
pip3 install --user --force-reinstall git+https://github.com/NowCode-dev/traktor-data-converter.git@v1.3.0
python3 -m traktord.gui  # option 1 = init complet, sur ton export RB
```

Au retour de Lorys, on enchaine selon ce qu'il rapporte (nouveaux bugs eventuels ou validation OK).

## Decouvertes notables (a garder en tete)

- **MP3 Beatport tombent tous sur le fallback encoder_delay 1152 samples** (pas de header Xing/LAME). Compensation uniforme = 26.122 ms a 44.1 kHz.
- **Traktor 4 lit le cache Coverart en BGRA** (pas RGBA) — bug subtil qui affichait les bleus en orange.
- **Traktor 4 ne semble PAS toujours lire le cache Coverart au load** : le test rouge a montre que le deck affiche l'APIC du MP3 ou le PRIV:TRAKTOR4, pas necessairement le fichier `Coverart/PPP/XXX000`. Ce cache pourrait n'etre utile que pour le browser thumbnail.
- **macOS TCC bloque SSH d'acces a ~/Documents** : il a fallu ajouter `/usr/libexec/sshd-keygen-wrapper` a Full Disk Access sur le MBP pour pouvoir investiguer en SSH (cf. memoire `reference_macos_ssh_full_disk_access.md`).

## Sujets en suspens (non bloquants)

- Probleme **divergence d'analyse Traktor vs Rekordbox** sur le beatgrid (probleme 2 de la discussion initiale). Lorys avait observe en mix quelques tracks decales meme apres encoder delay fix. Pas reproduit jamais formellement, a creuser si confirme.
- Audit complet de la biblio pour confirmer que TOUS les MP3 tombent sur le fallback (= aucun avec header LAME). 8/8 testes OK, mais ratio statistique sur 5511 a verifier.

## Fichiers principaux modifies aujourd'hui

- `src/traktord/__init__.py` (version 0.1.0 → 1.3.0)
- `src/traktord/converters/traktor.py` (encoder delay + RELEASE_DATE precise)
- `src/traktord/utils/encoder_delay.py` (nouveau, v1.1.0)
- `src/traktord/utils/track_date.py` (nouveau, v1.3.0)
- `src/traktord/utils/coverart.py` (swap BGRA, v1.1.1)
- `src/traktord/merge_cues.py` (load cue pad 8 + progress bar + fix imports)
- `src/traktord/cli.py` + `src/traktord/gui.py` (default --load-cue=True)
- `tests/test_encoder_delay.py` + `tests/test_track_date.py` (nouveaux)
- `scripts/diag_encoder_delay.py` (nouveau, util si on doit re-tester encoder delay)
- `pyproject.toml` (version)
- `CHANGELOG.md` + `HANDOFF.md` (historique session)
