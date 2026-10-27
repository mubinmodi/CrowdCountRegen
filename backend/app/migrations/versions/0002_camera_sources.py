"""Structured camera sources: kind, separate (encrypted) credentials, options, publish token.

Existing cameras get their kind inferred from the source string, and any user:password
embedded in their URL is moved into the new credential columns.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cameras") as batch:
        batch.add_column(sa.Column("kind", sa.String(20), nullable=False, server_default="stream"))
        batch.add_column(sa.Column("username", sa.String(200), nullable=True))
        batch.add_column(sa.Column("password_enc", sa.Text, nullable=True))
        batch.add_column(sa.Column("options", sa.JSON, nullable=True))
        batch.add_column(sa.Column("publish_token", sa.String(64), nullable=True))
        batch.create_unique_constraint("uq_cameras_publish_token", ["publish_token"])

    from app.crypto import encrypt
    from app.vision.sources.spec import infer_kind, split_credentials

    conn = op.get_bind()
    cameras = sa.table(
        "cameras",
        sa.column("id", sa.Integer),
        sa.column("source", sa.String),
        sa.column("kind", sa.String),
        sa.column("username", sa.String),
        sa.column("password_enc", sa.Text),
    )
    for camera_id, source in conn.execute(sa.select(cameras.c.id, cameras.c.source)).all():
        url, username, password = split_credentials(source)
        conn.execute(
            cameras.update()
            .where(cameras.c.id == camera_id)
            .values(
                kind=infer_kind(url),
                source=url,
                username=username,
                password_enc=encrypt(password) if password else None,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("cameras") as batch:
        batch.drop_constraint("uq_cameras_publish_token", type_="unique")
        for column in ("publish_token", "options", "password_enc", "username", "kind"):
            batch.drop_column(column)
