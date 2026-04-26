"""Recherche d'artwork via APIs externes en cascade multi-sources.

V1.9.0 — cascade ordonnee pour biblio DJ underground :

    1. Beatport via TrackID extrait du filename (rapide et fiable
       pour les achats Beatport recents qui suivent le pattern
       `(MM-YYYY)-(ID)_artist-title-mix-label.ext`).
    2. Discogs via API publique (catalogue large electronique
       underground). Token user optionnel via env var DISCOGS_TOKEN
       pour augmenter le rate limit (25 → 60 req/min).
    3. MusicBrainz + Cover Art Archive (couverture large, gratuite).
       Rate limit 1 req/s applique.
    4. iTunes Search API (V1.8.0). Fallback pour la pop / commercial.

La premiere source qui retourne une cover avec un score de match
suffisant arrete la cascade.

Notes ToS :

    - Beatport : scrape passif de la page produit (og:image meta tag).
      Pas de contournement d'auth, pas de mass scraping.
    - Discogs : API publique, conforme a leurs ToS (User-Agent identifie).
    - MusicBrainz / Cover Art Archive : usage gratuit, rate limit 1 req/s
      respecte (header User-Agent identifie).
    - iTunes : meme remarque qu'en V1.8.0.

L'API publique conservee pour compatibilite tests : `search_itunes_cover`.
La nouvelle API recommandee : `find_cover_cascade`.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional


#: Seuil de confiance minimum pour accepter un match.
_MATCH_SCORE_THRESHOLD = 0.7

#: Resolution HD a recuperer depuis iTunes (substitution de 100x100bb).
_ITUNES_HD_RES = "600x600bb"

#: Resolution Beatport HD (substitue dans l'URL geo-media).
_BEATPORT_HD_RES = "1400x1400"

#: Taille image Cover Art Archive (front-1200 = 1200px max).
_CAA_FRONT_SIZE = "1200"

#: Timeout des requetes HTTP en secondes.
_HTTP_TIMEOUT = 10

#: User-Agent generique (evite les blocs sur certains endpoints).
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "deck2deck-traktord/1.9"
)

#: User-Agent specifique MusicBrainz (require par leurs guidelines).
_MB_USER_AGENT = "deck2deck-traktord/1.9 (https://deck2deck.ch)"

#: Regex extraction TrackID Beatport dans le filename.
#: Format observe : `(MM-YYYY)-(ID)_artist-title-mix-label.ext`
_BEATPORT_ID_RE = re.compile(r"\(\d{2}-\d{4}\)-\((\d+)\)_")

#: Regex extraction og:image dans une page HTML.
_OG_IMAGE_RE = re.compile(
    r'<meta\s+property="og:image"\s+content="([^"]+)"', re.IGNORECASE
)

#: Variable de module pour rate limit MusicBrainz (1 req/s minimum).
_last_mb_call: float = 0.0


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def find_cover_cascade(
    artist: str,
    title: str,
    file_path: Optional[Path] = None,
    discogs_token: Optional[str] = None,
    threshold: float = _MATCH_SCORE_THRESHOLD,
) -> tuple[Optional[bytes], Optional[str]]:
    """Cascade multi-sources pour trouver une cover en ligne.

    Ordre teste : Beatport (TrackID filename) -> Discogs -> MusicBrainz/CAA
    -> iTunes. Premier match valide gagne.

    Args:
        artist: Nom de l'artiste.
        title: Nom du track.
        file_path: Chemin vers le fichier audio (optionnel) — utilise
            uniquement pour extraire le TrackID Beatport du nom de fichier.
        discogs_token: Token user Discogs (optionnel). Si None, lit l'env var
            DISCOGS_TOKEN. Si toujours None, requetes anonymes (rate limit
            plus bas).
        threshold: Score minimum pour accepter un match fuzzy (0.0-1.0).

    Returns:
        Tuple `(bytes, source)` ou `source` est l'une des chaines
        `"beatport"`, `"discogs"`, `"musicbrainz"`, `"itunes"`. Si aucune
        source ne trouve, retourne `(None, None)`.
    """
    if discogs_token is None:
        discogs_token = os.environ.get("DISCOGS_TOKEN")

    # 1. Beatport via TrackID (filename) — pas de fuzzy match necessaire,
    #    le TrackID est deterministe.
    if file_path is not None:
        cover = _search_beatport_id(file_path)
        if cover:
            return cover, "beatport"

    if not artist.strip() or not title.strip():
        return None, None

    # 2. Discogs
    cover = _search_discogs(artist, title, discogs_token, threshold)
    if cover:
        return cover, "discogs"

    # 3. MusicBrainz + Cover Art Archive
    cover = _search_musicbrainz(artist, title, threshold)
    if cover:
        return cover, "musicbrainz"

    # 4. iTunes (V1.8.0 logic)
    cover = _search_itunes(artist, title, threshold)
    if cover:
        return cover, "itunes"

    return None, None


def search_itunes_cover(
    artist: str,
    title: str,
    threshold: float = _MATCH_SCORE_THRESHOLD,
) -> Optional[bytes]:
    """Recherche une cover sur iTunes Search API.

    Conserve pour compatibilite avec les tests V1.8.0. Pour le code
    appelant nouveau, prefere `find_cover_cascade`.
    """
    if not artist.strip() or not title.strip():
        return None
    return _search_itunes(artist, title, threshold)


# ---------------------------------------------------------------------------
# Source 1 : Beatport via TrackID (filename)
# ---------------------------------------------------------------------------

def _search_beatport_id(file_path: Path) -> Optional[bytes]:
    """Cherche la cover Beatport via le TrackID extrait du filename.

    Le filename doit suivre le pattern Beatport recent :
    `(MM-YYYY)-(ID)_artist-title-mix-label.ext`.
    """
    match = _BEATPORT_ID_RE.search(file_path.name)
    if not match:
        return None
    track_id = match.group(1)
    return _fetch_beatport_track_image(track_id)


def _fetch_beatport_track_image(track_id: str) -> Optional[bytes]:
    """Telecharge l'image HD d'un track Beatport via son ID.

    GET la page produit, extrait le tag og:image (servi par geo-media
    en HD 1400x1400).
    """
    # Le slug peut etre arbitraire, Beatport redirige vers le bon.
    url = f"https://www.beatport.com/track/x/{track_id}"
    try:
        html = _http_get(url).decode("utf-8", errors="replace")
    except Exception:
        return None

    m = _OG_IMAGE_RE.search(html)
    if not m:
        return None

    img_url = m.group(1)
    # Force la resolution HD si besoin (Beatport sert deja en 1400x1400
    # par defaut, mais on s'assure).
    img_url = re.sub(r"/image_size/\d+x\d+/", f"/image_size/{_BEATPORT_HD_RES}/", img_url)

    try:
        return _download(img_url)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Source 2 : Discogs
# ---------------------------------------------------------------------------

def _search_discogs(
    artist: str,
    title: str,
    token: Optional[str],
    threshold: float,
) -> Optional[bytes]:
    """Recherche un release Discogs et telecharge la cover primaire."""
    primary_artist = artist.split(",")[0].strip()
    query = f"{primary_artist} {_strip_mix_suffix(title)}"

    headers = {"User-Agent": _USER_AGENT}
    if token:
        headers["Authorization"] = f"Discogs token={token}"

    url = (
        "https://api.discogs.com/database/search?"
        + urllib.parse.urlencode({"q": query, "type": "release", "per_page": 5})
    )
    try:
        data = _http_json(url, headers=headers)
    except Exception:
        return None

    results = data.get("results", [])
    if not results:
        return None

    # Selection du meilleur match en fuzzy avant de fetch les details.
    target_artist = _normalize(primary_artist)
    target_title = _normalize(_strip_mix_suffix(title))
    best: Optional[tuple[float, dict]] = None
    for item in results:
        # Discogs format release "Artist - Title"
        item_title_full = _normalize(item.get("title", ""))
        score = _string_similarity(
            f"{target_artist} {target_title}", item_title_full
        )
        if best is None or score > best[0]:
            best = (score, item)

    if best is None or best[0] < threshold:
        return None

    release_id = best[1].get("id")
    if not release_id:
        return None

    # Fetch le detail pour avoir les images (le champ cover_image de la
    # search est souvent vide).
    detail_url = f"https://api.discogs.com/releases/{release_id}"
    try:
        detail = _http_json(detail_url, headers=headers)
    except Exception:
        return None

    images = detail.get("images", [])
    if not images:
        return None

    # Privilegie l'image primary, sinon premiere.
    primary = next((img for img in images if img.get("type") == "primary"), images[0])
    img_url = primary.get("uri") or primary.get("uri150")
    if not img_url:
        return None

    try:
        return _download(img_url)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Source 3 : MusicBrainz + Cover Art Archive
# ---------------------------------------------------------------------------

def _search_musicbrainz(
    artist: str,
    title: str,
    threshold: float,
) -> Optional[bytes]:
    """Recherche un MBID release via MusicBrainz et fetch CAA."""
    primary_artist = artist.split(",")[0].strip()
    clean_title = _strip_mix_suffix(title)

    # Lucene query syntax MusicBrainz.
    query = f'artist:"{primary_artist}" AND recording:"{clean_title}"'
    url = (
        "https://musicbrainz.org/ws/2/recording/?"
        + urllib.parse.urlencode({"query": query, "fmt": "json", "limit": 5})
    )
    try:
        data = _mb_http_json(url)
    except Exception:
        return None

    recordings = data.get("recordings", [])
    if not recordings:
        return None

    # Selection du meilleur match.
    target_artist = _normalize(primary_artist)
    target_title = _normalize(clean_title)
    best: Optional[tuple[float, dict]] = None
    for rec in recordings:
        rec_artist = _normalize(
            ", ".join(c.get("name", "") for c in rec.get("artist-credit", []))
        )
        rec_title = _normalize(_strip_mix_suffix(rec.get("title", "")))
        artist_score = _string_similarity(target_artist, rec_artist)
        title_score = _string_similarity(target_title, rec_title)
        score = title_score * 0.6 + artist_score * 0.4
        if best is None or score > best[0]:
            best = (score, rec)

    if best is None or best[0] < threshold:
        return None

    releases = best[1].get("releases", [])
    if not releases:
        return None

    # Tente CAA sur les releases dans l'ordre, premier hit gagne.
    for release in releases[:3]:
        mbid = release.get("id")
        if not mbid:
            continue
        cover = _fetch_caa_front(mbid)
        if cover:
            return cover

    return None


def _fetch_caa_front(release_mbid: str) -> Optional[bytes]:
    """Telecharge l'image front depuis Cover Art Archive."""
    url = f"https://coverartarchive.org/release/{release_mbid}/front-{_CAA_FRONT_SIZE}"
    try:
        return _download(url)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Source 4 : iTunes (logique V1.8.0)
# ---------------------------------------------------------------------------

def _search_itunes(
    artist: str,
    title: str,
    threshold: float,
) -> Optional[bytes]:
    """Recherche une cover via iTunes Search API (logique V1.8.0)."""
    try:
        results = _query_itunes(artist, title)
    except Exception:
        return None

    if not results:
        return None

    best = _best_itunes_match(artist, title, results)
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


def _query_itunes(artist: str, title: str) -> list[dict]:
    """Lance une requete iTunes Search API et retourne les top resultats."""
    primary_artist = artist.split(",")[0].strip()
    query = f"{primary_artist} {_strip_mix_suffix(title)}"
    url = (
        "https://itunes.apple.com/search?"
        + urllib.parse.urlencode({"term": query, "entity": "song", "limit": 5})
    )
    data = _http_json(url, headers={"User-Agent": _USER_AGENT})
    return data.get("results", [])


def _best_itunes_match(
    artist: str, title: str, results: list[dict]
) -> Optional[tuple[float, dict]]:
    """Choisit le meilleur match parmi les resultats iTunes."""
    target_artist = _normalize(artist.split(",")[0])
    target_title = _normalize(_strip_mix_suffix(title))

    best: Optional[tuple[float, dict]] = None
    for item in results:
        item_artist = _normalize(item.get("artistName", ""))
        item_title = _normalize(_strip_mix_suffix(item.get("trackName", "")))
        artist_score = _string_similarity(target_artist, item_artist)
        title_score = _string_similarity(target_title, item_title)
        score = title_score * 0.6 + artist_score * 0.4
        if best is None or score > best[0]:
            best = (score, item)
    return best


# ---------------------------------------------------------------------------
# Utilitaires HTTP
# ---------------------------------------------------------------------------

def _http_get(url: str, headers: Optional[dict] = None) -> bytes:
    """GET HTTP simple avec User-Agent par defaut."""
    h = {"User-Agent": _USER_AGENT}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return resp.read()


def _http_json(url: str, headers: Optional[dict] = None) -> dict:
    """GET HTTP qui parse la reponse en JSON."""
    raw = _http_get(url, headers=headers)
    return json.loads(raw.decode("utf-8"))


def _mb_http_json(url: str) -> dict:
    """GET HTTP MusicBrainz avec rate limit 1 req/s."""
    global _last_mb_call
    now = time.monotonic()
    elapsed = now - _last_mb_call
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _last_mb_call = time.monotonic()
    return _http_json(url, headers={"User-Agent": _MB_USER_AGENT})


def _download(url: str) -> bytes:
    """Telecharge le contenu d'une URL et retourne ses bytes."""
    return _http_get(url)


# ---------------------------------------------------------------------------
# Utilitaires fuzzy match
# ---------------------------------------------------------------------------

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

    Approche bag-of-words : ratio de tokens communs sur l'union, avec
    bonus si l'un est substring de l'autre.
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

    if a in b or b in a:
        return min(1.0, jaccard + 0.2)
    return jaccard
