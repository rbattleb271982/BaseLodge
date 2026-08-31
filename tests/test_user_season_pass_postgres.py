"""Disposable PostgreSQL concurrency coverage for season-pass upserts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import psycopg2
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from models import User, UserSeasonPass
from services.user_season_passes import upsert_user_season_pass
from test_import_reference_data_postgres import (
    _initialized_database,
    disposable_postgres,
)


def test_concurrent_first_writes_keep_current_and_history_in_sync(
        disposable_postgres, monkeypatch):
    database_url = _initialized_database(
        disposable_postgres, monkeypatch, "season-pass-concurrency"
    )
    connection = psycopg2.connect(database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO "user" (first_name,email,pass_type) '
                    "VALUES ('Concurrent','concurrent@example.test','no_pass') "
                    "RETURNING id"
                )
                user_id = cursor.fetchone()[0]
    finally:
        connection.close()

    engine = sa.create_engine(database_url)
    Session = sessionmaker(bind=engine)
    barrier = Barrier(2)

    def write_pass(pass_type):
        with Session() as session:
            user = session.get(User, user_id)
            user.pass_type = pass_type
            barrier.wait(timeout=10)
            upsert_user_season_pass(
                user,
                pass_type,
                as_of=date(2026, 12, 1),
                session=session,
            )
            session.commit()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(write_pass, "epic"),
                executor.submit(write_pass, "ikon"),
            ]
            for future in futures:
                future.result(timeout=20)

        with Session() as session:
            user = session.get(User, user_id)
            rows = session.execute(
                sa.select(UserSeasonPass).where(
                    UserSeasonPass.user_id == user_id,
                    UserSeasonPass.season_start_year == 2026,
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].pass_type == user.pass_type
            assert rows[0].pass_type in {"epic", "ikon"}
    finally:
        engine.dispose()