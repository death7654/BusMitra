from .database import Base, SessionLocal, engine
from .models import Bus, BusStop, Route


def seed_database():
    """
    Populate the database with fake demo data.
    """

    # Make sure all tables exist
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        # ---------------------------------------------------------
        # Clear existing demo data
        # ---------------------------------------------------------

        db.query(BusStop).delete()
        db.query(Bus).delete()
        db.query(Route).delete()

        db.commit()

        # ---------------------------------------------------------
        # Routes
        # ---------------------------------------------------------

        route_101 = Route(
            route_number="101",
            route_name="City Center - Medical College",
        )

        route_102 = Route(
            route_number="102",
            route_name="Railway Station - Beach",
        )

        route_103 = Route(
            route_number="103",
            route_name="University - City Center",
        )

        db.add_all([
            route_101,
            route_102,
            route_103,
        ])

        db.commit()

        # ---------------------------------------------------------
        # Buses
        # ---------------------------------------------------------

        buses = [
            Bus(
                bus_number="BUS-101-A",
                route_id=route_101.id,
                capacity=50,
            ),
            Bus(
                bus_number="BUS-101-B",
                route_id=route_101.id,
                capacity=45,
            ),
            Bus(
                bus_number="BUS-102-A",
                route_id=route_102.id,
                capacity=50,
            ),
            Bus(
                bus_number="BUS-102-B",
                route_id=route_102.id,
                capacity=40,
            ),
            Bus(
                bus_number="BUS-103-A",
                route_id=route_103.id,
                capacity=45,
            ),
        ]

        db.add_all(buses)
        db.commit()

        # ---------------------------------------------------------
        # Bus stops
        # ---------------------------------------------------------

        bus_stops = [
            # Route 101
            BusStop(
                name="City Center",
                latitude=11.2588,
                longitude=75.7804,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station",
                latitude=11.2480,
                longitude=75.7800,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market",
                latitude=11.2450,
                longitude=75.7750,
                route_id=route_101.id,
            ),
            BusStop(
                name="Medical College",
                latitude=11.2740,
                longitude=75.7750,
                route_id=route_101.id,
            ),

            # Route 102
            BusStop(
                name="Railway Station",
                latitude=11.2480,
                longitude=75.7800,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road",
                latitude=11.2850,
                longitude=75.7700,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach",
                latitude=11.2920,
                longitude=75.7650,
                route_id=route_102.id,
            ),

            # Route 103
            BusStop(
                name="University",
                latitude=11.2900,
                longitude=75.8200,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium",
                latitude=11.2700,
                longitude=75.8050,
                route_id=route_103.id,
            ),
            BusStop(
                name="City Center",
                latitude=11.2588,
                longitude=75.7804,
                route_id=route_103.id,
            ),
        ]

        db.add_all(bus_stops)
        db.commit()

        # ---------------------------------------------------------
        # Display inserted data
        # ---------------------------------------------------------

        print()
        print("=" * 50)
        print("DATABASE SEEDED SUCCESSFULLY")
        print("=" * 50)

        print()
        print("Routes:")

        for route in db.query(Route).all():
            print(
                f"  {route.id}: "
                f"{route.route_number} - "
                f"{route.route_name}"
            )

        print()
        print("Buses:")

        for bus in db.query(Bus).all():
            print(
                f"  {bus.id}: "
                f"{bus.bus_number} | "
                f"Route {bus.route_id} | "
                f"Capacity {bus.capacity}"
            )

        print()
        print("Bus Stops:")

        for stop in db.query(BusStop).all():
            print(
                f"  {stop.id}: "
                f"{stop.name} | "
                f"Route {stop.route_id} | "
                f"({stop.latitude}, {stop.longitude})"
            )

        print()
        print("=" * 50)

    except Exception as error:
        db.rollback()

        print()
        print("ERROR WHILE SEEDING DATABASE")
        print(error)

        raise

    finally:
        db.close()


if __name__ == "__main__":
    seed_database()