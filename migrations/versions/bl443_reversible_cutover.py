"""Add reversible per-event messaging cutover controls.

Revision ID: bl443_reversible_cutover
Revises: bl440_message_outbox
"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime


revision = "bl443_reversible_cutover"
down_revision = "bl440_message_outbox"
branch_labels = None
depends_on = None

DELIVERABLE_EVENTS = (
    "friend.request.created", "friend.request.accepted", "friend.pass.changed",
    "friend.suggestions.created", "founder.new_user", "founder.app_open",
    "founder.invite_share", "push.test.sent", "trip.invite.created",
    "trip.invite.accepted", "trip.invite.declined", "trip.join.requested",
    "trip.participant.added", "trip.participant.left", "trip.cancelled",
    "trip.dates.updated", "trip.resort.updated", "trip.details.updated",
    "trip.accommodation.updated", "trip.planning_post.created",
)


def upgrade():
    op.create_table(
        "messaging_delivery_policy",
        sa.Column("event_name", sa.String(120), primary_key=True),
        sa.Column("delivery_mode", sa.String(24), nullable=False),
        sa.Column("cutover_epoch", sa.Integer(), nullable=False),
        sa.Column("claims_paused", sa.Boolean(), nullable=False),
        sa.Column("control_revision", sa.Integer(), nullable=False),
        sa.Column("operator_reason", sa.String(500), nullable=False),
        sa.Column("audit_identity", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "delivery_mode IN ('inline','enqueue_only')",
            name="ck_messaging_policy_mode",
        ),
        sa.CheckConstraint(
            "cutover_epoch > 0 AND control_revision > 0",
            name="ck_messaging_policy_versions",
        ),
    )
    op.create_table(
        "messaging_delivery_policy_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_name", sa.String(120), nullable=False),
        sa.Column("delivery_mode", sa.String(24), nullable=False),
        sa.Column("cutover_epoch", sa.Integer(), nullable=False),
        sa.Column("claims_paused", sa.Boolean(), nullable=False),
        sa.Column("control_revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("operator_reason", sa.String(500), nullable=False),
        sa.Column("audit_identity", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_name"], ["messaging_delivery_policy.event_name"]
        ),
    )
    op.create_index(
        "ix_messaging_delivery_policy_event_event_name",
        "messaging_delivery_policy_event", ["event_name"],
    )
    op.create_table(
        "messaging_replay_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_outbox_id", sa.Integer(), nullable=False),
        sa.Column("target_outbox_id", sa.Integer(), nullable=False),
        sa.Column("source_epoch", sa.Integer(), nullable=False),
        sa.Column("target_epoch", sa.Integer(), nullable=False),
        sa.Column("source_status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("operator_reason", sa.String(500), nullable=False),
        sa.Column("reconciliation_notes", sa.String(500), nullable=True),
        sa.Column("duplicate_risk_acknowledged", sa.Boolean(), nullable=False),
        sa.Column("audit_identity", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_outbox_id"], ["message_outbox.id"]),
        sa.ForeignKeyConstraint(["target_outbox_id"], ["message_outbox.id"]),
        sa.UniqueConstraint("source_outbox_id", "idempotency_key",
                            name="uq_messaging_replay_request"),
    )

    with op.batch_alter_table("message_outbox") as batch:
        batch.add_column(sa.Column(
            "configuration_epoch", sa.Integer(), nullable=False, server_default="1"
        ))
        batch.add_column(sa.Column("producer_release_sha", sa.String(40)))
        batch.add_column(sa.Column("last_worker_release_sha", sa.String(40)))
        batch.add_column(sa.Column("replay_reason", sa.String(500)))
        batch.add_column(sa.Column("replayed_by", sa.String(120)))
        batch.add_column(sa.Column("replayed_at", sa.DateTime()))
        batch.add_column(sa.Column("terminalized_at", sa.DateTime()))
        batch.add_column(sa.Column("terminalization_reason", sa.String(500)))
        batch.add_column(sa.Column("terminalized_by", sa.String(120)))
        batch.drop_constraint("ck_outbox_status", type_="check")
        batch.create_check_constraint(
            "ck_outbox_status",
            "status IN ('pending','processing','retryable','provider_accepted',"
            "'suppressed','dead_letter','delivery_unknown','operator_terminalized')",
        )
    op.create_index(
        "ix_outbox_family_epoch_claim", "message_outbox",
        ["event_name", "configuration_epoch", "status", "next_attempt_at", "id"],
    )
    op.create_index(
        "ix_outbox_family_epoch_lease", "message_outbox",
        ["event_name", "configuration_epoch", "status", "lease_expires_at"],
    )

    connection = op.get_bind()
    names = set(DELIVERABLE_EVENTS)
    names.update(row[0] for row in connection.execute(
        sa.text("SELECT DISTINCT event_name FROM message_outbox")
    ) if row[0])
    policy = sa.table(
        "messaging_delivery_policy",
        sa.column("event_name"), sa.column("delivery_mode"),
        sa.column("cutover_epoch"), sa.column("claims_paused"),
        sa.column("control_revision"), sa.column("operator_reason"),
        sa.column("audit_identity"), sa.column("created_at"), sa.column("updated_at"),
    )
    history = sa.table(
        "messaging_delivery_policy_event",
        sa.column("event_name"), sa.column("delivery_mode"),
        sa.column("cutover_epoch"), sa.column("claims_paused"),
        sa.column("control_revision"), sa.column("action"),
        sa.column("operator_reason"), sa.column("audit_identity"),
        sa.column("created_at"),
    )
    now = datetime.utcnow()
    for name in sorted(names):
        op.bulk_insert(policy, [{
            "event_name": name, "delivery_mode": "inline", "cutover_epoch": 1,
            "claims_paused": True, "control_revision": 1,
            "operator_reason": "bootstrap", "audit_identity": "migration",
            "created_at": now, "updated_at": now,
        }])
        op.bulk_insert(history, [{
            "event_name": name, "delivery_mode": "inline", "cutover_epoch": 1,
            "claims_paused": True, "control_revision": 1, "action": "bootstrap",
            "operator_reason": "bootstrap", "audit_identity": "migration",
            "created_at": now,
        }])


def downgrade():
    connection = op.get_bind()
    unsafe_history = connection.execute(sa.text(
        "SELECT COUNT(*) FROM messaging_delivery_policy_event "
        "WHERE action <> 'bootstrap'"
    )).scalar()
    unsafe_outbox = connection.execute(sa.text(
        "SELECT COUNT(*) FROM message_outbox WHERE configuration_epoch <> 1 "
        "OR replay_of_outbox_id IS NOT NULL OR replayed_at IS NOT NULL "
        "OR status = 'operator_terminalized' "
        "OR terminalized_at IS NOT NULL"
    )).scalar()
    if unsafe_history or unsafe_outbox:
        raise RuntimeError(
            "bl443 downgrade refused: operational cutover evidence exists"
        )
    op.drop_index("ix_outbox_family_epoch_lease", table_name="message_outbox")
    op.drop_index("ix_outbox_family_epoch_claim", table_name="message_outbox")
    with op.batch_alter_table("message_outbox") as batch:
        batch.drop_constraint("ck_outbox_status", type_="check")
        batch.create_check_constraint(
            "ck_outbox_status",
            "status IN ('pending','processing','retryable','provider_accepted',"
            "'suppressed','dead_letter','delivery_unknown')",
        )
        batch.drop_column("terminalized_by")
        batch.drop_column("terminalization_reason")
        batch.drop_column("terminalized_at")
        batch.drop_column("last_worker_release_sha")
        batch.drop_column("producer_release_sha")
        batch.drop_column("replayed_at")
        batch.drop_column("replayed_by")
        batch.drop_column("replay_reason")
        batch.drop_column("configuration_epoch")
    op.drop_table("messaging_replay_event")
    op.drop_table("messaging_delivery_policy_event")
    op.drop_table("messaging_delivery_policy")