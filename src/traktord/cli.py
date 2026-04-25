"""Point d'entree CLI pour Traktor Data Converter."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
from rich.table import Table

from traktord import __version__
from traktord.utils.detect import detect_format

console = Console()


def _find_traktor4_coverart_dir() -> Path | None:
    """Detecter le dossier Coverart/ de Traktor 4 dans ~/Documents."""
    ni_dir = Path.home() / "Documents" / "Native Instruments"
    if not ni_dir.exists():
        return None
    for d in sorted(ni_dir.iterdir(), reverse=True):
        if d.name.startswith("Traktor 4") and d.is_dir():
            coverart = d / "Coverart"
            if coverart.exists():
                return coverart
    return None


def _inject_metadata(collection) -> None:
    """Injecter les metadonnees completes (PRIV:TRAKTOR4 + COMM + POPM + artwork)."""
    from traktord.utils.trmd import inject_full_metadata

    coverart_dir = _find_traktor4_coverart_dir()
    if coverart_dir is None:
        console.print(
            "[yellow]Traktor 4 Coverart folder not found — "
            "artworks will not be cached (but will be written to PRIV tag).[/]"
        )

    console.print(f"\n[bold]Injecting metadata into MP3 files...[/]")
    if coverart_dir:
        console.print(f"  Cache Coverart : [dim]{coverart_dir}[/]")

    injected = 0
    skipped_missing = 0
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Tracks", total=len(collection.tracks))

        for track in collection.tracks:
            mp3_path = Path(track.file_path)
            if not mp3_path.exists() or mp3_path.suffix.lower() != ".mp3":
                skipped_missing += 1
                progress.advance(task)
                continue

            try:
                inject_full_metadata(mp3_path, track, coverart_dir)
                injected += 1
            except Exception as e:
                errors += 1
                console.print(f"  [red]Error[/] {mp3_path.name}: {e}")

            progress.advance(task)

    console.print(f"\n  [green]Injected[/]     : {injected}")
    if skipped_missing:
        console.print(f"  [dim]Not found[/]    : {skipped_missing}")
    if errors:
        console.print(f"  [red]Errors[/]       : {errors}")


def _get_parser(fmt: str):
    """Retourner le parser pour un format donne."""
    if fmt == "rekordbox":
        from traktord.parsers.rekordbox import RekordboxParser
        return RekordboxParser()
    raise click.ClickException(f"No parser available for format '{fmt}'")


def _get_writer(fmt: str):
    """Retourner le writer pour un format donne."""
    if fmt == "traktor":
        from traktord.converters.traktor import TraktorWriter
        return TraktorWriter()
    raise click.ClickException(f"No writer available for format '{fmt}'")


def _default_output(source: str, target_format: str) -> str:
    """Generer un nom de fichier de sortie par defaut."""
    extensions = {
        "traktor": ".nml",
        "rekordbox": ".xml",
        "virtualdj": ".xml",
    }
    ext = extensions.get(target_format, ".xml")
    return source.rsplit(".", 1)[0] + f"_converted{ext}"


@click.group()
@click.version_option(version=__version__, prog_name="traktor-convert")
def cli():
    """Multi-format DJ library converter.

    Supports: Traktor NML, Rekordbox XML.
    """


@cli.command()
@click.argument("source", type=click.Path(exists=True))
@click.option(
    "--from", "source_format",
    type=click.Choice(["traktor", "rekordbox", "serato", "virtualdj"], case_sensitive=False),
    help="Source format (auto-detected if not specified).",
)
@click.option(
    "--to", "target_format",
    type=click.Choice(["traktor", "rekordbox", "serato", "virtualdj"], case_sensitive=False),
    required=True,
    help="Target format.",
)
@click.option(
    "-o", "--output",
    type=click.Path(),
    help="Output file path.",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="Preview without writing any file.",
)
@click.option(
    "--volume",
    type=str,
    default=None,
    help="macOS volume name (e.g. 'Mac HD').",
)
@click.option(
    "--inject/--no-inject", default=True,
    help="Inject full metadata (cues, BPM, key, artwork, comments, rating) "
         "into MP3 files via PRIV:TRAKTOR4 + COMM + POPM. Enabled by default.",
)
def convert(
    source: str,
    source_format: str | None,
    target_format: str,
    output: str | None,
    dry_run: bool,
    volume: str | None,
    inject: bool,
):
    """Convert a DJ library from one format to another."""
    console.print(f"[bold blue]Traktor Data Converter v{__version__}[/]\n")

    # Auto-detection du format source
    if not source_format:
        source_format = detect_format(source)
        if not source_format:
            raise click.ClickException(
                "Unable to detect source format. Use --from to specify it."
            )
        console.print(f"Detected format: [cyan]{source_format}[/]")

    if source_format == target_format:
        raise click.ClickException("Source and target formats are identical.")

    # Parser
    console.print(f"Reading [cyan]{source}[/]...")
    parser = _get_parser(source_format)
    collection = parser.parse(source)

    # Stats
    total_cues = sum(len(t.cue_points) for t in collection.tracks)
    total_loops = sum(1 for t in collection.tracks for c in t.cue_points if c.type == "loop")
    tracks_with_key = sum(1 for t in collection.tracks if t.key)
    tracks_with_bpm = sum(1 for t in collection.tracks if t.bpm)

    console.print(f"\n[green]Collection loaded:[/]")
    console.print(f"  Tracks     : {len(collection.tracks)}")
    console.print(f"  Playlists  : {len(collection.playlists)}")
    console.print(f"  Cue points : {total_cues}")
    console.print(f"  Loops      : {total_loops}")
    console.print(f"  With BPM   : {tracks_with_bpm}")
    console.print(f"  With Key   : {tracks_with_key}")

    if dry_run:
        console.print("\n[yellow]Dry-run mode — no file written.[/]")
        return

    # Writer
    output_path = output or _default_output(source, target_format)
    console.print(f"\nWriting to [cyan]{output_path}[/]...")
    writer = _get_writer(target_format)
    writer.write(collection, output_path, volume_name=volume)

    # Injection des metadonnees completes (PRIV:TRAKTOR4 + COMM + POPM + artwork)
    if inject and target_format == "traktor":
        _inject_metadata(collection)

    console.print(f"\n[bold green]Conversion complete![/]")
    console.print(f"  {source_format} → {target_format}")
    console.print(f"  {len(collection.tracks)} tracks converted")
    console.print(f"  File: {output_path}")


@cli.command()
@click.argument("source", type=click.Path(exists=True))
def info(source: str):
    """Display information about a DJ library."""
    console.print(f"[bold blue]Traktor Data Converter v{__version__}[/]\n")

    fmt = detect_format(source)
    if not fmt:
        raise click.ClickException("Unrecognised format.")

    console.print(f"Format: [cyan]{fmt}[/]")
    console.print(f"File: {source}\n")

    parser = _get_parser(fmt)
    collection = parser.parse(source)

    # Resume
    console.print(f"[bold]Tracks : {len(collection.tracks)}[/]")
    console.print(f"Playlists : {len(collection.playlists)}")

    if not collection.tracks:
        return

    # Tableau des 10 premieres tracks
    table = Table(title="Preview (first 10 tracks)")
    table.add_column("#", style="dim", width=4)
    table.add_column("Artist", max_width=25)
    table.add_column("Title", max_width=30)
    table.add_column("BPM", width=7)
    table.add_column("Key", width=5)
    table.add_column("Cues", width=5)

    for i, track in enumerate(collection.tracks[:10], 1):
        table.add_row(
            str(i),
            track.artist or "-",
            track.title or "-",
            f"{track.bpm:.1f}" if track.bpm else "-",
            track.key or "-",
            str(len(track.cue_points)),
        )

    console.print(table)

    # Stats globales
    total_cues = sum(len(t.cue_points) for t in collection.tracks)
    bpm_tracks = [t for t in collection.tracks if t.bpm]
    if bpm_tracks:
        avg_bpm = sum(t.bpm for t in bpm_tracks) / len(bpm_tracks)  # type: ignore[arg-type]
        console.print(f"\nAverage BPM: {avg_bpm:.1f}")

    console.print(f"Total cue points: {total_cues}")

    if collection.playlists:
        console.print(f"\n[bold]Playlists:[/]")
        for name, paths in collection.playlists.items():
            console.print(f"  {name} ({len(paths)} tracks)")


@cli.command()
@click.argument("source", type=click.Path(exists=True))
@click.option("--traktor-dir", type=click.Path(), default=None,
              help="Traktor 4 folder (auto-detected by default).")
@click.option("--no-artwork", is_flag=True, default=False,
              help="Skip artwork injection (faster).")
def init(source: str, traktor_dir: str | None, no_artwork: bool):
    """Phase 1: Initial NML import (no cues) + artworks.

    Writes a collection.nml without cue points. Then open Traktor which
    will analyse all tracks (BPM, key, beatgrid, transients). Once
    analysis is complete, run 'merge-cues' to add the cues.
    """
    from traktord.parsers.rekordbox import RekordboxParser
    from traktord.converters.traktor import TraktorWriter

    console.print(f"[bold blue]Traktor Data Converter v{__version__} — Phase 1[/]\n")

    # Dossier Traktor
    if traktor_dir:
        tdir = Path(traktor_dir)
    else:
        from traktord.merge_cues import find_traktor_collection_nml
        nml = find_traktor_collection_nml()
        tdir = nml.parent if nml else None

    if not tdir or not tdir.exists():
        raise click.ClickException(
            "Traktor 4 folder not found. Use --traktor-dir."
        )

    console.print(f"Traktor : [cyan]{tdir}[/]")

    # Parser
    console.print(f"Reading [cyan]{source}[/]...")
    parser = RekordboxParser()
    collection = parser.parse(source)
    total = len(collection.tracks)
    console.print(f"  [green]{total}[/] tracks loaded")

    # Backup
    nml_path = tdir / "collection.nml"
    if nml_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = tdir / "Backup"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / f"collection_{timestamp}.nml"
        import shutil as _sh
        _sh.copy2(nml_path, backup)
        console.print(f"  Backup : [dim]{backup.name}[/]")

    # Artworks D'ABORD pour que les COVERARTID soient dans le NML
    if not no_artwork:
        _inject_artworks_phase1(collection)

    # Ecriture NML sans cues (avec COVERARTID dans INFO pour affichage browser)
    console.print("[cyan]Writing NML (no cues)...[/]")
    writer = TraktorWriter()
    writer.write(collection, str(nml_path), include_cues=False)
    console.print(f"  [green]OK[/] {nml_path}")

    console.print()
    console.print("[bold green]Phase 1 done![/]")
    console.print("\n[yellow]Next steps:[/]")
    console.print("  1. Open [cyan]Traktor Pro 4[/]")
    console.print("  2. Wait for analysis to complete (may take several hours)")
    console.print("  3. Close Traktor")
    console.print(f"  4. Run: [cyan]traktor-convert merge-cues {source}[/]")


def _inject_artworks_phase1(collection) -> None:
    """Injection artwork + collecte COVERARTID dans track.extra pour le NML."""
    from traktord.utils.trmd import inject_artwork

    coverart_dir = _find_traktor4_coverart_dir()

    console.print("[cyan]Injecting artworks...[/]")
    injected = 0
    skipped = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Artworks", total=len(collection.tracks))

        for track in collection.tracks:
            mp3 = Path(track.file_path)
            if mp3.exists() and mp3.suffix.lower() == ".mp3":
                try:
                    coverid = inject_artwork(mp3, coverart_dir)
                    if coverid:
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

    console.print(f"  [green]{injected}[/] injected, {skipped} skipped")


@cli.command("merge-cues")
@click.argument("source", type=click.Path(exists=True))
@click.option("--traktor-dir", type=click.Path(), default=None,
              help="Traktor 4 folder (auto-detected by default).")
@click.option("--keep-grid/--overwrite-grid", default=True,
              help="Keep Traktor beatgrid (recommended) or overwrite with Rekordbox.")
@click.option("--load-cue/--no-load-cue", default=True,
              help="Add a load cue at the position of the first hotcue.")
def merge_cues_cmd(source: str, traktor_dir: str | None, keep_grid: bool, load_cue: bool):
    """Phase 2: Merge Rekordbox cues into the analysed collection.nml.

    Run AFTER 'init' and after Traktor has finished its analysis
    (BPM, key, beatgrid). Adds Rekordbox CUE_V2 to collection.nml
    without touching any other data.
    """
    from traktord.parsers.rekordbox import RekordboxParser
    from traktord.merge_cues import find_traktor_collection_nml, merge_cues

    console.print(f"[bold blue]Traktor Data Converter v{__version__} — Phase 2[/]\n")

    # Trouver collection.nml
    if traktor_dir:
        nml_path = Path(traktor_dir) / "collection.nml"
    else:
        nml_path = find_traktor_collection_nml()

    if not nml_path or not nml_path.exists():
        raise click.ClickException(
            "Traktor collection.nml not found. Use --traktor-dir."
        )

    console.print(f"collection.nml: [cyan]{nml_path}[/]")

    # Parser Rekordbox pour les cues
    console.print(f"Reading cues from [cyan]{source}[/]...")
    parser = RekordboxParser()
    collection = parser.parse(source)
    total = len(collection.tracks)
    total_cues = sum(len(t.cue_points) for t in collection.tracks)
    console.print(f"  [green]{total}[/] tracks, [green]{total_cues}[/] cues")

    # Merge
    console.print("[cyan]Merging...[/]")
    stats = merge_cues(
        collection,
        nml_path,
        overwrite_existing_cues=True,
        overwrite_grid=not keep_grid,
        add_load_cue=load_cue,
    )

    console.print()
    console.print(f"  [green]Matched      :[/] {stats['matched']}")
    console.print(f"  [dim]Not found     :[/] {stats['not_matched']}")
    console.print(f"  [green]Cues added   :[/] {stats['total_cues_added']}")
    console.print(f"  Backup        : [dim]{stats['backup'].name}[/]")
    console.print()
    console.print("[bold green]Phase 2 done![/]")
    console.print("\n[yellow]Relaunch Traktor[/] — cues are now integrated.")


@cli.command("add")
@click.argument("source", type=click.Path(exists=True))
@click.option("--traktor-dir", type=click.Path(), default=None,
              help="Traktor 4 folder (auto-detected by default).")
def add_cmd(source: str, traktor_dir: str | None):
    """Add new Rekordbox tracks to the existing Traktor collection.

    Incremental import: only absent tracks are added.
    Traktor will only scan those tracks (seconds instead of hours).
    Then run merge-cues to add cues for the new tracks.
    """
    from traktord.parsers.rekordbox import RekordboxParser
    from traktord.merge_cues import find_traktor_collection_nml, add_new_tracks

    console.print(f"[bold blue]Traktor Data Converter v{__version__} — Import incremental[/]\n")

    if traktor_dir:
        nml_path = Path(traktor_dir) / "collection.nml"
    else:
        nml_path = find_traktor_collection_nml()

    if not nml_path or not nml_path.exists():
        raise click.ClickException("Traktor collection.nml not found.")

    console.print(f"collection.nml: [cyan]{nml_path}[/]")
    console.print(f"Reading [cyan]{source}[/]...")

    parser = RekordboxParser()
    collection = parser.parse(source)
    console.print(f"  [green]{len(collection.tracks)}[/] tracks in Rekordbox export")

    console.print("[cyan]Incremental import...[/]")
    stats = add_new_tracks(collection, nml_path, inject_artworks=True)

    console.print()
    console.print(f"  [green]New tracks[/]       : {stats['new_tracks']}")
    console.print(f"  [dim]Already present[/]  : {stats['already_present']}")
    console.print(f"  [green]Artworks injected[/]: {stats['artworks_injected']}")
    console.print(f"  [dim]Total collection[/] : {stats['total']}")
    console.print(f"  Backup             : [dim]{stats['backup'].name}[/]")

    if stats['new_tracks'] > 0:
        console.print()
        console.print("[bold green]OK![/]")
        console.print(f"\n[yellow]Next steps:[/]")
        console.print(f"  1. Open Traktor → scan {stats['new_tracks']} tracks (a few minutes)")
        console.print(f"  2. Close Traktor")
        console.print(f"  3. [cyan]traktor-convert merge-cues {source}[/]")
    else:
        console.print("\n[dim]No new tracks to add.[/]")


@cli.command("reinject-artworks")
@click.argument("source", type=click.Path(exists=True))
@click.option("--traktor-dir", type=click.Path(), default=None,
              help="Traktor 4 folder (auto-detected by default).")
def reinject_artworks_cmd(source: str, traktor_dir: str | None):
    """Re-inject artworks and update COVERARTID without touching cues.

    Use after fixing the APIC selector (e.g. picking the front cover
    instead of a waveform). Does NOT trigger a Traktor re-analysis.
    """
    from traktord.parsers.rekordbox import RekordboxParser
    from traktord.merge_cues import find_traktor_collection_nml, update_coverart_ids

    console.print(f"[bold blue]Traktor Data Converter v{__version__} — Reinject artworks[/]\n")

    if traktor_dir:
        nml_path = Path(traktor_dir) / "collection.nml"
    else:
        nml_path = find_traktor_collection_nml()

    if not nml_path or not nml_path.exists():
        raise click.ClickException("Traktor collection.nml not found.")

    console.print(f"collection.nml: [cyan]{nml_path}[/]")
    console.print(f"Reading tracks from [cyan]{source}[/]...")

    parser = RekordboxParser()
    collection = parser.parse(source)
    console.print(f"  [green]{len(collection.tracks)}[/] tracks")

    console.print("[cyan]Re-injecting artworks + updating NML...[/]")
    stats = update_coverart_ids(collection, nml_path)

    console.print()
    console.print(f"  [green]Injected[/]       : {stats['injected']}")
    console.print(f"  [dim]Skipped[/]        : {stats['skipped']}")
    console.print(f"  [green]NML entries upd[/]: {stats['nml_updated']}")
    console.print(f"  Backup         : [dim]{stats['backup'].name}[/]")
    console.print()
    console.print("[bold green]OK![/] Relaunch Traktor: artworks will be correct,")
    console.print("cues and BPM/key preserved (no re-analysis).")


@cli.command()
@click.option("--traktor-dir", type=click.Path(), default=None,
              help="Traktor 4 folder (auto-detected by default).")
def cleanup(traktor_dir: str | None):
    """Remove duplicate entries from the Traktor collection.nml.

    Use if Traktor created duplicates during import (e.g. after changing
    the VOLUME from 'Macintosh HD' to 'Mac HD'). Keeps the entry with
    AUDIO_ID (analysed) and removes the others.
    """
    from traktord.merge_cues import find_traktor_collection_nml, cleanup_duplicates

    console.print(f"[bold blue]Traktor Data Converter v{__version__} — Cleanup[/]\n")

    if traktor_dir:
        nml_path = Path(traktor_dir) / "collection.nml"
    else:
        nml_path = find_traktor_collection_nml()

    if not nml_path or not nml_path.exists():
        raise click.ClickException("Traktor collection.nml not found.")

    console.print(f"collection.nml: [cyan]{nml_path}[/]")
    console.print("[cyan]Removing duplicates...[/]")

    stats = cleanup_duplicates(nml_path)

    console.print()
    console.print(f"  Before   : [yellow]{stats['total_before']}[/] entries")
    console.print(f"  After    : [green]{stats['total_after']}[/] entries")
    console.print(f"  Removed  : [red]{stats['removed']}[/]")
    console.print(f"  Backup   : [dim]{stats['backup'].name}[/]")


if __name__ == "__main__":
    cli()
