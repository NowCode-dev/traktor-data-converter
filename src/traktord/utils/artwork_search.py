"""Recherche d'artwork via APIs externes pour les tracks sans cover embedded.

Strategie V1 : iTunes Search API uniquement (gratuit, sans cle, large
couverture musique commerciale).

Pour chaque track, on construit une query "artist title", on recupere
les top resultats, on compare en fuzzy match, et on telecharge l'image
HD du meilleur match si le score depasse le seuil.

Notes ToS :
    iTunes Search API impose dans ses Terms of Service que les resultats
    soient utilises pour "finding and recommending iTunes Store content
    to end users". L'usage "completer la cover manquante d'une biblio
    DJ proprietaire" est dans la zone grise — a documenter pour les
    utilisateurs commerciaux (deck2deck.ch).
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Optional


#: Seuil de confiance minimum pour accepter un match iTunes.
_MATCH_SCORE_THRESHOLD = 0.7

#: Resolution HD a recuperer depuis iTunes (substitution de 100x100bb).
_ITUNES_HD_RES = "600x600bb"

#: Timeout des requetes HTTP en secondes.
_HTTP_TIMEOUT = 8

#: User-Agent pour les requetes (evite les blocs sur certains endpoints).
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "deck2deck-traktord/1.x"
)


def search_itunes_cover(
    artist: str,
    title: str,
    threshold: float = _MATCH_SCORE_THRESHOLD,
) -> Optional[bytes]:
    """Recherche une cover sur iTunes Search API et retourne ses bytes JPEG.

    Args:
        artist: Nom de l'artiste (peut contenir des virgules pour les
            collaborations — on prend le premier nom pour le match).
        title: Nom du track (peut contenir des suffixes "(Original Mix)",
            "(Remix)", etc. — on les normalise pour le match).
        threshold: Score minimum pour accepter un match (0.0-1.0).

    Returns:
        Bytes JPEG de la cover en HD si trouvee avec score >= threshold,
        sinon None.
    """
    if not artist.strip() or not title.strip():
        return None

    try:
        results = _query_itunes(artist, title)
    except Exception:
        return None

    if not results:
        return None

    best = _best_match(artist, title, results)
    if best is None:
        return None

    score, item = best
    if score < threshold:
        return None

    artwork_url = item.get("artworkUrl100", "")
    if not artwork_url:
        return None

    hd_url = artwork_url.replace("100x100bb", _ITUNES_HD_RES)
    try:
        return _download(hd_url)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------

def _query_itunes(artist: str, title: str) -> list[dict]:
    """Lance une requete iTunes Search API et retourne les top resultats."""
    primary_artist = artist.split(",")[0].strip()
    query = f"{primary_artist} {_strip_mix_suffix(title)}"
    url = (
        "https://itunes.apple.com/search?"
        + urllib.parse.urlencode(
            {"term": query, "entity": "song", "limit": 5}
        )
    )
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("results", [])


def _best_match(artist: str, title: str, results: list[dict]):
    """Choisit le meilleur match parmi les resultats iTunes.

    Returns:
        Tuple (score, item) ou None si aucun match raisonnable.
    """
    target_artist = _normalize(artist.split(",")[0])
    target_title = _normalize(_strip_mix_suffix(title))

    best = None
    for item in results:
        item_artist = _normalize(item.get("artistName", ""))
        item_title = _normalize(_strip_mix_suffix(item.get("trackName", "")))
        artist_score = _string_similarity(target_artist, item_artist)
        title_score = _string_similarity(target_title, item_title)
        # Title pese plus que artist (un meme track peut avoir plusieurs credits)
        score = title_score * 0.6 + artist_score * 0.4
        if best is None or score > best[0]:
            best = (score, item)
    return best


def _strip_mix_suffix(s: str) -> str:
    """Enleve les suffixes type "(Original Mix)", "(Remix)", "[Mixed]"."""
    return re.sub(
        r"[\(\[].*?(mix|remix|edit|version|mixed|extended).*?[\)\]]\s*$",
        "",
        s,
        flags=re.IGNORECASE,
    ).strip()


def _normalize(s: str) -> str:
    """Lowercase + retire ponctuation/parens + reduit espaces."""
    s = s.lower()
    s = re.sub(r"[\(\[\{].*?[\)\]\}]", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _string_similarity(a: str, b: str) -> float:
    """Score de similarite entre 2 strings (0.0-1.0).

    Approche bag-of-words : ratio de tokens communs sur l'union, en
    incluant un bonus si l'un est substring de l'autre.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0

    common = tokens_a & tokens_b
    union = tokens_a | tokens_b
    jaccard = len(common) / len(union)

    # Bonus substring (pour gerer "bicep" vs "bicep glue mixed")
    if a in b or b in a:
        return min(1.0, jaccard + 0.2)
    return jaccard


def _download(url: str) -> bytes:
    """Telecharge le contenu d'une URL et retourne ses bytes."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return resp.read()
