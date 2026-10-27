from alembic import context

from app.db import Base, engine, migration_connection

target_metadata = Base.metadata


def run() -> None:
    # init_db() passes its own connection; the CLI falls back to the app's engine, through
    # the same helper (on SQLite it keeps batch table rebuilds from cascading deletes).
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _configure_and_run(connection)
        return
    with migration_connection(engine) as connection:
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
