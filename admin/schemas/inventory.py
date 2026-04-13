from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── Inventory ────────────────────────────────────────────────────────

class InventoryAggregated(BaseModel):
    sku_id: str
    available_qty: int


class InventoryRow(BaseModel):
    id: UUID
    warehouse_id: UUID
    warehouse_name: str = ""
    sku_id: str
    qty: int
    reserved_qty: int
    available_qty: int = 0
    reorder_threshold: int
    last_updated: datetime

    model_config = {"from_attributes": True}


class RestockRequest(BaseModel):
    warehouse_id: str  # warehouse_id string (e.g. WH-MAINST...)
    sku_id: str = Field(..., max_length=100)
    qty: int = Field(..., gt=0)
    reference_id: str = Field(..., max_length=100)


# ── Order reservation ───────────────────────────────────────────────

class OrderItem(BaseModel):
    sku_id: str
    qty: int = Field(..., gt=0)


class ReserveRequest(BaseModel):
    order_id: str
    pincode: str
    items: list[OrderItem]


class OrderLineSplitResponse(BaseModel):
    id: UUID
    order_id: str
    warehouse_id: UUID
    warehouse_name: str = ""
    sku_id: str
    qty: int
    priority_used: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Pick list ────────────────────────────────────────────────────────

class PickListItem(BaseModel):
    sku_id: str
    qty: int
    status: str


class PickListWarehouse(BaseModel):
    priority: int
    warehouse_id: str
    warehouse_name: str
    address: str
    items: list[PickListItem]


class PickList(BaseModel):
    order_id: str
    total_warehouses: int
    warehouses: list[PickListWarehouse]


# ── Audit ────────────────────────────────────────────────────────────

class AuditRow(BaseModel):
    id: UUID
    warehouse_id: UUID
    warehouse_name: str = ""
    sku_id: str
    delta: int
    reason: str
    reference_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Low-stock ────────────────────────────────────────────────────────

class LowStockRow(BaseModel):
    warehouse_id: UUID
    warehouse_name: str = ""
    sku_id: str
    qty: int
    reserved_qty: int
    available_qty: int
    reorder_threshold: int

    model_config = {"from_attributes": True}
