import logging
import time

from sqlalchemy import text

from app.config import get_settings
from app.database import get_engine, ping_database
from app.redis_client import ping_redis

logger = logging.getLogger(__name__)


def wait_for_dependencies(require_schema: bool = False) -> None:
    last_error: Exception | None = None
    for attempt in range(60):
        try:
            ping_database()
            ping_redis()
            if require_schema:
                with get_engine().connect() as connection:
                    connection.execute(text("SELECT 1 FROM users"))
            return
        except Exception as exc:  # dependencies are expected to be briefly unavailable
            last_error = exc
            logger.warning("waiting for dependencies (attempt %s): %s", attempt + 1, exc)
            time.sleep(1)
    raise SystemExit(f"dependencies were not ready: {last_error}")


if __name__ == "__main__":
    import os

    from app.logging_config import configure_logging

    configure_logging(get_settings().log_level)
    wait_for_dependencies(require_schema=os.environ.get("RUN_MIGRATIONS", "").lower() != "true")
