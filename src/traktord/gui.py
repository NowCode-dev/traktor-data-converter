"""Interface interactive Traktor Data Converter.

Assistant en terminal avec Rich + dialogues fichiers natifs macOS.
Fonctionne sur toutes les versions de macOS sans probleme de rendu.
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
from rich.prompt import Confirm

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
# Dialogue fichier natif macOS (via osascript)
# ----------------------------------------------------------------------------

def _pick_file_macos() -> Optional[str]:
    """Ouvre un dialogue natif macOS pour choisir un fichier XML."""
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
    """Ouvre un dialogue natif macOS pour choisir un dossier."""
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
# Conversion
# ----------------------------------------------------------------------------

def _run_conversion(xml_path: str, traktor_dir: Path, inject_art: bool) -> None:
    """Execute la conversion avec affichage Rich."""
    from traktord.parsers.rekordbox import RekordboxParser
    from traktord.converters.traktor import TraktorWriter

    # Etape 1 : Parser
    console.print("\n[cyan]Lecture de l'export Rekordbox...[/]")
    parser = RekordboxParser()
    collection = parser.parse(xml_path)
    total = len(collection.tracks)
    console.print(f"  [green]{total}[/] tracks chargees")

    # Etape 2 : Backup + NML
    backup = _backup_collection(traktor_dir)
    if backup:
        console.print(f"  Backup : [dim]{backup.name}[/]")

    nml_path = traktor_dir / "collection.nml"
    console.print("[cyan]Ecriture du fichier Traktor...[/]")
    writer = TraktorWriter()
    writer.write(collection, str(nml_path))
    console.print(f"  [green]OK[/] {nml_path}")

    # Etape 3 : Artworks
    if inject_art:
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

    # Resume final
    console.print()
    console.print(Panel(
        f"[bold green]{total}[/bold green] tracks converties\n"
        + (f"[bold green]{injected}[/bold green] artworks injectes\n" if inject_art else "")
        + f"\nFichier : [cyan]{nml_path}[/]"
        + (f"\nBackup  : [dim]{backup.name}[/]" if backup else ""),
        title="[bold green]Conversion terminee[/]",
        border_style="green",
    ))


# ----------------------------------------------------------------------------
# Interface interactive
# ----------------------------------------------------------------------------

def main() -> None:
    """Point d'entree de l'interface interactive."""

    # Banniere
    console.print()
    console.print(Panel(
        "[bold cyan]Traktor Data Converter[/]\n"
        "[dim]Rekordbox  \u2192  Traktor Pro 4[/]\n\n"
        "[dim]NowCode Sarl — nowcode.ch[/]",
        border_style="cyan",
        padding=(1, 4),
    ))

    # Etape 1 : Choisir le fichier Rekordbox
    console.print("\n[bold]1.[/] Selectionner l'export Rekordbox (.xml)")
    console.print("   [dim]Une fenetre de selection va s'ouvrir...[/]")
    xml_path = _pick_file_macos()

    if not xml_path:
        console.print("   [red]Aucun fichier selectionne. Abandon.[/]")
        sys.exit(1)

    console.print(f"   [green]\u2713[/] {xml_path}")

    # Etape 2 : Dossier Traktor
    traktor_dir = _find_traktor4_dir()
    if traktor_dir:
        console.print(f"\n[bold]2.[/] Dossier Traktor 4 detecte :")
        console.print(f"   [cyan]{traktor_dir}[/]")
        if not Confirm.ask("   Utiliser ce dossier ?", default=True):
            console.print("   [dim]Selectionner le bon dossier...[/]")
            folder = _pick_folder_macos()
            if folder:
                traktor_dir = Path(folder)
            else:
                console.print("   [red]Aucun dossier selectionne. Abandon.[/]")
                sys.exit(1)
    else:
        console.print("\n[bold]2.[/] Dossier Traktor 4 non detecte.")
        console.print("   [dim]Selectionner le dossier manuellement...[/]")
        folder = _pick_folder_macos()
        if folder:
            traktor_dir = Path(folder)
        else:
            console.print("   [red]Aucun dossier selectionne. Abandon.[/]")
            sys.exit(1)

    console.print(f"   [green]\u2713[/] {traktor_dir}")

    # Etape 3 : Options
    inject_art = Confirm.ask(
        "\n[bold]3.[/] Injecter les artworks (pochettes) dans les MP3 ?",
        default=True,
    )

    # Resume avant conversion
    console.print()
    console.print(Panel(
        f"Source   : [cyan]{xml_path}[/]\n"
        f"Traktor  : [cyan]{traktor_dir}[/]\n"
        f"Artworks : {'[green]Oui[/]' if inject_art else '[dim]Non[/]'}",
        title="[bold]Recapitulatif[/]",
        border_style="cyan",
    ))

    if not Confirm.ask("Lancer la conversion ?", default=True):
        console.print("[dim]Abandon.[/]")
        sys.exit(0)

    # Go
    _run_conversion(xml_path, traktor_dir, inject_art)


if __name__ == "__main__":
    main()
