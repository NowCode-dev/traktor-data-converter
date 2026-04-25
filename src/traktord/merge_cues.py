"""Merge des cues Rekordbox dans une collection.nml Traktor deja analysee.

Approche Phase 2 : apres que Traktor a fait son analyse complete
(BPM, key, beatgrid, transients, AUID), on injecte les cue points
Rekordbox dans la collection.nml existante sans toucher aux donnees
d'analyse de Traktor.

Les cues sont ajoutes comme elements <CUE_V2> dans chaque <ENTRY>.
Comme Traktor a deja ses AUID/TRN3 valides, il ne re-analysera pas
au load et les cues resteront.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from lxml import etree

from traktord.models.track import Collection, CuePoint


# Mapping CuePoint.type → NML TYPE (meme que dans converters/traktor.py)
_CUE_TYPE_TO_NML: dict[str, str] = {
    "cue": "0",
    "fade_in": "1",
    "fade_out": "2",
    "load": "3",
    "grid": "4",
    "loop": "5",
}


def _backup_nml(nml_path: Path) -> Path:
    """Sauvegarde le collection.nml avec timestamp avant modification."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = nml_path.parent / "Backup"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / f"collection_pre_merge_{timestamp}.nml"
    shutil.copy2(nml_path, backup)
    return backup


def _extract_filename_from_location(location_elem: etree._Element) -> str:
    """Extrait le FILE d'un element LOCATION."""
    return location_elem.get("FILE", "")


def _add_cue_to_entry(
    entry: etree._Element,
    cue: CuePoint,
    displ_order: int,
) -> None:
    """Ajoute un element CUE_V2 a une entree."""
    cue_elem = etree.SubElement(entry, "CUE_V2")
    cue_elem.set("NAME", cue.name or "")
    cue_elem.set("DISPL_ORDER", str(displ_order))
    cue_elem.set("TYPE", _CUE_TYPE_TO_NML.get(cue.type, "0"))
    cue_elem.set("START", f"{cue.position_ms:.6f}")
    cue_elem.set("LEN", f"{cue.length_ms:.6f}")
    cue_elem.set("REPEATS", "-1")
    cue_elem.set("HOTCUE", str(cue.hotcue))


def _add_grid_to_entry(entry: etree._Element, grid_offset_ms: float) -> None:
    """Ajoute un element AutoGrid (CUE_V2 TYPE=4) a une entree."""
    grid_cue = etree.SubElement(entry, "CUE_V2")
    grid_cue.set("NAME", "AutoGrid")
    grid_cue.set("DISPL_ORDER", "0")
    grid_cue.set("TYPE", "4")
    grid_cue.set("START", f"{grid_offset_ms:.6f}")
    grid_cue.set("LEN", "0.000000")
    grid_cue.set("REPEATS", "-1")
    grid_cue.set("HOTCUE", "-1")


def _add_load_cue(entry: etree._Element, position_ms: float, displ_order: int) -> None:
    """Ajoute un load cue (TYPE=3) — position de demarrage au load dans un deck.

    Le load cue prend par convention le pad 8 (HOTCUE=7) pour etre visible
    sur les pads tout en declenchant l'auto-jump au load. Si le pad 8 est
    deja occupe par un hot cue (cue avec TYPE=0 et HOTCUE=7), on cherche
    un pad libre en descendant 7 → 0. Si tous les pads sont pris, fallback
    HOTCUE=-1 (load cue fonctionnel mais invisible sur les pads).
    """
    # Pads deja occupes par les cues qu'on vient d'ajouter
    occupied = set()
    for cue in entry.findall("CUE_V2"):
        h = cue.get("HOTCUE", "-1")
        try:
            h_int = int(h)
            if 0 <= h_int <= 7:
                occupied.add(h_int)
        except ValueError:
            pass

    # Cherche le slot libre prefere : 7 (= pad 8 dans Traktor), puis 6, 5, ...
    chosen = -1
    for slot in (7, 6, 5, 4, 3, 2, 1, 0):
        if slot not in occupied:
            chosen = slot
            break

    load_cue = etree.SubElement(entry, "CUE_V2")
    load_cue.set("NAME", "Load")
    load_cue.set("DISPL_ORDER", str(displ_order))
    load_cue.set("TYPE", "3")
    load_cue.set("START", f"{position_ms:.6f}")
    load_cue.set("LEN", "0.000000")
    load_cue.set("REPEATS", "-1")
    load_cue.set("HOTCUE", str(chosen))


def _remove_existing_cues(entry: etree._Element) -> int:
    """Supprime les CUE_V2 existants (sauf beatgrid)."""
    removed = 0
    for cue in list(entry.findall("CUE_V2")):
        # On garde les AutoGrid (TYPE=4) de Traktor qui sont les bons apres analyse
        if cue.get("TYPE") != "4":
            entry.remove(cue)
            removed += 1
    return removed


def merge_cues(
    rekordbox_collection: Collection,
    traktor_nml_path: Path,
    overwrite_existing_cues: bool = True,
    overwrite_grid: bool = False,
    add_load_cue: bool = False,
) -> dict:
    """Merge les cues Rekordbox dans la collection.nml Traktor.

    Args:
        rekordbox_collection: Collection Rekordbox parsee (avec cue_points).
        traktor_nml_path: Chemin vers le collection.nml de Traktor.
        overwrite_existing_cues: Si True, supprime les cues Traktor existants
            avant d'ajouter les cues Rekordbox. Si False, les cues s'accumulent.
        overwrite_grid: Si True, remplace aussi l'AutoGrid Traktor par celui
            de Rekordbox. Par defaut on garde le grid de Traktor (meilleur).
        add_load_cue: Si True, ajoute un load cue (TYPE=3) a la position du
            premier hotcue. Le load cue determine ou Traktor demarre au load.

    Returns:
        Dict avec stats : matched, not_matched, total_cues_added.
    """
    if not traktor_nml_path.exists():
        raise FileNotFoundError(f"Collection Traktor introuvable : {traktor_nml_path}")

    # Backup
    backup = _backup_nml(traktor_nml_path)

    # Parser la collection Traktor
    tree = etree.parse(str(traktor_nml_path))
    root = tree.getroot()
    collection_elem = root.find("COLLECTION")
    if collection_elem is None:
        raise ValueError("COLLECTION element introuvable dans le NML")

    # Index des tracks Traktor par filename
    traktor_entries: dict[str, etree._Element] = {}
    for entry in collection_elem.findall("ENTRY"):
        location = entry.find("LOCATION")
        if location is not None:
            filename = _extract_filename_from_location(location)
            if filename:
                traktor_entries[filename] = entry

    # Matcher les tracks Rekordbox par filename
    matched = 0
    not_matched = 0
    total_cues_added = 0

    # Pour chaque filename, on peut avoir plusieurs entrees (doublons).
    # Priorite aux entrees avec AUDIO_ID (celles que Traktor a analysees).
    filename_to_entries: dict[str, list[etree._Element]] = {}
    for entry in collection_elem.findall("ENTRY"):
        location = entry.find("LOCATION")
        if location is not None:
            filename = _extract_filename_from_location(location)
            if filename:
                filename_to_entries.setdefault(filename, []).append(entry)

    for rb_track in rekordbox_collection.tracks:
        filename = Path(rb_track.file_path).name
        entries = filename_to_entries.get(filename, [])

        if not entries:
            not_matched += 1
            continue

        # Si plusieurs entrees pour ce filename, prioriser celles avec AUDIO_ID
        analyzed = [e for e in entries if e.get("AUDIO_ID")]
        entry = analyzed[0] if analyzed else entries[0]

        matched += 1

        # Nettoyer les cues existants si demande (sauf AutoGrid)
        if overwrite_existing_cues:
            _remove_existing_cues(entry)

        # Ajouter le grid si demande (sinon garder celui de Traktor)
        if overwrite_grid and rb_track.grid_offset_ms is not None and rb_track.bpm:
            # Enlever le AutoGrid Traktor
            for cue in list(entry.findall("CUE_V2")):
                if cue.get("TYPE") == "4":
                    entry.remove(cue)
            _add_grid_to_entry(entry, rb_track.grid_offset_ms)

        # Determiner le DISPL_ORDER de depart : apres les AutoGrids existants
        existing_grid_count = sum(
            1 for c in entry.findall("CUE_V2") if c.get("TYPE") == "4"
        )
        next_displ_order = existing_grid_count

        # Ajouter les cues Rekordbox
        for cue in rb_track.cue_points:
            _add_cue_to_entry(entry, cue, displ_order=next_displ_order)
            next_displ_order += 1
            total_cues_added += 1

        # Ajouter un load cue (TYPE=3) a la position du premier hotcue (pad A)
        if add_load_cue:
            first_hotcue = next(
                (c for c in rb_track.cue_points if c.hotcue == 0), None
            )
            if first_hotcue:
                _add_load_cue(entry, first_hotcue.position_ms, displ_order=next_displ_order)
                next_displ_order += 1
                total_cues_added += 1

        # Ajouter aussi commentaire et ranking si pas deja dans Traktor
        info = entry.find("INFO")
        if info is not None:
            if rb_track.comment and not info.get("COMMENT"):
                info.set("COMMENT", rb_track.comment)
            if rb_track.rating is not None and rb_track.rating > 0:
                ranking_val = rb_track.rating * 51  # 0-5 stars → 0/51/.../255
                if not info.get("RANKING"):
                    info.set("RANKING", str(ranking_val))

    # Reecrire le fichier
    tree.write(
        str(traktor_nml_path),
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
    )

    return {
        "matched": matched,
        "not_matched": not_matched,
        "total_cues_added": total_cues_added,
        "backup": backup,
    }


def update_coverart_ids(
    rekordbox_collection: Collection,
    traktor_nml_path: Path,
) -> dict:
    """Re-injecte les artworks et update les COVERARTID dans le NML existant.

    Flux non-destructif :
    1. Re-injecte l'artwork (avec selection APIC front cover) dans chaque MP3
    2. Re-ecrit les fichiers cache Coverart
    3. Update l'attribut COVERARTID dans INFO de chaque ENTRY du NML
    4. NE TOUCHE PAS aux CUE_V2, TEMPO, MUSICAL_KEY, LOUDNESS, AUDIO_ID

    Utilisation : quand on veut corriger juste les artworks sans declencher
    une re-analyse complete par Traktor.

    Args:
        rekordbox_collection: Collection Rekordbox (pour les chemins fichiers).
        traktor_nml_path: Chemin vers le collection.nml de Traktor.

    Returns:
        Dict avec stats : injected, skipped, nml_updated, backup.
    """
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )

    from .utils.trmd import inject_artwork

    if not traktor_nml_path.exists():
        raise FileNotFoundError(f"Collection Traktor introuvable : {traktor_nml_path}")

    # Backup avant modification
    backup = _backup_nml(traktor_nml_path)

    # Dossier Coverart a cote du NML
    coverart_dir = traktor_nml_path.parent / "Coverart"
    coverart_dir.mkdir(exist_ok=True)

    # 1. Re-injecter les artworks dans les MP3 + collecter les COVERARTID
    injected = 0
    skipped = 0
    path_to_coverid: dict[str, str] = {}

    total = len(rekordbox_collection.tracks)
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task("Re-injecting artworks", total=total)
        for track in rekordbox_collection.tracks:
            mp3_path = Path(track.file_path)
            if not mp3_path.exists() or mp3_path.suffix.lower() != ".mp3":
                skipped += 1
                progress.advance(task)
                continue

            try:
                coverid = inject_artwork(mp3_path, coverart_dir)
                if coverid:
                    path_to_coverid[mp3_path.name] = coverid
                    injected += 1
                else:
                    skipped += 1
            except Exception:
                skipped += 1

            progress.advance(task)

    # 2. Update NML : remplacer COVERARTID dans chaque INFO
    tree = etree.parse(str(traktor_nml_path))
    root = tree.getroot()
    collection_elem = root.find("COLLECTION")
    if collection_elem is None:
        raise ValueError("COLLECTION element introuvable")

    nml_updated = 0
    for entry in collection_elem.findall("ENTRY"):
        location = entry.find("LOCATION")
        if location is None:
            continue
        filename = location.get("FILE", "")
        new_coverid = path_to_coverid.get(filename)
        if not new_coverid:
            continue

        info = entry.find("INFO")
        if info is None:
            continue

        info.set("COVERARTID", new_coverid)
        nml_updated += 1

    tree.write(
        str(traktor_nml_path),
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
    )

    return {
        "injected": injected,
        "skipped": skipped,
        "nml_updated": nml_updated,
        "backup": backup,
    }


def add_new_tracks(
    rekordbox_collection: Collection,
    traktor_nml_path: Path,
    inject_artworks: bool = True,
) -> dict:
    """Ajoute uniquement les tracks Rekordbox absentes de la collection Traktor.

    Import incremental : seuls les nouveaux tracks sont ajoutes au NML.
    Traktor ne scannera que ces tracks-la (secondes au lieu d'heures).

    Flux :
    1. Compare Rekordbox XML avec le NML existant par filename
    2. Ajoute les ENTRY manquantes (sans cues, comme Phase 1)
    3. Injecte les artworks pour les nouveaux tracks seulement
    4. Ecrit les COVERARTID dans les nouvelles ENTRY
    5. Met a jour le compteur ENTRIES dans COLLECTION

    Args:
        rekordbox_collection: Collection Rekordbox parsee.
        traktor_nml_path: Chemin vers la collection.nml Traktor existante.
        inject_artworks: Si True, injecte les artworks dans les MP3.

    Returns:
        Dict avec stats : new_tracks, already_present, artworks_injected.
    """
    from .converters.traktor import _build_entry
    from .utils.trmd import inject_artwork

    if not traktor_nml_path.exists():
        raise FileNotFoundError(f"Collection Traktor introuvable : {traktor_nml_path}")

    backup = _backup_nml(traktor_nml_path)

    # Lire le NML existant
    tree = etree.parse(str(traktor_nml_path))
    root = tree.getroot()
    collection_elem = root.find("COLLECTION")
    if collection_elem is None:
        raise ValueError("COLLECTION element introuvable")

    # Index des filenames deja presents
    existing_filenames: set[str] = set()
    for entry in collection_elem.findall("ENTRY"):
        location = entry.find("LOCATION")
        if location is not None:
            existing_filenames.add(location.get("FILE", ""))

    # Trouver les nouveaux tracks
    new_tracks = 0
    already_present = 0
    artworks_injected = 0
    coverart_dir = traktor_nml_path.parent / "Coverart"

    for track in rekordbox_collection.tracks:
        filename = Path(track.file_path).name
        if filename in existing_filenames:
            already_present += 1
            continue

        # Injecter artwork si demande
        coverid = None
        if inject_artworks:
            mp3_path = Path(track.file_path)
            if mp3_path.exists() and mp3_path.suffix.lower() == ".mp3":
                coverart_dir.mkdir(exist_ok=True)
                try:
                    coverid = inject_artwork(mp3_path, coverart_dir)
                    if coverid:
                        artworks_injected += 1
                except Exception:
                    pass

        # Stocker coverid dans extra pour le writer
        if coverid:
            if not track.extra:
                track.extra = {}
            track.extra["coverartid"] = coverid

        # Construire l'ENTRY NML (sans cues — Phase 1 style)
        entry_elem = _build_entry(track, include_cues=False)
        collection_elem.append(entry_elem)
        new_tracks += 1

    # Mettre a jour le compteur
    total = len(collection_elem.findall("ENTRY"))
    collection_elem.set("ENTRIES", str(total))

    tree.write(
        str(traktor_nml_path),
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
    )

    return {
        "new_tracks": new_tracks,
        "already_present": already_present,
        "artworks_injected": artworks_injected,
        "total": total,
        "backup": backup,
    }


def cleanup_duplicates(traktor_nml_path: Path) -> dict:
    """Nettoie les entrees dupliquees dans la collection.nml Traktor.

    Quand on importe une collection et que Traktor re-analyse, il peut
    creer des doublons (meme filename, VOLUME different). Cette fonction
    garde uniquement l'entree avec AUDIO_ID (celle que Traktor a analysee)
    et supprime les autres.

    Args:
        traktor_nml_path: Chemin vers le collection.nml de Traktor.

    Returns:
        Dict avec stats : total_before, total_after, removed.
    """
    if not traktor_nml_path.exists():
        raise FileNotFoundError(f"Collection Traktor introuvable : {traktor_nml_path}")

    # Backup
    backup = _backup_nml(traktor_nml_path)

    tree = etree.parse(str(traktor_nml_path))
    root = tree.getroot()
    collection_elem = root.find("COLLECTION")
    if collection_elem is None:
        raise ValueError("COLLECTION element introuvable")

    # Grouper par filename
    filename_to_entries: dict[str, list[etree._Element]] = {}
    for entry in collection_elem.findall("ENTRY"):
        location = entry.find("LOCATION")
        if location is not None:
            filename = _extract_filename_from_location(location)
            if filename:
                filename_to_entries.setdefault(filename, []).append(entry)

    total_before = sum(len(v) for v in filename_to_entries.values())
    removed = 0

    # Pour chaque groupe de doublons, garder celle avec AUDIO_ID
    for filename, entries in filename_to_entries.items():
        if len(entries) <= 1:
            continue

        # Trier : AUDIO_ID d'abord, puis les autres
        with_audio = [e for e in entries if e.get("AUDIO_ID")]
        without_audio = [e for e in entries if not e.get("AUDIO_ID")]

        # Garder la premiere avec AUDIO_ID, supprimer les autres
        if with_audio:
            keep = with_audio[0]
            to_remove = with_audio[1:] + without_audio
        else:
            keep = entries[0]
            to_remove = entries[1:]

        for e in to_remove:
            collection_elem.remove(e)
            removed += 1

    # Mettre a jour le compte d'entries
    new_count = len(collection_elem.findall("ENTRY"))
    collection_elem.set("ENTRIES", str(new_count))

    tree.write(
        str(traktor_nml_path),
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
    )

    return {
        "total_before": total_before,
        "total_after": new_count,
        "removed": removed,
        "backup": backup,
    }


def find_traktor_collection_nml() -> Optional[Path]:
    """Trouve le collection.nml du Traktor 4 local."""
    ni_dir = Path.home() / "Documents" / "Native Instruments"
    if not ni_dir.exists():
        return None
    for d in sorted(ni_dir.iterdir(), reverse=True):
        if d.name.startswith("Traktor 4") and d.is_dir():
            nml = d / "collection.nml"
            if nml.exists():
                return nml
    return None
