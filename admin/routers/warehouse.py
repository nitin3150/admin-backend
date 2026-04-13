"""REST API router for hub and warehouse management."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.db.postgres import get_pg_db
from admin.exceptions import DuplicatePriorityError, WarehouseNotFoundError
from admin.models.hub import Hub, Warehouse, WarehousePincode
from admin.schemas.hub import (
    HubCreate,
    HubResponse,
    HubUpdate,
    PincodeAssignment,
    PincodeAssignmentBulk,
    PincodeUpdatePriority,
    WarehouseCreate,
    WarehousePincodeResponse,
    WarehouseResponse,
    WarehouseUpdate,
)
from admin.utils.id_generator import id_generator

router = APIRouter(prefix="/api/v1/warehouses", tags=["warehouses"])


# ── Hub endpoints ────────────────────────────────────────────────────

@router.post("/hubs", response_model=dict, status_code=201)
async def create_hub(body: HubCreate, db: AsyncSession = Depends(get_pg_db)):
    hub = Hub(hub_id=body.hub_id, name=body.name, city=body.city)
    db.add(hub)
    await db.commit()
    await db.refresh(hub)
    return {
        "id": str(hub.id),
        "hub_id": hub.hub_id,
        "name": hub.name,
        "city": hub.city,
        "is_active": hub.is_active,
    }


@router.get("/hubs")
async def list_hubs(db: AsyncSession = Depends(get_pg_db)):
    hubs = (await db.execute(select(Hub).order_by(Hub.created_at.desc()))).scalars().all()
    result = []
    for h in hubs:
        wh_count = (await db.execute(select(func.count()).where(Warehouse.hub_id == h.id))).scalar()
        result.append({
            "id": str(h.id),
            "hub_id": h.hub_id,
            "name": h.name,
            "city": h.city,
            "is_active": h.is_active,
            "warehouse_count": wh_count or 0,
        })
    return result


# ── Warehouse endpoints ──────────────────────────────────────────────

@router.get("/")
async def list_warehouses(db: AsyncSession = Depends(get_pg_db)):
    warehouses = (
        await db.execute(select(Warehouse).order_by(Warehouse.created_at.desc()))
    ).scalars().all()
    result = []
    for w in warehouses:
        pc_count = (
            await db.execute(select(func.count()).where(WarehousePincode.warehouse_id == w.id))
        ).scalar()
        hub = (await db.execute(select(Hub).where(Hub.id == w.hub_id))).scalar_one_or_none()
        result.append({
            "id": str(w.id),
            "warehouse_id": w.warehouse_id,
            "hub_id": str(w.hub_id),
            "hub_name": hub.name if hub else "",
            "name": w.name,
            "address": w.address,
            "lat": w.lat,
            "lng": w.lng,
            "is_active": w.is_active,
            "pincode_count": pc_count or 0,
        })
    return result


@router.get("/hub/{hub_id}")
async def list_warehouses_by_hub(hub_id: str, db: AsyncSession = Depends(get_pg_db)):
    hub = (await db.execute(select(Hub).where(Hub.hub_id == hub_id))).scalar_one_or_none()
    if not hub:
        raise WarehouseNotFoundError(hub_id)
    warehouses = (
        await db.execute(select(Warehouse).where(Warehouse.hub_id == hub.id))
    ).scalars().all()
    return [
        {
            "id": str(w.id),
            "warehouse_id": w.warehouse_id,
            "name": w.name,
            "address": w.address,
            "is_active": w.is_active,
        }
        for w in warehouses
    ]


@router.get("/{warehouse_id}")
async def get_warehouse(warehouse_id: str, db: AsyncSession = Depends(get_pg_db)):
    wh = (
        await db.execute(select(Warehouse).where(Warehouse.warehouse_id == warehouse_id))
    ).scalar_one_or_none()
    if not wh:
        raise WarehouseNotFoundError(warehouse_id)

    pincodes = (
        await db.execute(
            select(WarehousePincode)
            .where(WarehousePincode.warehouse_id == wh.id)
            .order_by(WarehousePincode.priority.asc())
        )
    ).scalars().all()
    hub = (await db.execute(select(Hub).where(Hub.id == wh.hub_id))).scalar_one_or_none()

    return {
        "id": str(wh.id),
        "warehouse_id": wh.warehouse_id,
        "hub_id": str(wh.hub_id),
        "hub_name": hub.name if hub else "",
        "name": wh.name,
        "address": wh.address,
        "lat": wh.lat,
        "lng": wh.lng,
        "is_active": wh.is_active,
        "pincodes": [
            {"pincode": p.pincode, "priority": p.priority} for p in pincodes
        ],
    }


@router.post("/", status_code=201)
async def create_warehouse_endpoint(body: WarehouseCreate, db: AsyncSession = Depends(get_pg_db)):
    hub = (await db.execute(select(Hub).where(Hub.hub_id == body.hub_id))).scalar_one_or_none()
    if not hub:
        raise WarehouseNotFoundError(body.hub_id)

    wh_id = await id_generator.generate_warehouse_id(body.name)
    wh = Warehouse(
        warehouse_id=wh_id,
        hub_id=hub.id,
        name=body.name,
        address=body.address,
        lat=body.lat,
        lng=body.lng,
    )
    db.add(wh)
    await db.commit()
    await db.refresh(wh)
    return {
        "id": str(wh.id),
        "warehouse_id": wh.warehouse_id,
        "hub_id": str(wh.hub_id),
        "name": wh.name,
        "address": wh.address,
        "is_active": wh.is_active,
    }


@router.put("/{warehouse_id}")
async def update_warehouse_endpoint(
    warehouse_id: str, body: WarehouseUpdate, db: AsyncSession = Depends(get_pg_db)
):
    wh = (
        await db.execute(select(Warehouse).where(Warehouse.warehouse_id == warehouse_id))
    ).scalar_one_or_none()
    if not wh:
        raise WarehouseNotFoundError(warehouse_id)

    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(wh, field, val)
    await db.commit()
    return {"success": True, "warehouse_id": warehouse_id}


# ── Pincode management ───────────────────────────────────────────────

@router.post("/{warehouse_id}/pincodes")
async def assign_pincodes(
    warehouse_id: str, body: PincodeAssignmentBulk, db: AsyncSession = Depends(get_pg_db)
):
    wh = (
        await db.execute(select(Warehouse).where(Warehouse.warehouse_id == warehouse_id))
    ).scalar_one_or_none()
    if not wh:
        raise WarehouseNotFoundError(warehouse_id)

    for pc in body.pincodes:
        # Check duplicate priority under same hub
        conflict = (
            await db.execute(
                select(WarehousePincode)
                .join(Warehouse, Warehouse.id == WarehousePincode.warehouse_id)
                .where(
                    Warehouse.hub_id == wh.hub_id,
                    Warehouse.id != wh.id,
                    WarehousePincode.pincode == pc.pincode,
                    WarehousePincode.priority == pc.priority,
                )
            )
        ).scalar_one_or_none()

        if conflict:
            conflict_wh = (
                await db.execute(select(Warehouse).where(Warehouse.id == conflict.warehouse_id))
            ).scalar_one()
            raise DuplicatePriorityError(pc.pincode, pc.priority, conflict_wh.warehouse_id)

        existing = (
            await db.execute(
                select(WarehousePincode).where(
                    WarehousePincode.warehouse_id == wh.id,
                    WarehousePincode.pincode == pc.pincode,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.priority = pc.priority
        else:
            db.add(WarehousePincode(warehouse_id=wh.id, pincode=pc.pincode, priority=pc.priority))

    await db.commit()
    return {"success": True}


@router.put("/{warehouse_id}/pincodes/{pincode}")
async def update_pincode_priority(
    warehouse_id: str,
    pincode: str,
    body: PincodeUpdatePriority,
    db: AsyncSession = Depends(get_pg_db),
):
    wh = (
        await db.execute(select(Warehouse).where(Warehouse.warehouse_id == warehouse_id))
    ).scalar_one_or_none()
    if not wh:
        raise WarehouseNotFoundError(warehouse_id)

    mapping = (
        await db.execute(
            select(WarehousePincode).where(
                WarehousePincode.warehouse_id == wh.id,
                WarehousePincode.pincode == pincode,
            )
        )
    ).scalar_one_or_none()

    if not mapping:
        raise WarehouseNotFoundError(f"{warehouse_id}/pincode/{pincode}")

    mapping.priority = body.priority
    await db.commit()
    return {"success": True}


@router.delete("/{warehouse_id}/pincodes/{pincode}")
async def remove_pincode(
    warehouse_id: str, pincode: str, db: AsyncSession = Depends(get_pg_db)
):
    wh = (
        await db.execute(select(Warehouse).where(Warehouse.warehouse_id == warehouse_id))
    ).scalar_one_or_none()
    if not wh:
        raise WarehouseNotFoundError(warehouse_id)

    await db.execute(
        delete(WarehousePincode).where(
            WarehousePincode.warehouse_id == wh.id,
            WarehousePincode.pincode == pincode,
        )
    )
    await db.commit()
    return {"success": True}
