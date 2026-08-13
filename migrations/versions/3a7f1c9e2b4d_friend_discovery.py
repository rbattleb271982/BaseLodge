"""Friend discovery: search columns, discoverable flag, FriendCooldown table

Adds:
  - user.discoverable_in_friend_search (Boolean, default True)
  - user.search_first_name (String 120, nullable) — pre-normalized for search
  - user.search_last_name  (String 120, nullable) — pre-normalized for search
  - friend_cooldown table (pair-specific 24h cooldown after decline/cancel/unfriend)
  - varchar_pattern_ops indexes on both search columns (PostgreSQL prefix LIKE)

Also backfills search_first_name / search_last_name for all existing users using
the same normalize_for_search() algorithm applied at write time.

Idempotent: safe to run whether or not the startup migration has already
applied the schema (uses IF NOT EXISTS / try-except for each step).

Revision ID: 3a7f1c9e2b4d
Revises: 7e24870bab12
Create Date: 2026-08-13
"""
import re
import unicodedata

from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError

# revision identifiers, used by Alembic.
revision = '3a7f1c9e2b4d'
down_revision = '7e24870bab12'
branch_labels = None
depends_on = None


# Inline copy of normalize_for_search() for migration safety.
# Must produce identical output to services/search_utils.py::normalize_for_search().
_TRANSLITERATION_MAP = str.maketrans({
    'ø': 'o', 'ł': 'l', 'đ': 'd', 'ð': 'd',
    'þ': 'th', 'æ': 'ae', 'œ': 'oe', 'ß': 'ss',
})


def _normalize(s):
    if not s:
        return ''
    s = s.lower()
    s = s.translate(_TRANSLITERATION_MAP)
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r"['\u2018\u2019\u0060`]", ' ', s)
    s = re.sub(r'[-\u2013\u2014]', ' ', s)
    s = ' '.join(s.split())
    return s


def _col_exists(bind, table, column):
    result = bind.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {'t': table, 'c': column}).fetchone()
    return result is not None


def _table_exists(bind, table):
    result = bind.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = :t"
    ), {'t': table}).fetchone()
    return result is not None


def _index_exists(bind, index_name):
    result = bind.execute(sa.text(
        "SELECT 1 FROM pg_indexes WHERE indexname = :i"
    ), {'i': index_name}).fetchone()
    return result is not None


def upgrade():
    bind = op.get_bind()

    # ── 1. New columns on user ─────────────────────────────────────────────
    if not _col_exists(bind, 'user', 'discoverable_in_friend_search'):
        op.add_column('user', sa.Column(
            'discoverable_in_friend_search',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true'),
        ))
    if not _col_exists(bind, 'user', 'search_first_name'):
        op.add_column('user', sa.Column('search_first_name', sa.String(120), nullable=True))
    if not _col_exists(bind, 'user', 'search_last_name'):
        op.add_column('user', sa.Column('search_last_name', sa.String(120), nullable=True))

    # ── 2. FriendCooldown table ───────────────────────────────────────────
    if not _table_exists(bind, 'friend_cooldown'):
        op.create_table(
            'friend_cooldown',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_a_id', sa.Integer(), nullable=False),
            sa.Column('user_b_id', sa.Integer(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_a_id'], ['user.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_b_id'], ['user.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_a_id', 'user_b_id', name='uq_friend_cooldown_pair'),
            sa.CheckConstraint('user_a_id < user_b_id', name='ck_friend_cooldown_order'),
        )

    # ── 3. Indexes for prefix LIKE on search columns ──────────────────────
    # postgresql_ops makes this a varchar_pattern_ops index on PostgreSQL,
    # enabling efficient LIKE 'prefix%' queries. On SQLite the kwarg is ignored.
    if not _index_exists(bind, 'ix_user_search_first_name'):
        op.create_index(
            'ix_user_search_first_name',
            'user',
            ['search_first_name'],
            postgresql_ops={'search_first_name': 'varchar_pattern_ops'},
        )
    if not _index_exists(bind, 'ix_user_search_last_name'):
        op.create_index(
            'ix_user_search_last_name',
            'user',
            ['search_last_name'],
            postgresql_ops={'search_last_name': 'varchar_pattern_ops'},
        )
    if not _index_exists(bind, 'ix_friend_cooldown_user_a'):
        op.create_index('ix_friend_cooldown_user_a', 'friend_cooldown', ['user_a_id'])
    if not _index_exists(bind, 'ix_friend_cooldown_user_b'):
        op.create_index('ix_friend_cooldown_user_b', 'friend_cooldown', ['user_b_id'])

    # ── 4. Backfill search columns for existing users ─────────────────────
    rows = bind.execute(
        sa.text('SELECT id, first_name, last_name FROM "user"')
    ).fetchall()
    for row in rows:
        sfn = _normalize(row.first_name or '')
        sln = _normalize(row.last_name or '')
        bind.execute(
            sa.text(
                'UPDATE "user" SET search_first_name = :sfn, search_last_name = :sln'
                ' WHERE id = :id'
            ),
            {'sfn': sfn, 'sln': sln, 'id': row.id},
        )


def downgrade():
    bind = op.get_bind()
    if _index_exists(bind, 'ix_friend_cooldown_user_b'):
        op.drop_index('ix_friend_cooldown_user_b', table_name='friend_cooldown')
    if _index_exists(bind, 'ix_friend_cooldown_user_a'):
        op.drop_index('ix_friend_cooldown_user_a', table_name='friend_cooldown')
    if _index_exists(bind, 'ix_user_search_last_name'):
        op.drop_index('ix_user_search_last_name', table_name='user')
    if _index_exists(bind, 'ix_user_search_first_name'):
        op.drop_index('ix_user_search_first_name', table_name='user')
    if _table_exists(bind, 'friend_cooldown'):
        op.drop_table('friend_cooldown')
    with op.batch_alter_table('user', schema=None) as batch_op:
        if _col_exists(bind, 'user', 'search_last_name'):
            batch_op.drop_column('search_last_name')
        if _col_exists(bind, 'user', 'search_first_name'):
            batch_op.drop_column('search_first_name')
        if _col_exists(bind, 'user', 'discoverable_in_friend_search'):
            batch_op.drop_column('discoverable_in_friend_search')
