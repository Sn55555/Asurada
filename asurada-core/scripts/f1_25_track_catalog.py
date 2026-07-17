from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrackCatalogEntry:
    leaderboard_slug: str
    track_id: int
    track_name: str
    profile_slug: str
    lap_length_m: float


F1_25_TRACK_CATALOG: tuple[TrackCatalogEntry, ...] = (
    TrackCatalogEntry("australia", 0, "Melbourne", "melbourne", 5278.0),
    TrackCatalogEntry("china", 2, "Shanghai", "shanghai", 5438.675),
    TrackCatalogEntry("bahrain", 3, "Bahrain", "bahrain", 5412.0),
    TrackCatalogEntry("spain", 4, "Catalunya", "catalunya", 4657.0),
    TrackCatalogEntry("monaco", 5, "Monaco", "monaco", 3337.0),
    TrackCatalogEntry("canada", 6, "Montreal", "montreal", 4361.0),
    TrackCatalogEntry("silverstone", 7, "Silverstone", "silverstone", 5891.0),
    TrackCatalogEntry("hungary", 9, "Hungaroring", "hungaroring", 4381.0),
    TrackCatalogEntry("spa", 10, "Spa", "spa", 7004.0),
    TrackCatalogEntry("monza", 11, "Monza", "monza", 5793.0),
    TrackCatalogEntry("singapore", 12, "Singapore", "singapore", 4940.0),
    TrackCatalogEntry("japan", 13, "Suzuka", "suzuka", 5807.0),
    TrackCatalogEntry("abudhabi", 14, "Abu Dhabi", "abu_dhabi", 5281.0),
    TrackCatalogEntry("usa", 15, "Texas", "texas", 5513.0),
    TrackCatalogEntry("brazil", 16, "Brazil", "brazil", 4309.0),
    TrackCatalogEntry("austria", 17, "Austria", "austria", 4323.0),
    TrackCatalogEntry("mexico", 19, "Mexico", "mexico", 4304.0),
    TrackCatalogEntry("azerbaijan", 20, "Baku", "baku", 6003.0),
    TrackCatalogEntry("netherlands", 26, "Zandvoort", "zandvoort", 4259.0),
    TrackCatalogEntry("imola", 27, "Imola", "imola", 4909.0),
    TrackCatalogEntry("saudi_arabia", 29, "Jeddah", "jeddah", 6174.0),
    TrackCatalogEntry("miami", 30, "Miami", "miami", 5412.0),
    TrackCatalogEntry("las_vegas", 31, "Las Vegas", "las_vegas", 6201.0),
    TrackCatalogEntry("qatar", 32, "Losail", "losail", 5419.0),
    TrackCatalogEntry("silverstone_reverse", 39, "Silverstone Reverse", "silverstone_reverse", 5891.0),
    TrackCatalogEntry("austria_reverse", 40, "Austria Reverse", "austria_reverse", 4323.0),
    TrackCatalogEntry("netherlands_reverse", 41, "Zandvoort Reverse", "zandvoort_reverse", 4259.0),
)


TRACK_NAMES_BY_ID = {entry.track_id: entry.track_name for entry in F1_25_TRACK_CATALOG}
CATALOG_BY_PROFILE_SLUG = {entry.profile_slug: entry for entry in F1_25_TRACK_CATALOG}
