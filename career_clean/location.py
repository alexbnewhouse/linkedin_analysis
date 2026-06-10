"""Deterministic location gazetteer (audit finding 6).

``location`` is 63.8% populated on career_steps with 555K distinct raw strings
and, before this module, zero normalization -- the same place appears as
"New York, NY", "New York, New York, United States" and "Greater New York City
Area". This is the head-coverage pass CAREER_PATHS_PLAN §5b calls for: a
curation-ratchet-style gazetteer (country -> US state -> city/metro) that
resolves the mechanically parseable patterns and leaves the tail honestly
unparsed (the raw string always survives in career_steps).

Output axes per value (see ``parse_location``):

    country   ISO-3166 alpha-2, uppercase ("US", "IN", "GB", ...)
    us_state  USPS code, uppercase ("NY"), only when country is US
    city      lowercase city/metro name ("new york"); metro strings are folded
              onto their anchor city so "Greater Chicago Area" merges with
              "Chicago, Illinois, United States"

Precision-first rules only:
  * 2-letter state codes must be uppercase in the raw string (", NY" yes,
    ", in time" no);
  * bare-city aliases are a small curated list of unambiguous head cities;
  * metro phrases come from a curated head table (the top "Greater X Area" /
    "X Metropolitan Area" strings);
  * anything else -> method 'unparsed', all axes NULL.

Ambiguity policy (documented, US-centric corpus): "Georgia" resolves to the US
state, "New York" (bare) to the state, "Washington" (bare) to the state.
"""

from __future__ import annotations

import re

__all__ = ["parse_location", "canon_location"]

_WS = re.compile(r"\s+")

# ---------------------------------------------------------------- US states
_US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    # federal district + common spellings
    "district of columbia": "DC", "washington d.c.": "DC", "washington dc": "DC",
    "washington, d.c.": "DC", "d.c.": "DC",
    # populous territories that appear in the data
    "puerto rico": "PR", "guam": "GU", "u.s. virgin islands": "VI",
    "american samoa": "AS", "northern mariana islands": "MP",
}
_US_STATE_CODES = set(_US_STATES.values())

# ----------------------------------------------------------------- countries
# Head country gazetteer: name/alias (lowercase) -> ISO-3166 alpha-2. Extend as
# review surfaces misses (curation ratchet); precision-first, so no fuzzy match.
_COUNTRIES = {
    "united states": "US", "united states of america": "US", "usa": "US",
    "u.s.": "US", "u.s.a.": "US", "us": "US", "estados unidos": "US",
    "india": "IN", "united kingdom": "GB", "uk": "GB", "england": "GB",
    "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "canada": "CA", "australia": "AU", "germany": "DE", "deutschland": "DE",
    "france": "FR", "brazil": "BR", "brasil": "BR", "china": "CN",
    "mexico": "MX", "méxico": "MX", "netherlands": "NL",
    "the netherlands": "NL", "spain": "ES", "españa": "ES", "italy": "IT",
    "japan": "JP", "singapore": "SG", "united arab emirates": "AE",
    "uae": "AE", "ireland": "IE", "switzerland": "CH", "sweden": "SE",
    "norway": "NO", "denmark": "DK", "finland": "FI", "belgium": "BE",
    "austria": "AT", "portugal": "PT", "poland": "PL", "greece": "GR",
    "turkey": "TR", "türkiye": "TR", "russia": "RU", "ukraine": "UA",
    "israel": "IL", "saudi arabia": "SA", "qatar": "QA", "kuwait": "KW",
    "egypt": "EG", "south africa": "ZA", "nigeria": "NG", "kenya": "KE",
    "ghana": "GH", "morocco": "MA", "pakistan": "PK", "bangladesh": "BD",
    "sri lanka": "LK", "nepal": "NP", "indonesia": "ID", "malaysia": "MY",
    "thailand": "TH", "vietnam": "VN", "philippines": "PH",
    "south korea": "KR", "korea": "KR", "republic of korea": "KR",
    "taiwan": "TW", "hong kong": "HK", "hong kong sar": "HK",
    "new zealand": "NZ", "argentina": "AR", "chile": "CL", "colombia": "CO",
    "peru": "PE", "venezuela": "VE", "ecuador": "EC", "uruguay": "UY",
    "costa rica": "CR", "panama": "PA", "guatemala": "GT",
    "dominican republic": "DO", "jamaica": "JM",
    "czech republic": "CZ", "czechia": "CZ", "hungary": "HU", "romania": "RO",
    "bulgaria": "BG", "croatia": "HR", "serbia": "RS", "slovakia": "SK",
    "slovenia": "SI", "lithuania": "LT", "latvia": "LV", "estonia": "EE",
    "iceland": "IS", "luxembourg": "LU",
}
# US states shadow same-named countries in this corpus ("Georgia" -> the state).
_COUNTRIES = {k: v for k, v in _COUNTRIES.items() if k not in _US_STATES}

# -------------------------------------------------------------------- metros
# Curated head metro table: phrase (lowercase, after stripping the
# Greater/Area/Metro wrappers) -> (city, USPS state). Sourced from the top
# metro strings in the data; extend via the curation ratchet.
_METROS = {
    "new york city": ("new york", "NY"),
    "new york": ("new york", "NY"),
    "san francisco bay": ("san francisco", "CA"),
    "san francisco": ("san francisco", "CA"),
    "los angeles": ("los angeles", "CA"),
    "chicago": ("chicago", "IL"),
    "washington d.c.": ("washington", "DC"),
    "washington dc": ("washington", "DC"),
    "washington dc-baltimore": ("washington", "DC"),
    "atlanta": ("atlanta", "GA"),
    "boston": ("boston", "MA"),
    "seattle": ("seattle", "WA"),
    "minneapolis-st. paul": ("minneapolis-st. paul", "MN"),
    "minneapolis-saint paul": ("minneapolis-st. paul", "MN"),
    "dallas/fort worth": ("dallas-fort worth", "TX"),
    "dallas-fort worth": ("dallas-fort worth", "TX"),
    "dallas-fort worth metroplex": ("dallas-fort worth", "TX"),
    "houston": ("houston", "TX"),
    "austin": ("austin", "TX"),
    "san antonio": ("san antonio", "TX"),
    "denver": ("denver", "CO"),
    "san diego": ("san diego", "CA"),
    "philadelphia": ("philadelphia", "PA"),
    "phoenix": ("phoenix", "AZ"),
    "miami": ("miami", "FL"),
    "miami-fort lauderdale": ("miami", "FL"),
    "miami/fort lauderdale": ("miami", "FL"),
    "tampa": ("tampa", "FL"),
    "tampa bay": ("tampa", "FL"),
    "tampa/st. petersburg": ("tampa", "FL"),
    "orlando": ("orlando", "FL"),
    "charlotte": ("charlotte", "NC"),
    "raleigh-durham": ("raleigh-durham", "NC"),
    "raleigh-durham-chapel hill": ("raleigh-durham", "NC"),
    "nashville": ("nashville", "TN"),
    "memphis": ("memphis", "TN"),
    "detroit": ("detroit", "MI"),
    "grand rapids": ("grand rapids", "MI"),
    "st. louis": ("st. louis", "MO"),
    "kansas city": ("kansas city", "MO"),
    "indianapolis": ("indianapolis", "IN"),
    "san jose": ("san jose", "CA"),
    "columbus": ("columbus", "OH"),
    "cleveland": ("cleveland", "OH"),
    "cincinnati": ("cincinnati", "OH"),
    "pittsburgh": ("pittsburgh", "PA"),
    "baltimore": ("baltimore", "MD"),
    "portland": ("portland", "OR"),
    "sacramento": ("sacramento", "CA"),
    "salt lake city": ("salt lake city", "UT"),
    "las vegas": ("las vegas", "NV"),
    "milwaukee": ("milwaukee", "WI"),
    "new orleans": ("new orleans", "LA"),
    "oklahoma city": ("oklahoma city", "OK"),
    "omaha": ("omaha", "NE"),
    "louisville": ("louisville", "KY"),
    "richmond": ("richmond", "VA"),
    "jacksonville": ("jacksonville", "FL"),
    "buffalo-niagara falls": ("buffalo", "NY"),
    "hartford": ("hartford", "CT"),
}

# Bare-city aliases: a curated, unambiguous head list for single-segment values.
_CITY_ALIASES = {
    "nyc": ("new york", "NY"),
    "new york city": ("new york", "NY"),
    "chicago": ("chicago", "IL"),
    "los angeles": ("los angeles", "CA"),
    "san francisco": ("san francisco", "CA"),
    "houston": ("houston", "TX"),
    "boston": ("boston", "MA"),
    "seattle": ("seattle", "WA"),
    "atlanta": ("atlanta", "GA"),
    "denver": ("denver", "CO"),
    "dallas": ("dallas", "TX"),
    "austin": ("austin", "TX"),
    "philadelphia": ("philadelphia", "PA"),
    "san diego": ("san diego", "CA"),
    "miami": ("miami", "FL"),
    "minneapolis": ("minneapolis", "MN"),
    "pittsburgh": ("pittsburgh", "PA"),
    "baltimore": ("baltimore", "MD"),
    "san antonio": ("san antonio", "TX"),
    "indianapolis": ("indianapolis", "IN"),
    "milwaukee": ("milwaukee", "WI"),
    "detroit": ("detroit", "MI"),
    "sacramento": ("sacramento", "CA"),
    "new orleans": ("new orleans", "LA"),
    "las vegas": ("las vegas", "NV"),
    "salt lake city": ("salt lake city", "UT"),
    "san jose": ("san jose", "CA"),
}

_REMOTE = {
    "remote", "remote, usa", "remote - usa", "fully remote", "100% remote",
    "virtual", "online", "work from home",
}

# wrappers around a metro phrase, e.g. "Greater Chicago Area",
# "New York City Metropolitan Area", "Washington D.C. Metro Area"
_METRO_WRAP = re.compile(
    r"^(?:greater\s+)?(.+?)(?:\s+(?:metropolitan\s+area|metro\s+area|area|metro|metroplex))?$"
)
# wrappers that may trail a state or country segment ("Texas Metropolitan
# Area", "Canada Area")
_SEG_WRAP = re.compile(r"\s+(?:metropolitan\s+area|metro\s+area|area|metro)$")


def _norm(value: str) -> str:
    return _WS.sub(" ", value.strip())


def _unwrap(segment: str) -> str:
    return _SEG_WRAP.sub("", segment).strip()


def _state_of(segment: str, raw_segment: str) -> str | None:
    """USPS code for a segment, else None. 2-letter codes must be uppercase in
    the raw string (precision guard: 'in time' is not Indiana)."""
    if raw_segment.isupper() and len(raw_segment) == 2:
        return raw_segment if raw_segment in _US_STATE_CODES else None
    return _US_STATES.get(_unwrap(segment))


def _metro_of(segment: str) -> tuple[str, str] | None:
    m = _METRO_WRAP.match(segment)
    if not m:
        return None
    inner = m.group(1).strip().rstrip(",")
    return _METROS.get(inner)


def parse_location(value: str | None) -> tuple[str | None, str | None, str | None, str, float]:
    """Parse one raw location string.

    Returns ``(country, us_state, city, method, confidence)``. Methods:
    city_state_country / city_state / state_country / city_country / metro /
    city_alias / state / country / remote / unparsed / empty.
    """
    if value is None or not value.strip():
        return None, None, None, "empty", 0.0
    raw = _norm(value)
    low = raw.lower()

    if low in _REMOTE:
        return None, None, None, "remote", 1.0

    raw_segs = [s.strip() for s in raw.split(",") if s.strip()]
    segs = [s.lower() for s in raw_segs]

    if len(segs) == 1:
        seg, rseg = segs[0], raw_segs[0]
        if seg in _CITY_ALIASES:  # before metro: bare "Chicago" is the city form
            city, state = _CITY_ALIASES[seg]
            return "US", state, city, "city_alias", 0.9
        metro = _metro_of(seg)  # before state: "Washington D.C. Metro Area"
        if metro:               # carries the city, not just the district
            city, state = metro
            return "US", state, city, "metro", 0.95
        state = _state_of(seg, rseg)
        if state:
            return "US", state, None, "state", 1.0
        if seg in _COUNTRIES:
            return _COUNTRIES[seg], None, None, "country", 1.0
        return None, None, None, "unparsed", 0.0

    # multi-segment: resolve country from the last segment, state from the
    # remaining tail, city from the first segment when distinct.
    country = _COUNTRIES.get(_unwrap(segs[-1]))
    rest_raw = raw_segs[:-1] if country else raw_segs
    rest = segs[:-1] if country else segs

    state = None
    state_idx = None
    for i in range(len(rest) - 1, -1, -1):
        state = _state_of(rest[i], rest_raw[i])
        if state:
            state_idx = i
            break

    if state is not None:
        if country is None:
            country = "US"
        if country != "US":
            # e.g. "Paris, Texas, France" nonsense -- refuse to guess
            return None, None, None, "unparsed", 0.0
        city = rest[0] if state_idx and state_idx > 0 else None
        if city is not None:
            method = "city_state_country" if len(segs) > len(rest) else "city_state"
            return country, state, city, method, 1.0
        method = "state_country" if len(segs) > len(rest) else "state"
        return country, state, None, method, 1.0

    if country is not None:
        # "London, United Kingdom" / "Hyderabad, Telangana, India": first
        # segment is the city; intermediate admin regions are not modeled.
        city = rest[0] if rest else None
        if city is None:
            return country, None, None, "country", 1.0
        return country, None, city, "city_country", 1.0

    # multi-segment, nothing recognized (could be "City, Suburb" etc.)
    return None, None, None, "unparsed", 0.0


def canon_location(values: list[tuple]) -> dict[str, tuple]:
    """Map distinct raw values -> parse_location tuples. ``values`` rows are
    ``(value, freq)`` (freq unused; kept for vocab-shape symmetry)."""
    return {v: parse_location(v) for v, *_ in values}
