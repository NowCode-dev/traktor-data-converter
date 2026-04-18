"""Interface interactive Traktor Data Converter.

Approche 2 phases :
- Phase 1 : Import NML basique (sans cues) + artworks → Traktor analyse
- Phase 2 : Merge des cues Rekordbox dans la collection.nml apres analyse
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
from rich.prompt import Confirm, Prompt

console = Console()


# ----------------------------------------------------------------------------
# Detection automatique
# ----------------------------------------------------------------------------

def _find_traktor4_dir() -> Optional[Path]:
    ni_dir = Path.home() / "Documents" / "Native Instruments"
    if not ni_dir.exists():
        return None
    for d in sorted(ni_dir.iterdir(), reverse=True):
        if d.name.startswith("Traktor 4") and d.is_dir():
            return d
    return None


def _backup_collection(traktor_dir: Path) -> Optional[Path]:
    nml = traktor_dir / "collection.nml"
    if not nml.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = traktor_dir / "Backup"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / f"collection_{timestamp}.nml"
    shutil.copy2(nml, backup)
    return backup


# ----------------------------------------------------------------------------
# Dialogues natifs macOS (via osascript)
# ----------------------------------------------------------------------------

def _pick_file_macos() -> Optional[str]:
    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                'set f to POSIX path of (choose file of type {"xml"} '
                'with prompt "Selectionner l\'export Rekordbox (.xml)")'
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _pick_folder_macos() -> Optional[str]:
    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                'set f to POSIX path of (choose folder '
                'with prompt "Selectionner le dossier Traktor 4")'
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


# ----------------------------------------------------------------------------
# Phase 1 : Import initial (NML sans cues + artworks)
# ----------------------------------------------------------------------------

def _check_license(track_count: int) -> bool:
    """Verifie la limite de tracks. Retourne True si autorise."""
    from traktord.license import check_track_limit, GUMROAD_URL
    ok, msg = check_track_limit(track_count)
    if ok:
        console.print(f"  [dim]{msg}[/]")
        return True
    console.print()
    console.print(Panel(
        f"[red]{msg}[/]\n\n"
        f"[cyan]{GUMROAD_URL}[/]\n\n"
        "[dim]Activez votre licence : option 6 du menu principal[/]",
        title="[bold yellow]Limite atteinte[/]",
        border_style="yellow",
    ))
    return False


def _run_phase1(xml_path: str, traktor_dir: Path, inject_artworks: bool) -> None:
    """Phase 1 : NML sans cues + artwork pour que Traktor analyse."""
    from traktord.parsers.rekordbox import RekordboxParser
    from traktord.converters.traktor import TraktorWriter

    console.print("\n[cyan]Phase 1/2 — Import initial[/]\n")

    # Parser
    console.print("[cyan]Lecture de l'export Rekordbox...[/]")
    parser = RekordboxParser()
    collection = parser.parse(xml_path)
    total = len(collection.tracks)
    console.print(f"  [green]{total}[/] tracks chargees")

    # Verification licence
    if not _check_license(total):
        return

    backup = _backup_collection(traktor_dir)
    if backup:
        console.print(f"  Backup : [dim]{backup.name}[/]")

    # Injection artworks D'ABORD (pour avoir les COVERARTID a ecrire dans le NML)
    injected = 0
    skipped = 0
    if inject_artworks:
        from traktord.utils.trmd import inject_artwork
        coverart_dir = traktor_dir / "Coverart"
        coverart_dir.mkdir(exist_ok=True)

        console.print("[cyan]Injection des artworks...[/]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=40),
            MofNCompleteColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Artworks", total=total)

            for track in collection.tracks:
                mp3 = Path(track.file_path)
                if mp3.exists() and mp3.suffix.lower() == ".mp3":
                    try:
                        coverid = inject_artwork(mp3, coverart_dir)
                        if coverid:
                            # Stocker le coverid dans track.extra pour le writer
                            if not track.extra:
                                track.extra = {}
                            track.extra["coverartid"] = coverid
                            injected += 1
                        else:
                            skipped += 1
                    except Exception:
                        skipped += 1
                else:
                    skipped += 1
                progress.advance(task)

        console.print(f"  [green]{injected}[/] artworks injectes, {skipped} ignores")

    # Ecriture NML avec COVERARTID maintenant disponibles dans track.extra
    nml_path = traktor_dir / "collection.nml"
    console.print("[cyan]Ecriture du NML (sans cues pour Phase 1)...[/]")
    writer = TraktorWriter()
    writer.write(collection, str(nml_path), include_cues=False)
    console.print(f"  [green]OK[/] {nml_path}")

    # Instructions Phase 2
    console.print()
    console.print(Panel(
        "[bold]Phase 1 terminee ![/]\n\n"
        f"[cyan]Tracks importees :[/] {total}\n"
        f"[cyan]NML ecrit :[/] [dim]{nml_path}[/]\n\n"
        "[bold yellow]Prochaine etape :[/]\n"
        "1. Ouvre [cyan]Traktor Pro 4[/]\n"
        "2. Traktor va analyser les tracks (BPM, key, beatgrid, transients)\n"
        "3. Attends la fin de l'analyse (peut prendre plusieurs heures)\n"
        "4. Quand c'est fini, ferme Traktor\n"
        "5. Relance cet outil et choisis [cyan]Phase 2 — Merge des cues[/]",
        title="[bold green]Phase 1 OK[/]",
        border_style="green",
    ))


# ----------------------------------------------------------------------------
# Phase 2 : Merge des cues
# ----------------------------------------------------------------------------

def _run_phase2(xml_path: str, traktor_dir: Path) -> None:
    """Phase 2 : Merge les cues Rekordbox dans la collection.nml analysee."""
    from traktord.parsers.rekordbox import RekordboxParser
    from traktord.merge_cues import merge_cues

    console.print("\n[cyan]Phase 2/2 — Merge des cues[/]\n")

    # Parser l'XML Rekordbox pour les cues
    console.print("[cyan]Lecture des cues Rekordbox...[/]")
    parser = RekordboxParser()
    collection = parser.parse(xml_path)
    total = len(collection.tracks)
    total_cues = sum(len(t.cue_points) for t in collection.tracks)
    console.print(f"  [green]{total}[/] tracks, {total_cues} cues")

    # Verification licence
    if not _check_license(total):
        return

    # Merge
    nml_path = traktor_dir / "collection.nml"
    console.print(f"[cyan]Merge dans {nml_path}...[/]")

    stats = merge_cues(
        collection,
        nml_path,
        overwrite_existing_cues=True,
        overwrite_grid=False,  # Garder le grid de Traktor (meilleur)
    )

    # Resume
    console.print()
    console.print(Panel(
        f"[cyan]Tracks matchees :[/] [green]{stats['matched']}[/]\n"
        f"[cyan]Tracks non trouvees :[/] {stats['not_matched']}\n"
        f"[cyan]Cues ajoutes :[/] [green]{stats['total_cues_added']}[/]\n\n"
        f"[cyan]Backup :[/] [dim]{stats['backup'].name}[/]\n"
        f"[cyan]NML :[/] [dim]{nml_path}[/]\n\n"
        "[bold yellow]Prochaine etape :[/]\n"
        "Relance Traktor. Tes cues Rekordbox sont maintenant integres\n"
        "avec l'analyse Traktor. Ils ne devraient plus etre ecrases au rescan.",
        title="[bold green]Phase 2 OK[/]",
        border_style="green",
    ))


# ----------------------------------------------------------------------------
# Interface interactive
# ----------------------------------------------------------------------------

def main() -> None:
    """Point d'entree interactif."""

    from traktord.license import (
        is_licensed, load_license, validate_license_key, save_license,
        FREE_TRACK_LIMIT, GUMROAD_URL,
    )

    # Banniere
    license_status = "[green]Unlimited[/]" if is_licensed() else f"[yellow]Free ({FREE_TRACK_LIMIT} tracks)[/]"
    console.print()
    console.print(Panel(
        "[bold cyan]deck2deck[/]\n"
        "[dim]Rekordbox  \u2192  Traktor Pro 4[/]\n\n"
        f"Licence : {license_status}\n"
        "[dim]deck2deck.ch[/]",
        border_style="cyan",
        padding=(1, 4),
    ))

    # Choix de phase
    console.print("\n[bold]Que veux-tu faire ?[/]")
    console.print("  [cyan]1[/] — Phase 1 : Import initial (NML + artworks)")
    console.print("  [cyan]2[/] — Phase 2 : Merge des cues (apres analyse Traktor)")
    console.print("  [cyan]3[/] — Cleanup : nettoyer les doublons de la collection.nml")
    console.print("  [cyan]4[/] — Reinjecter les artworks (sans re-analyse Traktor)")
    console.print("  [cyan]5[/] — Ajouter de nouveaux tracks (import incremental)")
    console.print("  [cyan]6[/] — Activer une licence unlimited")
    phase = Prompt.ask("Choix", choices=["1", "2", "3", "4", "5", "6"], default="1")

    # Activation de licence
    if phase == "6":
        console.print()
        if is_licensed():
            console.print(f"[green]Licence deja active :[/] {load_license()}")
            return

        console.print(f"Achetez une licence sur : [cyan]{GUMROAD_URL}[/]")
        console.print("Entrez la cle recue par email apres achat.\n")
        key = Prompt.ask("Cle de licence")
        if validate_license_key(key):
            save_license(key)
            console.print("[bold green]Licence activee ! Tracks illimites.[/]")
        else:
            console.print("[red]Cle invalide. Verifiez le format : D2D-XXXXX-XXXXX-XXXXX-XXXXX[/]")
        return

    # Cleanup ne demande pas d'XML
    if phase == "3":
        traktor_dir = _find_traktor4_dir()
        if not traktor_dir:
            folder = _pick_folder_macos()
            if folder:
                traktor_dir = Path(folder)
            else:
                console.print("[red]Abandon.[/]")
                sys.exit(1)

        from traktord.merge_cues import cleanup_duplicates
        nml_path = traktor_dir / "collection.nml"
        if not nml_path.exists():
            console.print(f"[red]collection.nml introuvable[/]")
            sys.exit(1)

        console.print("\n[cyan]Cleanup des doublons en cours...[/]")
        stats = cleanup_duplicates(nml_path)
        console.print()
        console.print(Panel(
            f"Avant  : [yellow]{stats['total_before']}[/] entrees\n"
            f"Apres  : [green]{stats['total_after']}[/] entrees\n"
            f"Supprimees : [red]{stats['removed']}[/]\n\n"
            f"Backup : [dim]{stats['backup'].name}[/]",
            title="[bold green]Cleanup OK[/]",
            border_style="green",
        ))
        return

    # Selection du fichier Rekordbox
    console.print("\n[bold]Selectionner l'export Rekordbox (.xml)[/]")
    console.print("   [dim]Une fenetre de selection va s'ouvrir...[/]")
    xml_path = _pick_file_macos()

    if not xml_path:
        console.print("   [red]Aucun fichier selectionne. Abandon.[/]")
        sys.exit(1)

    console.print(f"   [green]\u2713[/] {xml_path}")

    # Dossier Traktor
    traktor_dir = _find_traktor4_dir()
    if traktor_dir:
        console.print(f"\n[bold]Dossier Traktor 4 detecte :[/] [cyan]{traktor_dir}[/]")
        if not Confirm.ask("Utiliser ce dossier ?", default=True):
            folder = _pick_folder_macos()
            if folder:
                traktor_dir = Path(folder)
            else:
                console.print("[red]Abandon.[/]")
                sys.exit(1)
    else:
        console.print("\n[bold]Dossier Traktor 4 non detecte.[/]")
        folder = _pick_folder_macos()
        if folder:
            traktor_dir = Path(folder)
        else:
            console.print("[red]Abandon.[/]")
            sys.exit(1)

    # Lancer la phase choisie
    if phase == "1":
        inject_art = Confirm.ask(
            "\nInjecter les artworks (pochettes) ?",
            default=True,
        )
        if not Confirm.ask("Lancer la Phase 1 ?", default=True):
            sys.exit(0)
        _run_phase1(xml_path, traktor_dir, inject_art)
    elif phase == "4":
        # Reinjecter les artworks sans toucher aux cues
        nml_path = traktor_dir / "collection.nml"
        if not nml_path.exists():
            console.print(f"[red]collection.nml introuvable[/]")
            sys.exit(1)

        console.print(Panel(
            "Re-injection des artworks dans les MP3 +\n"
            "update des COVERARTID dans le NML existant.\n\n"
            "[yellow]Ne touche PAS aux cues, BPM, key — pas de re-analyse Traktor.[/]",
            border_style="cyan",
        ))
        if not Confirm.ask("Lancer ?", default=True):
            sys.exit(0)

        from traktord.parsers.rekordbox import RekordboxParser
        from traktord.merge_cues import update_coverart_ids

        console.print(f"\n[cyan]Lecture de {xml_path}...[/]")
        parser = RekordboxParser()
        collection = parser.parse(xml_path)
        console.print(f"  [green]{len(collection.tracks)}[/] tracks")

        console.print("[cyan]Re-injection + update NML...[/]")
        stats = update_coverart_ids(collection, nml_path)

        console.print()
        console.print(Panel(
            f"Injectes       : [green]{stats['injected']}[/]\n"
            f"Skipped        : [dim]{stats['skipped']}[/]\n"
            f"Entries NML MAJ: [green]{stats['nml_updated']}[/]\n\n"
            f"Backup : [dim]{stats['backup'].name}[/]",
            title="[bold green]OK[/]",
            border_style="green",
        ))
    elif phase == "5":
        # Import incremental
        nml_path = traktor_dir / "collection.nml"
        if not nml_path.exists():
            console.print(f"[red]collection.nml introuvable — lance d'abord la Phase 1[/]")
            sys.exit(1)

        if not Confirm.ask("\nAjouter les nouveaux tracks ?", default=True):
            sys.exit(0)

        from traktord.parsers.rekordbox import RekordboxParser
        from traktord.merge_cues import add_new_tracks

        console.print(f"\n[cyan]Lecture de {xml_path}...[/]")
        parser = RekordboxParser()
        collection = parser.parse(xml_path)
        console.print(f"  [green]{len(collection.tracks)}[/] tracks dans l'export")

        console.print("[cyan]Import incremental...[/]")
        stats = add_new_tracks(collection, nml_path, inject_artworks=True)

        console.print()
        console.print(Panel(
            f"Nouveaux tracks   : [green]{stats['new_tracks']}[/]\n"
            f"Deja presents     : [dim]{stats['already_present']}[/]\n"
            f"Artworks injectes : [green]{stats['artworks_injected']}[/]\n"
            f"Total collection  : {stats['total']}\n\n"
            f"Backup : [dim]{stats['backup'].name}[/]",
            title="[bold green]Import incremental OK[/]",
            border_style="green",
        ))

        if stats["new_tracks"] > 0:
            console.print()
            console.print("[yellow]Prochaines etapes :[/]")
            console.print(f"  1. Ouvre Traktor → scanne {stats['new_tracks']} tracks (quelques minutes)")
            console.print(f"  2. Ferme Traktor")
            console.print(f"  3. Relance cet outil → Phase 2 (merge des cues)")

    else:
        nml_path = traktor_dir / "collection.nml"
        if not nml_path.exists():
            console.print(f"[red]collection.nml introuvable dans {traktor_dir}[/]")
            console.print("[yellow]Lance d'abord la Phase 1 et l'analyse Traktor.[/]")
            sys.exit(1)

        console.print()
        console.print(Panel(
            "[yellow]As-tu bien :[/]\n"
            "1. Lance la Phase 1 ?\n"
            "2. Ouvert Traktor ?\n"
            "3. Attendu la fin de l'analyse (BPM, key, beatgrid) ?\n"
            "4. Ferme Traktor ?",
            border_style="yellow",
        ))
        if not Confirm.ask("Lancer la Phase 2 ?", default=True):
            sys.exit(0)
        _run_phase2(xml_path, traktor_dir)


if __name__ == "__main__":
    main()
