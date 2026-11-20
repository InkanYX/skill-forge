from alembic import context

from app.database import Base, database_url, make_engine

target_metadata = Base.metadata


def run_migrations():
    url = context.config.attributes.get("database_url") or database_url()
    if not url:
        raise RuntimeError("请先配置 DATABASE_URL。")
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = make_engine(url)
        try:
            with engine.connect() as connection:
                context.configure(connection=connection, target_metadata=target_metadata)
                with context.begin_transaction():
                    context.run_migrations()
        finally:
            engine.dispose()


run_migrations()
