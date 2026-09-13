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

            # Route 101 waypoints (dense, matches route-101.gpx path)
            BusStop(
                name="City Center-Railway Station WP1",
                latitude=11.258452,
                longitude=75.780387,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP2",
                latitude=11.258103,
                longitude=75.780374,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP3",
                latitude=11.257755,
                longitude=75.780361,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP4",
                latitude=11.257406,
                longitude=75.780348,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP5",
                latitude=11.257058,
                longitude=75.780335,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP6",
                latitude=11.256710,
                longitude=75.780323,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP7",
                latitude=11.256361,
                longitude=75.780310,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP8",
                latitude=11.256013,
                longitude=75.780297,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP9",
                latitude=11.255665,
                longitude=75.780284,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP10",
                latitude=11.255316,
                longitude=75.780271,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP11",
                latitude=11.254968,
                longitude=75.780258,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP12",
                latitude=11.254619,
                longitude=75.780245,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP13",
                latitude=11.254271,
                longitude=75.780232,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP14",
                latitude=11.253923,
                longitude=75.780219,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP15",
                latitude=11.253574,
                longitude=75.780206,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP16",
                latitude=11.253226,
                longitude=75.780194,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP17",
                latitude=11.252877,
                longitude=75.780181,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP18",
                latitude=11.252529,
                longitude=75.780168,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP19",
                latitude=11.252181,
                longitude=75.780155,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP20",
                latitude=11.251832,
                longitude=75.780142,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP21",
                latitude=11.251484,
                longitude=75.780129,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP22",
                latitude=11.251135,
                longitude=75.780116,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP23",
                latitude=11.250787,
                longitude=75.780103,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP24",
                latitude=11.250439,
                longitude=75.780090,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP25",
                latitude=11.250090,
                longitude=75.780077,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP26",
                latitude=11.249742,
                longitude=75.780065,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP27",
                latitude=11.249394,
                longitude=75.780052,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP28",
                latitude=11.249045,
                longitude=75.780039,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP29",
                latitude=11.248697,
                longitude=75.780026,
                route_id=route_101.id,
            ),
            BusStop(
                name="City Center-Railway Station WP30",
                latitude=11.248348,
                longitude=75.780013,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP1",
                latitude=11.247812,
                longitude=75.779687,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP2",
                latitude=11.247625,
                longitude=75.779375,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP3",
                latitude=11.247438,
                longitude=75.779063,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP4",
                latitude=11.247250,
                longitude=75.778750,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP5",
                latitude=11.247062,
                longitude=75.778437,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP6",
                latitude=11.246875,
                longitude=75.778125,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP7",
                latitude=11.246688,
                longitude=75.777813,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP8",
                latitude=11.246500,
                longitude=75.777500,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP9",
                latitude=11.246312,
                longitude=75.777187,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP10",
                latitude=11.246125,
                longitude=75.776875,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP11",
                latitude=11.245938,
                longitude=75.776563,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP12",
                latitude=11.245750,
                longitude=75.776250,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP13",
                latitude=11.245562,
                longitude=75.775937,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP14",
                latitude=11.245375,
                longitude=75.775625,
                route_id=route_101.id,
            ),
            BusStop(
                name="Railway Station-Market WP15",
                latitude=11.245188,
                longitude=75.775313,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP1",
                latitude=11.245358,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP2",
                latitude=11.245716,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP3",
                latitude=11.246074,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP4",
                latitude=11.246432,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP5",
                latitude=11.246790,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP6",
                latitude=11.247148,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP7",
                latitude=11.247506,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP8",
                latitude=11.247864,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP9",
                latitude=11.248222,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP10",
                latitude=11.248580,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP11",
                latitude=11.248938,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP12",
                latitude=11.249296,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP13",
                latitude=11.249654,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP14",
                latitude=11.250012,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP15",
                latitude=11.250370,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP16",
                latitude=11.250728,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP17",
                latitude=11.251086,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP18",
                latitude=11.251444,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP19",
                latitude=11.251802,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP20",
                latitude=11.252160,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP21",
                latitude=11.252519,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP22",
                latitude=11.252877,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP23",
                latitude=11.253235,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP24",
                latitude=11.253593,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP25",
                latitude=11.253951,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP26",
                latitude=11.254309,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP27",
                latitude=11.254667,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP28",
                latitude=11.255025,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP29",
                latitude=11.255383,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP30",
                latitude=11.255741,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP31",
                latitude=11.256099,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP32",
                latitude=11.256457,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP33",
                latitude=11.256815,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP34",
                latitude=11.257173,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP35",
                latitude=11.257531,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP36",
                latitude=11.257889,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP37",
                latitude=11.258247,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP38",
                latitude=11.258605,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP39",
                latitude=11.258963,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP40",
                latitude=11.259321,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP41",
                latitude=11.259679,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP42",
                latitude=11.260037,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP43",
                latitude=11.260395,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP44",
                latitude=11.260753,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP45",
                latitude=11.261111,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP46",
                latitude=11.261469,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP47",
                latitude=11.261827,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP48",
                latitude=11.262185,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP49",
                latitude=11.262543,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP50",
                latitude=11.262901,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP51",
                latitude=11.263259,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP52",
                latitude=11.263617,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP53",
                latitude=11.263975,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP54",
                latitude=11.264333,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP55",
                latitude=11.264691,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP56",
                latitude=11.265049,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP57",
                latitude=11.265407,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP58",
                latitude=11.265765,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP59",
                latitude=11.266123,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP60",
                latitude=11.266481,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP61",
                latitude=11.266840,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP62",
                latitude=11.267198,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP63",
                latitude=11.267556,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP64",
                latitude=11.267914,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP65",
                latitude=11.268272,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP66",
                latitude=11.268630,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP67",
                latitude=11.268988,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP68",
                latitude=11.269346,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP69",
                latitude=11.269704,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP70",
                latitude=11.270062,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP71",
                latitude=11.270420,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP72",
                latitude=11.270778,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP73",
                latitude=11.271136,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP74",
                latitude=11.271494,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP75",
                latitude=11.271852,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP76",
                latitude=11.272210,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP77",
                latitude=11.272568,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP78",
                latitude=11.272926,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP79",
                latitude=11.273284,
                longitude=75.775000,
                route_id=route_101.id,
            ),
            BusStop(
                name="Market-Medical College WP80",
                latitude=11.273642,
                longitude=75.775000,
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

            # Route 102 waypoints (dense, matches route-102.gpx path)
            BusStop(
                name="Railway Station-Beach Road WP1",
                latitude=11.248346,
                longitude=75.779907,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP2",
                latitude=11.248692,
                longitude=75.779813,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP3",
                latitude=11.249037,
                longitude=75.779720,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP4",
                latitude=11.249383,
                longitude=75.779626,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP5",
                latitude=11.249729,
                longitude=75.779533,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP6",
                latitude=11.250075,
                longitude=75.779439,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP7",
                latitude=11.250421,
                longitude=75.779346,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP8",
                latitude=11.250766,
                longitude=75.779252,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP9",
                latitude=11.251112,
                longitude=75.779159,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP10",
                latitude=11.251458,
                longitude=75.779065,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP11",
                latitude=11.251804,
                longitude=75.778972,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP12",
                latitude=11.252150,
                longitude=75.778879,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP13",
                latitude=11.252495,
                longitude=75.778785,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP14",
                latitude=11.252841,
                longitude=75.778692,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP15",
                latitude=11.253187,
                longitude=75.778598,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP16",
                latitude=11.253533,
                longitude=75.778505,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP17",
                latitude=11.253879,
                longitude=75.778411,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP18",
                latitude=11.254224,
                longitude=75.778318,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP19",
                latitude=11.254570,
                longitude=75.778224,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP20",
                latitude=11.254916,
                longitude=75.778131,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP21",
                latitude=11.255262,
                longitude=75.778037,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP22",
                latitude=11.255607,
                longitude=75.777944,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP23",
                latitude=11.255953,
                longitude=75.777850,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP24",
                latitude=11.256299,
                longitude=75.777757,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP25",
                latitude=11.256645,
                longitude=75.777664,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP26",
                latitude=11.256991,
                longitude=75.777570,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP27",
                latitude=11.257336,
                longitude=75.777477,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP28",
                latitude=11.257682,
                longitude=75.777383,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP29",
                latitude=11.258028,
                longitude=75.777290,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP30",
                latitude=11.258374,
                longitude=75.777196,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP31",
                latitude=11.258720,
                longitude=75.777103,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP32",
                latitude=11.259065,
                longitude=75.777009,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP33",
                latitude=11.259411,
                longitude=75.776916,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP34",
                latitude=11.259757,
                longitude=75.776822,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP35",
                latitude=11.260103,
                longitude=75.776729,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP36",
                latitude=11.260449,
                longitude=75.776636,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP37",
                latitude=11.260794,
                longitude=75.776542,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP38",
                latitude=11.261140,
                longitude=75.776449,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP39",
                latitude=11.261486,
                longitude=75.776355,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP40",
                latitude=11.261832,
                longitude=75.776262,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP41",
                latitude=11.262178,
                longitude=75.776168,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP42",
                latitude=11.262523,
                longitude=75.776075,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP43",
                latitude=11.262869,
                longitude=75.775981,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP44",
                latitude=11.263215,
                longitude=75.775888,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP45",
                latitude=11.263561,
                longitude=75.775794,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP46",
                latitude=11.263907,
                longitude=75.775701,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP47",
                latitude=11.264252,
                longitude=75.775607,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP48",
                latitude=11.264598,
                longitude=75.775514,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP49",
                latitude=11.264944,
                longitude=75.775421,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP50",
                latitude=11.265290,
                longitude=75.775327,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP51",
                latitude=11.265636,
                longitude=75.775234,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP52",
                latitude=11.265981,
                longitude=75.775140,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP53",
                latitude=11.266327,
                longitude=75.775047,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP54",
                latitude=11.266673,
                longitude=75.774953,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP55",
                latitude=11.267019,
                longitude=75.774860,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP56",
                latitude=11.267364,
                longitude=75.774766,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP57",
                latitude=11.267710,
                longitude=75.774673,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP58",
                latitude=11.268056,
                longitude=75.774579,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP59",
                latitude=11.268402,
                longitude=75.774486,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP60",
                latitude=11.268748,
                longitude=75.774393,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP61",
                latitude=11.269093,
                longitude=75.774299,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP62",
                latitude=11.269439,
                longitude=75.774206,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP63",
                latitude=11.269785,
                longitude=75.774112,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP64",
                latitude=11.270131,
                longitude=75.774019,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP65",
                latitude=11.270477,
                longitude=75.773925,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP66",
                latitude=11.270822,
                longitude=75.773832,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP67",
                latitude=11.271168,
                longitude=75.773738,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP68",
                latitude=11.271514,
                longitude=75.773645,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP69",
                latitude=11.271860,
                longitude=75.773551,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP70",
                latitude=11.272206,
                longitude=75.773458,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP71",
                latitude=11.272551,
                longitude=75.773364,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP72",
                latitude=11.272897,
                longitude=75.773271,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP73",
                latitude=11.273243,
                longitude=75.773178,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP74",
                latitude=11.273589,
                longitude=75.773084,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP75",
                latitude=11.273935,
                longitude=75.772991,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP76",
                latitude=11.274280,
                longitude=75.772897,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP77",
                latitude=11.274626,
                longitude=75.772804,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP78",
                latitude=11.274972,
                longitude=75.772710,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP79",
                latitude=11.275318,
                longitude=75.772617,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP80",
                latitude=11.275664,
                longitude=75.772523,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP81",
                latitude=11.276009,
                longitude=75.772430,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP82",
                latitude=11.276355,
                longitude=75.772336,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP83",
                latitude=11.276701,
                longitude=75.772243,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP84",
                latitude=11.277047,
                longitude=75.772150,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP85",
                latitude=11.277393,
                longitude=75.772056,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP86",
                latitude=11.277738,
                longitude=75.771963,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP87",
                latitude=11.278084,
                longitude=75.771869,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP88",
                latitude=11.278430,
                longitude=75.771776,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP89",
                latitude=11.278776,
                longitude=75.771682,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP90",
                latitude=11.279121,
                longitude=75.771589,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP91",
                latitude=11.279467,
                longitude=75.771495,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP92",
                latitude=11.279813,
                longitude=75.771402,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP93",
                latitude=11.280159,
                longitude=75.771308,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP94",
                latitude=11.280505,
                longitude=75.771215,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP95",
                latitude=11.280850,
                longitude=75.771121,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP96",
                latitude=11.281196,
                longitude=75.771028,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP97",
                latitude=11.281542,
                longitude=75.770935,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP98",
                latitude=11.281888,
                longitude=75.770841,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP99",
                latitude=11.282234,
                longitude=75.770748,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP100",
                latitude=11.282579,
                longitude=75.770654,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP101",
                latitude=11.282925,
                longitude=75.770561,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP102",
                latitude=11.283271,
                longitude=75.770467,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP103",
                latitude=11.283617,
                longitude=75.770374,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP104",
                latitude=11.283963,
                longitude=75.770280,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP105",
                latitude=11.284308,
                longitude=75.770187,
                route_id=route_102.id,
            ),
            BusStop(
                name="Railway Station-Beach Road WP106",
                latitude=11.284654,
                longitude=75.770093,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP1",
                latitude=11.285292,
                longitude=75.769792,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP2",
                latitude=11.285583,
                longitude=75.769583,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP3",
                latitude=11.285875,
                longitude=75.769375,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP4",
                latitude=11.286167,
                longitude=75.769167,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP5",
                latitude=11.286458,
                longitude=75.768958,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP6",
                latitude=11.286750,
                longitude=75.768750,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP7",
                latitude=11.287042,
                longitude=75.768542,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP8",
                latitude=11.287333,
                longitude=75.768333,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP9",
                latitude=11.287625,
                longitude=75.768125,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP10",
                latitude=11.287917,
                longitude=75.767917,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP11",
                latitude=11.288208,
                longitude=75.767708,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP12",
                latitude=11.288500,
                longitude=75.767500,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP13",
                latitude=11.288792,
                longitude=75.767292,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP14",
                latitude=11.289083,
                longitude=75.767083,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP15",
                latitude=11.289375,
                longitude=75.766875,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP16",
                latitude=11.289667,
                longitude=75.766667,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP17",
                latitude=11.289958,
                longitude=75.766458,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP18",
                latitude=11.290250,
                longitude=75.766250,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP19",
                latitude=11.290542,
                longitude=75.766042,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP20",
                latitude=11.290833,
                longitude=75.765833,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP21",
                latitude=11.291125,
                longitude=75.765625,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP22",
                latitude=11.291417,
                longitude=75.765417,
                route_id=route_102.id,
            ),
            BusStop(
                name="Beach Road-Beach WP23",
                latitude=11.291708,
                longitude=75.765208,
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

            # Route 103 waypoints (dense, matches route-103.gpx path)
            BusStop(
                name="University-Stadium WP1",
                latitude=11.289714,
                longitude=75.819786,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP2",
                latitude=11.289429,
                longitude=75.819571,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP3",
                latitude=11.289143,
                longitude=75.819357,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP4",
                latitude=11.288857,
                longitude=75.819143,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP5",
                latitude=11.288571,
                longitude=75.818929,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP6",
                latitude=11.288286,
                longitude=75.818714,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP7",
                latitude=11.288000,
                longitude=75.818500,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP8",
                latitude=11.287714,
                longitude=75.818286,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP9",
                latitude=11.287429,
                longitude=75.818071,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP10",
                latitude=11.287143,
                longitude=75.817857,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP11",
                latitude=11.286857,
                longitude=75.817643,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP12",
                latitude=11.286571,
                longitude=75.817429,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP13",
                latitude=11.286286,
                longitude=75.817214,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP14",
                latitude=11.286000,
                longitude=75.817000,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP15",
                latitude=11.285714,
                longitude=75.816786,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP16",
                latitude=11.285429,
                longitude=75.816571,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP17",
                latitude=11.285143,
                longitude=75.816357,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP18",
                latitude=11.284857,
                longitude=75.816143,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP19",
                latitude=11.284571,
                longitude=75.815929,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP20",
                latitude=11.284286,
                longitude=75.815714,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP21",
                latitude=11.284000,
                longitude=75.815500,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP22",
                latitude=11.283714,
                longitude=75.815286,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP23",
                latitude=11.283429,
                longitude=75.815071,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP24",
                latitude=11.283143,
                longitude=75.814857,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP25",
                latitude=11.282857,
                longitude=75.814643,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP26",
                latitude=11.282571,
                longitude=75.814429,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP27",
                latitude=11.282286,
                longitude=75.814214,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP28",
                latitude=11.282000,
                longitude=75.814000,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP29",
                latitude=11.281714,
                longitude=75.813786,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP30",
                latitude=11.281429,
                longitude=75.813571,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP31",
                latitude=11.281143,
                longitude=75.813357,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP32",
                latitude=11.280857,
                longitude=75.813143,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP33",
                latitude=11.280571,
                longitude=75.812929,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP34",
                latitude=11.280286,
                longitude=75.812714,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP35",
                latitude=11.280000,
                longitude=75.812500,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP36",
                latitude=11.279714,
                longitude=75.812286,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP37",
                latitude=11.279429,
                longitude=75.812071,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP38",
                latitude=11.279143,
                longitude=75.811857,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP39",
                latitude=11.278857,
                longitude=75.811643,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP40",
                latitude=11.278571,
                longitude=75.811429,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP41",
                latitude=11.278286,
                longitude=75.811214,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP42",
                latitude=11.278000,
                longitude=75.811000,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP43",
                latitude=11.277714,
                longitude=75.810786,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP44",
                latitude=11.277429,
                longitude=75.810571,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP45",
                latitude=11.277143,
                longitude=75.810357,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP46",
                latitude=11.276857,
                longitude=75.810143,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP47",
                latitude=11.276571,
                longitude=75.809929,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP48",
                latitude=11.276286,
                longitude=75.809714,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP49",
                latitude=11.276000,
                longitude=75.809500,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP50",
                latitude=11.275714,
                longitude=75.809286,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP51",
                latitude=11.275429,
                longitude=75.809071,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP52",
                latitude=11.275143,
                longitude=75.808857,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP53",
                latitude=11.274857,
                longitude=75.808643,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP54",
                latitude=11.274571,
                longitude=75.808429,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP55",
                latitude=11.274286,
                longitude=75.808214,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP56",
                latitude=11.274000,
                longitude=75.808000,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP57",
                latitude=11.273714,
                longitude=75.807786,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP58",
                latitude=11.273429,
                longitude=75.807571,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP59",
                latitude=11.273143,
                longitude=75.807357,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP60",
                latitude=11.272857,
                longitude=75.807143,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP61",
                latitude=11.272571,
                longitude=75.806929,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP62",
                latitude=11.272286,
                longitude=75.806714,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP63",
                latitude=11.272000,
                longitude=75.806500,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP64",
                latitude=11.271714,
                longitude=75.806286,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP65",
                latitude=11.271429,
                longitude=75.806071,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP66",
                latitude=11.271143,
                longitude=75.805857,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP67",
                latitude=11.270857,
                longitude=75.805643,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP68",
                latitude=11.270571,
                longitude=75.805429,
                route_id=route_103.id,
            ),
            BusStop(
                name="University-Stadium WP69",
                latitude=11.270286,
                longitude=75.805214,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP1",
                latitude=11.269849,
                longitude=75.804668,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP2",
                latitude=11.269697,
                longitude=75.804335,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP3",
                latitude=11.269546,
                longitude=75.804003,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP4",
                latitude=11.269395,
                longitude=75.803670,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP5",
                latitude=11.269243,
                longitude=75.803338,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP6",
                latitude=11.269092,
                longitude=75.803005,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP7",
                latitude=11.268941,
                longitude=75.802673,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP8",
                latitude=11.268789,
                longitude=75.802341,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP9",
                latitude=11.268638,
                longitude=75.802008,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP10",
                latitude=11.268486,
                longitude=75.801676,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP11",
                latitude=11.268335,
                longitude=75.801343,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP12",
                latitude=11.268184,
                longitude=75.801011,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP13",
                latitude=11.268032,
                longitude=75.800678,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP14",
                latitude=11.267881,
                longitude=75.800346,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP15",
                latitude=11.267730,
                longitude=75.800014,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP16",
                latitude=11.267578,
                longitude=75.799681,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP17",
                latitude=11.267427,
                longitude=75.799349,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP18",
                latitude=11.267276,
                longitude=75.799016,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP19",
                latitude=11.267124,
                longitude=75.798684,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP20",
                latitude=11.266973,
                longitude=75.798351,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP21",
                latitude=11.266822,
                longitude=75.798019,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP22",
                latitude=11.266670,
                longitude=75.797686,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP23",
                latitude=11.266519,
                longitude=75.797354,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP24",
                latitude=11.266368,
                longitude=75.797022,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP25",
                latitude=11.266216,
                longitude=75.796689,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP26",
                latitude=11.266065,
                longitude=75.796357,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP27",
                latitude=11.265914,
                longitude=75.796024,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP28",
                latitude=11.265762,
                longitude=75.795692,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP29",
                latitude=11.265611,
                longitude=75.795359,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP30",
                latitude=11.265459,
                longitude=75.795027,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP31",
                latitude=11.265308,
                longitude=75.794695,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP32",
                latitude=11.265157,
                longitude=75.794362,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP33",
                latitude=11.265005,
                longitude=75.794030,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP34",
                latitude=11.264854,
                longitude=75.793697,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP35",
                latitude=11.264703,
                longitude=75.793365,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP36",
                latitude=11.264551,
                longitude=75.793032,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP37",
                latitude=11.264400,
                longitude=75.792700,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP38",
                latitude=11.264249,
                longitude=75.792368,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP39",
                latitude=11.264097,
                longitude=75.792035,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP40",
                latitude=11.263946,
                longitude=75.791703,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP41",
                latitude=11.263795,
                longitude=75.791370,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP42",
                latitude=11.263643,
                longitude=75.791038,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP43",
                latitude=11.263492,
                longitude=75.790705,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP44",
                latitude=11.263341,
                longitude=75.790373,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP45",
                latitude=11.263189,
                longitude=75.790041,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP46",
                latitude=11.263038,
                longitude=75.789708,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP47",
                latitude=11.262886,
                longitude=75.789376,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP48",
                latitude=11.262735,
                longitude=75.789043,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP49",
                latitude=11.262584,
                longitude=75.788711,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP50",
                latitude=11.262432,
                longitude=75.788378,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP51",
                latitude=11.262281,
                longitude=75.788046,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP52",
                latitude=11.262130,
                longitude=75.787714,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP53",
                latitude=11.261978,
                longitude=75.787381,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP54",
                latitude=11.261827,
                longitude=75.787049,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP55",
                latitude=11.261676,
                longitude=75.786716,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP56",
                latitude=11.261524,
                longitude=75.786384,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP57",
                latitude=11.261373,
                longitude=75.786051,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP58",
                latitude=11.261222,
                longitude=75.785719,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP59",
                latitude=11.261070,
                longitude=75.785386,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP60",
                latitude=11.260919,
                longitude=75.785054,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP61",
                latitude=11.260768,
                longitude=75.784722,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP62",
                latitude=11.260616,
                longitude=75.784389,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP63",
                latitude=11.260465,
                longitude=75.784057,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP64",
                latitude=11.260314,
                longitude=75.783724,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP65",
                latitude=11.260162,
                longitude=75.783392,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP66",
                latitude=11.260011,
                longitude=75.783059,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP67",
                latitude=11.259859,
                longitude=75.782727,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP68",
                latitude=11.259708,
                longitude=75.782395,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP69",
                latitude=11.259557,
                longitude=75.782062,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP70",
                latitude=11.259405,
                longitude=75.781730,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP71",
                latitude=11.259254,
                longitude=75.781397,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP72",
                latitude=11.259103,
                longitude=75.781065,
                route_id=route_103.id,
            ),
            BusStop(
                name="Stadium-City Center WP73",
                latitude=11.258951,
                longitude=75.780732,
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