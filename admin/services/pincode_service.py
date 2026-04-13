from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.exceptions import PincodeNotServicedError
from admin.models.hub import Warehouse, WarehousePincode
from admin.models.inventory import Inventory


@dataclass
class WarehouseWithPriority:
    warehouse_id: UUID
    warehouse_str_id: str
    warehouse_name: str
    address: str
    priority: int
    available_qty: int = 0  # populated per-SKU when needed


async def get_warehouses_for_pincode(
    pincode: str,
    db: AsyncSession,
) -> list[WarehouseWithPriority]:
    """Return active warehouses serving *pincode*, ordered by priority ASC.

    Business rule: Only active warehouses are considered.
    Raises PincodeNotServicedError if no active warehouses serve this pincode.
    """
    stmt = (
        select(
            WarehousePincode.priority,
            Warehouse.id,
            Warehouse.warehouse_id,
            Warehouse.name,
            Warehouse.address,
        )
        .join(Warehouse, Warehouse.id == WarehousePincode.warehouse_id)
        .where(
            WarehousePincode.pincode == pincode,
            Warehouse.is_active.is_(True),
        )
        .order_by(WarehousePincode.priority.asc())
    )

    rows = (await db.execute(stmt)).all()

    if not rows:
        raise PincodeNotServicedError(pincode)

    return [
        WarehouseWithPriority(
            warehouse_id=r.id,
            warehouse_str_id=r.warehouse_id,
            warehouse_name=r.name,
            address=r.address,
            priority=r.priority,
        )
        for r in rows
    ]


async def get_warehouses_for_pincode_with_stock(
    pincode: str,
    sku_id: str,
    db: AsyncSession,
) -> list[WarehouseWithPriority]:
    """Return active warehouses for *pincode* with available stock for *sku_id*.

    Business rule: Sorted by priority ASC, then available_qty DESC (tiebreaker).
    """
    avail = (Inventory.qty - Inventory.reserved_qty).label("available_qty")

    stmt = (
        select(
            WarehousePincode.priority,
            Warehouse.id,
            Warehouse.warehouse_id,
            Warehouse.name,
            Warehouse.address,
            avail,
        )
        .join(Warehouse, Warehouse.id == WarehousePincode.warehouse_id)
        .outerjoin(
            Inventory,
            (Inventory.warehouse_id == Warehouse.id) & (Inventory.sku_id == sku_id),
        )
        .where(
            WarehousePincode.pincode == pincode,
            Warehouse.is_active.is_(True),
        )
        .order_by(WarehousePincode.priority.asc(), avail.desc())
    )

    rows = (await db.execute(stmt)).all()

    if not rows:
        raise PincodeNotServicedError(pincode)

    return [
        WarehouseWithPriority(
            warehouse_id=r.id,
            warehouse_str_id=r.warehouse_id,
            warehouse_name=r.name,
            address=r.address,
            priority=r.priority,
            available_qty=r.available_qty or 0,
        )
        for r in rows
    ]
