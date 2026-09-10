"""Deterministic, database-only capture fixtures.

This module deliberately has no application or Flask imports.  The caller is
responsible for configuring ``models.db`` (normally against disposable SQLite)
before importing it.
"""
from datetime import date, datetime, timedelta

from models import (
    Activity,
    ActivityType,
    Friend,
    GuestStatus,
    ParticipantRole,
    Resort,
    SkiTrip,
    SkiTripPlanningPost,
    SkiTripParticipant,
    User,
    UserAvailability,
    db,
)

FROZEN_TODAY = date(2027, 1, 15)
PERSONAS = ("EMPTY", "LIGHT", "TYPICAL", "HEAVY", "EXTREME", "EDGE")


def _specs():
    return {
        "EMPTY": ("empty", "Empty", "Capture", "Social", None),
        "LIGHT": ("light", "Light", "Capture", "Epic", "Beginner"),
        "TYPICAL": ("typical", "Typical", "Capture", "Ikon", "Intermediate"),
        "HEAVY": ("heavy", "Heavy", "Capture", "Epic", "Advanced"),
        "EXTREME": ("extreme", "Extreme", "Capture", "Ikon", "Expert"),
        "EDGE": ("edge", "Edge", "Capture", "Indy", "Intermediate"),
    }


def _user(label, first, last, pass_type, skill):
    social = label == "empty"
    return User(
        email=f"capture-{label}@fixture.invalid",
        first_name=first,
        last_name=last,
        rider_types=["Social"] if social else ["Skier"],
        pass_type=pass_type,
        skill_level=skill,
        lifecycle_stage="active" if not social else "new",
        is_seeded=True,
        is_verified=True,
        home_state="CO",
        terrain_preferences=[] if social else ["All-Mountain"],
        buddy_passes={"epic": pass_type == "Epic", "ikon": pass_type == "Ikon"},
        created_at=datetime(2026, 1, 15),
        first_planning_timestamp=None if social else datetime(2026, 2, 1),
    )


def _resorts():
    names = (
        ("Aspen", "capture-aspen", "Epic"),
        ("Vail", "capture-vail", "Epic"),
        ("Mammoth", "capture-mammoth", "Ikon"),
        ("Big Sky", "capture-big-sky", "Ikon"),
        ("Indy Basin", "capture-indy-basin", "Indy"),
        ("Alta", "capture-alta", "Ikon"),
        ("Park City", "capture-park-city", "Ikon"),
        ("Whistler", "capture-whistler", "Epic"),
        ("Stowe", "capture-stowe", "Epic"),
        ("Copper", "capture-copper", "Ikon"),
        ("Telluride", "capture-telluride", "Epic"),
        ("Jackson Hole", "capture-jackson-hole", "Ikon"),
        ("Snowbird", "capture-snowbird", "Ikon"),
        ("Keystone", "capture-keystone", "Epic"),
        ("Steamboat", "capture-steamboat", "Ikon"),
    )
    result = {}
    for name, slug, brand in names:
        r = Resort(
            name=name, slug=slug, state="CO", state_code="CO",
            country="US", country_code="US", country_name="United States",
            is_active=True, is_region=False, brand=brand,
            pass_brands=brand, pass_brands_json=[brand],
        )
        db.session.add(r)
        result[slug.removeprefix("capture-")] = r
    return result


def _trip(owner, resort, start, end, status="planning", public=True, **extra):
    t = SkiTrip(
        user_id=owner.id, created_by_user_id=owner.id, resort_id=resort.id,
        mountain=resort.name, start_date=start, end_date=end,
        trip_status=status, lifecycle_state=extra.pop("lifecycle_state", "active"),
        is_public=public, pass_type=extra.pop("pass_type", "No Pass"),
        is_group_trip=extra.pop("is_group_trip", False),
        **extra,
    )
    db.session.add(t)
    db.session.flush()
    db.session.add(SkiTripParticipant(
        trip_id=t.id, user_id=owner.id, status=GuestStatus.GOING,
        role=ParticipantRole.OWNER,
    ))
    return t


def _participant(trip, user, status):
    db.session.add(SkiTripParticipant(
        trip_id=trip.id, user_id=user.id, status=status,
        role=ParticipantRole.GUEST,
    ))


def seed_all(database=None):
    """Populate all six personas and return the stable logical registry."""
    global db
    database = database or db
    # Keep construction usable with a caller passing an equivalent extension.
    if database is not db:
        db = database
    registry = {"frozen_today": FROZEN_TODAY, "personas": {}, "resorts": {},
                "routes": {}}
    resorts = _resorts()
    registry["resorts"] = {k: r for k, r in resorts.items()}
    users = {}
    for label, (key, first, last, pass_type, skill) in _specs().items():
        u = _user(key, first, last, pass_type, skill)
        db.session.add(u)
        users[label] = u
    db.session.flush()
    for label, u in users.items():
        registry["personas"][label] = {"user": u, "logical_id": f"persona:{label.lower()}"}

    # Small personas are intentionally useful capture accounts, not empty
    # shells.  Their collections and trip counts stay independent of HEAVY.
    persona_shapes = {"LIGHT": (1, 2), "TYPICAL": (3, 4),
                      "EXTREME": (6, 8), "EDGE": (2, 1)}
    resort_values = list(resorts.values())
    for label, (trip_count, wishlist_count) in persona_shapes.items():
        u = users[label]
        u.visited_resort_ids = [r.id for r in resort_values[:trip_count]]
        u.wish_list_resorts = [r.id for r in resort_values[-wishlist_count:]]
        persona_trips = []
        for number in range(trip_count):
            start = FROZEN_TODAY + timedelta(days=number * 21 + 2)
            persona_trips.append(_trip(
                u, resort_values[(number + 2) % len(resort_values)], start,
                start + timedelta(days=2), "planning" if number % 2 else "going",
                public=(number % 2 == 0), pass_type=u.pass_type,
            ))
        registry["personas"][label]["trips"] = persona_trips
    heavy = users["HEAVY"]
    friends = []
    friend_logical_ids = {}
    clusters = (
        ("HF01", "Aspen Core", "Epic"),
        ("HF06", "Vail Weekend", "Epic"),
        ("HF11", "Mammoth Dates", "Ikon"),
        ("HF16", "Big Sky Collective", "Ikon"),
        ("HF21", "Indy Mix", "Indy"),
        ("HF24", "Social-only", "None"),
    )
    n = 0
    for prefix, cluster, pass_type in clusters:
        count = 5 if prefix != "HF21" else 3
        if prefix == "HF24":
            count = 2
        for i in range(count):
            n += 1
            social = prefix == "HF24"
            u = _user(f"hf{n:02d}", f"Friend{n:02d}", cluster.replace(" ", ""), pass_type,
                      None if social else "Intermediate")
            if social:
                u.rider_types = ["Social"]
                u.lifecycle_stage = "new"
            db.session.add(u)
            db.session.flush()
            friends.append(u)
            db.session.add(Friend(user_id=heavy.id, friend_id=u.id, is_seeded=True))
            db.session.add(Friend(user_id=u.id, friend_id=heavy.id, is_seeded=True))
            friend_logical_ids[u.id] = {
                "logical_id": f"HF{n:02d}",
                "cluster": cluster,
            }
    registry["personas"]["HEAVY"]["friends"] = friends
    registry["personas"]["HEAVY"]["friend_ids"] = friend_logical_ids
    friends[0].visited_resort_ids = [resorts["aspen"].id, resorts["vail"].id,
                                     resorts["mammoth"].id]
    friends[0].wish_list_resorts = [resorts["big-sky"].id, resorts["alta"].id]

    # The 15 trips intentionally cover every capture-state axis.
    dates = [
        (-30, -27, "going", True, "completed"),
        (-20, -18, "going", False, "cancelled"),
        (-10, -8, "planning", True, "active"),
        (-3, 0, "going", True, "active"),
        (0, 3, "planning", False, "active"),
        (5, 6, "going", True, "active"),
        (10, 14, "planning", True, "active"),
        (20, 24, "going", False, "active"),
        (30, 31, "planning", True, "active"),
        (40, 45, "going", True, "active"),
        (55, 60, "planning", False, "active"),
        (70, 75, "going", True, "active"),
        (90, 96, "planning", True, "active"),
        (120, 121, "going", False, "active"),
        (150, 155, "planning", True, "active"),
    ]
    trips = []
    for i, (start, end, status, public, lifecycle) in enumerate(dates, 1):
        stay = i in (4, 8, 12)
        owner = heavy if i <= 5 else friends[(i - 6) % len(friends)]
        t = _trip(
            owner, list(resorts.values())[i % len(resorts)],
            FROZEN_TODAY + timedelta(days=start),
            FROZEN_TODAY + timedelta(days=end), status, public,
            lifecycle_state=lifecycle, pass_type=("Epic" if i % 2 else "Ikon"),
            stay_name=f"HT{i:02d} Lodge" if stay else None,
            stay_description="Shared stay" if stay else None,
            is_group_trip=(i in (4, 8, 12)),
            notes="Friends Trips" if i in (4, 8, 12) else ("Planning" if status == "planning" else None),
        )
        trips.append(t)
        viewer_status = (
            GuestStatus.PENDING if i in (3, 9, 15)
            else GuestStatus.INTERESTED if i in (2, 7, 11)
            else GuestStatus.GOING
        )
        if owner.id == heavy.id:
            _participant(t, friends[i - 1], viewer_status)
        else:
            _participant(t, heavy, viewer_status)
    registry["personas"]["HEAVY"]["trips"] = trips
    # HT04 is the canonical narrow dense-roster capture: owner plus eight guests.
    for dense_friend in friends[:8]:
        if not SkiTripParticipant.query.filter_by(
            trip_id=trips[3].id, user_id=dense_friend.id
        ).first():
            _participant(trips[3], dense_friend, GuestStatus.GOING)
    posts = []
    for index, (trip, author) in enumerate(
        ((trips[3], heavy), (trips[6], friends[0]), (trips[7], friends[1])), 1
    ):
        post = SkiTripPlanningPost(
            trip_id=trip.id, user_id=author.id, category="Lodging",
            body=f"Deterministic lodging plan {index}", created_at=datetime(2027, 1, 2),
        )
        db.session.add(post)
        posts.append(post)
    registry["personas"]["HEAVY"]["planning_posts"] = posts
    heavy.visited_resort_ids = [r.id for r in list(resorts.values())[:12]]
    heavy.wish_list_resorts = [r.id for r in list(resorts.values())[:15]]
    # Availability consists of three stable ranges.
    availability = []
    for offset in (0, 1, 2):
        for day in range(5):
            row = UserAvailability(
                user_id=heavy.id, date=FROZEN_TODAY + timedelta(days=offset * 14 + day),
                is_available=True, note=f"capture-range-{offset + 1}",
            )
            db.session.add(row)
            availability.append(row)
    registry["personas"]["HEAVY"]["availability"] = availability
    # Exactly 25 notifications, with deterministic object and type diversity.
    activities = []
    types = (ActivityType.TRIP_CREATED.value, ActivityType.TRIP_OVERLAP.value,
             ActivityType.CONNECTION_ACCEPTED.value, ActivityType.FRIEND_JOINED_TRIP.value)
    for i in range(25):
        actor = friends[i % len(friends)]
        row = Activity(
            actor_user_id=actor.id, recipient_user_id=heavy.id,
            type=types[i % len(types)], object_type="trip" if i % 2 == 0 else "user",
            object_id=trips[i % len(trips)].id if i % 2 == 0 else actor.id,
            created_at=datetime(2027, 1, 1) + timedelta(days=i),
            extra_data={"fixture": f"activity:{i + 1:02d}", "plus_n": i >= 20},
        )
        db.session.add(row)
        activities.append(row)
    registry["personas"]["HEAVY"]["activities"] = activities
    registry["personas"]["HEAVY"]["scenarios"] = {
        "ideas": {"wishlist_resorts": 15, "visited_resorts": 12},
        "happening": {"current_trip": "HT04", "overlap_friends": 1},
        "social_overlap": {"friends": ["HF01", "HF06", "HF11"]},
        "plus_n": {"threshold": 20, "notifications": 5},
        "pagination": {"page_size": 10, "pages": (10, 10, 5)},
        "pass_families": ("Epic", "Ikon", "Indy"),
        "availability_ranges": ("2027-01-15/2027-01-19",
                                "2027-01-29/2027-02-02",
                                "2027-02-12/2027-02-16"),
    }
    registry["routes"] = {
        "home": "persona:heavy", "friends": "persona:heavy",
        "trips": "persona:heavy", "empty": "persona:empty",
        "light": "persona:light", "typical": "persona:typical",
        "extreme": "persona:extreme", "edge": "persona:edge",
    }
    db.session.flush()
    validate_fixtures(database, registry)
    db.session.commit()
    return registry


def validate_fixtures(database=None, registry=None):
    """Raise AssertionError, rather than silently accepting incomplete data."""
    registry = registry or seed_all(database)
    heavy = registry["personas"]["HEAVY"]["user"]
    friends = registry["personas"]["HEAVY"]["friends"]
    trips = registry["personas"]["HEAVY"]["trips"]
    assert len(friends) == 25, "HEAVY must have exactly 25 friends"
    assert Friend.query.filter_by(user_id=heavy.id).count() == 25
    for friend in friends:
        assert Friend.query.filter_by(user_id=friend.id, friend_id=heavy.id).count() == 1
    assert all(
        Friend.query.filter_by(user_id=heavy.id, friend_id=f.id).count() == 1
        and Friend.query.filter_by(user_id=f.id, friend_id=heavy.id).count() == 1
        for f in friends
    ), "friendship must be reciprocal"
    associated = {
        p.trip_id for p in SkiTripParticipant.query.filter_by(user_id=heavy.id)
    } | {t.id for t in SkiTrip.query.filter_by(user_id=heavy.id)}
    assert len(associated) == 15, "HEAVY must have exactly 15 associated trips"
    assert len({t.id for t in trips}) == 15
    assert SkiTripParticipant.query.filter_by(trip_id=trips[3].id).count() == 9
    assert {t.trip_status for t in trips} == {"planning", "going"}
    assert {t.lifecycle_state for t in trips} == {"active", "completed", "cancelled"}
    assert {t.is_public for t in trips} == {True, False}
    assert any(t.end_date < FROZEN_TODAY for t in trips)
    assert any(t.start_date <= FROZEN_TODAY <= t.end_date for t in trips)
    assert any(t.start_date > FROZEN_TODAY for t in trips)
    participants = [
        p for p in SkiTripParticipant.query.filter(
            SkiTripParticipant.trip_id.in_(associated)
        ).all() if p.user_id == heavy.id
    ]
    assert {p.role for p in participants} == {ParticipantRole.OWNER, ParticipantRole.GUEST}
    assert {p.status for p in participants} >= {
        GuestStatus.GOING, GuestStatus.INTERESTED, GuestStatus.PENDING
    }
    assert len(heavy.wish_list_resorts) == 15
    assert len(set(heavy.wish_list_resorts)) == 15
    assert len(heavy.visited_resort_ids) == 12
    assert len(set(heavy.visited_resort_ids)) == 12
    assert len(Activity.query.filter_by(recipient_user_id=heavy.id).all()) == 25
    assert len(UserAvailability.query.filter_by(user_id=heavy.id).all()) == 15
    assert len(registry["personas"]["HEAVY"]["planning_posts"]) == 3
    assert len(friends[0].wish_list_resorts) == 2
    assert len(friends[0].visited_resort_ids) == 3
    assert {v["cluster"] for v in registry["personas"]["HEAVY"]["friend_ids"].values()} == {
        "Aspen Core", "Vail Weekend", "Mammoth Dates", "Big Sky Collective",
        "Indy Mix", "Social-only",
    }
    cluster_sizes = {}
    for value in registry["personas"]["HEAVY"]["friend_ids"].values():
        cluster_sizes[value["cluster"]] = cluster_sizes.get(value["cluster"], 0) + 1
    assert cluster_sizes == {
        "Aspen Core": 5, "Vail Weekend": 5, "Mammoth Dates": 5,
        "Big Sky Collective": 5, "Indy Mix": 3, "Social-only": 2,
    }
    scenarios = registry["personas"]["HEAVY"]["scenarios"]
    assert scenarios["pass_families"] == ("Epic", "Ikon", "Indy")
    assert scenarios["pagination"]["pages"] == (10, 10, 5)
    assert scenarios["plus_n"]["notifications"] == 5
    return True


def resolve_route_binding(binding, registry):
    """Resolve a route fixture name or ``persona:<name>`` to a User."""
    logical = registry.get("routes", {}).get(binding, binding)
    if logical.startswith("persona:"):
        key = logical.split(":", 1)[1].upper()
        return registry["personas"][key]["user"]
    raise KeyError(f"Unknown capture route binding: {binding}")
