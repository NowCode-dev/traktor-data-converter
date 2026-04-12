"""Parser pour les exports XML Rekordbox (Pioneer DJ)."""

from lxml import etree

from traktord.models.track import Collection, CuePoint, Track
from traktord.utils.paths import rekordbox_uri_to_file_path

# Mapping POSITION_MARK Type → CuePoint type
_RB_CUE_TYPES: dict[int, str] = {
    0: "cue",
    1: "fade_in",
    2: "fade_out",
    3: "load",
    4: "loop",
}


def _parse_track(track_elem: etree._Element) -> Track:
    """Parser un element <TRACK> Rekordbox vers un Track unifie."""
    attr = track_elem.attrib

    # Rating Rekordbox : 0, 51, 102, 153, 204, 255 → 0-5
    rb_rating = int(attr.get("Rating", "0"))
    rating = rb_rating // 51 if rb_rating > 0 else 0

    # Kind → file_type
    kind = attr.get("Kind", "")
    file_type = ""
    if kind:
        # "MP3 File" → "mp3", "WAV File" → "wav"
        file_type = kind.split(" ")[0].lower()

    # Cue points
    cue_points: list[CuePoint] = []
    for pm in track_elem.findall("POSITION_MARK"):
        pm_attr = pm.attrib
        pm_type = int(pm_attr.get("Type", "0"))
        start_sec = float(pm_attr.get("Start", "0"))
        end_sec = float(pm_attr.get("End", "-1"))
        num = int(pm_attr.get("Num", "-1"))

        length_ms = 0.0
        if pm_type == 4 and end_sec > 0:
            length_ms = (end_sec - start_sec) * 1000.0

        cue_points.append(CuePoint(
            name=pm_attr.get("Name", ""),
            type=_RB_CUE_TYPES.get(pm_type, "cue"),
            position_ms=start_sec * 1000.0,
            length_ms=length_ms,
            hotcue=num,
            red=int(pm_attr.get("Red", "0")),
            green=int(pm_attr.get("Green", "0")),
            blue=int(pm_attr.get("Blue", "0")),
        ))

    # Beatgrid : premier element TEMPO
    grid_offset_ms = None
    tempo_elems = track_elem.findall("TEMPO")
    extra: dict = {}
    if tempo_elems:
        first_tempo = tempo_elems[0].attrib
        inizio = float(first_tempo.get("Inizio", "0"))
        grid_offset_ms = inizio * 1000.0
        extra["tempo_metro"] = first_tempo.get("Metro", "4/4")
        extra["tempo_battito"] = int(first_tempo.get("Battito", "1"))
        if len(tempo_elems) > 1:
            extra["multi_tempo"] = True
            extra["tempo_count"] = len(tempo_elems)

    # Chemin fichier
    location = attr.get("Location", "")
    file_path = rekordbox_uri_to_file_path(location) if location else ""

    return Track(
        title=attr.get("Name", ""),
        artist=attr.get("Artist", ""),
        album=attr.get("Album", ""),
        genre=attr.get("Genre", ""),
        comment=attr.get("Comments", ""),
        label=attr.get("Label", ""),
        key=attr.get("Tonality", ""),
        track_number=int(attr["TrackNumber"]) if attr.get("TrackNumber") else None,
        disc_number=int(attr["DiscNumber"]) if attr.get("DiscNumber") else None,
        year=int(attr["Year"]) if attr.get("Year") and attr["Year"] != "0" else None,
        composer=attr.get("Composer", ""),
        grouping=attr.get("Grouping", ""),
        remixer=attr.get("Remixer", ""),
        mix=attr.get("Mix", ""),
        file_path=file_path,
        file_size=int(attr["Size"]) if attr.get("Size") else None,
        file_type=file_type,
        bitrate=int(attr["BitRate"]) if attr.get("BitRate") else None,
        sample_rate=int(float(attr["SampleRate"])) if attr.get("SampleRate") else None,
        duration=float(attr["TotalTime"]) if attr.get("TotalTime") else None,
        bpm=float(attr["AverageBpm"]) if attr.get("AverageBpm") else None,
        rating=rating if rating > 0 else None,
        color=attr.get("Colour"),
        play_count=int(attr.get("PlayCount", "0")),
        last_played=attr.get("LastPlayed", None),
        date_added=attr.get("DateAdded", None),
        cue_points=cue_points,
        grid_offset_ms=grid_offset_ms,
        source_format="rekordbox",
        extra=extra,
    )


def _parse_playlists(
    playlists_elem: etree._Element,
    track_id_to_path: dict[str, str],
) -> dict[str, list[str]]:
    """Parser l'arbre de playlists Rekordbox."""
    result: dict[str, list[str]] = {}

    def _walk(node: etree._Element, prefix: str = "") -> None:
        name = node.attrib.get("Name", "")
        node_type = node.attrib.get("Type", "0")

        if name == "ROOT":
            # Dossier racine, parcourir les enfants
            for child in node:
                if child.tag == "NODE":
                    _walk(child, prefix)
            return

        full_name = f"{prefix}/{name}" if prefix else name

        if node_type == "1":
            # Playlist
            paths: list[str] = []
            for track_ref in node.findall("TRACK"):
                track_key = track_ref.attrib.get("Key", "")
                if track_key in track_id_to_path:
                    paths.append(track_id_to_path[track_key])
            if paths:
                result[full_name] = paths
        elif node_type == "0":
            # Dossier
            for child in node:
                if child.tag == "NODE":
                    _walk(child, full_name)

    for node in playlists_elem:
        if node.tag == "NODE":
            _walk(node)

    return result


class RekordboxParser:
    """Parser pour les exports XML Rekordbox."""

    def parse(self, file_path: str) -> Collection:
        """Lire un fichier XML Rekordbox et retourner une Collection."""
        tree = etree.parse(file_path)
        root = tree.getroot()

        if root.tag != "DJ_PLAYLISTS":
            raise ValueError(f"Format invalide : element racine '{root.tag}', attendu 'DJ_PLAYLISTS'")

        # Parser les tracks
        tracks: list[Track] = []
        track_id_to_path: dict[str, str] = {}

        collection_elem = root.find("COLLECTION")
        if collection_elem is not None:
            for track_elem in collection_elem.findall("TRACK"):
                track = _parse_track(track_elem)
                tracks.append(track)
                track_id = track_elem.attrib.get("TrackID", "")
                if track_id:
                    track_id_to_path[track_id] = track.file_path

        # Parser les playlists
        playlists: dict[str, list[str]] = {}
        playlists_elem = root.find("PLAYLISTS")
        if playlists_elem is not None:
            playlists = _parse_playlists(playlists_elem, track_id_to_path)

        return Collection(
            tracks=tracks,
            playlists=playlists,
            source_format="rekordbox",
            source_file=file_path,
        )
