from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from .database import Base


class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
    route_number = Column(String, nullable=False, unique=True, index=True)
    route_name = Column(String, nullable=False)

    buses = relationship(
        "Bus",
        back_populates="route",
        cascade="all, delete-orphan",
    )

    bus_stops = relationship(
        "BusStop",
        back_populates="route",
        cascade="all, delete-orphan",
    )


class Bus(Base):
    __tablename__ = "buses"

    id = Column(Integer, primary_key=True, index=True)
    bus_number = Column(String, nullable=False, unique=True, index=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    capacity = Column(Integer, nullable=False)

    route = relationship(
        "Route",
        back_populates="buses",
    )

    user_pings = relationship(
        "UserPing",
        back_populates="bus",
        cascade="all, delete-orphan",
    )

    checkins = relationship(
        "CheckIn",
        back_populates="bus",
        cascade="all, delete-orphan",
    )

    crowd_reports = relationship(
        "CrowdReport",
        back_populates="bus",
        cascade="all, delete-orphan",
    )


class BusStop(Base):
    __tablename__ = "bus_stops"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)

    route = relationship(
        "Route",
        back_populates="bus_stops",
    )


class UserPing(Base):
    __tablename__ = "user_pings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)

    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    speed = Column(Float, nullable=False)

    bus_id = Column(Integer, ForeignKey("buses.id"), nullable=True)
    timestamp = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    bus = relationship(
        "Bus",
        back_populates="user_pings",
    )


class CheckIn(Base):
    __tablename__ = "checkins"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    bus_id = Column(Integer, ForeignKey("buses.id"), nullable=False)

    timestamp = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    # NULL while the rider is still considered on board. Set when the
    # rider checks out (or is auto-checked-out), which is what makes a
    # check-in a *session* rather than a single moment in time. The
    # crowd aggregation only counts check-ins whose checked_out_at is
    # still NULL, so leaving a bus drops the count immediately instead
    # of waiting for the 5-minute activity window to lapse.
    checked_out_at = Column(
        DateTime,
        nullable=True,
        index=True,
    )

    bus = relationship(
        "Bus",
        back_populates="checkins",
    )


class CrowdReport(Base):
    __tablename__ = "crowd_reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    bus_id = Column(Integer, ForeignKey("buses.id"), nullable=False)

    crowd_level = Column(Integer, nullable=False)

    # 1 once this report has been compared against a later measurement
    # (or judged unscorable). Stops the trust scorer re-examining the
    # same rows on every pass, which is the difference between a query
    # that stays flat and one that grows with the report table.
    scored = Column(Integer, nullable=False, default=0, index=True)

    timestamp = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    bus = relationship(
        "Bus",
        back_populates="crowd_reports",
    )

class CrowdObservation(Base):
    """
    A snapshot of what the system actually measured on a bus.

    This is the training set the deployment writes for itself. The
    shipped model is trained on synthetic data, which is honest enough
    to demo but cannot know that this particular route fills up at 8:40
    because a school lets out. Every few minutes the sampler records
    what the live signals said, and `ml/train.py` folds those rows in
    the next time it runs.

    Two rules keep this from poisoning itself:

      * Nothing is recorded unless real evidence sits behind it. A bus
        with no app users aboard reads as 0% fullness, and recording
        that would teach the model that every bus is empty.
      * Rows written while the demo simulator is running are tagged
        is_simulated=1 and excluded from training by default. Generated
        numbers are fine to display behind a banner; they are not fine
        to learn from.
    """

    __tablename__ = "crowd_observations"

    id = Column(Integer, primary_key=True, index=True)
    bus_id = Column(Integer, ForeignKey("buses.id"), nullable=False, index=True)

    # Nearest stop on this bus's own route at the moment of the
    # snapshot. NULL when the bus had no usable live position.
    stop_id = Column(Integer, ForeignKey("bus_stops.id"), nullable=True)

    hour_of_day = Column(Integer, nullable=False, index=True)
    day_of_week = Column(Integer, nullable=False, index=True)

    observed_fullness = Column(Float, nullable=False)

    # Total evidence weight behind the figure (0.0-1.0). Carried into
    # training as a sample weight, so a snapshot backed by twenty
    # phones counts for more than one backed by a single report.
    evidence = Column(Float, nullable=False, default=0.0)

    # "devices", "reports" or "blended" - kept for analysis, not used
    # as a model feature.
    crowd_source = Column(String, nullable=False, default="none")

    # 1 while the demo simulator was running. Integer rather than
    # Boolean to match the rest of this schema's SQLite-first style.
    is_simulated = Column(Integer, nullable=False, default=0, index=True)

    timestamp = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    bus = relationship("Bus")

class SegmentTraversal(Base):
    """
    How fast one bus crossed one piece of one route.

    This is the traffic model, learned from the fleet's own movement.
    The ETA used to divide remaining distance by the bus's current
    speed, which assumes the road ahead is like the road underneath -
    false in exactly the situation riders care about, where a bus is
    moving freely now and about to hit the stretch that jams every
    evening.

    Rows are bucketed by hour and weekday/weekend rather than stored as
    a time series, because the question being asked is "how fast is
    this segment, usually, at this time" and that is an average, not a
    history. Keeping the raw rows anyway means the bucketing can be
    changed later without having thrown the evidence away.
    """

    __tablename__ = "segment_traversals"

    id = Column(Integer, primary_key=True, index=True)

    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False, index=True)

    # Index into RouteGeometry.prefix - i.e. which pair of consecutive
    # stops/waypoints this measurement describes.
    segment_index = Column(Integer, nullable=False, index=True)

    hour_of_day = Column(Integer, nullable=False, index=True)

    # "weekday" or "weekend". See services/segments.py for why this
    # isn't day-of-week.
    day_type = Column(String, nullable=False, index=True)

    speed_ms = Column(Float, nullable=False)

    # What the bus's occupancy was at the time, where known. Not used
    # by the current lookup, but recorded so the relationship between
    # load and speed can be examined later rather than assumed.
    occupancy_pct = Column(Float, nullable=True)

    is_simulated = Column(Integer, nullable=False, default=0, index=True)

    timestamp = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    route = relationship("Route")


class ReporterScore(Base):
    """
    A reporter's running accuracy, used to weight their future reports.

    Deliberately one row per user with a running mean rather than a log
    of judgements: the individual errors have no use once folded in,
    and keeping them would be building a per-person behavioural record
    for no operational benefit.
    """

    __tablename__ = "reporter_scores"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, unique=True, index=True)

    scored_reports = Column(Integer, nullable=False, default=0)

    # Mean absolute percentage-point error against later measurements.
    mean_error = Column(Float, nullable=False, default=0.0)

    # Derived from mean_error; stored so aggregation doesn't recompute
    # it per request.
    trust = Column(Float, nullable=False, default=1.0)

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class PredictionLog(Base):
    """
    What we predicted, and what actually happened.

    Nothing in the system previously measured whether its own numbers
    were any good. The confidence labels were derived from how much
    evidence went in, which is a statement about inputs, not about
    accuracy - a figure can be "mostly measured" and still be
    consistently ten points high.

    Each row is written when a prediction is served and completed later
    by the sampler with what was subsequently observed. The gap between
    the two columns is the only honest calibration signal available.
    """

    __tablename__ = "prediction_logs"

    id = Column(Integer, primary_key=True, index=True)

    bus_id = Column(Integer, ForeignKey("buses.id"), nullable=False, index=True)
    stop_id = Column(Integer, ForeignKey("bus_stops.id"), nullable=True)

    hour_of_day = Column(Integer, nullable=False, index=True)
    day_of_week = Column(Integer, nullable=False)

    # The three figures that made up the answer, kept separately so a
    # systematic error can be attributed to the model or to the live
    # blend rather than just observed in the total.
    predicted_fullness = Column(Float, nullable=False)
    live_fullness = Column(Float, nullable=True)
    final_fullness = Column(Float, nullable=False)

    live_weight = Column(Float, nullable=False, default=0.0)
    confidence = Column(String, nullable=False, default="model_only")

    # Filled in later, once a well-evidenced measurement exists.
    actual_fullness = Column(Float, nullable=True, index=True)
    actual_at = Column(DateTime, nullable=True)
    absolute_error = Column(Float, nullable=True)

    is_simulated = Column(Integer, nullable=False, default=0, index=True)

    timestamp = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    bus = relationship("Bus")
