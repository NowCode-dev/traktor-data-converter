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
                'with prompt "Select Rekordbox export (.xml)")'
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
                'with prompt "Select Traktor 4 folder")'
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
        "[dim]Activate your licence: option 6 from the main menu[/]",
        title="[bold yellow]Limit reached[/]",
        border_style="yellow",
    ))
    return False


def _run_phase1(xml_path: str, traktor_dir: Path, inject_artworks: bool) -> None:
    """Phase 1 : NML sans cues + artwork pour que Traktor analyse."""
    from traktord.parsers.rekordbox import RekordboxParser
    from traktord.converters.traktor import TraktorWriter

    console.print("\n[cyan]Phase 1/2 — Initial import[/]\n")

    # Parser
    console.print("[cyan]Reading Rekordbox export...[/]")
    parser = RekordboxParser()
    collection = parser.parse(xml_path)
    total = len(collection.tracks)
    console.print(f"  [green]{total}[/] tracks loaded")

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

        console.print("[cyan]Injecting artworks...[/]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=40),
            MofNCompleteColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Artworks", total=total)

            from traktord.utils.trmd import SUPPORTED_AUDIO_EXTS
            for track in collection.tracks:
                file_path = Path(track.file_path)
                if file_path.exists() and file_path.suffix.lower() in SUPPORTED_AUDIO_EXTS:
                    try:
                        coverid = inject_artwork(file_path, coverart_dir)
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

        console.print(f"  [green]{injected}[/] artworks injected, {skipped} skipped")

    # Ecriture NML avec COVERARTID maintenant disponibles dans track.extra
    nml_path = traktor_dir / "collection.nml"
    console.print("[cyan]Writing NML (no cues for Phase 1)...[/]")
    writer = TraktorWriter()
    smart_detected: list[tuple[str, str]] = []
    writer.write(
        collection,
        str(nml_path),
        include_cues=False,
        smart_playlists=True,
        smart_detected=smart_detected,
    )
    console.print(f"  [green]OK[/] {nml_path}")
    if smart_detected:
        console.print(
            f"  [cyan]Smart playlists detected ({len(smart_detected)}):[/]"
        )
        for pl_name, query in smart_detected[:20]:
            console.print(f"    [dim]{pl_name}[/] -> {query}")
        if len(smart_detected) > 20:
            console.print(f"    [dim]... and {len(smart_detected) - 20} more[/]")

    # Instructions Phase 2
    console.print()
    console.print(Panel(
        "[bold]Phase 1 done![/]\n\n"
        f"[cyan]Tracks imported:[/] {total}\n"
        f"[cyan]NML written:[/] [dim]{nml_path}[/]\n\n"
        "[bold yellow]Next steps:[/]\n"
        "1. Open [cyan]Traktor Pro 4[/]\n"
        "2. Traktor will analyse tracks (BPM, key, beatgrid, transients)\n"
        "3. Wait for analysis to complete (may take several hours)\n"
        "4. Once done, close Traktor\n"
        "5. Relaunch this tool and choose [cyan]Phase 2 — Merge cues[/]",
        title="[bold green]Phase 1 OK[/]",
        border_style="green",
    ))


# ----------------------------------------------------------------------------
# Phase 2 : Merge des cues
# ----------------------------------------------------------------------------

def _run_phase2(xml_path: str, traktor_dir: Path, add_load_cue: bool = False) -> None:
    """Phase 2 : Merge les cues Rekordbox dans la collection.nml analysee."""
    from traktord.parsers.rekordbox import RekordboxParser
    from traktord.merge_cues import merge_cues

    console.print("\n[cyan]Phase 2/2 — Merge cues[/]\n")

    # Parser l'XML Rekordbox pour les cues
    console.print("[cyan]Reading Rekordbox cues...[/]")
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
    console.print(f"[cyan]Merging into {nml_path}...[/]")

    stats = merge_cues(
        collection,
        nml_path,
        overwrite_existing_cues=True,
        overwrite_grid=False,
        add_load_cue=add_load_cue,
    )

    # Resume
    console.print()
    console.print(Panel(
        f"[cyan]Tracks matched:[/] [green]{stats['matched']}[/]\n"
        f"[cyan]Tracks not found:[/] {stats['not_matched']}\n"
        f"[cyan]Cues added:[/] [green]{stats['total_cues_added']}[/]\n\n"
        f"[cyan]Backup:[/] [dim]{stats['backup'].name}[/]\n"
        f"[cyan]NML:[/] [dim]{nml_path}[/]\n\n"
        "[bold yellow]Next step:[/]\n"
        "Relaunch Traktor. Your Rekordbox cues are now integrated\n"
        "with the Traktor analysis. They should no longer be overwritten on rescan.",
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
        f"Licence: {license_status}\n"
        "[dim]deck2deck.ch[/]",
        border_style="cyan",
        padding=(1, 4),
    ))

    # Choix de phase
    console.print("\n[bold]What do you want to do?[/]")
    console.print("  [cyan]1[/] — Phase 1: Initial import (NML + artworks)")
    console.print("  [cyan]2[/] — Phase 2: Merge cues (after Traktor analysis)")
    console.print("  [cyan]3[/] — Cleanup: remove duplicates from collection.nml")
    console.print("  [cyan]4[/] — Re-inject artworks (without Traktor re-analysis)")
    console.print("  [cyan]5[/] — Add new tracks (incremental import)")
    console.print("  [cyan]6[/] — Activate unlimited licence")
    console.print("  [cyan]7[/] — Find missing artworks online (iTunes Search API)")
    phase = Prompt.ask("Choice", choices=["1", "2", "3", "4", "5", "6", "7"], default="1")

    # Activation de licence
    if phase == "6":
        console.print()
        if is_licensed():
            console.print(f"[green]Licence already active:[/] {load_license()}")
            return

        console.print(f"Purchase a licence at: [cyan]{GUMROAD_URL}[/]")
        console.print("Enter the key received by email after purchase.\n")
        key = Prompt.ask("Licence key")
        if validate_license_key(key):
            save_license(key)
            console.print("[bold green]Licence activated! Unlimited tracks.[/]")
        else:
            console.print("[red]Invalid key. Check the format: D2D-XXXXX-XXXXX-XXXXX-XXXXX[/]")
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
            console.print(f"[red]collection.nml not found[/]")
            sys.exit(1)

        console.print("\n[cyan]Cleaning up duplicates...[/]")
        stats = cleanup_duplicates(nml_path)
        console.print()
        console.print(Panel(
            f"Before : [yellow]{stats['total_before']}[/] entries\n"
            f"After  : [green]{stats['total_after']}[/] entries\n"
            f"Removed: [red]{stats['removed']}[/]\n\n"
            f"Backup : [dim]{stats['backup'].name}[/]",
            title="[bold green]Cleanup OK[/]",
            border_style="green",
        ))
        return

    # Selection du fichier Rekordbox
    console.print("\n[bold]Select the Rekordbox export (.xml)[/]")
    console.print("   [dim]A file picker window will open...[/]")
    xml_path = _pick_file_macos()

    if not xml_path:
        console.print("   [red]No file selected. Aborting.[/]")
        sys.exit(1)

    console.print(f"   [green]\u2713[/] {xml_path}")

    # Dossier Traktor
    traktor_dir = _find_traktor4_dir()
    if traktor_dir:
        console.print(f"\n[bold]Traktor 4 folder detected:[/] [cyan]{traktor_dir}[/]")
        if not Confirm.ask("Use this folder?", default=True):
            folder = _pick_folder_macos()
            if folder:
                traktor_dir = Path(folder)
            else:
                console.print("[red]Aborted.[/]")
                sys.exit(1)
    else:
        console.print("\n[bold]Traktor 4 folder not detected.[/]")
        folder = _pick_folder_macos()
        if folder:
            traktor_dir = Path(folder)
        else:
            console.print("[red]Aborted.[/]")
            sys.exit(1)

    # Lancer la phase choisie
    if phase == "1":
        inject_art = Confirm.ask(
            "\nInject artworks (cover art)?",
            default=True,
        )
        if not Confirm.ask("Run Phase 1?", default=True):
            sys.exit(0)
        _run_phase1(xml_path, traktor_dir, inject_art)
    elif phase == "4":
        # Reinjecter les artworks sans toucher aux cues
        nml_path = traktor_dir / "collection.nml"
        if not nml_path.exists():
            console.print(f"[red]collection.nml not found[/]")
            sys.exit(1)

        console.print(Panel(
            "Re-injecting artworks into MP3 files +\n"
            "updating COVERARTID in the existing NML.\n\n"
            "[yellow]Does NOT touch cues, BPM, key — no Traktor re-analysis triggered.[/]",
            border_style="cyan",
        ))
        if not Confirm.ask("Run?", default=True):
            sys.exit(0)

        from traktord.parsers.rekordbox import RekordboxParser
        from traktord.merge_cues import update_coverart_ids

        console.print(f"\n[cyan]Reading {xml_path}...[/]")
        parser = RekordboxParser()
        collection = parser.parse(xml_path)
        console.print(f"  [green]{len(collection.tracks)}[/] tracks")

        console.print("[cyan]Re-injecting + updating NML...[/]")
        stats = update_coverart_ids(collection, nml_path)

        console.print()
        console.print(Panel(
            f"Injected       : [green]{stats['injected']}[/]\n"
            f"Skipped        : [dim]{stats['skipped']}[/]\n"
            f"NML entries upd: [green]{stats['nml_updated']}[/]\n\n"
            f"Backup : [dim]{stats['backup'].name}[/]",
            title="[bold green]OK[/]",
            border_style="green",
        ))
    elif phase == "5":
        # Import incremental
        nml_path = traktor_dir / "collection.nml"
        if not nml_path.exists():
            console.print(f"[red]collection.nml not found — run Phase 1 first[/]")
            sys.exit(1)

        if not Confirm.ask("\nAdd new tracks?", default=True):
            sys.exit(0)

        from traktord.parsers.rekordbox import RekordboxParser
        from traktord.merge_cues import add_new_tracks

        console.print(f"\n[cyan]Reading {xml_path}...[/]")
        parser = RekordboxParser()
        collection = parser.parse(xml_path)
        console.print(f"  [green]{len(collection.tracks)}[/] tracks in export")

        console.print("[cyan]Incremental import...[/]")
        stats = add_new_tracks(collection, nml_path, inject_artworks=True)

        console.print()
        console.print(Panel(
            f"New tracks        : [green]{stats['new_tracks']}[/]\n"
            f"Already present   : [dim]{stats['already_present']}[/]\n"
            f"Artworks injected : [green]{stats['artworks_injected']}[/]\n"
            f"Total collection  : {stats['total']}\n\n"
            f"Backup : [dim]{stats['backup'].name}[/]",
            title="[bold green]Incremental import OK[/]",
            border_style="green",
        ))

        if stats["new_tracks"] > 0:
            console.print()
            console.print("[yellow]Next steps:[/]")
            console.print(f"  1. Open Traktor → scan {stats['new_tracks']} tracks (a few minutes)")
            console.print(f"  2. Close Traktor")
            console.print(f"  3. Relaunch this tool → Phase 2 (merge cues)")

    elif phase == "7":
        # Recherche d'artworks manquants en ligne
        nml_path = traktor_dir / "collection.nml"
        if not nml_path.exists():
            console.print(f"[red]collection.nml not found — run Phase 1 first[/]")
            sys.exit(1)

        console.print()
        console.print(Panel(
            "[yellow]For each track without embedded cover, queries the[/]\n"
            "[yellow]iTunes Search API (free, no key) and injects the[/]\n"
            "[yellow]matching cover into the audio file + Traktor cache.[/]\n\n"
            "[red]Modifies the audio files (writes APIC / covr).[/]\n"
            "Backup of the .nml is automatic. Audio file backups: NONE.",
            title="[bold yellow]Find missing artworks online[/]",
            border_style="yellow",
        ))
        if not Confirm.ask("Run?", default=True):
            sys.exit(0)

        from traktord.parsers.rekordbox import RekordboxParser
        from traktord.merge_cues import find_missing_artworks

        console.print(f"\n[cyan]Reading {xml_path}...[/]")
        parser = RekordboxParser()
        collection = parser.parse(xml_path)
        console.print(f"  [green]{len(collection.tracks)}[/] tracks")

        console.print("[cyan]Searching missing artworks...[/]")
        stats = find_missing_artworks(collection, nml_path)

        by_src = stats.get("found_by_source", {})
        console.print()
        console.print(Panel(
            f"Tested              : {stats['tested']}\n"
            f"Already had cover   : [dim]{stats['already_had_cover']}[/]\n"
            f"Found online        : [green]{stats['found_external']}[/]\n"
            f"  via Beatport      : [green]{by_src.get('beatport', 0)}[/]\n"
            f"  via Discogs       : [green]{by_src.get('discogs', 0)}[/]\n"
            f"  via MusicBrainz   : [green]{by_src.get('musicbrainz', 0)}[/]\n"
            f"  via iTunes        : [green]{by_src.get('itunes', 0)}[/]\n"
            f"Not found online    : [yellow]{stats['not_found']}[/]\n"
            f"Errors              : [red]{stats['errors']}[/]\n"
            f"NML entries updated : [green]{stats['nml_updated']}[/]\n\n"
            f"Backup : [dim]{stats['backup'].name}[/]",
            title="[bold green]OK[/]",
            border_style="green",
        ))

    else:
        nml_path = traktor_dir / "collection.nml"
        if not nml_path.exists():
            console.print(f"[red]collection.nml not found in {traktor_dir}[/]")
            console.print("[yellow]Run Phase 1 and Traktor analysis first.[/]")
            sys.exit(1)

        console.print()
        console.print(Panel(
            "[yellow]Have you:[/]\n"
            "1. Run Phase 1?\n"
            "2. Opened Traktor?\n"
            "3. Waited for analysis to complete (BPM, key, beatgrid)?\n"
            "4. Closed Traktor?",
            border_style="yellow",
        ))
        load_cue = Confirm.ask(
            "Add a load cue at the position of the first hotcue (Q1 RB → Cue 8 Traktor)?",
            default=True,
        )
        if not Confirm.ask("Run Phase 2?", default=True):
            sys.exit(0)
        _run_phase2(xml_path, traktor_dir, add_load_cue=load_cue)


if __name__ == "__main__":
    main()
