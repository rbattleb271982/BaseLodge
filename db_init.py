"""Retired unsafe database initializer.

This legacy command previously imported the application and mutated user data.
Database schema changes must use the guarded Alembic path, while data operations
must use their dedicated explicitly authorized tools.
"""

from __future__ import annotations

import sys


RETIRED_MESSAGE = (
    "db_init.py is retired and cannot access a database. "
    "Use the guarded Alembic migration path for schema changes or an "
    "explicitly authorized maintenance tool for data operations."
)


def init_database() -> None:
    """Fail closed without importing the application or opening a database."""
    raise RuntimeError(RETIRED_MESSAGE)


def main() -> int:
    print(RETIRED_MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
