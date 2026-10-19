"""Alembic environment. Must work on SQLite and SQL Server."""

from logging.config import fileConfig

from alembic import context

from genie_copilot.config import get_settings
from genie_copilot.db.models import Base
from genie_copilot.db.session import make_engine

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

url = (
    context.get_x_argument(as_dictionary=True).get("url")
    or config.get_main_option("sqlalchemy.url")
    or get_settings().database_url
)


def _configure(**kwargs: object) -> None:
    context.configure(
        target_metadata=Base.metadata,
        render_as_batch=True,
        compare_type=True,
        **kwargs,
    )


if context.is_offline_mode():
    _configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(url)
    with engine.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
