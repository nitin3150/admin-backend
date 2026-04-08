from fastapi import WebSocket
from datetime import datetime
from admin.utils.id_generator import id_generator
from admin.connection_manager import manager
import logging

logger = logging.getLogger(__name__)


def serialize_document(value):
    if isinstance(value, dict):
        return {k: serialize_document(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize_document(v) for v in value]
    if isinstance(value, datetime):
        iso = value.isoformat()
        if not iso.endswith("Z") and "+" not in iso:
            iso += "Z"
        return iso
    return value


async def get_warehouses(websocket: WebSocket, db):
    """Fetch all warehouses"""
    try:
        result = await db.find_many("warehouses", {})

        warehouses = [
            {
                "id": doc.get("id"),
                "name": doc.get("name"),
                "address": doc.get("address"),
                "city": doc.get("city"),
                "state": doc.get("state"),
                "latitude": doc.get("latitude"),
                "longitude": doc.get("longitude"),
                "status": doc.get("status", True),
                "created_at": doc.get("created_at"),
            }
            for doc in result
        ]

        await websocket.send_json({
            "type": "warehouses_data",
            "warehouses": serialize_document(warehouses),
        })

    except Exception as e:
        logger.exception("Error fetching warehouses")
        await websocket.send_json({
            "type": "error",
            "message": "Failed to fetch warehouses",
        })


async def create_warehouse(websocket: WebSocket, data: dict, db):
    """Create a new warehouse"""
    try:
        # Validate required fields
        required_fields = ["name", "address", "city", "state"]
        for field in required_fields:
            if not data.get(field):
                await websocket.send_json({
                    "type": "error",
                    "message": f"Missing required field: {field}",
                })
                return

        # Generate warehouse ID
        warehouse_id = await id_generator.generate_warehouse_id(data["name"])

        warehouse_data = {
            "id": warehouse_id,
            "name": data["name"],
            "address": data["address"],
            "city": data["city"],
            "state": data["state"],
            "latitude": float(data["latitude"]) if data.get("latitude") else None,
            "longitude": float(data["longitude"]) if data.get("longitude") else None,
            "status": data.get("status", True),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

        result = await db.insert_one("warehouses", warehouse_data)

        if not result:
            await websocket.send_json({
                "type": "error",
                "message": "Failed to create warehouse",
            })
            return

        await websocket.send_json({
            "type": "warehouse_created",
            "warehouse": serialize_document(warehouse_data),
        })

        # Broadcast updated list to all admins
        await broadcast_warehouses_data(db)

        logger.info(f"Warehouse created: {warehouse_id} - {data['name']}")

    except Exception as e:
        logger.exception("Error creating warehouse")
        await websocket.send_json({
            "type": "error",
            "message": f"Failed to create warehouse: {str(e)}",
        })


async def update_warehouse(websocket: WebSocket, data: dict, db):
    """Update an existing warehouse"""
    try:
        warehouse_id = data.get("id")
        if not warehouse_id:
            await websocket.send_json({
                "type": "error",
                "message": "Warehouse ID is required",
            })
            return

        existing = await db.find_one("warehouses", {"id": warehouse_id})
        if not existing:
            await websocket.send_json({
                "type": "error",
                "message": "Warehouse not found",
            })
            return

        update_fields = {}
        for field in ["name", "address", "city", "state", "status"]:
            if field in data:
                update_fields[field] = data[field]

        if "latitude" in data:
            update_fields["latitude"] = float(data["latitude"]) if data["latitude"] else None
        if "longitude" in data:
            update_fields["longitude"] = float(data["longitude"]) if data["longitude"] else None

        update_fields["updated_at"] = datetime.utcnow()

        await db.update_one(
            "warehouses",
            {"id": warehouse_id},
            {"$set": update_fields},
        )

        await websocket.send_json({
            "type": "warehouse_updated",
            "warehouse_id": warehouse_id,
        })

        # Broadcast updated list to all admins
        await broadcast_warehouses_data(db)

        logger.info(f"Warehouse updated: {warehouse_id}")

    except Exception as e:
        logger.exception("Error updating warehouse")
        await websocket.send_json({
            "type": "error",
            "message": f"Failed to update warehouse: {str(e)}",
        })


async def delete_warehouse(websocket: WebSocket, data: dict, db):
    """Delete a warehouse"""
    try:
        warehouse_id = data.get("id")
        if not warehouse_id:
            await websocket.send_json({
                "type": "error",
                "message": "Warehouse ID is required",
            })
            return

        existing = await db.find_one("warehouses", {"id": warehouse_id})
        if not existing:
            await websocket.send_json({
                "type": "error",
                "message": "Warehouse not found",
            })
            return

        # Check if any products are linked to this warehouse
        linked_products = await db.count_documents("products", {"warehouse": warehouse_id})
        if linked_products > 0:
            await websocket.send_json({
                "type": "error",
                "message": f"Cannot delete warehouse. {linked_products} product(s) are linked to it. Please reassign them first.",
            })
            return

        await db.delete_one("warehouses", {"id": warehouse_id})

        await websocket.send_json({
            "type": "warehouse_deleted",
            "warehouse_id": warehouse_id,
        })

        # Broadcast updated list to all admins
        await broadcast_warehouses_data(db)

        logger.info(f"Warehouse deleted: {warehouse_id}")

    except Exception as e:
        logger.exception("Error deleting warehouse")
        await websocket.send_json({
            "type": "error",
            "message": f"Failed to delete warehouse: {str(e)}",
        })


async def broadcast_warehouses_data(db):
    """Broadcast warehouse data to all connected admins"""
    try:
        result = await db.find_many("warehouses", {})

        warehouses = [
            {
                "id": doc.get("id"),
                "name": doc.get("name"),
                "address": doc.get("address"),
                "city": doc.get("city"),
                "state": doc.get("state"),
                "latitude": doc.get("latitude"),
                "longitude": doc.get("longitude"),
                "status": doc.get("status", True),
                "created_at": doc.get("created_at"),
            }
            for doc in result
        ]

        message = {
            "type": "warehouses_data",
            "warehouses": serialize_document(warehouses),
        }

        await manager.broadcast_to_all(message)

    except Exception as e:
        logger.exception("Error broadcasting warehouses data")
