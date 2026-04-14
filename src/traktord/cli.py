"""Point d'entree CLI pour Traktor Data Converter."""

from __future__ import annotations

import sys
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
            "[yellow]Dossier Coverart Traktor 4 introuvable — "
            "les artworks ne seront pas mis en cache (mais dans le PRIV).[/]"
        )

    console.print(f"\n[bold]Injection des metadonnees dans les MP3...[/]")
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
                console.print(f"  [red]Erreur[/] {mp3_path.name}: {e}")

            progress.advance(task)

    console.print(f"\n  [green]Injectes[/]     : {injected}")
    if skipped_missing:
        console.print(f"  [dim]Non trouves[/]  : {skipped_missing}")
    if errors:
        console.print(f"  [red]Erreurs[/]      : {errors}")


def _get_parser(fmt: str):
    """Retourner le parser pour un format donne."""
    if fmt == "rekordbox":
        from traktord.parsers.rekordbox import RekordboxParser
        return RekordboxParser()
    raise click.ClickException(f"Parser non disponible pour le format '{fmt}'")


def _get_writer(fmt: str):
    """Retourner le writer pour un format donne."""
    if fmt == "traktor":
        from traktord.converters.traktor import TraktorWriter
        return TraktorWriter()
    raise click.ClickException(f"Writer non disponible pour le format '{fmt}'")


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
    """Convertisseur multi-formats de bibliotheques DJ.

    Supporte : Traktor NML, Rekordbox XML.
    """


@cli.command()
@click.argument("source", type=click.Path(exists=True))
@click.option(
    "--from", "source_format",
    type=click.Choice(["traktor", "rekordbox", "serato", "virtualdj"], case_sensitive=False),
    help="Format source (auto-detecte si non specifie).",
)
@click.option(
    "--to", "target_format",
    type=click.Choice(["traktor", "rekordbox", "serato", "virtualdj"], case_sensitive=False),
    required=True,
    help="Format de destination.",
)
@click.option(
    "-o", "--output",
    type=click.Path(),
    help="Chemin du fichier de sortie.",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="Afficher un apercu sans ecrire le fichier.",
)
@click.option(
    "--volume",
    type=str,
    default=None,
    help="Nom du volume macOS (ex: 'Mac HD').",
)
@click.option(
    "--inject/--no-inject", default=True,
    help="Injecter les metadonnees completes (cues, BPM, key, artwork, comments, rating) "
         "dans les MP3 via PRIV:TRAKTOR4 + COMM + POPM. Active par defaut.",
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
    """Convertir une bibliotheque DJ d'un format a un autre."""
    console.print(f"[bold blue]Traktor Data Converter v{__version__}[/]\n")

    # Auto-detection du format source
    if not source_format:
        source_format = detect_format(source)
        if not source_format:
            raise click.ClickException(
                "Impossible de detecter le format source. Utilisez --from pour le specifier."
            )
        console.print(f"Format detecte : [cyan]{source_format}[/]")

    if source_format == target_format:
        raise click.ClickException("Le format source et cible sont identiques.")

    # Parser
    console.print(f"Lecture de [cyan]{source}[/]...")
    parser = _get_parser(source_format)
    collection = parser.parse(source)

    # Stats
    total_cues = sum(len(t.cue_points) for t in collection.tracks)
    total_loops = sum(1 for t in collection.tracks for c in t.cue_points if c.type == "loop")
    tracks_with_key = sum(1 for t in collection.tracks if t.key)
    tracks_with_bpm = sum(1 for t in collection.tracks if t.bpm)

    console.print(f"\n[green]Collection chargee :[/]")
    console.print(f"  Tracks     : {len(collection.tracks)}")
    console.print(f"  Playlists  : {len(collection.playlists)}")
    console.print(f"  Cue points : {total_cues}")
    console.print(f"  Loops      : {total_loops}")
    console.print(f"  Avec BPM   : {tracks_with_bpm}")
    console.print(f"  Avec Key   : {tracks_with_key}")

    if dry_run:
        console.print("\n[yellow]Mode dry-run — aucun fichier ecrit.[/]")
        return

    # Writer
    output_path = output or _default_output(source, target_format)
    console.print(f"\nEcriture vers [cyan]{output_path}[/]...")
    writer = _get_writer(target_format)
    writer.write(collection, output_path, volume_name=volume)

    # Injection des metadonnees completes (PRIV:TRAKTOR4 + COMM + POPM + artwork)
    if inject and target_format == "traktor":
        _inject_metadata(collection)

    console.print(f"\n[bold green]Conversion terminee ![/]")
    console.print(f"  {source_format} → {target_format}")
    console.print(f"  {len(collection.tracks)} tracks converties")
    console.print(f"  Fichier : {output_path}")


@cli.command()
@click.argument("source", type=click.Path(exists=True))
def info(source: str):
    """Afficher les informations d'une bibliotheque DJ."""
    console.print(f"[bold blue]Traktor Data Converter v{__version__}[/]\n")

    fmt = detect_format(source)
    if not fmt:
        raise click.ClickException("Format non reconnu.")

    console.print(f"Format : [cyan]{fmt}[/]")
    console.print(f"Fichier : {source}\n")

    parser = _get_parser(fmt)
    collection = parser.parse(source)

    # Resume
    console.print(f"[bold]Tracks : {len(collection.tracks)}[/]")
    console.print(f"Playlists : {len(collection.playlists)}")

    if not collection.tracks:
        return

    # Tableau des 10 premieres tracks
    table = Table(title="Apercu (10 premieres tracks)")
    table.add_column("#", style="dim", width=4)
    table.add_column("Artiste", max_width=25)
    table.add_column("Titre", max_width=30)
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
        console.print(f"\nBPM moyen : {avg_bpm:.1f}")

    console.print(f"Total cue points : {total_cues}")

    if collection.playlists:
        console.print(f"\n[bold]Playlists :[/]")
        for name, paths in collection.playlists.items():
            console.print(f"  {name} ({len(paths)} tracks)")


if __name__ == "__main__":
    cli()
