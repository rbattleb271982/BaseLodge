"""Add durable BL-238 attention state and workflow linkage.

Revision ID: bl238_attention_state
Revises: bl83_rsvp_deadline
"""
from alembic import op
import sqlalchemy as sa

revision = "bl238_attention_state"
down_revision = "bl83_rsvp_deadline"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("activity", sa.Column("seen_at", sa.DateTime(), nullable=True))
    op.add_column("activity", sa.Column("subject_type", sa.String(length=40), nullable=True))
    op.add_column("activity", sa.Column("subject_id", sa.Integer(), nullable=True))
    op.create_index("ix_activity_attention_recipient_seen", "activity",
                    ["recipient_user_id", "seen_at", "created_at"])
    op.create_index("ix_activity_attention_subject", "activity",
                    ["subject_type", "subject_id", "type", "created_at"])

    # Existing activity is legacy history, not new attention.
    op.execute(
        "UPDATE activity SET seen_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
        "WHERE seen_at IS NULL"
    )
    # Seed durable evidence for pending incoming friend requests without
    # changing their canonical Invitation state.  Existing rows are seen.
    bind = op.get_bind()
    rows = bind.execute(sa.text("""
        SELECT i.id, i.sender_id, i.receiver_id, i.created_at
        FROM invitation i
        WHERE i.trip_id IS NULL
          AND i.invite_type = 'outbound'
          AND i.status = 'pending'
    """)).fetchall()
    for row in rows:
        exists = bind.execute(sa.text("""
            SELECT 1 FROM activity
            WHERE type = 'friend_request_received'
              AND subject_type = 'invitation' AND subject_id = :id
            LIMIT 1
        """), {"id": row.id}).first()
        if exists:
            continue
        bind.execute(sa.text("""
            INSERT INTO activity
              (actor_user_id, recipient_user_id, type, object_type, object_id,
               created_at, seen_at, subject_type, subject_id)
            VALUES (:actor, :recipient, 'friend_request_received', 'user',
                    :actor, :created, :created, 'invitation', :subject)
        """), {"actor": row.sender_id, "recipient": row.receiver_id,
               "created": row.created_at, "subject": row.id})


def downgrade():
    op.drop_index("ix_activity_attention_subject", table_name="activity")
    op.drop_index("ix_activity_attention_recipient_seen", table_name="activity")
    op.drop_column("activity", "subject_id")
    op.drop_column("activity", "subject_type")
    op.drop_column("activity", "seen_at")