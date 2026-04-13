"""Create inventory, order_line_splits, inventory_audit tables

Revision ID: 002
Revises: 001
Create Date: 2026-04-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Inventory
    op.create_table(
        "inventory",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("warehouse_id", UUID(as_uuid=True), sa.ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sku_id", sa.String(100), nullable=False),
        sa.Column("qty", sa.Integer, server_default="0", nullable=False),
        sa.Column("reserved_qty", sa.Integer, server_default="0", nullable=False),
        sa.Column("reorder_threshold", sa.Integer, server_default="10", nullable=False),
        sa.Column("last_updated", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("warehouse_id", "sku_id", name="uq_warehouse_sku"),
        sa.CheckConstraint("qty >= 0", name="ck_qty_non_negative"),
        sa.CheckConstraint("reserved_qty >= 0", name="ck_reserved_qty_non_negative"),
        sa.CheckConstraint("reserved_qty <= qty", name="ck_reserved_lte_qty"),
    )
    op.create_index("ix_inventory_warehouse_sku", "inventory", ["warehouse_id", "sku_id"])

    # Order line splits
    op.create_table(
        "order_line_splits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", sa.String(100), nullable=False),
        sa.Column("warehouse_id", UUID(as_uuid=True), sa.ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sku_id", sa.String(100), nullable=False),
        sa.Column("qty", sa.Integer, nullable=False),
        sa.Column("priority_used", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'picked', 'delivered', 'cancelled')",
            name="ck_split_status",
        ),
    )
    op.create_index("ix_order_line_splits_order_id", "order_line_splits", ["order_id"])

    # Inventory audit
    op.create_table(
        "inventory_audit",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("warehouse_id", UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("sku_id", sa.String(100), nullable=False),
        sa.Column("delta", sa.Integer, nullable=False),
        sa.Column("reason", sa.String(30), nullable=False),
        sa.Column("reference_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "reason IN ('order_reserved', 'order_delivered', 'order_cancelled', "
            "'manual_restock', 'manual_adjustment')",
            name="ck_audit_reason",
        ),
    )
    op.create_index(
        "ix_inventory_audit_wh_sku_ts",
        "inventory_audit",
        ["warehouse_id", "sku_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_audit_wh_sku_ts")
    op.drop_table("inventory_audit")
    op.drop_index("ix_order_line_splits_order_id")
    op.drop_table("order_line_splits")
    op.drop_index("ix_inventory_warehouse_sku")
    op.drop_table("inventory")
