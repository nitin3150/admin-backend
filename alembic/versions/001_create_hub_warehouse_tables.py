"""Create hub, warehouse, warehouse_pincodes tables

Revision ID: 001
Revises: None
Create Date: 2026-04-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Hubs
    op.create_table(
        "hubs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("hub_id", sa.String(50), unique=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Warehouses
    op.create_table(
        "warehouses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("warehouse_id", sa.String(50), unique=True, nullable=False),
        sa.Column("hub_id", UUID(as_uuid=True), sa.ForeignKey("hubs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("address", sa.Text, nullable=False),
        sa.Column("lat", sa.Float, nullable=True),
        sa.Column("lng", sa.Float, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Warehouse pincodes
    op.create_table(
        "warehouse_pincodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("warehouse_id", UUID(as_uuid=True), sa.ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pincode", sa.String(10), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.UniqueConstraint("warehouse_id", "pincode", name="uq_warehouse_pincode"),
        sa.CheckConstraint("priority > 0", name="ck_priority_positive"),
    )
    op.create_index("ix_warehouse_pincodes_pincode", "warehouse_pincodes", ["pincode"])


def downgrade() -> None:
    op.drop_index("ix_warehouse_pincodes_pincode")
    op.drop_table("warehouse_pincodes")
    op.drop_table("warehouses")
    op.drop_table("hubs")
