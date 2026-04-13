import uuid
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from admin.exceptions import (
    InsufficientStockError,
    OrderAlreadyProcessedError,
    WarehouseNotFoundError,
)
from admin.models.hub import Warehouse
from admin.models.inventory import Inventory, InventoryAudit, OrderLineSplit
from admin.schemas.inventory import (
    AuditRow,
    InventoryAggregated,
    OrderItem,
    PickList,
    PickListItem,
    PickListWarehouse,
)
from admin.services.pincode_service import get_warehouses_for_pincode_with_stock


async def get_available_inventory(
    pincode: str,
    db: AsyncSession,
    sku_ids: list[str] | None = None,
) -> list[InventoryAggregated]:
    """Aggregate inventory across all warehouses serving the pincode.

    Business rule: Users see SUM(qty - reserved_qty) per sku_id, never
    per-warehouse detail.  Only SKUs with available_qty > 0 are returned.
    """
    from admin.models.hub import WarehousePincode

    avail = (Inventory.qty - Inventory.reserved_qty).label("available_qty")

    stmt = (
        select(
            Inventory.sku_id,
            func.sum(avail).label("total_available"),
        )
        .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
        .join(
            WarehousePincode,
            (WarehousePincode.warehouse_id == Warehouse.id),
        )
        .where(
            WarehousePincode.pincode == pincode,
            Warehouse.is_active.is_(True),
        )
        .group_by(Inventory.sku_id)
        .having(func.sum(avail) > 0)
    )

    if sku_ids:
        stmt = stmt.where(Inventory.sku_id.in_(sku_ids))

    rows = (await db.execute(stmt)).all()

    return [
        InventoryAggregated(sku_id=r.sku_id, available_qty=r.total_available)
        for r in rows
    ]


async def reserve_inventory(
    order_id: str,
    pincode: str,
    items: list[OrderItem],
    db: AsyncSession,
) -> list[OrderLineSplit]:
    """Priority-based greedy allocation across warehouses for an order.

    Business rules:
    - Warehouses sorted by priority ASC, available stock DESC for ties.
    - All inventory rows locked with SELECT FOR UPDATE to prevent races.
    - On any SKU shortfall the entire transaction rolls back.
    - Creates order_line_splits + inventory_audit rows atomically.
    """
    async with db.begin():
        all_splits: list[OrderLineSplit] = []

        for item in items:
            wh_list = await get_warehouses_for_pincode_with_stock(
                pincode, item.sku_id, db
            )

            # Lock inventory rows for this SKU across relevant warehouses
            wh_ids = [w.warehouse_id for w in wh_list]
            lock_stmt = (
                select(Inventory)
                .where(
                    Inventory.warehouse_id.in_(wh_ids),
                    Inventory.sku_id == item.sku_id,
                )
                .with_for_update()
            )
            inv_rows = {
                r.warehouse_id: r for r in (await db.execute(lock_stmt)).scalars().all()
            }

            remaining = item.qty

            for wh in wh_list:
                if remaining <= 0:
                    break

                inv = inv_rows.get(wh.warehouse_id)
                if inv is None:
                    continue

                available = inv.qty - inv.reserved_qty
                if available <= 0:
                    continue

                allocate = min(available, remaining)
                inv.reserved_qty += allocate
                remaining -= allocate

                split = OrderLineSplit(
                    id=uuid.uuid4(),
                    order_id=order_id,
                    warehouse_id=wh.warehouse_id,
                    sku_id=item.sku_id,
                    qty=allocate,
                    priority_used=wh.priority,
                    status="pending",
                )
                db.add(split)

                audit = InventoryAudit(
                    id=uuid.uuid4(),
                    warehouse_id=wh.warehouse_id,
                    sku_id=item.sku_id,
                    delta=-allocate,
                    reason="order_reserved",
                    reference_id=order_id,
                )
                db.add(audit)

                all_splits.append(split)

            if remaining > 0:
                total_available = sum(
                    (inv_rows[w.warehouse_id].qty - inv_rows[w.warehouse_id].reserved_qty + (item.qty - remaining))
                    if w.warehouse_id in inv_rows
                    else 0
                    for w in wh_list
                )
                raise InsufficientStockError(
                    sku_id=item.sku_id,
                    requested=item.qty,
                    available=item.qty - remaining,
                )

        await db.flush()
        return all_splits


async def confirm_delivery(
    order_id: str,
    db: AsyncSession,
) -> bool:
    """Deduct actual stock when delivery agent marks order delivered.

    Business rules:
    - Only pending splits are processed.
    - qty and reserved_qty both decrease by split.qty.
    - Audit trail with reason='order_delivered'.
    - Single transaction — all or nothing.
    """
    async with db.begin():
        splits_stmt = (
            select(OrderLineSplit)
            .where(
                OrderLineSplit.order_id == order_id,
                OrderLineSplit.status == "pending",
            )
            .with_for_update()
        )
        splits = (await db.execute(splits_stmt)).scalars().all()

        if not splits:
            return False

        wh_ids = list({s.warehouse_id for s in splits})
        sku_ids = list({s.sku_id for s in splits})

        inv_stmt = (
            select(Inventory)
            .where(
                Inventory.warehouse_id.in_(wh_ids),
                Inventory.sku_id.in_(sku_ids),
            )
            .with_for_update()
        )
        inv_map = {}
        for inv in (await db.execute(inv_stmt)).scalars().all():
            inv_map[(inv.warehouse_id, inv.sku_id)] = inv

        for split in splits:
            inv = inv_map.get((split.warehouse_id, split.sku_id))
            if inv is None:
                continue

            inv.qty -= split.qty
            inv.reserved_qty -= split.qty
            split.status = "delivered"

            db.add(
                InventoryAudit(
                    id=uuid.uuid4(),
                    warehouse_id=split.warehouse_id,
                    sku_id=split.sku_id,
                    delta=-split.qty,
                    reason="order_delivered",
                    reference_id=order_id,
                )
            )

        await db.flush()
        return True


async def cancel_reservation(
    order_id: str,
    db: AsyncSession,
) -> bool:
    """Release reserved stock when an order is cancelled before delivery.

    Business rules:
    - Only pending splits are cancelled.
    - reserved_qty decreases; qty stays unchanged (items never left warehouse).
    - Audit trail with reason='order_cancelled', delta=+qty (restoring).
    """
    async with db.begin():
        splits_stmt = (
            select(OrderLineSplit)
            .where(
                OrderLineSplit.order_id == order_id,
                OrderLineSplit.status == "pending",
            )
            .with_for_update()
        )
        splits = (await db.execute(splits_stmt)).scalars().all()

        if not splits:
            return False

        wh_ids = list({s.warehouse_id for s in splits})
        sku_ids = list({s.sku_id for s in splits})

        inv_stmt = (
            select(Inventory)
            .where(
                Inventory.warehouse_id.in_(wh_ids),
                Inventory.sku_id.in_(sku_ids),
            )
            .with_for_update()
        )
        inv_map = {}
        for inv in (await db.execute(inv_stmt)).scalars().all():
            inv_map[(inv.warehouse_id, inv.sku_id)] = inv

        for split in splits:
            inv = inv_map.get((split.warehouse_id, split.sku_id))
            if inv is None:
                continue

            inv.reserved_qty -= split.qty
            split.status = "cancelled"

            db.add(
                InventoryAudit(
                    id=uuid.uuid4(),
                    warehouse_id=split.warehouse_id,
                    sku_id=split.sku_id,
                    delta=+split.qty,
                    reason="order_cancelled",
                    reference_id=order_id,
                )
            )

        await db.flush()
        return True


async def restock_warehouse(
    warehouse_id: str,
    sku_id: str,
    qty: int,
    reference_id: str,
    db: AsyncSession,
) -> Inventory:
    """UPSERT inventory: increment qty if row exists, create if not.

    Business rule: Every restock produces an audit row for traceability.
    """
    # Resolve warehouse by its string id
    wh = (
        await db.execute(
            select(Warehouse).where(Warehouse.warehouse_id == warehouse_id)
        )
    ).scalar_one_or_none()

    if wh is None:
        raise WarehouseNotFoundError(warehouse_id)

    async with db.begin():
        inv_stmt = (
            select(Inventory)
            .where(
                Inventory.warehouse_id == wh.id,
                Inventory.sku_id == sku_id,
            )
            .with_for_update()
        )
        inv = (await db.execute(inv_stmt)).scalar_one_or_none()

        if inv is None:
            inv = Inventory(
                id=uuid.uuid4(),
                warehouse_id=wh.id,
                sku_id=sku_id,
                qty=qty,
                reserved_qty=0,
            )
            db.add(inv)
        else:
            inv.qty += qty

        db.add(
            InventoryAudit(
                id=uuid.uuid4(),
                warehouse_id=wh.id,
                sku_id=sku_id,
                delta=+qty,
                reason="manual_restock",
                reference_id=reference_id,
            )
        )

        await db.flush()
        await db.refresh(inv)
        return inv


async def get_pick_list(
    order_id: str,
    db: AsyncSession,
) -> PickList | None:
    """Return order_line_splits grouped by warehouse, ordered by priority.

    Business rule: Delivery agent visits warehouses in priority order —
    priority 1 first, then 2, etc.
    """
    stmt = (
        select(OrderLineSplit)
        .where(OrderLineSplit.order_id == order_id)
        .order_by(OrderLineSplit.priority_used.asc())
    )
    splits = (await db.execute(stmt)).scalars().all()

    if not splits:
        return None

    # Load warehouse info
    wh_ids = list({s.warehouse_id for s in splits})
    wh_stmt = select(Warehouse).where(Warehouse.id.in_(wh_ids))
    wh_map = {
        w.id: w for w in (await db.execute(wh_stmt)).scalars().all()
    }

    # Group by warehouse
    grouped: dict[UUID, PickListWarehouse] = {}
    for s in splits:
        wh = wh_map.get(s.warehouse_id)
        if s.warehouse_id not in grouped:
            grouped[s.warehouse_id] = PickListWarehouse(
                priority=s.priority_used,
                warehouse_id=wh.warehouse_id if wh else str(s.warehouse_id),
                warehouse_name=wh.name if wh else "",
                address=wh.address if wh else "",
                items=[],
            )
        grouped[s.warehouse_id].items.append(
            PickListItem(sku_id=s.sku_id, qty=s.qty, status=s.status)
        )

    warehouses = sorted(grouped.values(), key=lambda w: w.priority)

    return PickList(
        order_id=order_id,
        total_warehouses=len(warehouses),
        warehouses=warehouses,
    )


async def get_audit_log(
    warehouse_id: str,
    db: AsyncSession,
    sku_id: str | None = None,
    reason: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[InventoryAudit]:
    """Return paginated audit rows for a warehouse."""
    wh = (
        await db.execute(
            select(Warehouse).where(Warehouse.warehouse_id == warehouse_id)
        )
    ).scalar_one_or_none()

    if wh is None:
        raise WarehouseNotFoundError(warehouse_id)

    stmt = (
        select(InventoryAudit)
        .where(InventoryAudit.warehouse_id == wh.id)
        .order_by(InventoryAudit.created_at.desc())
    )

    if sku_id:
        stmt = stmt.where(InventoryAudit.sku_id == sku_id)
    if reason:
        stmt = stmt.where(InventoryAudit.reason == reason)

    stmt = stmt.offset(offset).limit(limit)

    return (await db.execute(stmt)).scalars().all()


async def get_low_stock(
    db: AsyncSession,
    warehouse_id: str | None = None,
    threshold: int | None = None,
) -> list[Inventory]:
    """Return inventory rows where available stock is at or below reorder threshold."""
    avail = (Inventory.qty - Inventory.reserved_qty).label("available_qty")

    stmt = select(Inventory)

    if warehouse_id:
        wh = (
            await db.execute(
                select(Warehouse).where(Warehouse.warehouse_id == warehouse_id)
            )
        ).scalar_one_or_none()
        if wh is None:
            raise WarehouseNotFoundError(warehouse_id)
        stmt = stmt.where(Inventory.warehouse_id == wh.id)

    if threshold is not None:
        stmt = stmt.where((Inventory.qty - Inventory.reserved_qty) <= threshold)
    else:
        stmt = stmt.where(
            (Inventory.qty - Inventory.reserved_qty) <= Inventory.reorder_threshold
        )

    return (await db.execute(stmt)).scalars().all()
