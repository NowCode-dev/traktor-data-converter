#!/usr/bin/env python3
"""Diagnostic encoder delay — preparation du test empirique.

Pour chaque MP3 present dans data/test_injection/ :
    1. Lit l'encoder delay reel (Xing/LAME) via mutagen
    2. Retrouve le TRACK correspondant dans data/ExportRB_03.2026.xml
    3. Calcule les positions NML pour les 3 candidats du signe de compensation :
         SIGN=+1 (defaut actuel), SIGN=-1, SIGN=0
    4. Genere un mini NML de test ne contenant que ces tracks (compensation +1)
    5. Ecrit un rapport markdown dans data/encoder_delay_test/REPORT.md

Usage :
    .venv/bin/python scripts/diag_encoder_delay.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Rendre src/ importable sans installer le package
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lxml import etree  # noqa: E402

from traktord.converters.traktor import TraktorWriter  # noqa: E402
from traktord.models.track import Collection  # noqa: E402
from traktord.parsers.rekordbox import RekordboxParser  # noqa: E402
from traktord.utils.encoder_delay import get_encoder_delay_ms  # noqa: E402

TEST_MP3_DIRS = [
    ROOT / "data" / "test_injection",
    ROOT / "Import_MP3_25.04.26",  # noms de dossiers ad-hoc, ajouter au besoin
]
RB_XML = ROOT / "data" / "ExportRB_03.2026.xml"
OUT_DIR = ROOT / "data" / "encoder_delay_test"


def read_lame_info(mp3_path: Path) -> dict:
    """Lit directement les infos MPEG du fichier pour distinguer LAME-tagge vs fallback."""
    from mutagen.mp3 import MP3

    info = MP3(str(mp3_path)).info
    sr = getattr(info, "sample_rate", 44100) or 44100
    delay_samples_raw = getattr(info, "encoder_delay", None)
    is_lame = bool(delay_samples_raw and delay_samples_raw > 0)

    effective_samples = delay_samples_raw if is_lame else 1152
    effective_ms = (effective_samples / sr) * 1000.0

    return {
        "sample_rate": sr,
        "lame_tagged": is_lame,
        "raw_encoder_delay": delay_samples_raw,
        "effective_samples": effective_samples,
        "effective_ms": effective_ms,
        "bitrate": getattr(info, "bitrate", 0),
        "length_s": getattr(info, "length", 0.0),
    }


def find_track_in_xml(xml_path: Path, mp3_basename: str):
    """Parcourt le XML Rekordbox et retourne l'element TRACK dont le Location
    decode (URL → texte) se termine par mp3_basename. Retourne None si introuvable."""
    from urllib.parse import unquote

    tree = etree.parse(str(xml_path))
    for track_elem in tree.iter("TRACK"):
        loc = track_elem.attrib.get("Location", "")
        loc_decoded = unquote(loc)
        if loc_decoded.endswith(mp3_basename):
            return track_elem
    return None


def format_cues(track_elem) -> list[dict]:
    """Extrait les POSITION_MARK + TEMPO Inizio en secondes."""
    cues = []
    for tempo in track_elem.findall("TEMPO"):
        cues.append(
            {
                "kind": "beatgrid",
                "num": None,
                "type": 4,
                "start_s": float(tempo.attrib.get("Inizio", "0")),
                "name": f"TEMPO {tempo.attrib.get('Bpm', '?')} BPM",
            }
        )
        break  # premier seulement

    for pm in track_elem.findall("POSITION_MARK"):
        num = int(pm.attrib.get("Num", "-1"))
        kind = "memory" if num == -1 else f"hotcue_{chr(ord('A') + num)}"
        cues.append(
            {
                "kind": kind,
                "num": num,
                "type": int(pm.attrib.get("Type", "0")),
                "start_s": float(pm.attrib.get("Start", "0")),
                "name": pm.attrib.get("Name", ""),
            }
        )
    return cues


def main() -> int:
    mp3_files: list[Path] = []
    for d in TEST_MP3_DIRS:
        if d.is_dir():
            mp3_files.extend(sorted(d.glob("*.mp3")))
    # Filtrer les MP3 utilitaires de test (phase1_test, test_cuep_copy)
    real_mp3s = [m for m in mp3_files if not m.name.startswith(("phase1_", "test_"))]

    if not real_mp3s:
        print("ERREUR : aucun MP3 de test trouve dans", TEST_MP3_DIRS)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    report_lines = [
        "# Diagnostic encoder delay — rapport empirique",
        "",
        f"Genere depuis {len(real_mp3s)} MP3 (dossiers : "
        f"{', '.join(str(d.relative_to(ROOT)) for d in TEST_MP3_DIRS if d.is_dir())}) "
        f"vs `{RB_XML.relative_to(ROOT)}`.",
        "",
        "## Resume : encoder delay detecte par MP3",
        "",
        "| MP3 | SR | LAME tagge ? | Delay samples | Delay ms | Via module |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    per_track_details = []

    for mp3 in real_mp3s:
        lame = read_lame_info(mp3)
        module_ms = get_encoder_delay_ms(mp3)

        short_name = mp3.name[:48] + "..." if len(mp3.name) > 48 else mp3.name
        report_lines.append(
            f"| `{short_name}` | {lame['sample_rate']} Hz | "
            f"{'OUI' if lame['lame_tagged'] else 'NON (fallback 1152)'} | "
            f"{lame['effective_samples']} | "
            f"**{lame['effective_ms']:.3f} ms** | "
            f"{module_ms:.3f} ms |"
        )

        track_elem = find_track_in_xml(RB_XML, mp3.name)
        per_track_details.append((mp3, lame, module_ms, track_elem))

    report_lines += [
        "",
        "## Cas couverts",
        "",
    ]

    lame_count = sum(1 for _, lame, _, _ in per_track_details if lame["lame_tagged"])
    fallback_count = len(per_track_details) - lame_count
    report_lines.append(
        f"- **{lame_count}** MP3 avec header LAME valide"
    )
    report_lines.append(
        f"- **{fallback_count}** MP3 sans header LAME (fallback 1152 samples)"
    )
    if fallback_count == 0:
        report_lines.append("")
        report_lines.append(
            "> Aucun MP3 sans header LAME dans l'echantillon — le cas "
            "des ~6 % de la biblio (iTunes-encoded, vieux rippers) n'est **pas couvert** "
            "par ce test. Il faudra ajouter un MP3 iTunes-encoded dans `data/test_injection/` "
            "avant de releaser."
        )
    report_lines.append("")

    # Detail par track : positions RB + 3 candidats NML
    report_lines.append("## Detail par track — positions Rekordbox vs NML candidats")
    report_lines.append("")
    report_lines.append(
        "Les 3 colonnes SIGN montrent ce qui serait ecrit dans le NML selon "
        "la valeur de `_ENCODER_DELAY_SIGN`. Le fichier `collection_test.nml` "
        "livre ci-dessous utilise le SIGN actuellement en prod (+1)."
    )
    report_lines.append("")

    for mp3, lame, _, track_elem in per_track_details:
        report_lines.append(f"### {mp3.name}")
        report_lines.append("")

        if track_elem is None:
            report_lines.append("> Introuvable dans le XML Rekordbox. Saute.")
            report_lines.append("")
            continue

        delay_ms = lame["effective_ms"]
        rb_name = track_elem.attrib.get("Name", "?")
        rb_artist = track_elem.attrib.get("Artist", "?")
        rb_bpm = track_elem.attrib.get("AverageBpm", "?")
        report_lines.append(
            f"Rekordbox : **{rb_artist} — {rb_name}** ({rb_bpm} BPM)"
        )
        report_lines.append(f"Delay applique : **{delay_ms:.3f} ms**")
        report_lines.append("")
        report_lines.append(
            "| Cue | Type | Position RB (s) | Position RB (ms) | "
            "NML SIGN=+1 | NML SIGN=-1 | NML SIGN=0 |"
        )
        report_lines.append(
            "| --- | --- | --- | --- | --- | --- | --- |"
        )

        for cue in format_cues(track_elem):
            pos_rb_ms = cue["start_s"] * 1000.0
            pos_plus = pos_rb_ms + delay_ms
            pos_minus = pos_rb_ms - delay_ms
            pos_zero = pos_rb_ms
            report_lines.append(
                f"| `{cue['kind']}`"
                f"{' ' + cue['name'] if cue['name'] else ''} "
                f"| {cue['type']} "
                f"| {cue['start_s']:.3f} "
                f"| {pos_rb_ms:.3f} "
                f"| **{pos_plus:.3f}** "
                f"| {pos_minus:.3f} "
                f"| {pos_zero:.3f} |"
            )
        report_lines.append("")

    # Generation du mini NML de test.
    # Subtilite : le writer Traktor appelle get_encoder_delay_ms(track.file_path)
    # pour calculer la compensation. On est sur Mac Mini, donc les chemins MBP
    # du XML (/Users/lorysmarrocco/Music/Track Folder/Beatport/...) n'existent
    # pas → delay=0 → pas de compensation ecrite. Solution : rediriger file_path
    # vers test_injection/ local pour l'ecriture, puis patcher le LOCATION du
    # NML genere pour pointer vers les chemins MBP reels (attendus par Traktor).
    print("[*] Generation du mini NML de test (avec compensation SIGN=+1 actuelle)...")
    collection = RekordboxParser().parse(str(RB_XML))
    # Si plusieurs MP3 ont le meme basename (cas peu probable mais possible si
    # 2 dossiers contiennent un meme nom), le dernier vu gagne. C'est OK pour ce diag.
    basename_to_local = {m.name: m for m in real_mp3s}
    subset_tracks = []
    basename_to_mbp_path = {}
    for t in collection.tracks:
        bn = Path(t.file_path).name
        if bn in basename_to_local:
            basename_to_mbp_path[bn] = t.file_path  # chemin MBP original
            t.file_path = str(basename_to_local[bn].resolve())  # chemin local
            subset_tracks.append(t)

    mini = Collection(tracks=subset_tracks, playlists={})
    nml_out = OUT_DIR / "collection_test.nml"
    TraktorWriter().write(
        mini,
        str(nml_out),
        volume_name="Mac HD",
        include_cues=True,
    )

    # Post-traitement : remplacer les LOCATION par les chemins MBP pour que
    # Traktor retrouve les fichiers sur le vrai MacBook de Lorys.
    from traktord.utils.paths import file_path_to_traktor_location

    tree = etree.parse(str(nml_out))
    root = tree.getroot()
    for entry in root.iter("ENTRY"):
        loc_elem = entry.find("LOCATION")
        if loc_elem is None:
            continue
        current_file = loc_elem.attrib.get("FILE", "")
        if current_file in basename_to_mbp_path:
            new_loc = file_path_to_traktor_location(
                basename_to_mbp_path[current_file], volume_name="Mac HD"
            )
            loc_elem.set("DIR", new_loc["DIR"])
            loc_elem.set("FILE", new_loc["FILE"])
            loc_elem.set("VOLUME", new_loc["VOLUME"])
            loc_elem.set("VOLUMEID", new_loc["VOLUMEID"])
    tree.write(
        str(nml_out), xml_declaration=True, encoding="UTF-8", pretty_print=True
    )
    print(f"    {nml_out.relative_to(ROOT)} — {len(subset_tracks)} track(s)")

    report_lines += [
        "## Livrables pour test sur le MacBook Pro",
        "",
        f"- NML a importer dans Traktor : `{nml_out.relative_to(ROOT)}`",
        f"- Tracks dans le NML : **{len(subset_tracks)}** (compensation SIGN=+1 appliquee)",
        "",
        "### Pre-requis",
        "",
        "Les 4 MP3 doivent exister sur le MBP aux chemins absolus references dans le NML :",
        "",
    ]
    for mp3 in real_mp3s:
        mbp_path = basename_to_mbp_path.get(mp3.name, "?")
        report_lines.append(f"- `{mbp_path}`")
    report_lines += [
        "",
        "(C'est le cas si ta bibliotheque Beatport est structuree comme dans l'export Rekordbox du 03/2026. Sinon il faudra rsync ces 4 MP3 a ces chemins.)",
        "",
        "### Procedure cote MBP",
        "",
        "1. **Backup immediat** de ta `collection.nml` en prod. Sans exception.",
        "2. Copier `collection_test.nml` sur le MBP (via kDrive ou scp).",
        "3. Dans Traktor Pro 4 : **File → Import Collection** → pointer sur `collection_test.nml`.",
        "   Les 4 tracks sont ajoutes a ta collection (ne suppriment pas le reste).",
        "4. Laisser Traktor faire son analyse auto (1-2 min pour 4 tracks). Le beatgrid peut bouger mais les hotcues restent aux positions ecrites dans le NML.",
        "5. Pour chaque track : **ouvrir en deck A dans Traktor + meme track dans Rekordbox sur le MBP**. Comparer visuellement la position du **hot cue A** (= Q1 Rekordbox) par rapport au premier beat audible ou a un repere audio evident.",
        "6. Pour chacun des 4 tracks, noter l'observation :",
        "   - **Cues parfaitement alignes dans les deux softs** → SIGN=+1 est bon, on release.",
        "   - **Cues en retard dans Traktor** (apparaissent APRES le meme repere audio qu'a Rekordbox) → SIGN=+1 applique trop de decalage → basculer a **SIGN=-1** et regenerer.",
        "   - **Cues en avance dans Traktor** (apparaissent AVANT le repere audio) → il manquait encore du decalage → investiguer (divergence d'analyse Traktor vs RB, autre cause).",
        "7. Me remonter les 4 observations (une ligne par track suffit).",
        "",
        "### Limite importante de ce test",
        "",
        "Les 4 MP3 de l'echantillon sont **tous sans header Xing/LAME** → ils passent tous par le fallback 1152 samples = 26.122 ms a 44.1 kHz. Donc ce test valide **seulement** le cas fallback.",
        "",
        "Le cas \"MP3 avec header LAME valide\" (la majorite d'une biblio DJ typique — ~94 %) n'est **pas** couvert. Avant de bump `0.2.0`, il faudra :",
        "- ajouter 1-2 MP3 LAME-tagges dans `data/test_injection/` (Beatport recent encode avec LAME, donc un MP3 achete Beatport 2020+ fera l'affaire si il a du LAME header)",
        "- re-lancer ce script et verifier que `delay_samples` affiche une valeur autre que 1152 (souvent 576 ou ~1800 selon l'encodeur)",
        "",
        "### Separation des problemes — rappel",
        "",
        "Ce test valide uniquement **l'encoder delay compensation** (probleme 1). Les autres sources potentielles de decalage restent hors scope :",
        "- Divergence d'analyse Traktor vs Rekordbox (beatgrid detecte different)",
        "- Different traitement des cues lors de la re-analyse Traktor",
        "- Option `Q1 as load cue` (probleme 3 discute en session)",
        "",
        "Si apres le fix les cues sont alignes au ms : problem 1 resolu, on pourra attaquer les autres proprement.",
        "",
        "---",
        "",
        f"_Rapport genere automatiquement depuis `scripts/diag_encoder_delay.py`_",
    ]

    report_path = OUT_DIR / "REPORT.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"[*] Rapport : {report_path.relative_to(ROOT)}")
    print()
    print("=" * 70)
    print("AFFICHAGE TERMINAL :")
    print("=" * 70)
    for line in report_lines:
        print(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
