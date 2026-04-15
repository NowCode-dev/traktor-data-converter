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

    # Backup + ecriture NML sans cues
    backup = _backup_collection(traktor_dir)
    if backup:
        console.print(f"  Backup : [dim]{backup.name}[/]")

    nml_path = traktor_dir / "collection.nml"
    console.print("[cyan]Ecriture du NML (sans cues pour Phase 1)...[/]")
    writer = TraktorWriter()
    writer.write(collection, str(nml_path), include_cues=False)
    console.print(f"  [green]OK[/] {nml_path}")

    # Injection artworks (PRIV:TRAKTOR4 minimal + cache files)
    if inject_artworks:
        from traktord.utils.trmd import inject_artwork
        coverart_dir = traktor_dir / "Coverart"
        coverart_dir.mkdir(exist_ok=True)

        injected = 0
        skipped = 0

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
                        result = inject_artwork(mp3, coverart_dir)
                        if result:
                            injected += 1
                        else:
                            skipped += 1
                    except Exception:
                        skipped += 1
                else:
                    skipped += 1
                progress.advance(task)

        console.print(f"  [green]{injected}[/] artworks injectes, {skipped} ignores")

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

    console.print()
    console.print(Panel(
        "[bold cyan]Traktor Data Converter[/]\n"
        "[dim]Rekordbox  \u2192  Traktor Pro 4[/]\n\n"
        "[dim]Migration en 2 phases :[/]\n"
        "[dim]1. Import NML + artworks → Traktor analyse[/]\n"
        "[dim]2. Merge des cues dans la collection analysee[/]\n\n"
        "[dim]NowCode Sarl — nowcode.ch[/]",
        border_style="cyan",
        padding=(1, 4),
    ))

    # Choix de phase
    console.print("\n[bold]Que veux-tu faire ?[/]")
    console.print("  [cyan]1[/] — Phase 1 : Import initial (NML + artworks)")
    console.print("  [cyan]2[/] — Phase 2 : Merge des cues (apres analyse Traktor)")
    console.print("  [cyan]3[/] — Cleanup : nettoyer les doublons de la collection.nml")
    phase = Prompt.ask("Choix", choices=["1", "2", "3"], default="1")

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
