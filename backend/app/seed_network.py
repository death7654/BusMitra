"""
Extra demo network for BusMitra: more routes, return routes and lots of buses.

Everything here hangs off shared, exactly-named stops (City Center, Railway
Station, Market, Beach Road, ...). A rider going between two places that no
single route connects has to change bus at one of those shared stops, which
is what the multi-leg journey planner needs to have something to plan.

Data layout follows the existing seed: each route gets its named stops first,
then dense "A-B WPn" waypoints between each consecutive pair of named stops.

Called from seed.py via add_extra_network(). Nothing in here touches the
hand-written 101/102/103 stops.
"""

from math import asin, cos, radians, sin, sqrt

from .models import Bus, BusStop, Route

# Also create a reverse-direction route for every route (existing + new), so
# journeys work both ways. Reverse routes are numbered original + 10
# (101 -> 111, 104 -> 114, ...). Set to False for one-way routes only.
INCLUDE_RETURN_ROUTES = True

# Roughly one waypoint every this many metres (the GPX-based ones are ~40 m).
WAYPOINT_SPACING_M = 40

# Cycled through so bus sizes vary, deterministically.
CAPACITIES = [50, 45, 40, 55, 60, 35]

# ---------------------------------------------------------------------
# Named stops. The first eight are copied exactly from seed.py so shared
# stops match by name AND coordinates on every route that uses them.
# ---------------------------------------------------------------------
STOPS = {
    # existing
    "City Center":      (11.2588, 75.7804),
    "Railway Station":  (11.2480, 75.7800),
    "Market":           (11.2450, 75.7750),
    "Medical College":  (11.2740, 75.7750),
    "Beach Road":       (11.2850, 75.7700),
    "Beach":            (11.2920, 75.7650),
    "University":       (11.2900, 75.8200),
    "Stadium":          (11.2700, 75.8050),
    # new
    "Central Terminal": (11.2520, 75.7860),
    "Mavoor Road":      (11.2600, 75.7950),
    "Tech Park":        (11.2800, 75.8300),
    "Old Fort":         (11.2680, 75.7700),
    "Lighthouse":       (11.2980, 75.7680),
    "South Bypass":     (11.2350, 75.7900),
    "Airport Road":     (11.2300, 75.8150),
    "Mall Junction":    (11.2650, 75.7850),
    "Temple Gate":      (11.2540, 75.7720),
}

# (route_number, route_name, named stops in order, number of buses)
NEW_ROUTES = [
    ("104", "Central Terminal - Beach",
     ["Central Terminal", "City Center", "Old Fort", "Beach Road", "Beach"], 4),
    ("105", "Airport Road - City Center",
     ["Airport Road", "South Bypass", "Central Terminal", "Mavoor Road", "City Center"], 4),
    ("106", "Tech Park - Medical College",
     ["Tech Park", "University", "Mall Junction", "Medical College"], 3),
    ("107", "Tech Park - Railway Station",
     ["Tech Park", "Stadium", "Mavoor Road", "Central Terminal", "Railway Station"], 4),
    ("108", "Lighthouse - Market",
     ["Lighthouse", "Beach", "Beach Road", "Old Fort", "Temple Gate", "Market"], 4),
    ("109", "Airport Road - Beach",
     ["Airport Road", "South Bypass", "Market", "Railway Station", "Beach Road", "Beach"], 3),
    ("110", "Stadium - Lighthouse",
     ["Stadium", "Mall Junction", "Medical College", "Beach Road", "Lighthouse"], 3),
]

# Named stops of the hand-written routes (from seed.py), used only to build
# their reverse routes and to name extra buses. Their own rows are untouched.
EXISTING_ROUTE_STOPS = {
    "101": ["City Center", "Railway Station", "Market", "Medical College"],
    "102": ["Railway Station", "Beach Road", "Beach"],
    "103": ["University", "Stadium", "City Center"],
}
# Buses seed.py already creates per existing route, and how many more to add.
EXISTING_BUS_COUNT = {"101": 2, "102": 2, "103": 1}
EXTRA_BUSES_ON_EXISTING = {"101": 3, "102": 3, "103": 4}
RETURN_BUSES_ON_EXISTING = 4


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _haversine_m(a, b):
    lat1, lon1, lat2, lon2 = map(radians, (*a, *b))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * asin(sqrt(h))


def _waypoints(route_id, name_a, name_b):
    """Evenly spaced points strictly between two named stops."""
    a, b = STOPS[name_a], STOPS[name_b]
    segments = max(2, round(_haversine_m(a, b) / WAYPOINT_SPACING_M))
    for i in range(1, segments):
        t = i / segments
        yield BusStop(
            name=f"{name_a}-{name_b} WP{i}",
            latitude=round(a[0] + (b[0] - a[0]) * t, 6),
            longitude=round(a[1] + (b[1] - a[1]) * t, 6),
            route_id=route_id,
        )


def _route_stops(route_id, names):
    """Named stops first, then waypoints between each consecutive pair."""
    stops = [
        BusStop(name=n, latitude=STOPS[n][0], longitude=STOPS[n][1], route_id=route_id)
        for n in names
    ]
    for a, b in zip(names, names[1:]):
        stops.extend(_waypoints(route_id, a, b))
    return stops


def _buses(route, count, start=0):
    for i in range(start, start + count):
        yield Bus(
            bus_number=f"BUS-{route.route_number}-{chr(ord('A') + i)}",
            route_id=route.id,
            capacity=CAPACITIES[(int(route.route_number) + i) % len(CAPACITIES)],
        )


def _reverse_name(name):
    return " - ".join(reversed(name.split(" - ")))


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------
def add_extra_network(db, existing_routes):
    """
    Add the extra routes and every new bus, and return the new BusStop rows
    (not yet added to the session) for the caller to add with its own.

    existing_routes: {"101": route_101, "102": route_102, "103": route_103},
    Route rows that have already been committed.
    """
    # (route_number, route_name, stop names, bus count) for each NEW Route row
    specs = [(n, name, list(stops), buses) for n, name, stops, buses in NEW_ROUTES]

    if INCLUDE_RETURN_ROUTES:
        for number, stops in EXISTING_ROUTE_STOPS.items():
            specs.append((
                str(int(number) + 10),
                _reverse_name(existing_routes[number].route_name),
                stops[::-1],
                RETURN_BUSES_ON_EXISTING,
            ))
        for number, name, stops, buses in NEW_ROUTES:
            specs.append((str(int(number) + 10), _reverse_name(name), stops[::-1], buses))

    new_routes = [Route(route_number=n, route_name=name) for n, name, _, _ in specs]
    db.add_all(new_routes)
    db.commit()  # assigns ids

    buses = []
    for number, extra in EXTRA_BUSES_ON_EXISTING.items():
        buses.extend(_buses(existing_routes[number], extra, start=EXISTING_BUS_COUNT[number]))
    for route, (_, _, _, count) in zip(new_routes, specs):
        buses.extend(_buses(route, count))
    db.add_all(buses)
    db.commit()

    stops = []
    for route, (_, _, names, _) in zip(new_routes, specs):
        stops.extend(_route_stops(route.id, names))
    return stops