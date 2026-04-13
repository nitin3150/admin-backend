"""WebSocket handlers for Hub and Warehouse CRUD operations (admin panel)."""

from datetime import datetime
from uuid import UUID

from fastapi import WebSocket
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from admin.connection_manager import manager
from admin.db.postgres import async_session_factory
from admin.exceptions import DuplicatePriorityError
from admin.models.hub import Hub, Warehouse, WarehousePincode
from admin.models.inventory import Inventory
from admin.utils.id_generator import id_generator
import logging

logger = logging.getLogger(__name__)


def _serialize_dt(v):
    if isinstance(v, datetime):
        iso = v.isoformat()
        if not iso.endswith("Z") and "+" not in iso:
            iso += "Z"
        return iso
    return v


# ── Hub handlers ─────────────────────────────────────────────────────

async def get_hubs(websocket: WebSocket):
    """Fetch all hubs with warehouse count."""
    try:
        async with async_session_factory() as db:
            stmt = select(Hub).order_by(Hub.created_at.desc())
            hubs = (await db.execute(stmt)).scalars().all()

            hub_list = []
            for h in hubs:
                wh_count = (
                    await db.execute(
                        select(func.count()).where(Warehouse.hub_id == h.id)
                    )
                ).scalar()
                hub_list.append(
                    {
                        "id": str(h.id),
                        "hub_id": h.hub_id,
                        "name": h.name,
                        "city": h.city,
                        "is_active": h.is_active,
                        "warehouse_count": wh_count or 0,
                        "created_at": _serialize_dt(h.created_at),
                        "updated_at": _serialize_dt(h.updated_at),
                    }
                )

            await websocket.send_json({"type": "hubs_data", "hubs": hub_list})
    except Exception as e:
        logger.exception("Error fetching hubs")
        await websocket.send_json({"type": "error", "message": f"Failed to fetch hubs: {str(e)}"})


async def create_hub(websocket: WebSocket, data: dict):
    """Create a new hub."""
    try:
        async with async_session_factory() as db:
            async with db.begin():
                hub = Hub(
                    hub_id=data["hub_id"],
                    name=data["name"],
                    city=data["city"],
                )
                db.add(hub)

            await websocket.send_json({
                "type": "hub_created",
                "hub": {
                    "id": str(hub.id),
                    "hub_id": hub.hub_id,
                    "name": hub.name,
                    "city": hub.city,
                    "is_active": hub.is_active,
                    "created_at": _serialize_dt(hub.created_at),
                    "updated_at": _serialize_dt(hub.updated_at),
                },
            })

            await broadcast_hubs_data()
            logger.info(f"Hub created: {hub.hub_id}")
    except Exception as e:
        logger.exception("Error creating hub")
        await websocket.send_json({"type": "error", "message": f"Failed to create hub: {str(e)}"})


async def update_hub(websocket: WebSocket, data: dict):
    """Update an existing hub."""
    try:
        async with async_session_factory() as db:
            async with db.begin():
                hub = (
                    await db.execute(select(Hub).where(Hub.hub_id == data["hub_id"]))
                ).scalar_one_or_none()

                if not hub:
                    await websocket.send_json({"type": "error", "message": "Hub not found"})
                    return

                for field in ["name", "city", "is_active"]:
                    if field in data:
                        setattr(hub, field, data[field])

            await websocket.send_json({"type": "hub_updated", "hub_id": data["hub_id"]})
            await broadcast_hubs_data()
            logger.info(f"Hub updated: {data['hub_id']}")
    except Exception as e:
        logger.exception("Error updating hub")
        await websocket.send_json({"type": "error", "message": f"Failed to update hub: {str(e)}"})


async def broadcast_hubs_data():
    """Broadcast hubs list to all connected admins."""
    try:
        async with async_session_factory() as db:
            hubs = (await db.execute(select(Hub).order_by(Hub.created_at.desc()))).scalars().all()
            hub_list = []
            for h in hubs:
                wh_count = (await db.execute(select(func.count()).where(Warehouse.hub_id == h.id))).scalar()
                hub_list.append({
                    "id": str(h.id),
                    "hub_id": h.hub_id,
                    "name": h.name,
                    "city": h.city,
                    "is_active": h.is_active,
                    "warehouse_count": wh_count or 0,
                    "created_at": _serialize_dt(h.created_at),
                    "updated_at": _serialize_dt(h.updated_at),
                })
            await manager.broadcast_to_all({"type": "hubs_data", "hubs": hub_list})
    except Exception as e:
        logger.exception("Error broadcasting hubs data")


# ── Warehouse handlers (PostgreSQL) ─────────────────────────────────

async def get_pg_warehouses(websocket: WebSocket):
    """Fetch all warehouses from PostgreSQL with hub info and pincode count."""
    try:
        async with async_session_factory() as db:
            stmt = select(Warehouse).order_by(Warehouse.created_at.desc())
            warehouses = (await db.execute(stmt)).scalars().all()

            wh_list = []
            for w in warehouses:
                pc_count = (
                    await db.execute(
                        select(func.count()).where(WarehousePincode.warehouse_id == w.id)
                    )
                ).scalar()

                hub = (await db.execute(select(Hub).where(Hub.id == w.hub_id))).scalar_one_or_none()

                wh_list.append({
                    "id": str(w.id),
                    "warehouse_id": w.warehouse_id,
                    "hub_id": str(w.hub_id),
                    "hub_name": hub.name if hub else "",
                    "hub_hub_id": hub.hub_id if hub else "",
                    "name": w.name,
                    "address": w.address,
                    "lat": w.lat,
                    "lng": w.lng,
                    "is_active": w.is_active,
                    "pincode_count": pc_count or 0,
                    "created_at": _serialize_dt(w.created_at),
                    "updated_at": _serialize_dt(w.updated_at),
                })

            await websocket.send_json({"type": "pg_warehouses_data", "warehouses": wh_list})
    except Exception as e:
        logger.exception("Error fetching PG warehouses")
        await websocket.send_json({"type": "error", "message": f"Failed to fetch warehouses: {str(e)}"})


async def create_pg_warehouse(websocket: WebSocket, data: dict):
    """Create a warehouse in PostgreSQL, auto-generating warehouse_id."""
    try:
        async with async_session_factory() as db:
            async with db.begin():
                # Resolve hub by hub_id string
                hub = (
                    await db.execute(select(Hub).where(Hub.hub_id == data["hub_id"]))
                ).scalar_one_or_none()

                if not hub:
                    await websocket.send_json({"type": "error", "message": f"Hub not found: {data['hub_id']}"})
                    return

                warehouse_id = await id_generator.generate_warehouse_id(data["name"])

                wh = Warehouse(
                    warehouse_id=warehouse_id,
                    hub_id=hub.id,
                    name=data["name"],
                    address=data["address"],
                    lat=float(data["lat"]) if data.get("lat") else None,
                    lng=float(data["lng"]) if data.get("lng") else None,
                )
                db.add(wh)

            await websocket.send_json({
                "type": "pg_warehouse_created",
                "warehouse": {
                    "id": str(wh.id),
                    "warehouse_id": wh.warehouse_id,
                    "hub_id": str(wh.hub_id),
                    "name": wh.name,
                    "address": wh.address,
                    "lat": wh.lat,
                    "lng": wh.lng,
                    "is_active": wh.is_active,
                    "created_at": _serialize_dt(wh.created_at),
                },
            })

            await broadcast_pg_warehouses_data()
            logger.info(f"PG Warehouse created: {warehouse_id}")
    except Exception as e:
        logger.exception("Error creating PG warehouse")
        await websocket.send_json({"type": "error", "message": f"Failed to create warehouse: {str(e)}"})


async def update_pg_warehouse(websocket: WebSocket, data: dict):
    """Update a warehouse in PostgreSQL."""
    try:
        async with async_session_factory() as db:
            async with db.begin():
                wh = (
                    await db.execute(
                        select(Warehouse).where(Warehouse.warehouse_id == data["warehouse_id"])
                    )
                ).scalar_one_or_none()

                if not wh:
                    await websocket.send_json({"type": "error", "message": "Warehouse not found"})
                    return

                for field in ["name", "address", "is_active"]:
                    if field in data:
                        setattr(wh, field, data[field])
                if "lat" in data:
                    wh.lat = float(data["lat"]) if data["lat"] else None
                if "lng" in data:
                    wh.lng = float(data["lng"]) if data["lng"] else None

            await websocket.send_json({"type": "pg_warehouse_updated", "warehouse_id": data["warehouse_id"]})
            await broadcast_pg_warehouses_data()
            logger.info(f"PG Warehouse updated: {data['warehouse_id']}")
    except Exception as e:
        logger.exception("Error updating PG warehouse")
        await websocket.send_json({"type": "error", "message": f"Failed to update warehouse: {str(e)}"})


async def broadcast_pg_warehouses_data():
    """Broadcast PG warehouses list to all connected admins."""
    try:
        async with async_session_factory() as db:
            warehouses = (await db.execute(select(Warehouse).order_by(Warehouse.created_at.desc()))).scalars().all()
            wh_list = []
            for w in warehouses:
                pc_count = (await db.execute(select(func.count()).where(WarehousePincode.warehouse_id == w.id))).scalar()
                hub = (await db.execute(select(Hub).where(Hub.id == w.hub_id))).scalar_one_or_none()
                wh_list.append({
                    "id": str(w.id),
                    "warehouse_id": w.warehouse_id,
                    "hub_id": str(w.hub_id),
                    "hub_name": hub.name if hub else "",
                    "hub_hub_id": hub.hub_id if hub else "",
                    "name": w.name,
                    "address": w.address,
                    "lat": w.lat,
                    "lng": w.lng,
                    "is_active": w.is_active,
                    "pincode_count": pc_count or 0,
                    "created_at": _serialize_dt(w.created_at),
                    "updated_at": _serialize_dt(w.updated_at),
                })
            await manager.broadcast_to_all({"type": "pg_warehouses_data", "warehouses": wh_list})
    except Exception as e:
        logger.exception("Error broadcasting PG warehouses data")


# ── Pincode assignment handlers ──────────────────────────────────────

async def get_warehouse_pincodes(websocket: WebSocket, data: dict):
    """Fetch pincode mappings for a warehouse."""
    try:
        async with async_session_factory() as db:
            wh = (
                await db.execute(
                    select(Warehouse).where(Warehouse.warehouse_id == data["warehouse_id"])
                )
            ).scalar_one_or_none()

            if not wh:
                await websocket.send_json({"type": "error", "message": "Warehouse not found"})
                return

            pincodes = (
                await db.execute(
                    select(WarehousePincode)
                    .where(WarehousePincode.warehouse_id == wh.id)
                    .order_by(WarehousePincode.priority.asc())
                )
            ).scalars().all()

            pc_list = [
                {
                    "id": str(p.id),
                    "pincode": p.pincode,
                    "priority": p.priority,
                }
                for p in pincodes
            ]

            await websocket.send_json({
                "type": "warehouse_pincodes_data",
                "warehouse_id": data["warehouse_id"],
                "pincodes": pc_list,
            })
    except Exception as e:
        logger.exception("Error fetching warehouse pincodes")
        await websocket.send_json({"type": "error", "message": f"Failed to fetch pincodes: {str(e)}"})


async def assign_warehouse_pincodes(websocket: WebSocket, data: dict):
    """Assign pincodes with priorities to a warehouse.

    Validates that no two warehouses under the same hub have the same
    priority for the same pincode.
    """
    try:
        async with async_session_factory() as db:
            async with db.begin():
                wh = (
                    await db.execute(
                        select(Warehouse).where(Warehouse.warehouse_id == data["warehouse_id"])
                    )
                ).scalar_one_or_none()

                if not wh:
                    await websocket.send_json({"type": "error", "message": "Warehouse not found"})
                    return

                for pc in data["pincodes"]:
                    pincode = pc["pincode"]
                    priority = pc["priority"]

                    # Check for duplicate priority under the same hub
                    conflict = (
                        await db.execute(
                            select(WarehousePincode)
                            .join(Warehouse, Warehouse.id == WarehousePincode.warehouse_id)
                            .where(
                                Warehouse.hub_id == wh.hub_id,
                                Warehouse.id != wh.id,
                                WarehousePincode.pincode == pincode,
                                WarehousePincode.priority == priority,
                            )
                        )
                    ).scalar_one_or_none()

                    if conflict:
                        conflict_wh = (
                            await db.execute(
                                select(Warehouse).where(Warehouse.id == conflict.warehouse_id)
                            )
                        ).scalar_one()
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Priority {priority} for pincode {pincode} already assigned to warehouse {conflict_wh.warehouse_id}",
                        })
                        return

                    # Upsert
                    existing = (
                        await db.execute(
                            select(WarehousePincode).where(
                                WarehousePincode.warehouse_id == wh.id,
                                WarehousePincode.pincode == pincode,
                            )
                        )
                    ).scalar_one_or_none()

                    if existing:
                        existing.priority = priority
                    else:
                        db.add(
                            WarehousePincode(
                                warehouse_id=wh.id,
                                pincode=pincode,
                                priority=priority,
                            )
                        )

            await websocket.send_json({
                "type": "warehouse_pincodes_assigned",
                "warehouse_id": data["warehouse_id"],
            })
            logger.info(f"Pincodes assigned to warehouse {data['warehouse_id']}")
    except Exception as e:
        logger.exception("Error assigning pincodes")
        await websocket.send_json({"type": "error", "message": f"Failed to assign pincodes: {str(e)}"})


async def update_warehouse_pincode_priority(websocket: WebSocket, data: dict):
    """Update priority for a specific warehouse-pincode mapping."""
    try:
        async with async_session_factory() as db:
            async with db.begin():
                wh = (
                    await db.execute(
                        select(Warehouse).where(Warehouse.warehouse_id == data["warehouse_id"])
                    )
                ).scalar_one_or_none()

                if not wh:
                    await websocket.send_json({"type": "error", "message": "Warehouse not found"})
                    return

                mapping = (
                    await db.execute(
                        select(WarehousePincode).where(
                            WarehousePincode.warehouse_id == wh.id,
                            WarehousePincode.pincode == data["pincode"],
                        )
                    )
                ).scalar_one_or_none()

                if not mapping:
                    await websocket.send_json({"type": "error", "message": "Pincode mapping not found"})
                    return

                # Check for duplicate priority under same hub
                conflict = (
                    await db.execute(
                        select(WarehousePincode)
                        .join(Warehouse, Warehouse.id == WarehousePincode.warehouse_id)
                        .where(
                            Warehouse.hub_id == wh.hub_id,
                            Warehouse.id != wh.id,
                            WarehousePincode.pincode == data["pincode"],
                            WarehousePincode.priority == data["priority"],
                        )
                    )
                ).scalar_one_or_none()

                if conflict:
                    conflict_wh = (
                        await db.execute(select(Warehouse).where(Warehouse.id == conflict.warehouse_id))
                    ).scalar_one()
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Priority {data['priority']} for pincode {data['pincode']} already assigned to warehouse {conflict_wh.warehouse_id}",
                    })
                    return

                mapping.priority = data["priority"]

            await websocket.send_json({
                "type": "warehouse_pincode_updated",
                "warehouse_id": data["warehouse_id"],
                "pincode": data["pincode"],
            })
    except Exception as e:
        logger.exception("Error updating pincode priority")
        await websocket.send_json({"type": "error", "message": f"Failed to update pincode: {str(e)}"})


async def delete_warehouse_pincode(websocket: WebSocket, data: dict):
    """Remove a pincode from a warehouse."""
    try:
        async with async_session_factory() as db:
            async with db.begin():
                wh = (
                    await db.execute(
                        select(Warehouse).where(Warehouse.warehouse_id == data["warehouse_id"])
                    )
                ).scalar_one_or_none()

                if not wh:
                    await websocket.send_json({"type": "error", "message": "Warehouse not found"})
                    return

                await db.execute(
                    delete(WarehousePincode).where(
                        WarehousePincode.warehouse_id == wh.id,
                        WarehousePincode.pincode == data["pincode"],
                    )
                )

            await websocket.send_json({
                "type": "warehouse_pincode_deleted",
                "warehouse_id": data["warehouse_id"],
                "pincode": data["pincode"],
            })
    except Exception as e:
        logger.exception("Error deleting pincode")
        await websocket.send_json({"type": "error", "message": f"Failed to delete pincode: {str(e)}"})
