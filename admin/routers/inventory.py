"""REST API router for inventory operations (user, agent, internal, admin)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.db.postgres import get_pg_db
from admin.exceptions import InsufficientStockError, WarehouseNotFoundError
from admin.models.hub import Warehouse
from admin.models.inventory import Inventory, InventoryAudit
from admin.schemas.inventory import (
    OrderItem,
    ReserveRequest,
    RestockRequest,
)
from admin.services.inventory_service import (
    cancel_reservation,
    confirm_delivery,
    get_audit_log,
    get_available_inventory,
    get_low_stock,
    get_pick_list,
    reserve_inventory,
    restock_warehouse,
)

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


# ── User-facing ──────────────────────────────────────────────────────

@router.get("/available")
async def available_inventory(
    pincode: str = Query(...),
    db: AsyncSession = Depends(get_pg_db),
):
    """Aggregated inventory across all warehouses for the pincode."""
    items = await get_available_inventory(pincode=pincode, db=db)
    return [{"sku_id": i.sku_id, "available_qty": i.available_qty} for i in items]


@router.get("/available/{sku_id}")
async def available_inventory_for_sku(
    sku_id: str,
    pincode: str = Query(...),
    db: AsyncSession = Depends(get_pg_db),
):
    """Available qty for a single SKU at a pincode. Returns 0 if not found."""
    items = await get_available_inventory(pincode=pincode, db=db, sku_ids=[sku_id])
    for i in items:
        if i.sku_id == sku_id:
            return {"sku_id": sku_id, "available_qty": i.available_qty}
    return {"sku_id": sku_id, "available_qty": 0}


# ── Agent-facing ─────────────────────────────────────────────────────

@router.get("/pick-list/{order_id}")
async def pick_list(order_id: str, db: AsyncSession = Depends(get_pg_db)):
    """Grouped warehouse pick list for a delivery agent."""
    pl = await get_pick_list(order_id=order_id, db=db)
    if pl is None:
        return {"error": "ORDER_NOT_FOUND", "detail": {"order_id": order_id}}, 404
    return pl.model_dump()


@router.post("/confirm-delivery/{order_id}")
async def confirm_delivery_endpoint(
    order_id: str, db: AsyncSession = Depends(get_pg_db)
):
    """Mark an order as delivered — deducts actual stock."""
    ok = await confirm_delivery(order_id=order_id, db=db)
    if not ok:
        return {"error": "ORDER_NOT_FOUND", "detail": {"order_id": order_id}}, 404
    return {"success": True}


# ── Internal (order service calls on checkout) ───────────────────────

@router.post("/reserve", status_code=201)
async def reserve(body: ReserveRequest, db: AsyncSession = Depends(get_pg_db)):
    """Priority-based inventory reservation for an order."""
    splits = await reserve_inventory(
        order_id=body.order_id,
        pincode=body.pincode,
        items=body.items,
        db=db,
    )
    return [
        {
            "id": str(s.id),
            "order_id": s.order_id,
            "warehouse_id": str(s.warehouse_id),
            "sku_id": s.sku_id,
            "qty": s.qty,
            "priority_used": s.priority_used,
            "status": s.status,
        }
        for s in splits
    ]


@router.post("/cancel/{order_id}")
async def cancel(order_id: str, db: AsyncSession = Depends(get_pg_db)):
    """Cancel an order reservation — releases reserved stock."""
    ok = await cancel_reservation(order_id=order_id, db=db)
    if not ok:
        return {"error": "ORDER_NOT_FOUND", "detail": {"order_id": order_id}}, 404
    return {"success": True}


# ── Admin ────────────────────────────────────────────────────────────

@router.post("/restock")
async def restock(body: RestockRequest, db: AsyncSession = Depends(get_pg_db)):
    """UPSERT inventory with restock quantity."""
    inv = await restock_warehouse(
        warehouse_id=body.warehouse_id,
        sku_id=body.sku_id,
        qty=body.qty,
        reference_id=body.reference_id,
        db=db,
    )
    wh = (
        await db.execute(select(Warehouse).where(Warehouse.id == inv.warehouse_id))
    ).scalar_one_or_none()
    return {
        "id": str(inv.id),
        "warehouse_id": wh.warehouse_id if wh else str(inv.warehouse_id),
        "sku_id": inv.sku_id,
        "qty": inv.qty,
        "reserved_qty": inv.reserved_qty,
        "available_qty": inv.qty - inv.reserved_qty,
    }


@router.get("/audit/{warehouse_id}")
async def audit(
    warehouse_id: str,
    sku_id: str | None = Query(None),
    reason: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_pg_db),
):
    """Paginated audit log for a warehouse."""
    rows = await get_audit_log(
        warehouse_id=warehouse_id,
        db=db,
        sku_id=sku_id,
        reason=reason,
        limit=limit,
        offset=offset,
    )
    return [
        {
            "id": str(a.id),
            "sku_id": a.sku_id,
            "delta": a.delta,
            "reason": a.reason,
            "reference_id": a.reference_id,
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


@router.get("/low-stock")
async def low_stock(
    warehouse_id: str | None = Query(None),
    threshold: int | None = Query(None),
    db: AsyncSession = Depends(get_pg_db),
):
    """Inventory rows where available stock is at or below reorder threshold."""
    rows = await get_low_stock(db=db, warehouse_id=warehouse_id, threshold=threshold)
    wh_ids = list({r.warehouse_id for r in rows})
    wh_map = {}
    if wh_ids:
        whs = (await db.execute(select(Warehouse).where(Warehouse.id.in_(wh_ids)))).scalars().all()
        wh_map = {w.id: w for w in whs}

    return [
        {
            "warehouse_id": wh_map[r.warehouse_id].warehouse_id if r.warehouse_id in wh_map else str(r.warehouse_id),
            "warehouse_name": wh_map[r.warehouse_id].name if r.warehouse_id in wh_map else "",
            "sku_id": r.sku_id,
            "qty": r.qty,
            "reserved_qty": r.reserved_qty,
            "available_qty": r.qty - r.reserved_qty,
            "reorder_threshold": r.reorder_threshold,
        }
        for r in rows
    ]
