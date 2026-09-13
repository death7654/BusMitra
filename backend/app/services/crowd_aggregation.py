from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Bus, CheckIn, CrowdReport, UserPing


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

ACTIVE_WINDOW_MINUTES = 5

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
    2. A recent manual check-in for this bus.

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
    # Recent check-in users
    # -----------------------------------------------------

    recent_checkins = (
        db.query(CheckIn.user_id)
        .filter(
            CheckIn.bus_id == bus_id,
            CheckIn.timestamp >= cutoff,
        )
        .distinct()
        .all()
    )

    for row in recent_checkins:
        active_user_ids.add(row[0])

    return active_user_ids


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

def calculate_manual_fullness(
    db: Session,
    bus_id: int,
):
    """
    Calculate average fullness from recent manual
    crowd reports.

    Returns:
        (manual_fullness, number_of_reports)
    """

    cutoff = get_active_cutoff()

    reports = (
        db.query(CrowdReport.crowd_level)
        .filter(
            CrowdReport.bus_id == bus_id,
            CrowdReport.timestamp >= cutoff,
        )
        .all()
    )

    if not reports:
        return None, 0

    fullness_values = []

    for report in reports:
        crowd_level = report[0]

        percentage = CROWD_LEVEL_TO_PERCENTAGE.get(
            crowd_level
        )

        if percentage is not None:
            fullness_values.append(percentage)

    if not fullness_values:
        return None, 0

    average_fullness = (
        sum(fullness_values)
        / len(fullness_values)
    )

    return round(average_fullness, 2), len(fullness_values)


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

    manual_fullness, report_count = (
        calculate_manual_fullness(
            db=db,
            bus_id=bus_id,
        )
    )

    # -----------------------------------------------------
    # Overall fullness
    # -----------------------------------------------------

    if manual_fullness is not None:
        overall_fullness = (
            passenger_fullness + manual_fullness
        ) / 2
    else:
        overall_fullness = passenger_fullness

    overall_fullness = round(
        overall_fullness,
        2,
    )

    # -----------------------------------------------------
    # Return aggregated information
    # -----------------------------------------------------

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
        "report_count": report_count,
    }