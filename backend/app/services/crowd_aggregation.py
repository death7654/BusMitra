from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Bus, CheckIn, CrowdReport, UserPing
from . import trust as trust_service


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

ACTIVE_WINDOW_MINUTES = 5

# Longest a single ride is allowed to count for. Open check-ins don't
# expire on their own - that's the point of a session - so this is the
# backstop against a forgotten one counting forever.
MAX_RIDE_HOURS = 3

# Manual reports stay relevant for longer than a GPS ping: a rider
# saying "this bus is packed" is still informative several minutes
# later, whereas a position fix isn't. The old 5-minute window meant a
# report effectively vanished before anyone searching could see it,
# which is most of why reports felt like they did nothing.
REPORT_WINDOW_MINUTES = 15

# Each report's influence halves every this many minutes, so a fresh
# report outweighs a stale one instead of both counting equally until
# the older falls off a cliff.
REPORT_HALFLIFE_MINUTES = 5

# Evidence needed before a signal is trusted at full weight. Below
# these, the signal still counts - just proportionally less, which
# stops a single tap from outvoting twenty phones.
FULL_TRUST_REPORTERS = 3
FULL_TRUST_DEVICES = 5

# A device may refresh its own report this often. Anything faster is
# either a double tap or someone trying to stuff the average.
MIN_REPORT_INTERVAL_SECONDS = 60

CROWD_LEVEL_TO_PERCENTAGE = {
    1: 20.0,
    2: 40.0,
    3: 60.0,
    4: 80.0,
    5: 100.0,
}


# ---------------------------------------------------------
# Helper: current active time window
# ---------------------------------------------------------

def get_active_cutoff():
    """
    Return the timestamp representing the beginning
    of the active 5-minute window.
    """

    return datetime.utcnow() - timedelta(
        minutes=ACTIVE_WINDOW_MINUTES
    )


# ---------------------------------------------------------
# Check-in sessions
# ---------------------------------------------------------

def get_open_checkin(
    db: Session,
    user_id: int,
    bus_id: int | None = None,
):
    """
    Return the user's current open check-in (checked_out_at IS NULL),
    optionally restricted to one bus.

    A rider can only physically be on one bus at a time, so callers use
    this both to close an existing session on check-out and to avoid
    opening a duplicate one on check-in.
    """

    query = (
        db.query(CheckIn)
        .filter(
            CheckIn.user_id == user_id,
            CheckIn.checked_out_at.is_(None),
        )
    )

    if bus_id is not None:
        query = query.filter(CheckIn.bus_id == bus_id)

    return query.order_by(CheckIn.timestamp.desc()).first()


def get_recently_checked_out_user_ids(
    db: Session,
    bus_id: int,
):
    """
    Users who explicitly left this bus inside the active window.

    They matter because GPS pings keep arriving for a while after
    someone steps off - they're walking away from a bus that is itself
    still nearby, and bus_matching will happily keep matching them. An
    explicit check-out is a stronger signal than proximity, so it wins
    until the ride is far enough in the past to stop mattering.
    """

    cutoff = get_active_cutoff()

    rows = (
        db.query(CheckIn.user_id)
        .filter(
            CheckIn.bus_id == bus_id,
            CheckIn.checked_out_at.isnot(None),
            CheckIn.checked_out_at >= cutoff,
        )
        .distinct()
        .all()
    )

    checked_out = {row[0] for row in rows}

    if not checked_out:
        return checked_out

    # A rider who checked out and then checked straight back in (wrong
    # button, or re-boarding after a transfer) is on board again.
    reboarded = (
        db.query(CheckIn.user_id)
        .filter(
            CheckIn.bus_id == bus_id,
            CheckIn.user_id.in_(checked_out),
            CheckIn.checked_out_at.is_(None),
        )
        .distinct()
        .all()
    )

    return checked_out - {row[0] for row in reboarded}


# ---------------------------------------------------------
# Active passengers
# ---------------------------------------------------------

def get_active_passenger_ids(
    db: Session,
    bus_id: int,
):
    """
    Find unique users who appear to be active on a bus.

    A user is considered active if they have either:

    1. A recent GPS ping matched to this bus, OR
    2. An open manual check-in for this bus.

    Users who explicitly checked out are removed afterwards, even if
    their GPS still places them next to the bus.

    The same user is counted only once.
    """

    cutoff = get_active_cutoff()

    active_user_ids = set()

    # -----------------------------------------------------
    # Recent GPS users
    # -----------------------------------------------------

    recent_pings = (
        db.query(UserPing.user_id)
        .filter(
            UserPing.bus_id == bus_id,
            UserPing.timestamp >= cutoff,
        )
        .distinct()
        .all()
    )

    for row in recent_pings:
        active_user_ids.add(row[0])

    # -----------------------------------------------------
    # Open check-in users
    # -----------------------------------------------------
    #
    # An open check-in means the rider told us they're on board and
    # never told us otherwise, which stays true through a long ride
    # with no GPS - so this deliberately isn't limited to the 5-minute
    # activity window the way pings are.
    #
    # It *is* limited to MAX_RIDE_HOURS, and that bound lives here
    # rather than only in auto_checkout_stale_sessions: cleanup runs at
    # startup, so on a server that's been up for days a forgotten
    # check-in would otherwise keep inflating this count until the next
    # restart.

    ride_cutoff = datetime.utcnow() - timedelta(hours=MAX_RIDE_HOURS)

    open_checkins = (
        db.query(CheckIn.user_id)
        .filter(
            CheckIn.bus_id == bus_id,
            CheckIn.checked_out_at.is_(None),
            CheckIn.timestamp >= ride_cutoff,
        )
        .distinct()
        .all()
    )

    for row in open_checkins:
        active_user_ids.add(row[0])

    # -----------------------------------------------------
    # Remove riders who have checked out
    # -----------------------------------------------------

    active_user_ids -= get_recently_checked_out_user_ids(
        db=db,
        bus_id=bus_id,
    )

    return active_user_ids


# ---------------------------------------------------------
# Stale session cleanup
# ---------------------------------------------------------

MAX_RIDE_HOURS = 3


def auto_checkout_stale_sessions(db: Session) -> int:
    """
    Close check-ins that were never checked out.

    People close the app mid-ride, phones die, and nobody remembers to
    press Check out at their stop. Without this, one forgotten session
    would inflate a bus's rider count forever, because open check-ins
    deliberately don't expire on their own.

    Returns the number of sessions closed.
    """

    cutoff = datetime.utcnow() - timedelta(hours=MAX_RIDE_HOURS)

    stale = (
        db.query(CheckIn)
        .filter(
            CheckIn.checked_out_at.is_(None),
            CheckIn.timestamp < cutoff,
        )
        .all()
    )

    for checkin in stale:
        # Credit the ride at the cap rather than "now", so a session
        # abandoned days ago doesn't look like a 3-day bus journey.
        checkin.checked_out_at = checkin.timestamp + timedelta(
            hours=MAX_RIDE_HOURS
        )

    if stale:
        db.commit()

    return len(stale)


# ---------------------------------------------------------
# Passenger-based fullness
# ---------------------------------------------------------

def calculate_passenger_fullness(
    active_passenger_count: int,
    capacity: int,
):
    """
    Calculate fullness percentage from active passengers.
    """

    if capacity <= 0:
        return 0.0

    fullness = (
        active_passenger_count / capacity
    ) * 100

    # Prevent values above 100%.
    return min(fullness, 100.0)


# ---------------------------------------------------------
# Manual-report fullness
# ---------------------------------------------------------

def get_report_window_cutoff():
    return datetime.utcnow() - timedelta(minutes=REPORT_WINDOW_MINUTES)


def calculate_manual_fullness(
    db: Session,
    bus_id: int,
):
    """
    Fullness according to the people actually on the bus.

    Three rules, each fixing a way the old flat average could be
    misled:

      * One vote per device. Only each user's most recent report
        counts, so tapping five times carries no more weight than
        tapping once - the row history is kept for model training,
        but it doesn't get to vote five times.
      * Recency decays. A report's weight halves every few minutes,
        so the bus's state now matters more than its state a quarter
        of an hour ago.
      * Reports outlive pings. A 15-minute window means a report is
        still visible to the next person searching for this bus.

    And a fourth, added once there was history to support it:

      * Accuracy counts. Each reporter's weight is multiplied by how
        close their past reports have been to what was subsequently
        measured. A reporter with no track record is unaffected - see
        services/trust.py for why the default is full trust rather
        than none.

    Returns:
        (manual_fullness, reporter_count, total_weight)
    """

    cutoff = get_report_window_cutoff()

    reports = (
        db.query(CrowdReport)
        .filter(
            CrowdReport.bus_id == bus_id,
            CrowdReport.timestamp >= cutoff,
        )
        .order_by(CrowdReport.timestamp.desc())
        .all()
    )

    if not reports:
        return None, 0, 0.0

    # Ordered newest first, so the first sighting of a user is their
    # latest report and everything after it is superseded.
    latest_per_user: dict[int, CrowdReport] = {}

    for report in reports:
        latest_per_user.setdefault(report.user_id, report)

    now = datetime.utcnow()

    # One query for every reporter's standing, rather than one per
    # reporter inside the loop.
    trust_by_user = trust_service.get_trust_map(db, latest_per_user.keys())

    weighted_sum = 0.0
    total_weight = 0.0

    for report in latest_per_user.values():
        percentage = CROWD_LEVEL_TO_PERCENTAGE.get(report.crowd_level)

        if percentage is None:
            continue

        age_minutes = max(
            0.0, (now - report.timestamp).total_seconds() / 60.0
        )
        weight = 0.5 ** (age_minutes / REPORT_HALFLIFE_MINUTES)

        # Recency and accuracy multiply: a fresh report from a
        # consistently-wrong reporter and a stale one from a reliable
        # reporter are both partial evidence, for different reasons.
        weight *= trust_by_user.get(report.user_id, 1.0)

        weighted_sum += percentage * weight
        total_weight += weight

    if total_weight <= 0:
        return None, 0, 0.0

    return (
        round(weighted_sum / total_weight, 2),
        len(latest_per_user),
        round(total_weight, 3),
    )


def get_last_report(db: Session, user_id: int, bus_id: int):
    """This device's most recent report for this bus, if any."""

    return (
        db.query(CrowdReport)
        .filter(
            CrowdReport.user_id == user_id,
            CrowdReport.bus_id == bus_id,
        )
        .order_by(CrowdReport.timestamp.desc())
        .first()
    )


def calculate_trend(db: Session, bus_id: int) -> str:
    """
    Whether the bus is filling up or emptying out.

    Compares distinct devices aboard in the last few minutes against
    the few before that. Direction of travel matters to a rider
    deciding whether to take this bus or wait for the next one.
    """

    now = datetime.utcnow()
    half = timedelta(minutes=ACTIVE_WINDOW_MINUTES)

    def distinct_devices(since, until):
        return (
            db.query(UserPing.user_id)
            .filter(
                UserPing.bus_id == bus_id,
                UserPing.timestamp >= since,
                UserPing.timestamp < until,
            )
            .distinct()
            .count()
        )

    recent = distinct_devices(now - half, now)
    previous = distinct_devices(now - 2 * half, now - half)

    # Below this there aren't enough phones aboard for a change to mean
    # anything - one person boarding would read as a 100% surge.
    if recent < 3 and previous < 3:
        return "unknown"

    if previous == 0:
        return "rising" if recent > 0 else "steady"

    change = (recent - previous) / previous

    if change > 0.25:
        return "rising"
    if change < -0.25:
        return "falling"

    return "steady"


# ---------------------------------------------------------
# Overall crowd aggregation
# ---------------------------------------------------------

def aggregate_bus_crowd(
    db: Session,
    bus_id: int,
):
    """
    Calculate the current crowd/fullness information
    for a bus.
    """

    # -----------------------------------------------------
    # Verify bus
    # -----------------------------------------------------

    bus = (
        db.query(Bus)
        .filter(Bus.id == bus_id)
        .first()
    )

    if bus is None:
        return None

    # -----------------------------------------------------
    # Active passengers
    # -----------------------------------------------------

    active_user_ids = get_active_passenger_ids(
        db=db,
        bus_id=bus_id,
    )

    active_passenger_count = len(active_user_ids)

    # -----------------------------------------------------
    # Passenger fullness
    # -----------------------------------------------------

    passenger_fullness = calculate_passenger_fullness(
        active_passenger_count=active_passenger_count,
        capacity=bus.capacity,
    )

    # -----------------------------------------------------
    # Manual fullness
    # -----------------------------------------------------

    manual_fullness, reporter_count, report_weight = (
        calculate_manual_fullness(
            db=db,
            bus_id=bus_id,
        )
    )

    # -----------------------------------------------------
    # Overall fullness
    # -----------------------------------------------------
    #
    # The old blend averaged the two signals 50/50 whenever any report
    # existed, which let one person's tap cancel out twenty phones -
    # and made the number lurch every time a single report aged out.
    #
    # Each signal is now weighted by how much evidence is behind it:
    #
    #   * Device count is a headcount of app users aboard. It's
    #     reliable in aggregate but systematically undercounts, since
    #     most riders don't have the app - so it needs several devices
    #     before it's worth full weight.
    #   * Reports are direct human judgements of the whole vehicle,
    #     including the people phones can't see. A handful of recent
    #     ones is strong evidence.
    #
    # With plenty of both they contribute equally. With one report and
    # no devices, that report decides - which is the point of asking.

    passenger_weight = min(
        1.0, active_passenger_count / FULL_TRUST_DEVICES
    )
    manual_weight = (
        min(1.0, report_weight / FULL_TRUST_REPORTERS)
        if manual_fullness is not None
        else 0.0
    )

    total_weight = passenger_weight + manual_weight

    if total_weight <= 0:
        overall_fullness = 0.0
        crowd_source = "none"
    else:
        overall_fullness = (
            passenger_fullness * passenger_weight
            + (manual_fullness or 0.0) * manual_weight
        ) / total_weight

        if manual_weight > 0 and passenger_weight > 0:
            crowd_source = "blended"
        elif manual_weight > 0:
            crowd_source = "reports"
        else:
            crowd_source = "devices"

    overall_fullness = round(
        min(100.0, overall_fullness),
        2,
    )

    return {
        "bus_id": bus.id,
        "bus_number": bus.bus_number,
        "capacity": bus.capacity,
        "active_passengers": active_passenger_count,
        "passenger_fullness": round(
            passenger_fullness,
            2,
        ),
        "manual_fullness": manual_fullness,
        "overall_fullness": overall_fullness,
        # Distinct devices that reported, not raw rows - the number a
        # rider cares about is how many people said this, not how many
        # times they tapped.
        "report_count": reporter_count,
        "reporter_count": reporter_count,
        "passenger_weight": round(passenger_weight, 3),
        "report_weight": round(manual_weight, 3),
        "crowd_source": crowd_source,
        "trend": calculate_trend(db=db, bus_id=bus_id),
    }