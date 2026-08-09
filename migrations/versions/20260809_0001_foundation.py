"""Create the M01 database foundation.

Revision ID: 20260809_0001
Revises:
Create Date: 2026-08-09
"""


revision: str = "20260809_0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Reserve the initial schema revision without introducing M02 tables."""


def downgrade() -> None:
    """The foundation revision has no application tables to remove."""
