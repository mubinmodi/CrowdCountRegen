from alembic import context

from app.db import Base, engine

target_metadata = Base.metadata


def run() -> None:
    # init_db() passes its own connection; the CLI falls back to the app's engine.
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _configure_and_run(connection)
        return
    with engine.begin() as connection:
        _configure_and_run(connection)


def _configure_and_run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite can't ALTER most things
    )
    with context.begin_transaction():
        context.run_migrations()


run()
