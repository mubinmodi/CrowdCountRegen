"""Camera modes (occupancy | danger_zone), descriptions, demo scenario keys, and the incident
log.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cameras") as batch:
        batch.add_column(
            sa.Column("mode", sa.String(20), nullable=False, server_default="occupancy")
        )
        batch.add_column(sa.Column("description", sa.Text, nullable=True))
        batch.add_column(sa.Column("scenario", sa.String(50), nullable=True))

    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "camera_id",
            sa.Integer,
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("peak", sa.Integer, nullable=False),
        sa.Column("limit", sa.Integer, nullable=False),
        sa.Column("snapshot", sa.LargeBinary, nullable=True),
    )
    op.create_index("ix_incidents_camera_started", "incidents", ["camera_id", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_incidents_camera_started", "incidents")
    op.drop_table("incidents")
    with op.batch_alter_table("cameras") as batch:
        batch.drop_column("scenario")
        batch.drop_column("description")
        batch.drop_column("mode")
