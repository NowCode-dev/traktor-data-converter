#!/usr/bin/env python3
"""
inspect_traktor.py
==================

Script de diagnostic pour le projet Traktor Data Converter.

CONTEXTE POUR L'AGENT QUI EXECUTE CE SCRIPT
-------------------------------------------
Ce script est lance depuis le MacBook de Lorys pour collecter des informations
introuvables depuis l'environnement de developpement principal (Mac mini).

Le projet Traktor Data Converter convertit les collections Rekordbox vers
Traktor (format NML). Les CUE points, BPM, beatgrids, playlists sont
correctement convertis MAIS les artworks (pochettes d'album) ne s'affichent
PAS dans Traktor 4 apres import du NML, alors que :
- les fichiers MP3 ont bien leur frame APIC ID3 intacte (verifie)
- "Re-Analyze (Async)" + "Update Artwork from ID3" ne fonctionne pas

DECOUVERTES DEJA FAITES (cote dev) :
1. Le format binaire des fichiers cache Coverart de Traktor 4 a ete reverse :
   - Header 9 bytes : marker(0x08) + width_LE(2) + 0x0000 + height_LE(2) + 0x0000
   - Pixel data : RGBA brut (4 bytes/pixel)
   - 3 resolutions par fichier (suffixe 000=125x125, 001=75x75, 002=56x56)
2. Le NML Traktor 4 (version 20) ne contient AUCUN attribut COVERARTID.
   Le mapping audio file -> cache file est stocke ailleurs (DB SQLite probable).

CE QU'IL RESTE A TROUVER :
A. Localisation de la base de donnees Traktor 4 qui contient le mapping
   audio_file_path -> cache_file_id
B. Algorithme de hash qui transforme un MP3 -> nom de fichier cache
   (ex: "024/YYD3ERCC0DVARAJLBQGUCGT5NO5A")
C. Confirmer si Traktor regenere automatiquement le cache lorsqu'on
   charge un MP3 sur un deck (vs uniquement a l'import drag&drop)

SANS CES INFOS, LA FONCTIONNALITE ARTWORK NE PEUT PAS ETRE FINALISEE
DANS LE CONVERTER. C'est pour FINALISER L'APPLICATION et faire des
tests reels que ce script existe.

INSTRUCTIONS POUR L'AGENT
-------------------------
1. Lis ce header en entier
2. Lance le script avec la sous-commande "scan" en premier (auto-detecte
   tout, pas d'arguments necessaires)
3. Aide Lorys a executer "monitor" puis "analyze" sur quelques tracks
4. Quand le rapport est genere, transmets-le tel quel a Lorys (il le
   ramenera dans la session principale du Mac mini pour finalisation)

USAGE
-----
    python3 inspect_traktor.py scan [--out PATH]
        Inspection passive : detecte version Traktor, structure dossier,
        cherche DB, echantillonne Coverart, copie l'essentiel.

    python3 inspect_traktor.py monitor
        Surveillance temps reel du dossier Coverart. A lancer AVANT de
        charger un track sur un deck dans Traktor : le script affichera
        en direct les fichiers cache crees, ce qui donne le mapping
        track -> cache file de maniere triviale.

    python3 inspect_traktor.py analyze <mp3_path>
        Extrait l'APIC d'un MP3, calcule de nombreux hashes possibles
        (MD5, SHA1, SHA256 sur le path / le contenu APIC / le binaire
        complet, en hex / base32 / base64), puis cherche dans le cache
        Coverart un nom de fichier qui matcherait. Aide a reverse le
        hash si on a au moins un mapping connu.

    python3 inspect_traktor.py db-dump <db_file>
        Si on trouve un fichier .db / .sqlite Traktor 4, dump son schema
        et un echantillon de chaque table.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Couleurs ANSI pour le terminal
class C:
    R = "\033[0m"
    B = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"


def banner(text: str) -> None:
    print(f"\n{C.B}{C.BLUE}=== {text} ==={C.R}")


def info(text: str) -> None:
    print(f"{C.CYAN}>{C.R} {text}")


def ok(text: str) -> None:
    print(f"{C.GREEN}OK{C.R} {text}")


def warn(text: str) -> None:
    print(f"{C.YELLOW}WARN{C.R} {text}")


def err(text: str) -> None:
    print(f"{C.RED}ERR{C.R} {text}")


# ----------------------------------------------------------------------------
# Auto-install des dependances
# ----------------------------------------------------------------------------

def ensure_deps() -> None:
    """Installe mutagen et Pillow si manquants."""
    missing = []
    try:
        import mutagen  # noqa: F401
    except ImportError:
        missing.append("mutagen")
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    if missing:
        info(f"Installation des dependances : {', '.join(missing)}")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", *missing]
        )


# ----------------------------------------------------------------------------
# Detection de l'installation Traktor
# ----------------------------------------------------------------------------

HOME = Path.home()
DOC_NI = HOME / "Documents" / "Native Instruments"
LIB_APP_NI = HOME / "Library" / "Application Support" / "Native Instruments"
LIB_PREFS = HOME / "Library" / "Preferences"
LIB_CACHES = HOME / "Library" / "Caches"


def find_traktor_install_dirs() -> list[Path]:
    """Cherche les dossiers Traktor sous ~/Documents/Native Instruments/."""
    if not DOC_NI.exists():
        return []
    return sorted([
        p for p in DOC_NI.iterdir()
        if p.is_dir() and p.name.lower().startswith("traktor")
    ])


def find_db_files() -> list[Path]:
    """Cherche tous les fichiers .db / .sqlite / .realm / .db-wal sous
    ~/Library/Application Support/Native Instruments/."""
    results = []
    if not LIB_APP_NI.exists():
        return results
    extensions = {".db", ".sqlite", ".sqlite3", ".realm", ".db-wal", ".db-shm"}
    for path in LIB_APP_NI.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            results.append(path)
    # Aussi chercher des fichiers sans extension qui pourraient etre des DBs
    # (verifier le magic byte SQLite : "SQLite format 3\000")
    for path in LIB_APP_NI.rglob("*"):
        if path.is_file() and path.suffix == "":
            try:
                with path.open("rb") as f:
                    head = f.read(16)
                if head.startswith(b"SQLite format 3"):
                    results.append(path)
            except Exception:
                pass
    return results


# ----------------------------------------------------------------------------
# Format Traktor Coverart
# ----------------------------------------------------------------------------

def parse_coverart_header(data: bytes) -> dict | None:
    """Parse le header 9 bytes d'un fichier Coverart Traktor.

    Returns:
        dict avec marker, width, height, expected_size, ou None si invalide.
    """
    if len(data) < 9:
        return None
    marker = data[0]
    width = struct.unpack("<H", data[1:3])[0]
    pad1 = struct.unpack("<H", data[3:5])[0]
    height = struct.unpack("<H", data[5:7])[0]
    pad2 = struct.unpack("<H", data[7:9])[0]
    expected = 9 + width * height * 4
    valid = (
        marker == 8
        and pad1 == 0
        and pad2 == 0
        and 0 < width < 2000
        and 0 < height < 2000
        and expected == len(data)
    )
    return {
        "marker": marker,
        "width": width,
        "height": height,
        "expected_size": expected,
        "actual_size": len(data),
        "valid_format": valid,
    }


def coverart_files_in(coverart_dir: Path) -> list[Path]:
    """Liste tous les fichiers cache d'un dossier Coverart Traktor."""
    if not coverart_dir.exists():
        return []
    files = []
    for sub in sorted(coverart_dir.iterdir()):
        if sub.is_dir():
            for f in sorted(sub.iterdir()):
                if f.is_file() and not f.name.startswith("."):
                    files.append(f)
    return files


# ----------------------------------------------------------------------------
# Hashing helpers
# ----------------------------------------------------------------------------

import base64


def hash_variants(data: bytes) -> dict[str, str]:
    """Genere de nombreux hashes encodes dans plusieurs bases."""
    out = {}
    for algo_name, algo_fn in [
        ("md5", hashlib.md5),
        ("sha1", hashlib.sha1),
        ("sha256", hashlib.sha256),
    ]:
        digest = algo_fn(data).digest()
        out[f"{algo_name}_hex"] = digest.hex()
        out[f"{algo_name}_b32"] = (
            base64.b32encode(digest).decode().rstrip("=")
        )
        out[f"{algo_name}_b64"] = (
            base64.b64encode(digest).decode().rstrip("=")
        )
        # Tronque a 28 chars pour matcher le format Traktor (~140 bits)
        b32 = base64.b32encode(digest).decode().rstrip("=")
        out[f"{algo_name}_b32_28"] = b32[:28]
    return out


# ----------------------------------------------------------------------------
# SOUS-COMMANDE : scan
# ----------------------------------------------------------------------------

def cmd_scan(args) -> None:
    """Inspection passive complete de l'installation Traktor."""
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": datetime.now().isoformat(),
        "host": os.uname().nodename,
        "user": HOME.name,
        "traktor_install_dirs": [],
        "db_files": [],
        "coverart_summary": {},
        "nml_summary": {},
    }

    banner("Detection des installations Traktor")
    install_dirs = find_traktor_install_dirs()
    if not install_dirs:
        err(f"Aucun dossier Traktor trouve sous {DOC_NI}")
    for d in install_dirs:
        ok(str(d))
        # Lister tout ce qu'il y a dedans
        children = sorted([c.name for c in d.iterdir() if not c.name.startswith(".")])
        info(f"   contenu : {', '.join(children)}")
        report["traktor_install_dirs"].append({
            "path": str(d),
            "name": d.name,
            "children": children,
        })

    banner("Recherche de bases de donnees Traktor")
    if not LIB_APP_NI.exists():
        warn(f"{LIB_APP_NI} n'existe pas")
    else:
        info(f"Scan de {LIB_APP_NI} ...")
        db_files = find_db_files()
        if not db_files:
            warn("Aucun fichier .db / .sqlite / .realm trouve")
            # Lister quand meme les dossiers Traktor sous Application Support
            for sub in LIB_APP_NI.iterdir():
                if sub.is_dir() and "traktor" in sub.name.lower():
                    info(f"  Dossier Traktor present : {sub}")
                    children = sorted([
                        c.name for c in sub.rglob("*")
                        if c.is_file() and not c.name.startswith(".")
                    ])[:30]
                    for c in children:
                        print(f"     {c}")
                    report["db_files"].append({
                        "container": str(sub),
                        "files_listed": children,
                    })
        for db in db_files:
            ok(f"DB candidate : {db} ({db.stat().st_size} bytes)")
            with db.open("rb") as f:
                magic = f.read(16)
            report["db_files"].append({
                "path": str(db),
                "size": db.stat().st_size,
                "magic_hex": magic.hex(),
                "is_sqlite": magic.startswith(b"SQLite format 3"),
            })
            # Copier la DB dans le dump (utile pour analyse offline)
            dest = out_dir / "db" / db.name
            dest.parent.mkdir(exist_ok=True)
            try:
                shutil.copy2(db, dest)
                info(f"   copie -> {dest}")
            except Exception as e:
                err(f"   copie impossible : {e}")

    banner("Inspection du cache Coverart")
    for inst in install_dirs:
        cover_dir = inst / "Coverart"
        if not cover_dir.exists():
            warn(f"Pas de Coverart dans {inst}")
            continue
        files = coverart_files_in(cover_dir)
        info(f"{cover_dir} : {len(files)} fichiers cache")
        # Stats par taille
        sizes = {}
        prefixes = set()
        for f in files:
            sz = f.stat().st_size
            sizes[sz] = sizes.get(sz, 0) + 1
            prefixes.add(f.parent.name)
        info(f"   {len(prefixes)} sous-dossiers (prefixes)")
        info(f"   distribution des tailles : {dict(list(sorted(sizes.items()))[:5])}...")

        # Echantillonner 5 fichiers et valider le format
        sample = files[:5] if len(files) <= 5 else files[: len(files) // 100 + 5]
        sample_info = []
        for f in sample[:10]:
            data = f.read_bytes()
            hdr = parse_coverart_header(data)
            sample_info.append({
                "name": f.parent.name + "/" + f.name,
                "size": len(data),
                "header": hdr,
            })
            if hdr:
                fmt = "OK" if hdr["valid_format"] else "MISMATCH"
                info(f"   {f.parent.name}/{f.name}  {hdr['width']}x{hdr['height']}  {fmt}")

        # Copier 6 fichiers (2 de chaque resolution si possible) vers le dump
        dest_dir = out_dir / "coverart_sample" / inst.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        seen_prefixes = set()
        for f in files:
            if f.parent.name in seen_prefixes:
                continue
            seen_prefixes.add(f.parent.name)
            sub_dest = dest_dir / f.parent.name
            sub_dest.mkdir(exist_ok=True)
            # copier les 3 resolutions du meme nom de base
            base = f.name[:-3]  # enleve "000" / "001" / "002"
            for sibling in f.parent.glob(base + "*"):
                shutil.copy2(sibling, sub_dest / sibling.name)
                copied += 1
            if copied >= 18:  # 6 prefixes * 3 resolutions
                break
        info(f"   {copied} fichiers cache copies vers {dest_dir}")

        report["coverart_summary"][inst.name] = {
            "total_files": len(files),
            "n_prefixes": len(prefixes),
            "sample": sample_info,
        }

    banner("Inspection des NML Traktor")
    for inst in install_dirs:
        nml_main = inst / "collection.nml"
        if nml_main.exists():
            data = nml_main.read_bytes()
            n_entries = data.count(b"<ENTRY ")
            n_coverartid = data.count(b"COVERARTID")
            head = data[:200].decode("utf-8", errors="replace")
            ok(f"{nml_main} : {n_entries} entries, {n_coverartid} COVERARTID")
            info(f"   debut : {head[:150]!r}")
            report["nml_summary"][inst.name] = {
                "path": str(nml_main),
                "size": len(data),
                "n_entries": n_entries,
                "n_coverartid": n_coverartid,
            }
            # Copier le NML
            dest = out_dir / "nml" / f"{inst.name}__collection.nml"
            dest.parent.mkdir(exist_ok=True)
            shutil.copy2(nml_main, dest)
            info(f"   copie -> {dest}")
        else:
            warn(f"Pas de collection.nml dans {inst}")

    banner("Sauvegarde du rapport")
    report_path = out_dir / "scan_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    ok(f"Rapport JSON : {report_path}")

    print(f"\n{C.B}{C.GREEN}Inspection terminee.{C.R}")
    print(f"Tout est dans : {C.CYAN}{out_dir}{C.R}")
    print(f"\nProchaine etape recommandee :")
    print(f"  {C.CYAN}python3 {sys.argv[0]} monitor{C.R}")
    print(f"\nPuis charge un track sur un deck dans Traktor pour")
    print(f"capturer le mapping (track -> fichier cache cree).")


# ----------------------------------------------------------------------------
# SOUS-COMMANDE : monitor
# ----------------------------------------------------------------------------

def cmd_monitor(args) -> None:
    """Surveille le dossier Coverart en temps reel."""
    install_dirs = find_traktor_install_dirs()
    if not install_dirs:
        err(f"Aucun dossier Traktor trouve sous {DOC_NI}")
        sys.exit(1)
    cover_dir = Path(args.coverart) if args.coverart else (install_dirs[-1] / "Coverart")
    if not cover_dir.exists():
        err(f"Coverart introuvable : {cover_dir}")
        sys.exit(1)

    banner(f"Surveillance temps reel : {cover_dir}")
    print(f"{C.YELLOW}Instructions :{C.R}")
    print(f"  1. Garde Traktor ouvert")
    print(f"  2. Dans Traktor, charge un track sur un deck (un que tu sais")
    print(f"     ne PAS avoir d'artwork affiche, idealement issu de la")
    print(f"     conversion Rekordbox)")
    print(f"  3. Le script affichera en direct les fichiers crees/modifies")
    print(f"  4. Note l'association : track charge -> fichier cache cree")
    print(f"  5. Ctrl+C pour arreter\n")

    # Snapshot initial
    def snapshot() -> dict[Path, float]:
        result = {}
        for sub in cover_dir.iterdir():
            if sub.is_dir():
                for f in sub.iterdir():
                    if f.is_file() and not f.name.startswith("."):
                        try:
                            result[f] = f.stat().st_mtime
                        except FileNotFoundError:
                            pass
        return result

    initial = snapshot()
    info(f"Snapshot initial : {len(initial)} fichiers")
    info("En attente de nouveaux fichiers... (Ctrl+C pour arreter)")
    print()

    log = []
    try:
        while True:
            time.sleep(1)
            current = snapshot()
            new_files = [
                f for f, mt in current.items()
                if f not in initial or initial.get(f) != mt
            ]
            for f in new_files:
                ts = datetime.now().strftime("%H:%M:%S")
                rel = f.parent.name + "/" + f.name
                size = f.stat().st_size
                hdr = parse_coverart_header(f.read_bytes())
                if hdr:
                    dim = f"{hdr['width']}x{hdr['height']}"
                else:
                    dim = "?"
                line = f"{C.GREEN}[{ts}]{C.R} {C.B}{rel}{C.R}  {size} bytes  {dim}"
                print(line)
                log.append({
                    "ts": ts,
                    "path": str(f),
                    "rel": rel,
                    "size": size,
                    "dimensions": dim,
                    "header": hdr,
                })
                initial[f] = current[f]
    except KeyboardInterrupt:
        print()
        banner("Surveillance interrompue")
        info(f"Total de fichiers nouveaux/modifies : {len(log)}")
        if log:
            log_path = Path("monitor_log.json")
            log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False))
            ok(f"Log sauvegarde : {log_path.resolve()}")
            print(f"\n{C.YELLOW}IMPORTANT pour Lorys :{C.R}")
            print(f"Pour chaque ligne ci-dessus, note dans un fichier .txt :")
            print(f"  - le chemin complet du MP3 que tu venais de charger sur le deck")
            print(f"  - le nom de fichier cache qui a ete cree (rel)")
            print(f"\nCa donne le mapping mp3_path -> cache_filename qu'on cherche.")


# ----------------------------------------------------------------------------
# SOUS-COMMANDE : analyze
# ----------------------------------------------------------------------------

def cmd_analyze(args) -> None:
    """Analyse un MP3 et tente de matcher avec un fichier cache."""
    ensure_deps()
    from mutagen.id3 import ID3
    from PIL import Image
    import io

    mp3_path = Path(args.mp3).resolve()
    if not mp3_path.exists():
        err(f"MP3 introuvable : {mp3_path}")
        sys.exit(1)

    banner(f"Analyse de {mp3_path.name}")

    # 1. Lecture du fichier audio
    try:
        tags = ID3(mp3_path)
    except Exception as e:
        err(f"Erreur lecture ID3 : {e}")
        sys.exit(1)

    apics = tags.getall("APIC")
    info(f"Frames APIC : {len(apics)}")
    if not apics:
        err("Pas d'APIC dans ce MP3")
        sys.exit(1)

    apic = apics[0]
    apic_data = apic.data
    info(f"APIC mime : {apic.mime}")
    info(f"APIC type : {apic.type}")
    info(f"APIC taille : {len(apic_data)} bytes")

    # Charger l'image pour avoir ses dimensions
    img = Image.open(io.BytesIO(apic_data))
    info(f"Image : {img.size} {img.mode} {img.format}")

    # 2. Generer tous les hashes possibles
    banner("Generation des candidats de hash")
    hashes = {}
    inputs = {
        "audio_path_full": str(mp3_path).encode(),
        "audio_path_lower": str(mp3_path).lower().encode(),
        "audio_filename": mp3_path.name.encode(),
        "audio_path_traktor_format": (
            "/:" + str(mp3_path).replace("/", "/:")
        ).encode(),
        "apic_data": apic_data,
        "audio_full_bytes": mp3_path.read_bytes(),
        "audio_first_1mb": mp3_path.read_bytes()[: 1024 * 1024],
    }
    for input_name, input_bytes in inputs.items():
        h = hash_variants(input_bytes)
        for k, v in h.items():
            hashes[f"{input_name}__{k}"] = v
    info(f"{len(hashes)} candidats hash generes")

    # 3. Chercher dans le dossier Coverart un fichier qui matche
    install_dirs = find_traktor_install_dirs()
    if not install_dirs:
        warn("Pas de Traktor install : impossible de chercher des matches")
        return

    cover_dir = Path(args.cache_dir) if args.cache_dir else (install_dirs[-1] / "Coverart")
    if not cover_dir.exists():
        err(f"Coverart introuvable : {cover_dir}")
        return

    banner(f"Recherche de match dans {cover_dir}")
    files = coverart_files_in(cover_dir)
    info(f"{len(files)} fichiers cache a comparer")

    # Set de noms de fichier (sans suffixe 000/001/002)
    cache_names = set()
    cache_full = {}  # nom_base -> liste de fichiers
    for f in files:
        base = f.name[:-3]
        cache_names.add(base)
        cache_full.setdefault(base, []).append(f)

    matches = []
    for hash_name, hash_value in hashes.items():
        for cache_base in cache_names:
            # Match exact ou prefixe
            if hash_value == cache_base or cache_base.startswith(hash_value) or hash_value.startswith(cache_base):
                matches.append((hash_name, hash_value, cache_base))
                ok(f"MATCH ! {hash_name} = {hash_value}")
                ok(f"   cache : {cache_base}")
                for f in cache_full[cache_base]:
                    ok(f"   -> {f}")

    if not matches:
        warn("Aucun match direct trouve")
        info("Sample des cache names disponibles :")
        for n in list(cache_names)[:5]:
            print(f"   {n}")
        info("Sample des hashes generes (premiers 5) :")
        for k, v in list(hashes.items())[:5]:
            print(f"   {k} = {v}")

    # Sauvegarder le rapport
    report = {
        "mp3": str(mp3_path),
        "apic_size": len(apic_data),
        "image_dimensions": img.size,
        "hashes_tried": hashes,
        "matches_found": [
            {"hash_name": m[0], "hash_value": m[1], "cache_base": m[2]}
            for m in matches
        ],
        "cache_names_count": len(cache_names),
    }
    report_path = Path(f"analyze_{mp3_path.stem[:30]}.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    ok(f"Rapport : {report_path.resolve()}")


# ----------------------------------------------------------------------------
# SOUS-COMMANDE : reverse-coverid
# ----------------------------------------------------------------------------

# Alphabet Base32 custom Native Instruments
# 32 chars : 6 chiffres (0-5) + 26 lettres
NI_ALPHABET = "012345ABCDEFGHIJKLMNOPQRSTUVWXYZ"
NI_ALPHABET_REV = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"


def decode_ni_b32(s: str, alphabet: str = NI_ALPHABET) -> bytes:
    """Decode 28 chars NI custom Base32 -> 18 bytes (140 bits + 4 bits padding)."""
    table = {c: i for i, c in enumerate(alphabet)}
    bits = 0
    nbits = 0
    out = bytearray()
    for c in s:
        if c not in table:
            return b""
        bits = (bits << 5) | table[c]
        nbits += 5
        while nbits >= 8:
            nbits -= 8
            out.append((bits >> nbits) & 0xFF)
    if nbits > 0:
        out.append((bits << (8 - nbits)) & 0xFF)
    return bytes(out)


def parse_traktor3_nml_with_covers(nml_path: Path) -> list[dict]:
    """Parse un NML Traktor 3 et retourne les entries qui ont un COVERARTID."""
    text = nml_path.read_text(encoding="utf-8", errors="replace")
    entries = []
    pattern = re.compile(
        r'<ENTRY([^>]*?)>(.*?)</ENTRY>',
        re.DOTALL,
    )
    for m in pattern.finditer(text):
        attrs = m.group(1)
        body = m.group(2)
        loc = re.search(
            r'<LOCATION DIR="([^"]*)" FILE="([^"]*)"(?: VOLUME="([^"]*)")?',
            body,
        )
        if not loc:
            continue
        info_match = re.search(r'<INFO[^>]*?>', body)
        if not info_match:
            continue
        cover = re.search(r'COVERARTID="([^"]*)"', info_match.group(0))
        if not cover:
            continue
        title = re.search(r'TITLE="([^"]*)"', attrs)
        artist = re.search(r'ARTIST="([^"]*)"', attrs)
        album = re.search(r'<ALBUM[^>]*?TITLE="([^"]*)"', body)
        # Construire le chemin reel : Traktor format /:Library/:Application Support/:...
        dir_traktor = loc.group(1)
        file_name = loc.group(2)
        volume = loc.group(3) if loc.group(3) else ""
        # Convertir /:foo/:bar/: -> /foo/bar/
        clean_dir = dir_traktor.replace("/:", "/").lstrip("/")
        # Tenter plusieurs racines
        candidates = []
        if clean_dir.startswith("Library/"):
            candidates.append(Path("/") / clean_dir / file_name)
        if clean_dir.startswith("Users/"):
            candidates.append(Path("/") / clean_dir / file_name)
        candidates.append(Path("/") / clean_dir / file_name)
        candidates.append(HOME / clean_dir / file_name)
        # Trouver le premier qui existe
        real_path = None
        for c in candidates:
            if c.exists():
                real_path = c
                break
        entries.append({
            "title": title.group(1) if title else "",
            "artist": artist.group(1) if artist else "",
            "album": album.group(1) if album else "",
            "coverid": cover.group(1),
            "dir_traktor": dir_traktor,
            "file_name": file_name,
            "volume": volume,
            "real_path": str(real_path) if real_path else None,
        })
    return entries


def generate_hash_candidates(data: bytes) -> dict[str, bytes]:
    """Genere une trentaine de hashs sur un buffer."""
    out = {}
    for algo in ["md5", "sha1", "sha224", "sha256", "sha384", "sha512",
                 "blake2b", "blake2s"]:
        try:
            out[algo] = hashlib.new(algo, data).digest()
        except Exception:
            pass
    # ripemd160
    try:
        out["ripemd160"] = hashlib.new("ripemd160", data).digest()
    except Exception:
        pass
    # xxhash si dispo
    try:
        import xxhash
        for name, fn in [
            ("xxh32", xxhash.xxh32),
            ("xxh64", xxhash.xxh64),
            ("xxh3_64", xxhash.xxh3_64),
            ("xxh3_128", xxhash.xxh3_128),
        ]:
            out[name] = fn(data).digest()
    except ImportError:
        pass
    return out


def cmd_reverse_coverid(args) -> None:
    """Reverse-engineer l'algo COVERARTID en testant N hashs sur les APIC.

    Strategie :
    1. Lire le NML Traktor 3 (qui contient COVERARTID)
    2. Pour chaque entry, retrouver le MP3 source et lire son APIC
    3. Decoder le COVERARTID en 18 bytes (Base32 custom NI)
    4. Hasher l'APIC de plein de manieres et chercher des matches sur 17 bytes
       (140 bits utiles)
    5. Si on trouve un algo qui match sur PLUSIEURS entries, c'est gagne
    """
    ensure_deps()
    from mutagen.id3 import ID3
    from PIL import Image
    import io

    install_dirs = find_traktor_install_dirs()
    nml_path = None
    for d in install_dirs:
        if "3." in d.name or "Pro 3" in d.name:
            candidate = d / "collection.nml"
            if candidate.exists():
                nml_path = candidate
                break
    if not nml_path:
        # fallback : prendre n'importe quel NML
        for d in install_dirs:
            candidate = d / "collection.nml"
            if candidate.exists():
                nml_path = candidate
                break
    if not nml_path:
        err("Aucun collection.nml trouve")
        sys.exit(1)

    banner(f"Parsing {nml_path}")
    entries = parse_traktor3_nml_with_covers(nml_path)
    info(f"{len(entries)} entries avec COVERARTID")
    n_resolved = sum(1 for e in entries if e["real_path"])
    info(f"{n_resolved} chemins MP3 resolus sur le disque")

    if n_resolved == 0:
        err("Aucun MP3 trouve. Verifie que les fichiers existent.")
        info("Echantillon de chemins du NML :")
        for e in entries[:5]:
            print(f"  dir={e['dir_traktor']}")
            print(f"  file={e['file_name']}")
            print(f"  ->guess={e['real_path']}")
        sys.exit(1)

    # 2. Pour chaque entry resolue (limite a N), tester les hashs
    max_entries = args.max
    sample = [e for e in entries if e["real_path"]][:max_entries]
    info(f"Test sur {len(sample)} entries")

    # Algo qui matche -> liste des entries OK
    algo_matches = {}  # algo_name -> list of entry indices that matched
    failures = []

    for idx, entry in enumerate(sample):
        try:
            tags = ID3(entry["real_path"])
        except Exception as e:
            failures.append((entry, f"ID3 err: {e}"))
            continue
        apics = tags.getall("APIC")
        if not apics:
            failures.append((entry, "no APIC"))
            continue
        apic = apics[0]
        apic_data = apic.data

        # Decoder le COVERARTID en bytes
        prefix, name = entry["coverid"].split("/")
        target_v1 = decode_ni_b32(name, NI_ALPHABET)
        target_v2 = decode_ni_b32(name, NI_ALPHABET_REV)

        # Generer les inputs candidats
        inputs = {
            "apic_full": apic_data,
            "apic_no_first_2": apic_data[2:],  # parfois APIC a un mime byte
        }
        # Re-encoder en JPEG pour eliminer les variations APIC
        try:
            img = Image.open(io.BytesIO(apic_data))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=95)
            inputs["apic_reencoded_jpeg"] = buf.getvalue()
            buf2 = io.BytesIO()
            img.convert("RGB").save(buf2, format="JPEG", quality=85)
            inputs["apic_reencoded_jpeg85"] = buf2.getvalue()
            # Bitmap raw RGBA
            rgba = img.convert("RGBA")
            inputs["bitmap_rgba"] = rgba.tobytes()
            inputs["bitmap_rgb"] = img.convert("RGB").tobytes()
        except Exception as e:
            warn(f"  {entry['title']} : decode image err {e}")

        # Toutes les combinaisons hash * input
        all_candidates = {}
        for in_name, in_bytes in inputs.items():
            for algo, digest in generate_hash_candidates(in_bytes).items():
                all_candidates[f"{in_name}__{algo}"] = digest

        # Comparer aux 2 targets (alphabets v1 et v2)
        for cand_name, cand_digest in all_candidates.items():
            for tname, target in [("v1", target_v1), ("v2", target_v2)]:
                # Match sur 17 bytes (140 bits)
                if cand_digest[:17] == target[:17]:
                    full_name = f"{cand_name}__alphabet_{tname}"
                    algo_matches.setdefault(full_name, []).append(idx)

        if (idx + 1) % 5 == 0:
            info(f"  ... {idx + 1}/{len(sample)} testes")

    banner("RESULTATS")
    if algo_matches:
        # Trier par nombre de matches
        sorted_algos = sorted(algo_matches.items(), key=lambda x: -len(x[1]))
        for algo_name, indices in sorted_algos:
            color = C.GREEN if len(indices) >= 2 else C.YELLOW
            print(f"{color}{algo_name}{C.R} : {len(indices)} matches")
            for i in indices[:3]:
                e = sample[i]
                print(f"   - {e['coverid']} <- {e['album']} - {e['title'][:40]}")
        if any(len(indices) >= 2 for _, indices in algo_matches.items()):
            print(f"\n{C.B}{C.GREEN}ALGORITHME TROUVE !{C.R}")
            best = sorted_algos[0]
            print(f"Le hash gagnant : {best[0]}")
    else:
        warn("Aucun algorithme connu ne matche.")
        info("Sauvegarde de quelques APIC en JPEG pour analyse manuelle...")
        out_dir = Path("./reverse_coverid_dump")
        out_dir.mkdir(exist_ok=True)
        for idx, entry in enumerate(sample[:5]):
            try:
                tags = ID3(entry["real_path"])
                apics = tags.getall("APIC")
                if apics:
                    safe_name = entry["coverid"].replace("/", "_")
                    out_file = out_dir / f"{safe_name}__{entry['title'][:30].replace('/', '_')}.jpg"
                    out_file.write_bytes(apics[0].data)
                    info(f"  -> {out_file}")
            except Exception:
                pass

    # Toujours sauvegarder un rapport JSON detaille
    report = {
        "nml": str(nml_path),
        "entries_total": len(entries),
        "entries_resolved": n_resolved,
        "entries_tested": len(sample),
        "matches": {
            algo: [
                {
                    "coverid": sample[i]["coverid"],
                    "album": sample[i]["album"],
                    "title": sample[i]["title"],
                    "real_path": sample[i]["real_path"],
                }
                for i in indices
            ]
            for algo, indices in algo_matches.items()
        },
        "failures": [
            {"title": e["title"], "reason": r}
            for e, r in failures[:10]
        ],
        # Echantillon des entries pour debug
        "sample_entries": [
            {
                "coverid": e["coverid"],
                "album": e["album"],
                "title": e["title"],
                "real_path": e["real_path"],
                "decoded_v1_hex": decode_ni_b32(e["coverid"].split("/")[1], NI_ALPHABET).hex(),
                "decoded_v2_hex": decode_ni_b32(e["coverid"].split("/")[1], NI_ALPHABET_REV).hex(),
            }
            for e in sample[:10]
        ],
    }
    report_path = Path("reverse_coverid_report.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    ok(f"Rapport : {report_path.resolve()}")


# ----------------------------------------------------------------------------
# SOUS-COMMANDE : db-dump
# ----------------------------------------------------------------------------

def cmd_db_dump(args) -> None:
    """Dump du schema et echantillon d'une DB SQLite."""
    import sqlite3

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        err(f"DB introuvable : {db_path}")
        sys.exit(1)

    banner(f"Dump SQLite : {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()

    # Liste des tables
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = cur.fetchall()
    ok(f"{len(tables)} tables :")
    for name, sql in tables:
        print(f"  {C.B}{name}{C.R}")
        if sql:
            for line in sql.split("\n")[:10]:
                print(f"    {C.DIM}{line}{C.R}")

    # Echantillon de chaque table
    report = {"db": str(db_path), "tables": {}}
    for name, sql in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {name}")
            count = cur.fetchone()[0]
            cur.execute(f"SELECT * FROM {name} LIMIT 3")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            print(f"\n  {C.CYAN}{name}{C.R} ({count} rows)")
            print(f"    cols : {cols}")
            for r in rows:
                # Tronquer les valeurs trop longues
                short = tuple(
                    (str(v)[:60] + "...") if len(str(v)) > 60 else v
                    for v in r
                )
                print(f"    {short}")
            report["tables"][name] = {
                "count": count,
                "columns": cols,
                "sample": [list(r) for r in rows[:3]],
            }
        except Exception as e:
            err(f"   {name} : {e}")

    conn.close()
    report_path = Path(f"db_dump_{db_path.stem}.json")
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str)
    )
    ok(f"Rapport : {report_path.resolve()}")


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnostic Traktor Data Converter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Inspection passive complete")
    p_scan.add_argument(
        "--out",
        default="./inspection_dump",
        help="Dossier de sortie (default: ./inspection_dump)",
    )

    p_mon = sub.add_parser("monitor", help="Surveillance temps reel du Coverart")
    p_mon.add_argument(
        "--coverart",
        default=None,
        help="Chemin du Coverart (auto-detecte sinon)",
    )

    p_an = sub.add_parser("analyze", help="Analyse un MP3 et cherche son cache")
    p_an.add_argument("mp3", help="Chemin du MP3 a analyser")
    p_an.add_argument(
        "--cache-dir",
        default=None,
        help="Chemin du Coverart (auto-detecte sinon)",
    )

    p_db = sub.add_parser("db-dump", help="Dump d'une DB SQLite")
    p_db.add_argument("db", help="Chemin du fichier .db / .sqlite")

    p_rev = sub.add_parser(
        "reverse-coverid",
        help="Reverse-engineer l'algo COVERARTID via le NML Traktor 3 + APIC",
    )
    p_rev.add_argument(
        "--max",
        type=int,
        default=20,
        help="Nombre max d'entries a tester (default: 20)",
    )

    args = parser.parse_args()

    print(f"{C.B}{C.BLUE}Traktor Data Converter — Diagnostic v1{C.R}")
    print(f"{C.DIM}Host: {os.uname().nodename}  User: {HOME.name}{C.R}")

    if args.cmd == "scan":
        cmd_scan(args)
    elif args.cmd == "monitor":
        cmd_monitor(args)
    elif args.cmd == "analyze":
        cmd_analyze(args)
    elif args.cmd == "db-dump":
        cmd_db_dump(args)
    elif args.cmd == "reverse-coverid":
        cmd_reverse_coverid(args)


if __name__ == "__main__":
    main()
