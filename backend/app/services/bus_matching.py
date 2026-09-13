import math

from sqlalchemy.orm import Session

from ..models import Bus, BusStop


# Maximum distance allowed for automatic matching.
MATCH_RADIUS_METERS = 30.0


def haversine_distance(
    latitude1: float,
    longitude1: float,
    latitude2: float,
    longitude2: float,
) -> float:
    """
    Calculate the distance between two GPS coordinates
    using the Haversine formula.

    Returns:
        Distance in meters.
    """

    earth_radius = 6_371_000  # meters

    lat1 = math.radians(latitude1)
    lat2 = math.radians(latitude2)

    delta_lat = math.radians(latitude2 - latitude1)
    delta_lon = math.radians(longitude2 - longitude1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )

    return earth_radius * c


def find_nearest_bus_stop(
    db: Session,
    latitude: float,
    longitude: float,
):
    """
    Find the nearest bus stop to the supplied GPS location.

    Returns:
        (bus_stop, distance_in_meters)
    """

    bus_stops = db.query(BusStop).all()

    if not bus_stops:
        return None, None

    nearest_stop = None
    nearest_distance = float("inf")

    for stop in bus_stops:
        distance = haversine_distance(
            latitude,
            longitude,
            stop.latitude,
            stop.longitude,
        )

        if distance < nearest_distance:
            nearest_distance = distance
            nearest_stop = stop

    return nearest_stop, nearest_distance


def match_user_to_bus(
    db: Session,
    latitude: float,
    longitude: float,
):
    """
    Attempt to match a GPS location to a bus.

    Demo strategy:
    1. Find the nearest bus stop.
    2. Check whether it is within 30 meters.
    3. Find a bus operating on that stop's route.
    4. Return the first available bus on that route.

    This is a demo approximation because we do not
    have live bus GPS positions yet.
    """

    nearest_stop, distance = find_nearest_bus_stop(
        db,
        latitude,
        longitude,
    )

    if nearest_stop is None:
        return {
            "matched": False,
            "bus": None,
            "stop": None,
            "distance": None,
        }

    if distance > MATCH_RADIUS_METERS:
        return {
            "matched": False,
            "bus": None,
            "stop": nearest_stop,
            "distance": distance,
        }

    bus = (
        db.query(Bus)
        .filter(Bus.route_id == nearest_stop.route_id)
        .order_by(Bus.id)
        .first()
    )

    if bus is None:
        return {
            "matched": False,
            "bus": None,
            "stop": nearest_stop,
            "distance": distance,
        }

    return {
        "matched": True,
        "bus": bus,
        "stop": nearest_stop,
        "distance": distance,
    }