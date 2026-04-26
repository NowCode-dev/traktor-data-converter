"""Writer pour le format Traktor NML (Native Instruments).

Format valide selon les specs reverse-engineerees :
- traktor-nml-utils (wolkenarchitekt) — XSD + fixtures
- rb2tk (MartinBloedorn) — writer Python de reference
- dj-data-converter (digital-dj-tools) — writer Clojure
- polamjag/traktor-nml — fixture NML reelle
"""

from __future__ import annotations

import uuid
from datetime import datetime

from lxml import etree

from traktord.models.track import Collection, CuePoint, Track
from traktord.utils.encoder_delay import get_encoder_delay_ms
from traktord.utils.keys import classical_to_traktor_key
from traktord.utils.track_date import get_release_date
from traktord.utils.paths import file_path_to_traktor_location

# Mapping CuePoint type → NML CUE_V2 TYPE
_CUE_TYPE_TO_NML: dict[str, str] = {
    "cue": "0",
    "fade_in": "1",
    "fade_out": "2",
    "load": "3",
    "grid": "4",
    "loop": "5",
}

# Compensation de l'encoder delay lors de l'ecriture des positions de cue.
# Rekordbox exporte ses positions en audio-seconds (delay deja absorbe).
# Traktor interprete les positions NML depuis le debut du fichier brut sur
# les formats avec padding (MP3 Xing/LAME, M4A iTunSMPB, Opus pre-skip).
# Valeur :
#   +1 → additionne le delay aux positions (cas attendu)
#   -1 → soustrait (a basculer si les cues arrivent en avance apres le fix)
#    0 → desactive la compensation (regression / debug)
#
# A valider empiriquement avec un MP3 concret avant de figer. Cf. HANDOFF.md
# section "Encoder delay compensation".
_ENCODER_DELAY_SIGN: int = 1


def _build_entry(
    track: Track,
    volume_name: str | None = None,
    include_cues: bool = True,
) -> etree._Element:
    """Construire un element <ENTRY> NML depuis un Track.

    Args:
        include_cues: Si False, omet les CUE_V2 (pour Phase 1 import initial
            ou Traktor analyse d'abord avant qu'on merge les cues).

    Structure Traktor :
    <ENTRY MODIFIED_DATE="2019/10/19" MODIFIED_TIME="13047" TITLE="..." ARTIST="...">
      <LOCATION DIR="/:path/:" FILE="file.mp3" VOLUME="osx" VOLUMEID="osx"/>
      <MODIFICATION_INFO AUTHOR_TYPE="user"/>
      <ALBUM TRACK="2" TITLE="Album"/>
      <INFO BITRATE="320000" GENRE="..." FILESIZE="12345" .../>
      <TEMPO BPM="128.000000" BPM_QUALITY="100.000000"/>
      <MUSICAL_KEY VALUE="21"/>
      <CUE_V2 NAME="..." TYPE="0" START="500.0" LEN="0" REPEATS="-1" HOTCUE="0"/>
    </ENTRY>
    """
    now = datetime.now()
    entry = etree.Element("ENTRY")
    entry.set("MODIFIED_DATE", now.strftime("%Y/%m/%d"))
    entry.set("MODIFIED_TIME", str(int(now.timestamp()) % 86400))
    entry.set("TITLE", track.title)
    entry.set("ARTIST", track.artist)

    # LOCATION
    location = file_path_to_traktor_location(track.file_path, volume_name=volume_name)
    loc_elem = etree.SubElement(entry, "LOCATION")
    loc_elem.set("DIR", location["DIR"])
    loc_elem.set("FILE", location["FILE"])
    loc_elem.set("VOLUME", location["VOLUME"])
    loc_elem.set("VOLUMEID", location["VOLUMEID"])

    # MODIFICATION_INFO (obligatoire dans les vrais NML)
    mod_info = etree.SubElement(entry, "MODIFICATION_INFO")
    mod_info.set("AUTHOR_TYPE", "user")

    # ALBUM
    if track.album or track.track_number:
        album_elem = etree.SubElement(entry, "ALBUM")
        if track.album:
            album_elem.set("TITLE", track.album)
        if track.track_number is not None:
            album_elem.set("TRACK", str(track.track_number))

    # INFO
    info_elem = etree.SubElement(entry, "INFO")
    if track.bitrate:
        info_elem.set("BITRATE", str(track.bitrate * 1000))  # NML stocke en bps
    if track.genre:
        info_elem.set("GENRE", track.genre)
    if track.comment:
        info_elem.set("COMMENT", track.comment)
    if track.label:
        info_elem.set("LABEL", track.label)
    # COVERARTID : si disponible (dans track.extra), Traktor l'utilise pour
    # afficher l'artwork dans le browser sans avoir a loader le track
    coverid = track.extra.get("coverartid") if track.extra else None
    if coverid:
        info_elem.set("COVERARTID", coverid)
    if track.remixer:
        info_elem.set("REMIXER", track.remixer)
    if track.mix:
        info_elem.set("MIX", track.mix)
    if track.duration:
        info_elem.set("PLAYTIME", str(int(track.duration)))
        info_elem.set("PLAYTIME_FLOAT", f"{track.duration:.6f}")
    if track.date_added:
        info_elem.set("IMPORT_DATE", track.date_added.replace("-", "/"))
    # RELEASE_DATE : prefere la date precise lue du fichier (TDRL/TDOR ou
    # birthtime), fallback sur l'annee Rekordbox si rien d'exploitable.
    release_date = get_release_date(track.file_path) if track.file_path else None
    if release_date:
        info_elem.set("RELEASE_DATE", release_date)
    elif track.year:
        info_elem.set("RELEASE_DATE", str(track.year))
    if track.file_size:
        # FILESIZE en KB dans le format NML (pas en bytes)
        info_elem.set("FILESIZE", str(track.file_size // 1024))
    if track.play_count:
        info_elem.set("PLAYCOUNT", str(track.play_count))
    if track.last_played:
        info_elem.set("LAST_PLAYED", track.last_played.replace("-", "/"))
    if track.rating is not None:
        info_elem.set("RANKING", str(track.rating * 51))
    info_elem.set("FLAGS", "8")

    # TEMPO
    if track.bpm:
        tempo_elem = etree.SubElement(entry, "TEMPO")
        tempo_elem.set("BPM", f"{track.bpm:.6f}")
        tempo_elem.set("BPM_QUALITY", "100.000000")

    # MUSICAL_KEY
    if track.key:
        key_value = classical_to_traktor_key(track.key)
        if key_value is not None:
            key_elem = etree.SubElement(entry, "MUSICAL_KEY")
            key_elem.set("VALUE", str(key_value))

    # CUE_V2 — d'abord le beatgrid, puis les cues (Phase 2 uniquement)
    if include_cues:
        # Compensation encoder delay : lu une fois par track depuis le fichier
        # audio reel (Xing/LAME, iTunSMPB, pre-skip Opus). Retourne 0.0 pour
        # les formats sans padding (FLAC/WAV/AIFF) ou si la lecture echoue.
        delay_ms = get_encoder_delay_ms(track.file_path) * _ENCODER_DELAY_SIGN

        if track.grid_offset_ms is not None and track.bpm:
            grid_cue = etree.SubElement(entry, "CUE_V2")
            grid_cue.set("NAME", "AutoGrid")
            grid_cue.set("DISPL_ORDER", "0")
            grid_cue.set("TYPE", "4")
            grid_cue.set("START", f"{track.grid_offset_ms + delay_ms:.6f}")
            grid_cue.set("LEN", "0.000000")
            grid_cue.set("REPEATS", "-1")
            grid_cue.set("HOTCUE", "-1")

        for i, cue in enumerate(track.cue_points):
            cue_elem = etree.SubElement(entry, "CUE_V2")
            cue_elem.set("NAME", cue.name or "")
            cue_elem.set("DISPL_ORDER", str(i))
            cue_elem.set("TYPE", _CUE_TYPE_TO_NML.get(cue.type, "0"))
            cue_elem.set("START", f"{cue.position_ms + delay_ms:.6f}")
            cue_elem.set("LEN", f"{cue.length_ms:.6f}")
            cue_elem.set("REPEATS", "-1")
            cue_elem.set("HOTCUE", str(cue.hotcue))

    return entry


def _build_primarykey(track: Track, volume_name: str | None = None) -> str:
    """Construire la PRIMARYKEY Traktor pour une track (VOLUME + DIR + FILE)."""
    loc = file_path_to_traktor_location(track.file_path, volume_name=volume_name)
    return f"{loc['VOLUME']}{loc['DIR']}{loc['FILE']}"


#: Ratio de tracks d'une playlist devant partager le meme genre pour qu'on
#: la considere comme "smart playlist Genre = X".
_SMART_GENRE_RATIO_THRESHOLD = 0.95


def _detect_genre_smart_match(
    playlist_name: str,
    track_paths: list[str],
    path_to_track: dict[str, Track],
) -> str | None:
    """Detecte si une playlist correspond a un filtre genre simple.

    Heuristique : >=95 % des tracks de la playlist ont un genre qui
    contient le nom de la playlist (ou inversement), apres normalisation
    case-insensitive (tirets et slashes -> espaces). Permet de capturer
    les variantes : playlist "Techno" matche "Techno", "Classic Techno",
    "Techno (Peak Time)", etc.

    Returns:
        Le nom de la playlist (a utiliser comme base de query Traktor),
        ou None si la playlist ne match pas la convention.
    """
    if not track_paths:
        return None

    norm_pl = _normalize_genre(playlist_name)
    if not norm_pl:
        return None

    matching = 0
    total = 0
    for p in track_paths:
        track = path_to_track.get(p)
        if not (track and track.genre):
            continue
        total += 1
        norm_g = _normalize_genre(track.genre)
        if norm_pl in norm_g or norm_g in norm_pl:
            matching += 1

    if total == 0:
        return None
    if matching / total < _SMART_GENRE_RATIO_THRESHOLD:
        return None

    return playlist_name


def _normalize_genre(s: str) -> str:
    """Normalise un nom de genre / playlist pour la comparaison."""
    return s.lower().replace("-", " ").replace("/", " ").strip()


def _build_smartlist_query(genre: str) -> str:
    """Construit la query SEARCH_EXPRESSION pour un filtre genre.

    Couvre les variations courantes (avec/sans tiret/espace) en OR.
    Exemple : `Tech-House` → `$GENRE % "Tech-House" | $GENRE % "Tech House"`.
    """
    variants = [genre]
    if "-" in genre:
        variants.append(genre.replace("-", " "))
    elif " " in genre:
        variants.append(genre.replace(" ", "-"))
    seen = set()
    unique = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            unique.append(v)
    return " | ".join(f'$GENRE % "{v}"' for v in unique)


def _build_playlists(
    collection: Collection,
    path_to_track: dict[str, Track],
    volume_name: str | None = None,
    smart_playlists: bool = True,
    smart_detected: list[tuple[str, str]] | None = None,
) -> etree._Element:
    """Construire l'arbre <PLAYLISTS> NML.

    Structure Traktor correcte :
    <PLAYLISTS>
      <NODE TYPE="FOLDER" NAME="$ROOT">
        <SUBNODES COUNT="1">
          <NODE TYPE="FOLDER" NAME="Mon Dossier">
            <SUBNODES COUNT="1">
              <NODE TYPE="PLAYLIST" NAME="Ma Playlist">
                <PLAYLIST ENTRIES="3" TYPE="LIST" UUID="abc123...">
                  <ENTRY><PRIMARYKEY TYPE="TRACK" KEY="..."/></ENTRY>
                </PLAYLIST>
              </NODE>
            </SUBNODES>
          </NODE>
        </SUBNODES>
      </NODE>
    </PLAYLISTS>
    """
    playlists_elem = etree.Element("PLAYLISTS")
    root_node = etree.SubElement(playlists_elem, "NODE")
    root_node.set("TYPE", "FOLDER")
    root_node.set("NAME", "$ROOT")

    # Construire un arbre de dossiers/playlists
    tree: dict[str, dict] = {"": {"_folders": set(), "_playlists": []}}

    for playlist_name, track_paths in collection.playlists.items():
        parts = playlist_name.split("/")
        if len(parts) == 1:
            tree[""]["_playlists"].append((parts[0], track_paths))
        else:
            folder = "/".join(parts[:-1])
            list_name = parts[-1]

            for i in range(1, len(parts)):
                parent_path = "/".join(parts[:i-1]) if i > 1 else ""
                folder_name = parts[i-1]
                current_path = "/".join(parts[:i])

                if parent_path not in tree:
                    tree[parent_path] = {"_folders": set(), "_playlists": []}
                tree[parent_path]["_folders"].add(folder_name)

                if current_path not in tree:
                    tree[current_path] = {"_folders": set(), "_playlists": []}

            tree[folder]["_playlists"].append((list_name, track_paths))

    def _write_node(parent_elem: etree._Element, path: str) -> None:
        """Ecrire recursivement les noeuds de l'arbre."""
        node = tree.get(path, {"_folders": set(), "_playlists": []})
        folders = sorted(node["_folders"])
        playlists = node["_playlists"]

        total = len(folders) + len(playlists)
        subnodes = etree.SubElement(parent_elem, "SUBNODES")
        subnodes.set("COUNT", str(total))

        # Ecrire les sous-dossiers (NODE TYPE="FOLDER")
        for folder_name in folders:
            folder_node = etree.SubElement(subnodes, "NODE")
            folder_node.set("TYPE", "FOLDER")
            folder_node.set("NAME", folder_name)
            child_path = f"{path}/{folder_name}" if path else folder_name
            _write_node(folder_node, child_path)

        # Ecrire les playlists : SMARTLIST si convention "Genre = X" detectee,
        # sinon LIST static avec les tracks listees.
        for list_name, track_paths in playlists:
            playlist_node = etree.SubElement(subnodes, "NODE")
            playlist_node.set("NAME", list_name)

            detected_genre = None
            if smart_playlists:
                detected_genre = _detect_genre_smart_match(
                    list_name, track_paths, path_to_track
                )

            if detected_genre:
                playlist_node.set("TYPE", "SMARTLIST")
                smartlist = etree.SubElement(playlist_node, "SMARTLIST")
                smartlist.set("UUID", uuid.uuid4().hex)
                search = etree.SubElement(smartlist, "SEARCH_EXPRESSION")
                search.set("VERSION", "1")
                search.set("QUERY", _build_smartlist_query(detected_genre))
                if smart_detected is not None:
                    smart_detected.append((list_name, detected_genre))
            else:
                playlist_node.set("TYPE", "PLAYLIST")
                valid_entries = [p for p in track_paths if p in path_to_track]
                playlist_inner = etree.SubElement(playlist_node, "PLAYLIST")
                playlist_inner.set("ENTRIES", str(len(valid_entries)))
                playlist_inner.set("TYPE", "LIST")
                playlist_inner.set("UUID", uuid.uuid4().hex)
                for p in valid_entries:
                    track = path_to_track[p]
                    entry = etree.SubElement(playlist_inner, "ENTRY")
                    pk = etree.SubElement(entry, "PRIMARYKEY")
                    pk.set("TYPE", "TRACK")
                    pk.set("KEY", _build_primarykey(track, volume_name=volume_name))

    _write_node(root_node, "")

    return playlists_elem


class TraktorWriter:
    """Writer pour le format Traktor NML."""

    def write(
        self,
        collection: Collection,
        output_path: str,
        volume_name: str | None = None,
        include_cues: bool = True,
        smart_playlists: bool = True,
        smart_detected: list[tuple[str, str]] | None = None,
    ) -> None:
        """Ecrire une Collection vers un fichier NML Traktor.

        Args:
            include_cues: Si False, omet les CUE_V2 (Phase 1). Traktor fera
                son analyse propre, puis merge-cues ajoutera les cues en Phase 2.
            smart_playlists: Si True, detecte les playlists "Genre = X"
                (>=95 % des tracks meme genre + nom matche) et les ecrit en
                SMARTLIST plutot que LIST.
            smart_detected: Si fourni, sera rempli avec les tuples
                `(playlist_name, genre)` des playlists transformees en
                SMARTLIST. Utile pour rapport.
        """
        root = etree.Element("NML")
        root.set("VERSION", "19")

        # HEAD
        head = etree.SubElement(root, "HEAD")
        head.set("COMPANY", "www.native-instruments.com")
        head.set("PROGRAM", "Traktor")

        # MUSICFOLDERS
        etree.SubElement(root, "MUSICFOLDERS")

        # COLLECTION
        collection_elem = etree.SubElement(root, "COLLECTION")
        collection_elem.set("ENTRIES", str(len(collection.tracks)))

        path_to_track: dict[str, Track] = {}
        for track in collection.tracks:
            entry = _build_entry(track, volume_name=volume_name, include_cues=include_cues)
            collection_elem.append(entry)
            path_to_track[track.file_path] = track

        # SETS (element obligatoire, generalement vide)
        sets_elem = etree.SubElement(root, "SETS")
        sets_elem.set("ENTRIES", "0")

        # PLAYLISTS
        if collection.playlists:
            playlists_elem = _build_playlists(
                collection,
                path_to_track,
                volume_name=volume_name,
                smart_playlists=smart_playlists,
                smart_detected=smart_detected,
            )
            root.append(playlists_elem)

        # Ecrire le fichier
        tree = etree.ElementTree(root)
        tree.write(
            output_path,
            xml_declaration=True,
            encoding="UTF-8",
            pretty_print=True,
        )
