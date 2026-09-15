"""
Journey planning across routes, including transfers.

Until now the app could only answer "which bus goes from A to B
directly". That is a real limitation rather than a cosmetic one: on any
network with more than a couple of routes, most pairs of stops have no
direct service, and the honest answer "no direct bus was found" is
useless to someone who can plainly see that two buses would do it.

The search here is deliberately small. Bus networks at the scale this
app targets have tens of routes, not thousands, and the useful answers
are one or two legs - nobody voluntarily makes three transfers. So this
is a breadth-first search over routes bounded at MAX_LEGS, not a
general shortest-path algorithm, and it runs entirely on data already
loaded for the Predict page.

Stops are matched by *name*, because each route carries its own
bus_stops rows: "Central Market" on route 101 and "Central Market" on
route 205 are two database rows describing one physical place. Matching
on name is what makes a transfer expressible at all. Where a network
has genuinely distinct stops that share a name, this would need a
station identifier - the join is isolated in _interchange_names() so
that change touches one function.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import Bus, BusStop, Route


# Nobody wants a three-bus journey across a small network, and allowing
# one mostly produces absurd routings that happen to be technically
# valid.
MAX_LEGS = 2

# Charged per transfer when ranking. It stands for walking between
# stands, waiting for the connection, and the risk of missing it - a
# two-leg journey has to be meaningfully better than a direct one
# before it's worth recommending.
TRANSFER_PENALTY_SECONDS = 420


@dataclass
class Leg:
    route_id: int
    route_number: str
    route_name: str
    board_stop_id: int
    board_stop_name: str
    alight_stop_id: int
    alight_stop_name: str
    stops_count: int
    bus_ids: list[int] = field(default_factory=list)


@dataclass
class Journey:
    legs: list[Leg]

    @property
    def transfers(self) -> int:
        return max(0, len(self.legs) - 1)

    @property
    def total_stops(self) -> int:
        return sum(leg.stops_count for leg in self.legs)


# ---------------------------------------------------------
# Network model
# ---------------------------------------------------------

class Network:
    """
    The route network, shaped for search rather than for display.

    Built once per request from three queries. At this scale that is
    cheaper than maintaining a cache that could go stale when a bus or
    route is added.
    """

    def __init__(self, db: Session):
        self.routes = {r.id: r for r in db.query(Route).all()}

        self.stops_by_route: dict[int, list[BusStop]] = {}

        for stop in db.query(BusStop).order_by(BusStop.route_id, BusStop.id).all():
            self.stops_by_route.setdefault(stop.route_id, []).append(stop)

        self.buses_by_route: dict[int, list[Bus]] = {}

        for bus in db.query(Bus).order_by(Bus.id).all():
            self.buses_by_route.setdefault(bus.route_id, []).append(bus)

        # name -> [(route_id, stop)] for every place a route touches.
        self.routes_by_stop_name: dict[str, list[tuple[int, BusStop]]] = {}

        for route_id, stops in self.stops_by_route.items():
            for stop in stops:
                if _is_waypoint(stop):
                    continue

                self.routes_by_stop_name.setdefault(stop.name, []).append(
                    (route_id, stop)
                )

    def index_of(self, route_id: int, stop_name: str) -> int:
        """Position of a named stop in a route's ordered stop list."""

        for i, stop in enumerate(self.stops_by_route.get(route_id, [])):
            if stop.name == stop_name and not _is_waypoint(stop):
                return i

        return -1

    def named_stops(self, route_id: int) -> list[BusStop]:
        return [
            s for s in self.stops_by_route.get(route_id, [])
            if not _is_waypoint(s)
        ]


def _is_waypoint(stop: BusStop) -> bool:
    """
    Waypoints describe road geometry so the ETA can measure progress.
    Nobody boards at one, so they must never appear as a transfer point
    or as a journey endpoint.
    """

    return " WP" in stop.name


# ---------------------------------------------------------
# Search
# ---------------------------------------------------------

def _build_leg(network: Network, route_id: int, from_name: str, to_name: str) -> Leg | None:
    """
    One ride on one route, if the route serves both stops in order.

    Direction matters: a route that visits B before A cannot take you
    from A to B, however close together they are.
    """

    stops = network.stops_by_route.get(route_id, [])

    idx_from = _index_in(stops, from_name)
    idx_to = _index_in(stops, to_name)

    if idx_from == -1 or idx_to == -1 or idx_from >= idx_to:
        return None

    route = network.routes.get(route_id)

    if route is None:
        return None

    between = [
        s for s in stops[idx_from:idx_to + 1] if not _is_waypoint(s)
    ]

    return Leg(
        route_id=route_id,
        route_number=route.route_number,
        route_name=route.route_name,
        board_stop_id=stops[idx_from].id,
        board_stop_name=stops[idx_from].name,
        alight_stop_id=stops[idx_to].id,
        alight_stop_name=stops[idx_to].name,
        stops_count=max(0, len(between) - 1),
        bus_ids=[b.id for b in network.buses_by_route.get(route_id, [])],
    )


def _index_in(stops: list[BusStop], name: str) -> int:
    for i, stop in enumerate(stops):
        if stop.name == name and not _is_waypoint(stop):
            return i

    return -1


def plan(db: Session, from_name: str, to_name: str) -> list[Journey]:
    """
    Every reasonable way to get from one named stop to another.

    Direct journeys first, then one-transfer options. Results are
    de-duplicated by the sequence of routes used, so two buses on the
    same route don't produce two identical itineraries - the bus
    choice is a separate decision the Predict page already handles
    well, and folding it in here would multiply the list by fleet size
    for no extra information.
    """

    if from_name == to_name:
        return []

    network = Network(db)

    journeys: list[Journey] = []
    seen: set[tuple] = set()

    # -----------------------------------------------------
    # Direct
    # -----------------------------------------------------

    for route_id in network.routes:
        leg = _build_leg(network, route_id, from_name, to_name)

        if leg is not None:
            key = (route_id,)

            if key not in seen:
                seen.add(key)
                journeys.append(Journey(legs=[leg]))

    # -----------------------------------------------------
    # One transfer
    # -----------------------------------------------------
    #
    # For each route serving the origin, find every place it meets a
    # route serving the destination. The interchange has to come after
    # boarding on the first route and before alighting on the second,
    # which _build_leg enforces on both halves.

    if MAX_LEGS >= 2:
        origin_routes = [
            route_id for route_id, _ in network.routes_by_stop_name.get(from_name, [])
        ]
        destination_routes = [
            route_id for route_id, _ in network.routes_by_stop_name.get(to_name, [])
        ]

        for first in origin_routes:
            for second in destination_routes:
                if first == second:
                    continue  # already covered as a direct journey

                for interchange in _interchange_names(network, first, second):
                    if interchange in (from_name, to_name):
                        continue

                    leg_one = _build_leg(network, first, from_name, interchange)

                    if leg_one is None:
                        continue

                    leg_two = _build_leg(network, second, interchange, to_name)

                    if leg_two is None:
                        continue

                    key = (first, second, interchange)

                    if key in seen:
                        continue

                    seen.add(key)
                    journeys.append(Journey(legs=[leg_one, leg_two]))

    # Fewest transfers first, then fewest stops. Without live ETAs this
    # is the best ordering available; the router re-ranks by real
    # arrival times once it has them.
    journeys.sort(key=lambda j: (j.transfers, j.total_stops))

    return journeys


def _interchange_names(network: Network, route_a: int, route_b: int) -> list[str]:
    """
    Stop names served by both routes.

    This is the one place the "same name means same place" assumption
    lives. A network with duplicate stop names across neighbourhoods
    would replace this with a station-id join and nothing else in the
    module would need to change.
    """

    names_b = {s.name for s in network.named_stops(route_b)}

    return [s.name for s in network.named_stops(route_a) if s.name in names_b]