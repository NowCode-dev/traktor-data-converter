"""Gestion de licence freemium deck2deck.

Modele :
- Gratuit : 25 tracks max par operation
- Unlimited : $19.90 one-shot via Gumroad

La cle de licence est stockee dans ~/.deck2deck-license
Format de cle : D2D-XXXXX-XXXXX-XXXXX-XXXXX (20 chars hex + prefixe)
Verification locale (pas de serveur) via checksum integre.
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from typing import Optional


#: Nombre max de tracks en mode gratuit
FREE_TRACK_LIMIT = 25

#: Fichier de licence
LICENSE_FILE = Path.home() / ".deck2deck-license"

#: Lien d'achat Gumroad
GUMROAD_URL = "https://marrocco3.gumroad.com/l/vrellq"

#: Sel pour la verification de cle (pas un secret, juste un checksum)
_SALT = "deck2deck-2026-ch"


def _compute_checksum(parts: str) -> str:
    """Calcule un checksum de 5 chars hex depuis les 3 premiers blocs."""
    h = hashlib.sha256(f"{_SALT}:{parts}".encode()).hexdigest()
    return h[:5].upper()


def generate_license_key() -> str:
    """Genere une cle de licence valide.

    Format : D2D-XXXXX-XXXXX-XXXXX-XXXXX
    Les 3 premiers blocs sont aleatoires, le 4eme est un checksum.
    """
    blocks = [secrets.token_hex(3)[:5].upper() for _ in range(3)]
    parts = "-".join(blocks)
    checksum = _compute_checksum(parts)
    return f"D2D-{parts}-{checksum}"


def validate_license_key(key: str) -> bool:
    """Verifie qu'une cle de licence est valide (format + checksum)."""
    key = key.strip().upper()
    if not key.startswith("D2D-"):
        return False

    rest = key[4:]  # Apres "D2D-"
    parts = rest.split("-")
    if len(parts) != 4:
        return False

    # Chaque bloc doit etre 5 chars hex
    for p in parts:
        if len(p) != 5:
            return False
        try:
            int(p, 16)
        except ValueError:
            return False

    # Verifier le checksum (4eme bloc)
    first_three = "-".join(parts[:3])
    expected = _compute_checksum(first_three)
    return parts[3] == expected


def save_license(key: str) -> None:
    """Sauvegarde la cle de licence dans ~/.deck2deck-license."""
    LICENSE_FILE.write_text(key.strip().upper() + "\n")


def load_license() -> Optional[str]:
    """Lit la cle de licence sauvegardee, ou None si absente/invalide."""
    if not LICENSE_FILE.exists():
        return None
    key = LICENSE_FILE.read_text().strip()
    if validate_license_key(key):
        return key
    return None


def is_licensed() -> bool:
    """Verifie si une licence valide est active."""
    return load_license() is not None


def check_track_limit(track_count: int) -> tuple[bool, str]:
    """Verifie si le nombre de tracks est dans la limite.

    Returns:
        Tuple (autorise, message).
    """
    if is_licensed():
        return True, "Licence unlimited active"

    if track_count <= FREE_TRACK_LIMIT:
        remaining = FREE_TRACK_LIMIT - track_count
        return True, f"Mode gratuit : {track_count}/{FREE_TRACK_LIMIT} tracks ({remaining} restants)"

    return False, (
        f"Mode gratuit limite a {FREE_TRACK_LIMIT} tracks "
        f"({track_count} demandes).\n"
        f"Achetez une licence unlimited sur {GUMROAD_URL}"
    )
