"""Run the isolated migration job for every authorized tenant."""

from __future__ import annotations

import asyncio
import logging

from platform_database.migration import migrate_all_tenants

from app.core.config import settings


async def migrate() -> None:
    await migrate_all_tenants(settings, "platform-project-product")


def main() -> None:
    logging.basicConfig(level=settings.LOG_LEVEL)
    asyncio.run(migrate())


if __name__ == "__main__":
    main()
