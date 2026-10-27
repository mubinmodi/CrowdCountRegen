"""Initial v2 schema: users, cameras, per-minute count samples.

Revision ID: 0001
Revises:
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "owner_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source", sa.String(1000), nullable=False),
        sa.Column("zone", sa.JSON, nullable=True),
        sa.Column("threshold", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cameras_owner_id", "cameras", ["owner_id"])

    op.create_table(
        "count_samples",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "camera_id",
            sa.Integer,
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("avg_occupancy", sa.Float, nullable=False),
        sa.Column("peak_occupancy", sa.Integer, nullable=False),
        sa.Column("entries", sa.Integer, nullable=False),
        sa.Column("frames", sa.Integer, nullable=False),
        sa.UniqueConstraint("camera_id", "minute"),
    )
    op.create_index("ix_count_samples_camera_id", "count_samples", ["camera_id"])
    op.create_index("ix_count_samples_minute", "count_samples", ["minute"])


def downgrade() -> None:
    op.drop_table("count_samples")
    op.drop_table("cameras")
    op.drop_table("users")
