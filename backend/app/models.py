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