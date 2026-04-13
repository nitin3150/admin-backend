from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── Hub ──────────────────────────────────────────────────────────────

class HubCreate(BaseModel):
    hub_id: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    city: str = Field(..., max_length=100)


class HubUpdate(BaseModel):
    name: str | None = None
    city: str | None = None
    is_active: bool | None = None


class HubResponse(BaseModel):
    id: UUID
    hub_id: str
    name: str
    city: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    warehouse_count: int = 0

    model_config = {"from_attributes": True}


# ── Warehouse ────────────────────────────────────────────────────────

class WarehouseCreate(BaseModel):
    hub_id: str  # hub's hub_id (admin-facing string)
    name: str = Field(..., max_length=100)
    address: str
    lat: float | None = None
    lng: float | None = None


class WarehouseUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    is_active: bool | None = None


class WarehouseResponse(BaseModel):
    id: UUID
    warehouse_id: str
    hub_id: UUID
    hub_name: str = ""
    name: str
    address: str
    lat: float | None = None
    lng: float | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    pincode_count: int = 0

    model_config = {"from_attributes": True}


# ── Warehouse Pincode ────────────────────────────────────────────────

class PincodeAssignment(BaseModel):
    pincode: str = Field(..., max_length=10)
    priority: int = Field(..., gt=0)


class PincodeAssignmentBulk(BaseModel):
    pincodes: list[PincodeAssignment]


class PincodeUpdatePriority(BaseModel):
    priority: int = Field(..., gt=0)


class WarehousePincodeResponse(BaseModel):
    id: UUID
    warehouse_id: UUID
    pincode: str
    priority: int

    model_config = {"from_attributes": True}
