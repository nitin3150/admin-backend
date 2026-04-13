"""WebSocket handlers for Inventory management (admin panel)."""

from datetime import datetime

from fastapi import WebSocket
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from admin.db.postgres import async_session_factory
from admin.models.hub import Warehouse
from admin.models.inventory import Inventory, InventoryAudit
from admin.services.inventory_service import (
    get_available_inventory,
    get_audit_log,
    get_low_stock,
    restock_warehouse,
)
import logging

logger = logging.getLogger(__name__)


def _serialize_dt(v):
    if isinstance(v, datetime):
        iso = v.isoformat()
        if not iso.endswith("Z") and "+" not in iso:
            iso += "Z"
        return iso
    return v


async def handle_get_inventory(websocket: WebSocket, data: dict):
    """Fetch inventory for a specific warehouse or all warehouses."""
    try:
        async with async_session_factory() as db:
            stmt = select(Inventory).order_by(Inventory.last_updated.desc())

            if data.get("warehouse_id"):
                wh = (
                    await db.execute(
                        select(Warehouse).where(Warehouse.warehouse_id == data["warehouse_id"])
                    )
                ).scalar_one_or_none()
                if wh:
                    stmt = stmt.where(Inventory.warehouse_id == wh.id)

            rows = (await db.execute(stmt)).scalars().all()

            # Load warehouse names
            wh_ids = list({r.warehouse_id for r in rows})
            wh_map = {}
            if wh_ids:
                whs = (await db.execute(select(Warehouse).where(Warehouse.id.in_(wh_ids)))).scalars().all()
                wh_map = {w.id: w for w in whs}

            inv_list = [
                {
                    "id": str(r.id),
                    "warehouse_id": str(r.warehouse_id),
                    "warehouse_name": wh_map[r.warehouse_id].name if r.warehouse_id in wh_map else "",
                    "warehouse_str_id": wh_map[r.warehouse_id].warehouse_id if r.warehouse_id in wh_map else "",
                    "sku_id": r.sku_id,
                    "qty": r.qty,
                    "reserved_qty": r.reserved_qty,
                    "available_qty": r.qty - r.reserved_qty,
                    "reorder_threshold": r.reorder_threshold,
                    "last_updated": _serialize_dt(r.last_updated),
                }
                for r in rows
            ]

            await websocket.send_json({"type": "inventory_data", "inventory": inv_list})
    except Exception as e:
        logger.exception("Error fetching inventory")
        await websocket.send_json({"type": "error", "message": f"Failed to fetch inventory: {str(e)}"})


async def handle_restock(websocket: WebSocket, data: dict):
    """Restock a warehouse with a product."""
    try:
        async with async_session_factory() as db:
            inv = await restock_warehouse(
                warehouse_id=data["warehouse_id"],
                sku_id=data["sku_id"],
                qty=int(data["qty"]),
                reference_id=data.get("reference_id", "admin_restock"),
                db=db,
            )

            wh = (
                await db.execute(select(Warehouse).where(Warehouse.id == inv.warehouse_id))
            ).scalar_one_or_none()

            await websocket.send_json({
                "type": "inventory_restocked",
                "inventory": {
                    "id": str(inv.id),
                    "warehouse_id": str(inv.warehouse_id),
                    "warehouse_name": wh.name if wh else "",
                    "warehouse_str_id": wh.warehouse_id if wh else "",
                    "sku_id": inv.sku_id,
                    "qty": inv.qty,
                    "reserved_qty": inv.reserved_qty,
                    "available_qty": inv.qty - inv.reserved_qty,
                    "reorder_threshold": inv.reorder_threshold,
                    "last_updated": _serialize_dt(inv.last_updated),
                },
            })
            logger.info(f"Restocked {data['sku_id']} at {data['warehouse_id']} +{data['qty']}")
    except Exception as e:
        logger.exception("Error restocking inventory")
        await websocket.send_json({"type": "error", "message": f"Failed to restock: {str(e)}"})


async def handle_get_audit_log(websocket: WebSocket, data: dict):
    """Fetch audit log for a warehouse."""
    try:
        async with async_session_factory() as db:
            audits = await get_audit_log(
                warehouse_id=data["warehouse_id"],
                db=db,
                sku_id=data.get("sku_id"),
                reason=data.get("reason"),
                limit=int(data.get("limit", 50)),
                offset=int(data.get("offset", 0)),
            )

            wh_ids = list({a.warehouse_id for a in audits})
            wh_map = {}
            if wh_ids:
                whs = (await db.execute(select(Warehouse).where(Warehouse.id.in_(wh_ids)))).scalars().all()
                wh_map = {w.id: w for w in whs}

            audit_list = [
                {
                    "id": str(a.id),
                    "warehouse_id": str(a.warehouse_id),
                    "warehouse_name": wh_map[a.warehouse_id].name if a.warehouse_id in wh_map else "",
                    "sku_id": a.sku_id,
                    "delta": a.delta,
                    "reason": a.reason,
                    "reference_id": a.reference_id,
                    "created_at": _serialize_dt(a.created_at),
                }
                for a in audits
            ]

            await websocket.send_json({
                "type": "inventory_audit_data",
                "warehouse_id": data["warehouse_id"],
                "audits": audit_list,
            })
    except Exception as e:
        logger.exception("Error fetching audit log")
        await websocket.send_json({"type": "error", "message": f"Failed to fetch audit log: {str(e)}"})


async def handle_get_low_stock(websocket: WebSocket, data: dict):
    """Fetch low-stock items."""
    try:
        async with async_session_factory() as db:
            rows = await get_low_stock(
                db=db,
                warehouse_id=data.get("warehouse_id"),
                threshold=int(data["threshold"]) if data.get("threshold") else None,
            )

            wh_ids = list({r.warehouse_id for r in rows})
            wh_map = {}
            if wh_ids:
                whs = (await db.execute(select(Warehouse).where(Warehouse.id.in_(wh_ids)))).scalars().all()
                wh_map = {w.id: w for w in whs}

            low_stock_list = [
                {
                    "warehouse_id": str(r.warehouse_id),
                    "warehouse_name": wh_map[r.warehouse_id].name if r.warehouse_id in wh_map else "",
                    "warehouse_str_id": wh_map[r.warehouse_id].warehouse_id if r.warehouse_id in wh_map else "",
                    "sku_id": r.sku_id,
                    "qty": r.qty,
                    "reserved_qty": r.reserved_qty,
                    "available_qty": r.qty - r.reserved_qty,
                    "reorder_threshold": r.reorder_threshold,
                }
                for r in rows
            ]

            await websocket.send_json({"type": "low_stock_data", "items": low_stock_list})
    except Exception as e:
        logger.exception("Error fetching low stock")
        await websocket.send_json({"type": "error", "message": f"Failed to fetch low stock: {str(e)}"})
