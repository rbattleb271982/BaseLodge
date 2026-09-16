"""PostgreSQL-only two-session concurrency coverage for BL-79."""

from concurrent.futures import ThreadPoolExecutor
import getpass
import os
import shutil
import socket
import subprocess
import sys
from threading import Barrier
from urllib.parse import quote
from uuid import uuid4

import pytest
import sqlalchemy as sa

from app import app
from models import (
    Friend,
    FriendConnectionEvent,
    FriendCooldown,
    Invitation,
    InviteType,
    db,
)
from services.connection_transitions import transition_connection
from tests.conftest import (
    _login,
    _make_user,
    _swap_engine,
    json_delete,
    json_post,
)


def _free_local_port():
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


@pytest.fixture(scope="module")
def postgres_connection_database(tmp_path_factory):
    """Run only against a unique database in a disposable local cluster."""
    initdb = shutil.which("initdb")
    pg_ctl = shutil.which("pg_ctl")
    createdb = shutil.which("createdb")
    dropdb = shutil.which("dropdb")
    if not all((initdb, pg_ctl, createdb, dropdb)):
        pytest.fail(
            "Local PostgreSQL tools initdb, pg_ctl, createdb, and dropdb "
            "are required for connection concurrency tests"
        )

    root = tmp_path_factory.mktemp("connection-transitions-postgres")
    data = root / "data"
    sockets = root / "socket"
    sockets.mkdir()
    log = root / "postgres.log"
    port = _free_local_port()
    role = getpass.getuser()
    database_name = f"bl79_{uuid4().hex}"
    database_url = (
        f"postgresql://{quote(role, safe='')}@127.0.0.1:{port}/"
        f"{database_name}"
    )
    engine = None
    saved_engine = None
    server_start_attempted = False
    try:
        server_start_attempted = True
        subprocess.run(
            [
                initdb,
                "-D",
                str(data),
                "-A",
                "trust",
                "--no-locale",
                "--encoding=UTF8",
                "-U",
                role,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                pg_ctl,
                "-D",
                str(data),
                "-o",
                f"-F -h 127.0.0.1 -k {sockets} -p {port}",
                "-l",
                str(log),
                "-w",
                "start",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                createdb,
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
                "-U",
                role,
                database_name,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        engine = sa.create_engine(database_url, pool_pre_ping=True)
        saved_engine = _swap_engine(engine)
        with app.app_context():
            db.create_all()
        yield
    finally:
        primary_error_active = sys.exc_info()[0] is not None
        cleanup_errors = []

        def attempt_cleanup(label, operation):
            try:
                operation()
            except Exception as exc:
                cleanup_errors.append(f"{label}: {exc}")

        if saved_engine is not None:
            def remove_session():
                with app.app_context():
                    db.session.remove()

            attempt_cleanup("remove database session", remove_session)
            attempt_cleanup(
                "restore Flask-SQLAlchemy engine",
                lambda: _swap_engine(saved_engine),
            )
        if engine is not None:
            attempt_cleanup("dispose PostgreSQL engine", engine.dispose)
        if server_start_attempted:
            try:
                status = subprocess.run(
                    [pg_ctl, "-D", str(data), "status"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                server_is_running = status.returncode == 0
            except Exception as exc:
                cleanup_errors.append(
                    f"inspect disposable PostgreSQL server: {exc}"
                )
                server_is_running = False
            attempt_cleanup(
                "drop disposable PostgreSQL database",
                lambda: subprocess.run(
                    [
                        dropdb,
                        "--if-exists",
                        "-h",
                        "127.0.0.1",
                        "-p",
                        str(port),
                        "-U",
                        role,
                        database_name,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                ),
            )
            try:
                stop = subprocess.run(
                    [
                        pg_ctl,
                        "-D",
                        str(data),
                        "-m",
                        "immediate",
                        "-w",
                        "stop",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if server_is_running and stop.returncode != 0:
                    cleanup_errors.append(
                        "stop disposable PostgreSQL server: "
                        + (stop.stderr.strip() or stop.stdout.strip())
                    )
            except Exception as exc:
                cleanup_errors.append(
                    f"stop disposable PostgreSQL server: {exc}"
                )
            try:
                final_status = subprocess.run(
                    [pg_ctl, "-D", str(data), "status"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if final_status.returncode == 0:
                    cleanup_errors.append(
                        "disposable PostgreSQL server is still running"
                    )
                elif final_status.returncode == 3:
                    attempt_cleanup(
                        "remove disposable PostgreSQL cluster",
                        lambda: shutil.rmtree(root),
                    )
                else:
                    cleanup_errors.append(
                        "could not confirm disposable PostgreSQL shutdown: "
                        + (
                            final_status.stderr.strip()
                            or final_status.stdout.strip()
                            or f"pg_ctl status exited {final_status.returncode}"
                        )
                    )
            except Exception as exc:
                cleanup_errors.append(
                    f"verify disposable PostgreSQL shutdown: {exc}"
                )
        if cleanup_errors and not primary_error_active:
            pytest.fail(
                "Disposable PostgreSQL cleanup failed: "
                + "; ".join(cleanup_errors)
            )


def _setup_pair(connected=False):
    with app.app_context():
        first = _make_user(f"pg-connection-first-{os.urandom(5).hex()}")
        second = _make_user(f"pg-connection-second-{os.urandom(5).hex()}")
        db.session.commit()
        if connected:
            transition_connection(
                user_id=first.id, other_user_id=second.id, connected=True,
                source="qr_connect",
            )
            db.session.commit()
        return first.id, second.id


def _concurrently(first_id, second_id, requests):
    barrier = Barrier(len(requests))

    def worker(args):
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                result = transition_connection(
                    user_id=first_id, other_user_id=second_id, **args
                )
                db.session.commit()
                return result.changed, result.event.event_type if result.event else None
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        return list(executor.map(worker, requests))


def _pair_friend_count(first_id, second_id):
    return Friend.query.filter(
        Friend.user_id.in_((first_id, second_id)),
        Friend.friend_id.in_((first_id, second_id)),
    ).count()


def _pair_event_types(first_id, second_id):
    user_a_id, user_b_id = sorted((first_id, second_id))
    return [
        event.event_type
        for event in FriendConnectionEvent.query.filter_by(
            user_a_id=user_a_id,
            user_b_id=user_b_id,
        ).order_by(FriendConnectionEvent.id).all()
    ]


def test_concurrent_formation_writes_one_pair_and_formed_event(postgres_connection_database):
    first_id, second_id = _setup_pair()
    outcomes = _concurrently(first_id, second_id, [
        {"connected": True, "source": "qr_connect"},
        {"connected": True, "source": "qr_connect"},
    ])
    assert sorted(outcome[0] for outcome in outcomes) == [False, True]
    with app.app_context():
        assert _pair_friend_count(first_id, second_id) == 2
        assert _pair_event_types(first_id, second_id) == ["formed"]


def test_concurrent_removal_writes_one_removed_event(postgres_connection_database):
    first_id, second_id = _setup_pair(connected=True)
    outcomes = _concurrently(first_id, second_id, [
        {"connected": False, "source": "api_unfriend"},
        {"connected": False, "source": "api_unfriend"},
    ])
    assert sorted(outcome[0] for outcome in outcomes) == [False, True]
    with app.app_context():
        assert _pair_friend_count(first_id, second_id) == 0
        assert _pair_event_types(first_id, second_id) == ["formed", "removed"]


def test_concurrent_remove_and_reconnect_are_serialized(postgres_connection_database):
    first_id, second_id = _setup_pair(connected=True)
    outcomes = _concurrently(first_id, second_id, [
        {"connected": False, "source": "web_unfriend"},
        {"connected": True, "source": "group_trip_accept"},
    ])
    assert all(outcome[0] in {False, True} for outcome in outcomes)
    with app.app_context():
        events = _pair_event_types(first_id, second_id)
        # Either lock winner is valid, but the recorded history must be one
        # complete serial ordering rather than duplicate or partial events.
        assert events in (
            ["formed", "removed"],
            ["formed", "removed", "formed"],
        )
        assert _pair_friend_count(first_id, second_id) == (
            2 if events[-1] == "formed" else 0
        )


def test_concurrent_friend_request_accept_and_withdraw_serialize(
    postgres_connection_database,
):
    """PostgreSQL proves the Invitation FOR UPDATE behavior SQLite cannot."""
    with app.app_context():
        sender = _make_user(f"pg-invitation-sender-{os.urandom(5).hex()}")
        receiver = _make_user(f"pg-invitation-receiver-{os.urandom(5).hex()}")
        invitation = Invitation(
            sender_id=sender.id,
            receiver_id=receiver.id,
            status="pending",
            invite_type=InviteType.OUTBOUND,
        )
        db.session.add(invitation)
        db.session.commit()
        sender_id = sender.id
        receiver_id = receiver.id
        invitation_id = invitation.id

    barrier = Barrier(2)

    def worker(operation):
        client = app.test_client()
        user_id = receiver_id if operation == "accept" else sender_id
        _login(client, user_id)
        barrier.wait(timeout=10)
        try:
            if operation == "accept":
                response = json_post(
                    client,
                    f"/api/friends/invite/{invitation_id}/accept",
                )
            else:
                response = json_delete(
                    client,
                    f"/api/friends/invite/{invitation_id}",
                )
            return operation, response.status_code
        finally:
            with app.app_context():
                db.session.remove()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = dict(executor.map(worker, ("accept", "withdraw")))

    assert sorted(outcomes.values()) == [200, 409]
    with app.app_context():
        invitation = db.session.get(Invitation, invitation_id)
        friend_count = _pair_friend_count(sender_id, receiver_id)
        cooldown_count = FriendCooldown.query.filter_by(
            user_a_id=min(sender_id, receiver_id),
            user_b_id=max(sender_id, receiver_id),
        ).count()
        if invitation.status == "accepted":
            assert outcomes == {"accept": 200, "withdraw": 409}
            assert friend_count == 2
            assert cooldown_count == 0
            assert _pair_event_types(sender_id, receiver_id) == ["formed"]
        else:
            assert invitation.status == "cancelled"
            assert outcomes == {"accept": 409, "withdraw": 200}
            assert friend_count == 0
            assert cooldown_count == 1
            assert _pair_event_types(sender_id, receiver_id) == []