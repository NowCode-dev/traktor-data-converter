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
) -> dict:
    """Merge les cues Rekordbox dans la collection.nml Traktor.

    Args:
        rekordbox_collection: Collection Rekordbox parsee (avec cue_points).
        traktor_nml_path: Chemin vers le collection.nml de Traktor.
        overwrite_existing_cues: Si True, supprime les cues Traktor existants
            avant d'ajouter les cues Rekordbox. Si False, les cues s'accumulent.
        overwrite_grid: Si True, remplace aussi l'AutoGrid Traktor par celui
            de Rekordbox. Par defaut on garde le grid de Traktor (meilleur).

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

    for rb_track in rekordbox_collection.tracks:
        filename = Path(rb_track.file_path).name
        entry = traktor_entries.get(filename)

        if entry is None:
            not_matched += 1
            continue

        matched += 1

        # Nettoyer les cues existants si demande
        if overwrite_existing_cues:
            _remove_existing_cues(entry)

        # Ajouter le grid si demande (sinon garder celui de Traktor)
        if overwrite_grid and rb_track.grid_offset_ms is not None and rb_track.bpm:
            # Enlever le AutoGrid Traktor
            for cue in list(entry.findall("CUE_V2")):
                if cue.get("TYPE") == "4":
                    entry.remove(cue)
            _add_grid_to_entry(entry, rb_track.grid_offset_ms)

        # Ajouter les cues Rekordbox
        for i, cue in enumerate(rb_track.cue_points):
            _add_cue_to_entry(entry, cue, displ_order=i)
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
