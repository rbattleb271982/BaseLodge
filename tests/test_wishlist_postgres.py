"""Disposable PostgreSQL concurrency coverage for wishlist transitions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from models import Resort, User, WishlistResortEvent
from services.wishlist import (
    add_wishlist_resort,
    remove_wishlist_resort,
    replace_wishlist,
    rewrite_wishlists_for_resort_merge,
)
from test_import_reference_data_postgres import (
    _initialized_database,
    disposable_postgres,
)


def _seed(Session, initial_ids):
    suffix = uuid4().hex
    with Session.begin() as session:
        resorts = [
            Resort(
                name=f"Concurrent {suffix} {index}",
                state="CO",
                slug=f"concurrent-{suffix}-{index}",
                is_active=True,
                is_region=False,
            )
            for index in range(4)
        ]
        user = User(
            first_name="Concurrent",
            email=f"wishlist-{suffix}@example.test",
            pass_type="no_pass",
        )
        session.add_all([user, *resorts])
        session.flush()
        ids = [resort.id for resort in resorts]
        user.wish_list_resorts = [ids[index] for index in initial_ids]
        return user.id, ids


def _run_concurrently(Session, operations):
    barrier = Barrier(len(operations))

    def run(operation):
        with Session() as session:
            barrier.wait(timeout=10)
            operation(session)
            session.commit()

    with ThreadPoolExecutor(max_workers=len(operations)) as executor:
        futures = [executor.submit(run, operation) for operation in operations]
        for future in futures:
            future.result(timeout=20)


def test_concurrent_wishlist_mutations_serialize_on_subject_user(
    disposable_postgres, monkeypatch
):
    database_url = _initialized_database(
        disposable_postgres, monkeypatch, "wishlist-concurrency"
    )
    engine = sa.create_engine(database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    try:
        # add/add: neither update is lost, and each real transition is recorded.
        user_id, resort_ids = _seed(Session, [])
        _run_concurrently(Session, [
            lambda session: add_wishlist_resort(
                session,
                user_id=user_id,
                resort_id=resort_ids[0],
                actor_user_id=user_id,
            ),
            lambda session: add_wishlist_resort(
                session,
                user_id=user_id,
                resort_id=resort_ids[1],
                actor_user_id=user_id,
            ),
        ])
        with Session() as session:
            user = session.get(User, user_id)
            assert set(user.wish_list_resorts) == set(resort_ids[:2])
            assert session.scalar(sa.select(sa.func.count()).select_from(
                WishlistResortEvent
            ).where(WishlistResortEvent.user_id == user_id)) == 2

        # add/remove: independent changes compose under either lock order.
        user_id, resort_ids = _seed(Session, [0])
        _run_concurrently(Session, [
            lambda session: add_wishlist_resort(
                session,
                user_id=user_id,
                resort_id=resort_ids[1],
                actor_user_id=user_id,
            ),
            lambda session: remove_wishlist_resort(
                session,
                user_id=user_id,
                resort_id=resort_ids[0],
                actor_user_id=user_id,
            ),
        ])
        with Session() as session:
            user = session.get(User, user_id)
            assert user.wish_list_resorts == [resort_ids[1]]
            events = session.scalars(sa.select(WishlistResortEvent).where(
                WishlistResortEvent.user_id == user_id
            )).all()
            assert {(event.event_type, event.resort_id) for event in events} == {
                ("added", resort_ids[1]),
                ("removed", resort_ids[0]),
            }

        # replace/replace: both requests observe committed state in one serial order.
        user_id, resort_ids = _seed(Session, [0])
        replacements = ([resort_ids[1]], [resort_ids[2]])
        _run_concurrently(Session, [
            lambda session, value=value: replace_wishlist(
                session,
                user_id=user_id,
                requested_ids=value,
                actor_user_id=user_id,
            )
            for value in replacements
        ])
        with Session() as session:
            user = session.get(User, user_id)
            assert user.wish_list_resorts in [list(value) for value in replacements]
            assert session.scalar(sa.select(sa.func.count()).select_from(
                WishlistResortEvent
            ).where(WishlistResortEvent.user_id == user_id)) == 4

        # replace/single: final state matches one of the two valid serial orders.
        user_id, resort_ids = _seed(Session, [0])
        _run_concurrently(Session, [
            lambda session: replace_wishlist(
                session,
                user_id=user_id,
                requested_ids=[resort_ids[1]],
                actor_user_id=user_id,
            ),
            lambda session: add_wishlist_resort(
                session,
                user_id=user_id,
                resort_id=resort_ids[2],
                actor_user_id=user_id,
            ),
        ])
        with Session() as session:
            user = session.get(User, user_id)
            assert user.wish_list_resorts in (
                [resort_ids[1]],
                [resort_ids[1], resort_ids[2]],
            )
            event_count = session.scalar(
                sa.select(sa.func.count())
                .select_from(WishlistResortEvent)
                .where(WishlistResortEvent.user_id == user_id)
            )
            assert event_count in (3, 4)

        # Merge maintenance refreshes a stale identity-map entry after locking.
        user_id, resort_ids = _seed(Session, [0])
        with Session() as merge_session:
            stale_user = merge_session.get(User, user_id)
            assert stale_user.wish_list_resorts == [resort_ids[0]]

            with Session() as transition_session:
                add_wishlist_resort(
                    transition_session,
                    user_id=user_id,
                    resort_id=resort_ids[2],
                    actor_user_id=user_id,
                )
                transition_session.commit()

            assert stale_user.wish_list_resorts == [resort_ids[0]]
            changed = rewrite_wishlists_for_resort_merge(
                merge_session,
                duplicate_ids=[resort_ids[0]],
                canonical_id=resort_ids[1],
            )
            assert changed == 1
            merge_session.commit()

        with Session() as session:
            user = session.get(User, user_id)
            assert user.wish_list_resorts == [resort_ids[1], resort_ids[2]]
            events = session.scalars(sa.select(WishlistResortEvent).where(
                WishlistResortEvent.user_id == user_id
            )).all()
            assert [(event.event_type, event.resort_id) for event in events] == [
                ("added", resort_ids[2])
            ]
    finally:
        engine.dispose()