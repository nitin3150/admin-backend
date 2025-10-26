# admin/handlers/porter.py
from fastapi import WebSocket
from bson import ObjectId
from datetime import datetime
from admin.utils.serialize import serialize_document
import logging

logger = logging.getLogger(__name__)

async def get_porter_requests(websocket: WebSocket, filters: dict, db):
    """Get all porter requests with optional filters"""
    try:
        # Build query based on filters
        query = {}
        
        if filters.get("status") and filters["status"] != "all":
            query["status"] = filters["status"]
        
        if filters.get("urgent") is not None:
            query["urgent"] = filters["urgent"]
        
        if filters.get("package_size") and filters["package_size"] != "all":
            query["package_size"] = filters["package_size"]
        
        logger.info(f"Fetching porter requests with query: {query}")
        
        # Get porter requests
        requests = await db.find_many(
            "porter_requests", 
            query, 
            sort=[("created_at", -1)]
        )
        
        logger.info(f"Found {len(requests)} porter requests")
        
        # Process each request
        enriched_requests = []
        for request in requests:
            try:
                # Get user info
                user_info = None
                if request.get("user_id"):
                    user_info = await db.find_one("users", {"_id": request["user_id"]})
                
                # Serialize the request
                serialized_request = {
                    "_id": str(request["_id"]),
                    "id": str(request["_id"]),
                    "pickup_address": request.get("pickup_address", {}),
                    "delivery_address": request.get("delivery_address", {}),
                    "phone": request.get("phone", "Not provided"),
                    "description": request.get("description", ""),
                    "estimated_distance": request.get("estimated_distance"),
                    "package_size": request.get("package_size", "small"),
                    "urgent": request.get("urgent", False),
                    "status": request.get("status", "pending"),
                    "created_at": request["created_at"].isoformat() if request.get("created_at") else None,
                    "updated_at": request.get("updated_at").isoformat() if request.get("updated_at") else None,
                    "assigned_partner_id": str(request["assigned_partner_id"]) if request.get("assigned_partner_id") else None,
                    "assigned_partner_name": request.get("assigned_partner_name"),
                    "estimated_cost": request.get("estimated_cost"),
                    "actual_cost": request.get("actual_cost"),
                    "admin_notes": request.get("admin_notes"),
                }
                
                # Add user information
                if user_info:
                    serialized_request["user_name"] = user_info.get("name", "Unknown")
                    serialized_request["user_email"] = user_info.get("email", "Unknown")
                    serialized_request["user_phone"] = user_info.get("phone", "Not provided")
                else:
                    serialized_request["user_name"] = request.get("user_name", "Unknown")
                    serialized_request["user_email"] = request.get("user_email", "Unknown")
                    serialized_request["user_phone"] = request.get("user_phone", "Not provided")
                
                enriched_requests.append(serialized_request)
                
            except Exception as request_error:
                logger.error(f"Error processing porter request {request.get('_id')}: {request_error}")
                continue

        logger.info(f"Successfully processed {len(enriched_requests)} porter requests")

        await websocket.send_json({
            "type": "porter_requests_data",
            "requests": enriched_requests,
            "total_count": len(enriched_requests)
        })
        
    except Exception as e:
        logger.error(f"Error getting porter requests: {e}")
        await websocket.send_json({
            "type": "error",
            "message": f"Failed to fetch porter requests: {str(e)}"
        })

async def update_porter_request_status(websocket: WebSocket, data: dict, db):
    """Update porter request status"""
    try:
        request_id = data.get("request_id")
        new_status = data.get("status")
        admin_notes = data.get("admin_notes", "")
        estimated_cost = data.get("estimated_cost")
        
        valid_statuses = ["pending", "assigned", "in_transit", "delivered", "cancelled"]
        
        if not request_id or not new_status:
            await websocket.send_json({
                "type": "error",
                "message": "Request ID and status are required"
            })
            return
        
        if new_status not in valid_statuses:
            await websocket.send_json({
                "type": "error",
                "message": f"Invalid status. Valid options: {', '.join(valid_statuses)}"
            })
            return
        
        if not ObjectId.is_valid(request_id):
            await websocket.send_json({
                "type": "error",
                "message": "Invalid request ID format"
            })
            return
        
        logger.info(f"Updating porter request {request_id} status to {new_status}")
        
        # Update request
        update_data = {
            "status": new_status,
            "updated_at": datetime.utcnow()
        }
        
        if admin_notes:
            update_data["admin_notes"] = admin_notes
        
        if estimated_cost is not None:
            update_data["estimated_cost"] = float(estimated_cost)
        
        await db.update_one(
            "porter_requests",
            {"_id": ObjectId(request_id)},
            update_data
        )
        
        logger.info(f"Porter request {request_id} status updated to {new_status}")
        
        await websocket.send_json({
            "type": "porter_request_updated",
            "message": f"Porter request status updated to {new_status}",
            "request_id": request_id
        })
        
    except Exception as e:
        logger.error(f"Error updating porter request status: {e}")
        await websocket.send_json({
            "type": "error",
            "message": f"Failed to update status: {str(e)}"
        })

async def assign_porter_partner(websocket: WebSocket, data: dict, db):
    """Assign a delivery partner to a porter request"""
    try:
        request_id = data.get("request_id")
        partner_id = data.get("partner_id")
        estimated_cost = data.get("estimated_cost")
        
        if not request_id or not partner_id:
            await websocket.send_json({
                "type": "error",
                "message": "Request ID and partner ID are required"
            })
            return
        
        if not ObjectId.is_valid(request_id) or not ObjectId.is_valid(partner_id):
            await websocket.send_json({
                "type": "error",
                "message": "Invalid ID format"
            })
            return
        
        # Get partner info
        partner = await db.find_one("users", {"_id": ObjectId(partner_id)})
        
        if not partner or partner.get("role") != "delivery_partner":
            await websocket.send_json({
                "type": "error",
                "message": "Invalid delivery partner"
            })
            return
        
        # Update porter request
        update_data = {
            "assigned_partner_id": ObjectId(partner_id),
            "assigned_partner_name": partner.get("name", "Unknown"),
            "status": "assigned",
            "updated_at": datetime.utcnow()
        }
        
        if estimated_cost is not None:
            update_data["estimated_cost"] = float(estimated_cost)
        
        await db.update_one(
            "porter_requests",
            {"_id": ObjectId(request_id)},
            update_data
        )
        
        logger.info(f"Assigned partner {partner_id} to porter request {request_id}")
        
        await websocket.send_json({
            "type": "porter_request_updated",
            "message": f"Partner assigned successfully",
            "request_id": request_id
        })
        
    except Exception as e:
        logger.error(f"Error assigning porter partner: {e}")
        await websocket.send_json({
            "type": "error",
            "message": f"Failed to assign partner: {str(e)}"
        })

async def get_porter_stats(websocket: WebSocket, data: dict, db):
    """Get porter request statistics"""
    try:
        logger.info("Fetching porter request statistics")
        
        # Get all porter requests
        all_requests = await db.find_many("porter_requests", {})
        
        # Calculate stats
        status_breakdown = {
            "pending": 0,
            "assigned": 0,
            "in_transit": 0,
            "delivered": 0,
            "cancelled": 0
        }
        
        today_count = 0
        urgent_count = 0
        total_revenue = 0.0
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        for request in all_requests:
            status = request.get("status", "pending")
            if status in status_breakdown:
                status_breakdown[status] += 1
            
            # Count today's requests
            created_at = request.get("created_at")
            if created_at and created_at >= today_start:
                today_count += 1
            
            # Count urgent requests
            if request.get("urgent"):
                urgent_count += 1
            
            # Calculate revenue from delivered requests
            if status == "delivered" and request.get("actual_cost"):
                total_revenue += float(request.get("actual_cost", 0))
        
        stats = {
            "total_requests": len(all_requests),
            "today_requests": today_count,
            "urgent_requests": urgent_count,
            "total_revenue": total_revenue,
            "status_breakdown": status_breakdown
        }
        
        await websocket.send_json({
            "type": "porter_stats_data",
            "stats": stats
        })
        
        logger.info(f"Sent porter stats: {stats}")
        
    except Exception as e:
        logger.error(f"Error getting porter stats: {e}")
        await websocket.send_json({
            "type": "error",
            "message": f"Failed to get stats: {str(e)}"
        })