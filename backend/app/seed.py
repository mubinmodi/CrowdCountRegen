"""Creates the demo account and its scenario cameras on sample videos. For local development.

    uv run python -m app.seed

Same as `python -m app.demo`: downloads and trims the scenario clips into
ZW_DEMO_VIDEO_DIR (default data/demo-videos) if they aren't there yet. Sign in as
demo@example.com / demo-password (or ZW_DEMO_PASSWORD), or run the API with
ZW_DEMO_MODE=true to skip the login entirely.
"""

import logging

from app.config import get_settings
from app.db import init_db
from app.demo import DEMO_EMAIL, SCENARIOS, seed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    seed(get_settings())
    print(f"Demo account ready: {DEMO_EMAIL} with {len(SCENARIOS)} scenario cameras")
    print("Restart the API server if it is running so it picks up the new cameras.")


if __name__ == "__main__":
    main()
