import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from admin.db.postgres import Base


def utcnow():
    return datetime.now(timezone.utc)


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    warehouse_id = Column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sku_id = Column(String(100), nullable=False)
    qty = Column(Integer, default=0, nullable=False)
    reserved_qty = Column(Integer, default=0, nullable=False)
    reorder_threshold = Column(Integer, default=10, nullable=False)
    last_updated = Column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    warehouse = relationship("Warehouse", back_populates="inventory", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("warehouse_id", "sku_id", name="uq_warehouse_sku"),
        CheckConstraint("qty >= 0", name="ck_qty_non_negative"),
        CheckConstraint("reserved_qty >= 0", name="ck_reserved_qty_non_negative"),
        CheckConstraint("reserved_qty <= qty", name="ck_reserved_lte_qty"),
        Index("ix_inventory_warehouse_sku", "warehouse_id", "sku_id"),
    )


class OrderLineSplit(Base):
    __tablename__ = "order_line_splits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(String(100), nullable=False)
    warehouse_id = Column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sku_id = Column(String(100), nullable=False)
    qty = Column(Integer, nullable=False)
    priority_used = Column(Integer, nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    warehouse = relationship("Warehouse", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'picked', 'delivered', 'cancelled')",
            name="ck_split_status",
        ),
        Index("ix_order_line_splits_order_id", "order_id"),
    )


class InventoryAudit(Base):
    __tablename__ = "inventory_audit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    warehouse_id = Column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id"),
        nullable=False,
    )
    sku_id = Column(String(100), nullable=False)
    delta = Column(Integer, nullable=False)
    reason = Column(String(30), nullable=False)
    reference_id = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    warehouse = relationship("Warehouse", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "reason IN ('order_reserved', 'order_delivered', 'order_cancelled', "
            "'manual_restock', 'manual_adjustment')",
            name="ck_audit_reason",
        ),
        Index("ix_inventory_audit_wh_sku_ts", "warehouse_id", "sku_id", "created_at"),
    )
