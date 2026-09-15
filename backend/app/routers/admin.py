import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus, CheckIn, CrowdReport, Route, UserPing
from ..schemas import (
    BusCreateRequest,
    BusDeleteResponse,
    BusOut,
)
from ..services.crowd_aggregation import get_active_passenger_ids


router = APIRouter(prefix="/api", tags=["Fleet admin"])


# ---------------------------------------------------------
# Admin authentication
# ---------------------------------------------------------

ADMIN_TOKEN_ENV = "BUSMITRA_ADMIN_TOKEN"


def _configured_token() -> str | None:
    token = os.environ.get(ADMIN_TOKEN_ENV, "").strip()
    return token or None


def require_admin_strict(
    x_admin_token: str | None = Header(default=None),
) -> str:
    """
    Gate for destructive operations.

    Deliberately fails closed. If nobody has configured an admin token,
    the endpoint is unusable rather than open - an unset environment
    variable should never be the thing standing between a stranger on
    the LAN and the fleet table.
    """

    expected = _configured_token()

    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Bus deletion is disabled: no admin token is "
                f"configured. Set {ADMIN_TOKEN_ENV} on the server "
                "and restart it."
            ),
        )

    if x_admin_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Admin-Token header.",
            headers={"WWW-Authenticate": "X-Admin-Token"},
        )

    # Constant-time compare so a caller can't narrow the token down
    # one character at a time by measuring how long we take to say no.
    # Compared as bytes: compare_digest rejects str inputs that aren't
    # pure ASCII, and a pasted token with a stray non-ASCII character
    # should be a clean 401 rather than a 500.
    if not secrets.compare_digest(
        x_admin_token.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token.",
        )

    return x_admin_token


def require_admin_soft(
    x_admin_token: str | None = Header(default=None),
) -> bool:
    """
    Gate for additive operations (creating a bus).

    Adding a bus is reversible and harmless enough that we don't want
    it to block a fresh dev checkout, so an unconfigured token means
    "open". Once a token *is* configured it's enforced exactly as
    strictly as on delete - you don't get to skip it by omitting the
    header.

    Returns True when the request was actually authenticated.
    """

    expected = _configured_token()

    if expected is None:
        return False

    if x_admin_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Admin-Token header.",
            headers={"WWW-Authenticate": "X-Admin-Token"},
        )

    if not secrets.compare_digest(
        x_admin_token.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token.",
        )

    return True


# ---------------------------------------------------------
# List buses
# ---------------------------------------------------------

@router.get("/buses", response_model=list[BusOut])
def list_buses(db: Session = Depends(get_db)):
    """
    Every bus in the fleet with its route and current rider count.

    Unlike /api/routes this is a flat fleet view, which is what a
    management screen needs - including buses on routes that have no
    usable stops yet.
    """

    buses = (
        db.query(Bus)
        .join(Route, Bus.route_id == Route.id)
        .order_by(Route.route_number, Bus.bus_number)
        .all()
    )

    return [
        BusOut(
            id=bus.id,
            bus_number=bus.bus_number,
            capacity=bus.capacity,
            route_id=bus.route_id,
            route_number=bus.route.route_number,
            route_name=bus.route.route_name,
            active_passengers=len(
                get_active_passenger_ids(db=db, bus_id=bus.id)
            ),
        )
        for bus in buses
    ]


# ---------------------------------------------------------
# Add a bus
# ---------------------------------------------------------

@router.post(
    "/buses",
    response_model=BusOut,
    status_code=status.HTTP_201_CREATED,
)
def create_bus(
    payload: BusCreateRequest,
    db: Session = Depends(get_db),
    _authenticated: bool = Depends(require_admin_soft),
):
    """
    Add a bus to an existing route.

    The bus number is normalised by the schema before it gets here, so
    the uniqueness check below compares like with like.
    """

    route = (
        db.query(Route)
        .filter(Route.id == payload.route_id)
        .first()
    )

    if route is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Route {payload.route_id} does not exist. "
                "Create the route before adding buses to it."
            ),
        )

    clash = (
        db.query(Bus)
        .filter(Bus.bus_number == payload.bus_number)
        .first()
    )

    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Bus number {payload.bus_number} is already in use "
                f"on route {clash.route.route_number}."
            ),
        )

    bus = Bus(
        bus_number=payload.bus_number,
        route_id=payload.route_id,
        capacity=payload.capacity,
    )

    db.add(bus)
    db.commit()
    db.refresh(bus)

    return BusOut(
        id=bus.id,
        bus_number=bus.bus_number,
        capacity=bus.capacity,
        route_id=bus.route_id,
        route_number=route.route_number,
        route_name=route.route_name,
        active_passengers=0,
    )


# ---------------------------------------------------------
# Delete a bus (strict)
# ---------------------------------------------------------

@router.delete(
    "/buses/{bus_id}",
    response_model=BusDeleteResponse,
)
def delete_bus(
    bus_id: int,
    confirm: str = Query(
        ...,
        description=(
            "The exact bus_number of the bus being deleted. Must match "
            "the stored value or the request is rejected."
        ),
    ),
    force: bool = Query(
        default=False,
        description=(
            "Required when the bus still has pings, check-ins or crowd "
            "reports attached. Those records are deleted with it."
        ),
    ),
    db: Session = Depends(get_db),
    _token: str = Depends(require_admin_strict),
):
    """
    Permanently delete a bus and its history.

    Every guard here exists because deletion is unrecoverable on a
    SQLite file with no backups:

      1. A valid admin token is mandatory, and absent configuration
         disables the endpoint entirely (see require_admin_strict).
      2. `confirm` must match the bus's own number, so a stale bus_id
         from a cached UI can't silently remove a different vehicle.
      3. A bus with riders on board is never deleted, with or without
         force - it's in service and someone is depending on it.
      4. Attached history requires an explicit `force`, so the first
         attempt reports what would be destroyed instead of doing it.
    """

    bus = db.query(Bus).filter(Bus.id == bus_id).first()

    if bus is None:
        raise HTTPException(
            status_code=404,
            detail=f"Bus {bus_id} not found.",
        )

    # -----------------------------------------------------
    # 2. Confirmation must match this exact bus
    # -----------------------------------------------------

    submitted = " ".join(confirm.strip().upper().split())

    # A plain comparison, not compare_digest: the bus number isn't a
    # secret, it's printed on the vehicle. compare_digest would also
    # raise TypeError on a non-ASCII bus_number from an older seed,
    # turning a clear 400 into a 500.
    if submitted != bus.bus_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Confirmation mismatch: bus {bus_id} is "
                f"'{bus.bus_number}', but you sent '{confirm}'. "
                "Nothing was deleted."
            ),
        )

    # -----------------------------------------------------
    # 3. Never delete a bus that currently has riders
    # -----------------------------------------------------

    active_riders = len(
        get_active_passenger_ids(db=db, bus_id=bus.id)
    )

    if active_riders > 0:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                f"{bus.bus_number} has {active_riders} active "
                f"rider{'s' if active_riders != 1 else ''} on board. "
                "Wait until they check out or their tracking goes "
                "quiet, then try again."
            ),
        )

    # -----------------------------------------------------
    # 4. Attached history requires force
    # -----------------------------------------------------

    ping_count = (
        db.query(UserPing).filter(UserPing.bus_id == bus.id).count()
    )
    checkin_count = (
        db.query(CheckIn).filter(CheckIn.bus_id == bus.id).count()
    )
    report_count = (
        db.query(CrowdReport)
        .filter(CrowdReport.bus_id == bus.id)
        .count()
    )

    total = ping_count + checkin_count + report_count

    if total > 0 and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{bus.bus_number} has {total} historical record"
                f"{'s' if total != 1 else ''} attached "
                f"({ping_count} pings, {checkin_count} check-ins, "
                f"{report_count} reports). These are training data for "
                "the prediction model. Re-send with force=true to "
                "delete the bus and all of it."
            ),
        )

    # -----------------------------------------------------
    # Delete
    # -----------------------------------------------------
    #
    # db.delete() walks the cascade="all, delete-orphan" relationships
    # on the Bus model, so the child rows go with it in one
    # transaction - either all of it lands or none of it does.

    bus_number = bus.bus_number

    db.delete(bus)
    db.commit()

    return BusDeleteResponse(
        success=True,
        bus_id=bus_id,
        bus_number=bus_number,
        deleted_pings=ping_count,
        deleted_checkins=checkin_count,
        deleted_reports=report_count,
        message=(
            f"{bus_number} and {total} attached record"
            f"{'s' if total != 1 else ''} were permanently deleted."
        ),
    )