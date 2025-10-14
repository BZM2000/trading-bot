"""Rename run kind enum values to plan/order/monitor/pnl."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20251020_0006"
down_revision = "20251005_0005"
branch_labels = None
depends_on = None


RENAME_MAP = (
    ("daily", "plan"),
    ("2h", "order"),
    ("5m", "monitor"),
    ("manual", "pnl"),
)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        for old_value, new_value in RENAME_MAP:
            statement = sa.text(
                f"ALTER TYPE run_kind RENAME VALUE '{old_value}' TO '{new_value}'"
            )
            op.execute(statement)
    else:
        for old_value, new_value in RENAME_MAP:
            stmt = sa.text("UPDATE run_logs SET kind = :new WHERE kind = :old").bindparams(
                old=old_value, new=new_value
            )
            op.execute(stmt)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        for old_value, new_value in reversed(RENAME_MAP):
            statement = sa.text(
                f"ALTER TYPE run_kind RENAME VALUE '{new_value}' TO '{old_value}'"
            )
            op.execute(statement)
    else:
        for old_value, new_value in reversed(RENAME_MAP):
            stmt = sa.text("UPDATE run_logs SET kind = :old WHERE kind = :new").bindparams(
                old=old_value, new=new_value
            )
            op.execute(stmt)
