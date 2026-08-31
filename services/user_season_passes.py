"""Canonical persistence helpers for season-specific user pass ownership."""

from datetime import date, datetime

from sqlalchemy import select

from models import db, UserSeasonPass
from services.pass_utils import normalize_pass_selection
from services.ski_seasons import get_ski_season_start_year


def upsert_user_season_pass(user, pass_type, *, as_of=None, session=None):
    """Create or correct a user's pass value for the season containing ``as_of``.

    Blank or unrecognized input is intentionally ignored. Explicit ``no_pass``
    and ``no_pass_yet`` values are meaningful historical states and are stored.
    The caller owns the surrounding transaction.
    """
    canonical_pass = normalize_pass_selection(pass_type)
    if not canonical_pass:
        return None
    if user.id is None:
        raise ValueError("User must be persisted before recording season pass history.")

    session = session or db.session
    season_start_year = get_ski_season_start_year(as_of or date.today())
    now = datetime.utcnow()
    values = {
        "user_id": user.id,
        "season_start_year": season_start_year,
        "pass_type": canonical_pass,
        "created_at": now,
        "updated_at": now,
    }
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError(
            f"Unsupported database dialect for user season pass upsert: "
            f"{dialect_name}"
        )

    statement = insert(UserSeasonPass).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=["user_id", "season_start_year"],
        set_={
            "pass_type": canonical_pass,
            "updated_at": now,
        },
    )
    session.execute(statement)

    return session.execute(
        select(UserSeasonPass).where(
            UserSeasonPass.user_id == user.id,
            UserSeasonPass.season_start_year == season_start_year,
        ).execution_options(populate_existing=True)
    ).scalar_one()


def get_user_pass_for_season(user_id, season_start_year, *, session=None):
    """Return the canonical pass value for one user-season, or ``None``."""
    session = session or db.session
    row = session.execute(
        select(UserSeasonPass).where(
            UserSeasonPass.user_id == user_id,
            UserSeasonPass.season_start_year == int(season_start_year),
        )
    ).scalar_one_or_none()
    return row.pass_type if row else None