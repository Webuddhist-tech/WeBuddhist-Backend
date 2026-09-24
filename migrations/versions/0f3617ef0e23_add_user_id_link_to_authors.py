"""add user_id link to authors

Revision ID: 0f3617ef0e23
Revises: 2c2032c2abec
Create Date: 2026-09-08 18:45:03.833337

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migrations.idempotency import column_exists, fk_exists, index_exists


# revision identifiers, used by Alembic.
revision: str = '0f3617ef0e23'
down_revision: Union[str, None] = '2c2032c2abec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("authors", "user_id"):
        op.add_column(
            "authors",
            sa.Column("user_id", sa.UUID(as_uuid=True), nullable=True),
        )
    if not fk_exists("authors", "fk_authors_user_id"):
        op.create_foreign_key(
            "fk_authors_user_id",
            "authors",
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if not index_exists("authors", "uq_authors_user_id"):
        op.create_index(
            "uq_authors_user_id",
            "authors",
            ["user_id"],
            unique=True,
        )


def downgrade() -> None:
    if index_exists("authors", "uq_authors_user_id"):
        op.drop_index("uq_authors_user_id", table_name="authors")
    if fk_exists("authors", "fk_authors_user_id"):
        op.drop_constraint("fk_authors_user_id", "authors", type_="foreignkey")
    if column_exists("authors", "user_id"):
        op.drop_column("authors", "user_id")
