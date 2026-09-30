"""Baseline: extensions the platform relies on.

Revision ID: 0001
Revises:
Create Date: 2026-09-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector for asset_embeddings (spec §5, ADR-009). Requires the pgvector-enabled Postgres image (M01).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
