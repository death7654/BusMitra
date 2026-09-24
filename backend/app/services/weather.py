"""
Weather for the service area, and what it means for riders.

Someone deciding whether to wait for a specific bus or just start
walking benefits from knowing it's about to pour, not just from a
temperature number. This calls Open-Meteo (no API key, no signup, free
for non-commercial use) for whichever coordinates the caller supplies,
and turns the numeric weather code it returns into what a rider
actually recognises - "rain", "storm", "clear" - plus a one-line
advisory when conditions are likely to slow buses down or pack them
tighter than usual.

Results are cached in memory for a few minutes. A Predict-page refresh
every fifteen seconds would otherwise mean a fresh outbound call for a
figure that doesn't move inside that window, and a slow or unreachable
weather provider has no business delaying the bus predictions that
don't depend on it.
"""

import time

import httpx

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

CACHE_TTL_SECONDS = 600
REQUEST_TIMEOUT_SECONDS = 6.0

# WMO weather codes (https://open-meteo.com/en/docs), grouped into what
# a rider needs to know rather than kept as raw numbers.
_CODE_GROUPS: list[tuple[set[int], str, str]] = [
    ({0}, "Clear", "clear"),
    ({1, 2, 3}, "Partly cloudy", "clouds"),
    ({45, 48}, "Foggy", "fog"),
    ({51, 53, 55, 56, 57}, "Drizzle", "rain"),
    ({61, 63, 65, 66, 67, 80, 81, 82}, "Rain", "rain"),
    ({71, 73, 75, 77, 85, 86}, "Snow", "snow"),
    ({95, 96, 99}, "Thunderstorm", "storm"),
]

# (latitude, longitude) rounded to 2dp -> (fetched_at, result)
_cache: dict[tuple[float, float], tuple[float, dict]] = {}


def _describe(weather_code: int) -> tuple[str, str]:
    for codes, label, category in _CODE_GROUPS:
        if weather_code in codes:
            return label, category
    return "Unknown", "unknown"


def _advisory(category: str, precipitation_mm: float) -> str | None:
    if category == "storm":
        return "Thunderstorms in the area \u2014 expect delays and slower boarding."
    if category == "snow":
        return "Snow in the area \u2014 expect significant delays."
    if category == "rain" and precipitation_mm >= 2.5:
        return "Heavy rain \u2014 expect slower buses and more riders sheltering aboard."
    if category == "rain":
        return "Light rain \u2014 some delay and extra crowding is likely."
    if category == "fog":
        return "Reduced visibility \u2014 buses may run slower than usual."
    return None


async def get_weather(latitude: float, longitude: float) -> dict:
    """
    Current conditions for one point, cached for CACHE_TTL_SECONDS.

    Raises on a network or upstream failure - the caller turns that
    into an HTTP error rather than serving a silently stale or fake
    forecast.
    """

    key = (round(latitude, 2), round(longitude, 2))
    now = time.monotonic()

    cached = _cache.get(key)
    if cached is not None and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(
            OPEN_METEO_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": (
                    "temperature_2m,precipitation,weather_code,wind_speed_10m"
                ),
                "timezone": "auto",
            },
        )
        response.raise_for_status()
        payload = response.json()

    current = payload.get("current", {})
    weather_code = int(current.get("weather_code", 0) or 0)
    precipitation_mm = float(current.get("precipitation", 0.0) or 0.0)
    condition, category = _describe(weather_code)

    result = {
        "latitude": latitude,
        "longitude": longitude,
        "temperature_c": current.get("temperature_2m"),
        "precipitation_mm": precipitation_mm,
        "wind_speed_kmh": current.get("wind_speed_10m"),
        "condition": condition,
        "condition_category": category,
        "advisory": _advisory(category, precipitation_mm),
        "observed_at": current.get("time"),
    }

    _cache[key] = (now, result)
    return result
