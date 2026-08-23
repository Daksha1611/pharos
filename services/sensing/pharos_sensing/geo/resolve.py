"""Geo-resolution cascade.

Ordered, stopping at the first hit, and always recording which step fired:

  1. Coordinates attached by the channel      point / building / street / ward
  2. Coordinates written into the message     point
  3. Structured address via Nominatim         building        (optional)
  4. Landmark gazetteer match                 street
  5. Sender cell region                       ward
  6. Nothing                                  unknown

The resolution level is never upgraded to make a map look better. A ward-level
demand renders as a hex, an unknown-level demand renders as a list row, and
neither is ever drawn as a pin. That visual honesty is the direct fix for the
documented Kerala 2018 failure where supply drops landed away from the target
house because shared coordinates were not precise enough.

Step 1 reads the channel's own accuracy claim and demotes accordingly - a
dropped pin is metres, a cell-tower fix is kilometres, and calling both
"point" would be the same lie in a different place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pharos_core import GeoResolution, Location, MessageEnvelope

from .gazetteer import Gazetteer

# Accuracy claimed by the channel -> what we are actually entitled to say.
ACCURACY_LADDER = [
    (50.0, GeoResolution.POINT, 0.95),
    (150.0, GeoResolution.BUILDING, 0.86),
    (600.0, GeoResolution.STREET, 0.66),
    (2500.0, GeoResolution.WARD, 0.42),
]
ACCURACY_FLOOR = (GeoResolution.WARD, 0.28)

# Confidence for each non-coordinate step.
GAZETTEER_CONFIDENCE = 0.65
NOMINATIM_CONFIDENCE = 0.80
REGION_CONFIDENCE = 0.35

# Decimal-degree pairs written into the text. Deliberately strict: a bare
# "9.93, 76.26" is a coordinate, but "7, 12" is a headcount and a house number.
_COORD = re.compile(
    r"(?<![\d.])([-+]?\d{1,2}\.\d{3,8})\s*[,;/ ]\s*([-+]?\d{2,3}\.\d{3,8})(?![\d.])"
)

# Anything at or below this level is not safe to treat as a pin, and the
# dedupe gate must widen for it.
COARSE_LEVELS = frozenset({GeoResolution.WARD, GeoResolution.UNKNOWN})


@dataclass
class GeoResolver:
    gazetteer: Gazetteer
    region_centre: tuple[float, float]
    nominatim_url: str | None = None

    def resolve(self, msg: MessageEnvelope) -> Location:
        for step in (
            self._from_attached_geo,
            self._from_text_coordinates,
            self._from_nominatim,
            self._from_gazetteer,
            self._from_sender_region,
        ):
            loc = step(msg)
            if loc is not None:
                return loc
        return self._unknown()

    # -- 1 -----------------------------------------------------------------
    def _from_attached_geo(self, msg) -> Location | None:
        g = msg.attached_geo
        if g is None:
            return None
        acc = g.accuracy_m if g.accuracy_m is not None else 100.0
        level, conf = _ladder(acc)
        return Location(
            lat=g.lat,
            lon=g.lon,
            resolution=level,
            geo_confidence=conf,
            method=f"channel_geo(accuracy={acc:.0f}m)",
        )

    # -- 2 -----------------------------------------------------------------
    def _from_text_coordinates(self, msg) -> Location | None:
        m = _COORD.search(msg.raw_text)
        if not m:
            return None
        lat, lon = float(m.group(1)), float(m.group(2))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return Location(
            lat=lat,
            lon=lon,
            resolution=GeoResolution.POINT,
            geo_confidence=0.92,
            method="coordinates_in_text",
        )

    # -- 3 -----------------------------------------------------------------
    def _from_nominatim(self, msg) -> Location | None:
        """Self-hosted geocoder, when one is configured.

        Off by default. The Kerala OSM import takes tens of minutes and several
        gigabytes, and coordinate extraction plus the gazetteer cover the demo
        without it - so this stays optional rather than becoming a hard
        dependency that can fail on the day.
        """
        if not self.nominatim_url:
            return None
        try:
            import json
            import urllib.parse
            import urllib.request

            q = urllib.parse.quote(msg.text_for_analysis()[:200])
            url = f"{self.nominatim_url.rstrip('/')}/search?q={q}&format=json&limit=1"
            with urllib.request.urlopen(url, timeout=1.5) as fh:
                hits = json.loads(fh.read())
        except Exception:
            # A geocoder that is slow or down must never stall intake.
            return None
        if not hits:
            return None
        return Location(
            lat=float(hits[0]["lat"]),
            lon=float(hits[0]["lon"]),
            resolution=GeoResolution.BUILDING,
            geo_confidence=NOMINATIM_CONFIDENCE,
            method="nominatim",
        )

    # -- 4 -----------------------------------------------------------------
    def _from_gazetteer(self, msg) -> Location | None:
        entry = self.gazetteer.match(msg.text_for_analysis())
        if entry is None:
            return None
        # A landmark tells us the street, not the building. Someone "behind the
        # old mill" is within a couple of hundred metres of it, and claiming
        # more than that is exactly the failure this cascade exists to avoid.
        return Location(
            lat=entry.lat,
            lon=entry.lon,
            resolution=GeoResolution.STREET,
            geo_confidence=GAZETTEER_CONFIDENCE,
            method=f"landmark:{entry.name}",
        )

    # -- 5 -----------------------------------------------------------------
    def _from_sender_region(self, msg) -> Location | None:
        """Cell-tower or channel region, plus an unprefixed place-word.

        "Near the panchayat office" names a dozen places in one district. Paired
        with the region the message came from it is worth a ward and nothing
        finer.
        """
        region = msg.channel_metadata.get("sender_region")
        if region and isinstance(region, dict) and "lat" in region:
            generic = self.gazetteer.mentions_generic_place(msg.text_for_analysis())
            return Location(
                lat=float(region["lat"]),
                lon=float(region["lon"]),
                resolution=GeoResolution.WARD,
                geo_confidence=REGION_CONFIDENCE if generic else REGION_CONFIDENCE * 0.8,
                method=f"sender_region{'+generic_place:' + generic if generic else ''}",
            )
        return None

    # -- 6 -----------------------------------------------------------------
    def _unknown(self) -> Location:
        """Nothing resolved. The demand still exists and still gets a record -
        it renders in a side list, never silently dropped and never on the map
        as though we knew where it was."""
        return Location(
            lat=self.region_centre[0],
            lon=self.region_centre[1],
            resolution=GeoResolution.UNKNOWN,
            geo_confidence=0.0,
            method="unresolved",
        )


def _ladder(accuracy_m: float) -> tuple[GeoResolution, float]:
    """What a claimed accuracy actually entitles us to say.

    A dropped pin is metres and a cell-tower fix is kilometres. Calling both
    "point" would be the same lie in a different place.
    """
    for limit, level, conf in ACCURACY_LADDER:
        if accuracy_m <= limit:
            return level, conf
    return ACCURACY_FLOOR


def is_coarse(loc: Location) -> bool:
    return loc.resolution in COARSE_LEVELS


def consensus(locations: list[Location]) -> Location:
    """Collapse a cluster's member locations into one.

    Take the finest resolution present, and average only the members that
    reached it. Averaging a GPS pin with a ward centroid produces a point that
    is wrong in a way neither input was.
    """
    if not len(locations):
        raise ValueError("no locations to reconcile")

    order = [
        GeoResolution.POINT,
        GeoResolution.BUILDING,
        GeoResolution.STREET,
        GeoResolution.WARD,
        GeoResolution.UNKNOWN,
    ]
    best = min(locations, key=lambda loc: order.index(loc.resolution)).resolution
    same = [loc for loc in locations if loc.resolution == best]

    lat = sum(loc.lat for loc in same) / len(same)
    lon = sum(loc.lon for loc in same) / len(same)

    # Independent reports agreeing at the same resolution is evidence. Cap the
    # bonus so corroboration can sharpen a location but never promote it to a
    # level no single method actually supported.
    base = max(loc.geo_confidence for loc in same)
    corroboration = min(0.12, 0.04 * (len(same) - 1))

    methods = sorted({loc.method.split("(")[0] for loc in same})
    return Location(
        lat=round(lat, 6),
        lon=round(lon, 6),
        resolution=best,
        geo_confidence=round(min(0.97, base + corroboration), 3),
        method=" + ".join(methods[:3]),
    )
