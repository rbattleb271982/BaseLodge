"""Reconcile MountainPageView foreign keys.

Revision ID: bl306_mpv_fk_reconcile
Revises: bl305_ski_day_foundation
Create Date: 2026-08-21

The legacy startup DDL created mountain_page_view without foreign keys.  This
migration is deliberately data-conservative: existing orphan references are
reported and abort the migration so their disposition can be reviewed before
any production rows are changed.
"""

from collections import defaultdict

from alembic import op
import sqlalchemy as sa


revision = "bl306_mpv_fk_reconcile"
down_revision = "bl305_ski_day_foundation"
branch_labels = None
depends_on = None


TABLE_NAME = "mountain_page_view"
RESORT_FK_NAME = "fk_mountain_page_view_resort_id"
USER_FK_NAME = "fk_mountain_page_view_user_id"
INDEX_NAME = "idx_mpv_resort_time"


def _table_exists(bind, table_name):
    return sa.inspect(bind).has_table(table_name)


def _reflect_tables(bind):
    metadata = sa.MetaData()
    return (
        sa.Table(TABLE_NAME, metadata, autoload_with=bind),
        sa.Table("resort", metadata, autoload_with=bind),
        sa.Table("user", metadata, autoload_with=bind),
    )


def _format_orphan_rows(bind, page_views, target_table, source_column, label):
    """Return grouped diagnostics without changing any rows."""
    target_id = target_table.c.id
    statement = (
        sa.select(
            page_views.c.id.label("page_view_id"),
            page_views.c[source_column].label("orphan_id"),
            page_views.c.viewed_at,
            page_views.c.user_id,
            page_views.c.session_key,
        )
        .where(
            page_views.c[source_column].is_not(None),
            ~sa.exists(sa.select(target_id).where(target_id == page_views.c[source_column])),
        )
        .order_by(page_views.c[source_column], page_views.c.viewed_at, page_views.c.id)
    )
    rows = bind.execute(statement).mappings().all()
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["orphan_id"]].append(row)

    diagnostics = []
    for orphan_id, orphan_rows in grouped.items():
        diagnostics.append(
            {
                "label": label,
                "orphan_id": orphan_id,
                "count": len(orphan_rows),
                "page_view_ids": [row["page_view_id"] for row in orphan_rows],
                "viewed_at": [str(row["viewed_at"]) for row in orphan_rows],
                "user_ids": sorted(
                    {
                        row["user_id"]
                        for row in orphan_rows
                        if row["user_id"] is not None
                    }
                ),
            }
        )
    return diagnostics


def _validate_existing_table(bind):
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns(TABLE_NAME)}
    required_columns = {"id", "resort_id", "user_id", "viewed_at", "session_key"}
    missing_columns = sorted(required_columns - columns.keys())
    if missing_columns:
        raise RuntimeError(
            f"{TABLE_NAME} is missing required columns: {', '.join(missing_columns)}"
        )
    if columns["resort_id"]["nullable"] is not False:
        raise RuntimeError(
            f"{TABLE_NAME}.resort_id must remain NOT NULL before FK reconciliation"
        )
    if columns["user_id"]["nullable"] is not True:
        raise RuntimeError(
            f"{TABLE_NAME}.user_id must remain nullable before FK reconciliation"
        )

    page_views, resorts, users = _reflect_tables(bind)
    orphan_resorts = _format_orphan_rows(
        bind, page_views, resorts, "resort_id", "resort_id"
    )
    orphan_users = _format_orphan_rows(bind, page_views, users, "user_id", "user_id")
    if orphan_resorts or orphan_users:
        diagnostics = orphan_resorts + orphan_users
        raise RuntimeError(
            "MountainPageView FK reconciliation stopped because orphan references "
            "require an explicit data decision; no rows were changed. "
            f"diagnostics={diagnostics!r}"
        )


def _existing_fk_map(bind):
    foreign_keys = sa.inspect(bind).get_foreign_keys(TABLE_NAME)
    result = {}
    for foreign_key in foreign_keys:
        constrained = tuple(foreign_key.get("constrained_columns") or ())
        referred_table = foreign_key.get("referred_table")
        if constrained == ("resort_id",) and referred_table == "resort":
            result["resort_id"] = foreign_key
        elif constrained == ("user_id",) and referred_table == "user":
            result["user_id"] = foreign_key
    return result


def _validate_existing_fks(bind, existing):
    for column, expected_action in (
        ("resort_id", "CASCADE"),
        ("user_id", "SET NULL"),
    ):
        foreign_key = existing.get(column)
        if not foreign_key:
            continue
        actual_action = (foreign_key.get("options") or {}).get("ondelete")
        if (actual_action or "").upper() != expected_action:
            raise RuntimeError(
                f"{TABLE_NAME}.{column} already has an incompatible FK action "
                f"{actual_action!r}; expected {expected_action!r}"
            )


def _add_missing_fks(bind, existing):
    missing = []
    if "resort_id" not in existing:
        missing.append(
            (
                RESORT_FK_NAME,
                "resort",
                ["resort_id"],
                ["id"],
                "CASCADE",
            )
        )
    if "user_id" not in existing:
        missing.append(
            (
                USER_FK_NAME,
                "user",
                ["user_id"],
                ["id"],
                "SET NULL",
            )
        )
    if not missing:
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(TABLE_NAME, recreate="always") as batch_op:
            for name, referred_table, local_columns, remote_columns, ondelete in missing:
                batch_op.create_foreign_key(
                    name,
                    referred_table,
                    local_columns,
                    remote_columns,
                    ondelete=ondelete,
                )
    else:
        for name, referred_table, local_columns, remote_columns, ondelete in missing:
            op.create_foreign_key(
                name,
                TABLE_NAME,
                referred_table,
                local_columns,
                remote_columns,
                ondelete=ondelete,
            )


def _ensure_index(bind):
    existing_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes(TABLE_NAME)
    }
    if INDEX_NAME not in existing_indexes:
        op.create_index(INDEX_NAME, TABLE_NAME, ["resort_id", "viewed_at"])


def upgrade():
    bind = op.get_bind()

    if not _table_exists(bind, TABLE_NAME):
        op.create_table(
            TABLE_NAME,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("resort_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column(
                "viewed_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("session_key", sa.String(length=32), nullable=True),
            sa.ForeignKeyConstraint(
                ["resort_id"],
                ["resort.id"],
                name=RESORT_FK_NAME,
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["user.id"],
                name=USER_FK_NAME,
                ondelete="SET NULL",
            ),
        )
        op.create_index(INDEX_NAME, TABLE_NAME, ["resort_id", "viewed_at"])
        return

    _validate_existing_table(bind)
    existing = _existing_fk_map(bind)
    _validate_existing_fks(bind, existing)
    _add_missing_fks(bind, existing)
    _ensure_index(bind)


def downgrade():
    """Fail closed: automatic rollback could remove pre-existing schema/data."""
    raise RuntimeError(
        "bl306_mpv_fk_reconcile has no automatic downgrade. "
        "Use an explicit, reviewed forward migration or restore a backup; "
        "dropping the reconciliation FKs/table could destroy analytics or "
        "remove constraints that predated this revision."
    )