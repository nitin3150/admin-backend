import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from admin.db.postgres import Base


def utcnow():
    return datetime.now(timezone.utc)


class Hub(Base):
    __tablename__ = "hubs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hub_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    city = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    warehouses = relationship("Warehouse", back_populates="hub", lazy="selectin")


class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    warehouse_id = Column(String(50), unique=True, nullable=False)
    hub_id = Column(
        UUID(as_uuid=True),
        ForeignKey("hubs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name = Column(String(100), nullable=False)
    address = Column(Text, nullable=False)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    hub = relationship("Hub", back_populates="warehouses", lazy="selectin")
    pincodes = relationship(
        "WarehousePincode", back_populates="warehouse", lazy="selectin", cascade="all, delete-orphan"
    )
    inventory = relationship("Inventory", back_populates="warehouse", lazy="noload")


class WarehousePincode(Base):
    __tablename__ = "warehouse_pincodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    warehouse_id = Column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="CASCADE"),
        nullable=False,
    )
    pincode = Column(String(10), nullable=False)
    priority = Column(Integer, nullable=False)

    warehouse = relationship("Warehouse", back_populates="pincodes")

    __table_args__ = (
        UniqueConstraint("warehouse_id", "pincode", name="uq_warehouse_pincode"),
        CheckConstraint("priority > 0", name="ck_priority_positive"),
        Index("ix_warehouse_pincodes_pincode", "pincode"),
    )
