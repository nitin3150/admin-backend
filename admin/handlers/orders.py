from fastapi import WebSocket
import logging
from datetime import datetime
# from admin.utils.serialize import serialize_document
from typing import Dict, Any
import math

logger = logging.getLogger(__name__)

def serialize_document(value):
    if isinstance(value, dict):
        return {k: serialize_document(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize_document(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value

async def send_orders(websocket: WebSocket, filters: dict, db):
    try:
        if websocket.client_state.value != 1:
            return

        query = await build_orders_query(filters)

        page = int(filters.get("page", 1))
        limit = int(filters.get("limit", 10))
        skip = (page - 1) * limit

        total_count = await db.count_documents("orders", query)
        total_pages = max(1, math.ceil(total_count / limit))

        orders = await db.find_many(
            "orders",
            query,
            sort=[("created_at", -1)],
            skip=skip,
            limit=limit,
        )

        # Batch fetch users
        user_ids = list({o["user"] for o in orders if o.get("user")})
        partner_ids = list({o["delivery_partner"] for o in orders if o.get("delivery_partner")})

        users = await db.find_many("users", {"id": {"$in": user_ids}})
        partners = await db.find_many("users", {"id": {"$in": partner_ids}})

        users_map = {u["id"]: u for u in users}
        partners_map = {p["id"]: p for p in partners}

        serialized = []
        for o in orders:
            order = serialize_document(o)

            user = users_map.get(order["user"], {})
            partner = partners_map.get(order.get("delivery_partner"), {})

            serialized.append({
                "id": str(order.get("id") or order.get("_id")),
                "user_name": user.get("name", "Unknown"),
                "user_email": user.get("email", ""),
                "user_phone": user.get("phone", ""),
                "delivery_partner_name": partner.get("name") if partner else None,
                "total": order.get("total_amount", 0),
                "status": order.get("order_status", "pending"),
                "order_type": order.get("order_type", "product"),
                "created_at": order.get("created_at", ""),
            })

        await websocket.send_json({
            "type": "orders_data",
            "orders": serialized,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_items": total_count,
                "has_prev": page > 1,
                "has_next": page < total_pages,
            },
        })

    except Exception as e:
        logger.exception("send_orders failed")
        await websocket.send_json({"type": "error", "message": "Failed to fetch orders"})

async def send_order_details(websocket: WebSocket, data: dict, db):
    try:
        order = await db.find_one("orders", {"id": data.get('order_id')})
        if not order:
            await websocket.send_json({
                "type": "error",
                "message": "Order not found",
            })
            return

        # Copy safely
        order = serialize_document(dict(order))
        order["items"] = [dict(i) for i in order.get("items", [])]

        # Fetch user
        user = await db.find_one("users", {"id": order["user"]})

        # Fetch products
        product_ids = [
            i["product"] for i in order["items"]
            if i.get("type") == "product"
        ]

        products = await db.find_many("products", {"id": {"$in": product_ids}})
        products_map = {p["id"]: p for p in products}

        for item in order["items"]:
            if item["type"] == "product":
                product = products_map.get(item["product"], {})
                item["product_name"] = product.get("name")
                item["product_image"] = product.get("images", [])

        # Normalize addresses
        if "delivery_address" in order:
            addr = order["delivery_address"]
            order["delivery_address"] = {
                "address": addr.get("street"),
                "city": addr.get("city"),
                "state": addr.get("state"),
                "pincode": addr.get("pincode"),
                "phone": addr.get("mobile_number"),
            }

        await websocket.send_json({
            "type": "order_details",
            "order": {
                "id": str(order.get("id") or order.get("_id")),
                "order_type": order.get("order_type", "product"),
                "status": order.get("order_status", "pending"),
                "status_history": order.get("status_change_history", []),
                "items": order["items"],
                "delivery_address": order.get("delivery_address"),
                "total": order.get("total_amount", 0),
                "promo_code": order.get("promo_code",""),
                "promo_discount": order.get("promo_discount",0),
                "tip_amount": order.get("tip_amount",0),
                "payment_method": order.get("payment_method",""),
                "payment_status": order.get("payment_status","pending"),
                "created_at": order.get("created_at",""),
                "customer": {
                    "name": user.get("name") if user else None,
                    "email": user.get("email") if user else None,
                    "phone": user.get("phone") if user else None,
                },
            }
        })

    except Exception:
        logger.exception("send_order_details failed")
        await websocket.send_json({
            "type": "error",
            "message": "Failed to fetch order details",
        })


async def build_orders_query(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Build MongoDB query from filters - FIXED for custom IDs"""
    query = {}
    
    try:
        # Status filter
        if filters.get("status") and filters["status"] != "all":
            query["order_status"] = filters["status"]
        
        # Date range filters
        date_conditions = []
        
        if filters.get("from_date"):
            try:
                from_date = datetime.fromisoformat(filters["from_date"].replace('Z', '+00:00'))
                date_conditions.append({"created_at": {"$gte": from_date}})
            except ValueError as e:
                logger.warning(f"Invalid from_date format: {filters['from_date']}")
        
        if filters.get("to_date"):
            try:
                to_date = datetime.fromisoformat(filters["to_date"].replace('Z', '+00:00'))
                date_conditions.append({"created_at": {"$lte": to_date}})
            except ValueError as e:
                logger.warning(f"Invalid to_date format: {filters['to_date']}")
        
        if date_conditions:
            if len(date_conditions) == 1:
                query.update(date_conditions[0])
            else:
                query["$and"] = date_conditions
        
        # Amount range filters
        amount_conditions = []
        
        if filters.get("min_amount"):
            try:
                min_amount = float(filters["min_amount"])
                amount_conditions.append({"total_amount": {"$gte": min_amount}})
            except ValueError:
                logger.warning(f"Invalid min_amount: {filters['min_amount']}")
        
        if filters.get("max_amount"):
            try:
                max_amount = float(filters["max_amount"])
                amount_conditions.append({"total_amount": {"$lte": max_amount}})
            except ValueError:
                logger.warning(f"Invalid max_amount: {filters['max_amount']}")
        
        if amount_conditions:
            if "$and" in query:
                query["$and"].extend(amount_conditions)
            else:
                query["$and"] = amount_conditions
        
        # ✅ Search by custom order ID
        if filters.get("search"):
            search_term = filters["search"].strip()
            logger.info(f"Searching for order ID: {search_term}")
            
            # Remove # if present
            if search_term.startswith('#'):
                search_term = search_term[1:]
            
            # Search by custom 'id' field (case-insensitive)
            query["id"] = {"$regex": search_term, "$options": "i"}
        
        logger.info(f"Built query: {query}")
        return query
        
    except Exception as e:
        logger.error(f"Error building orders query: {e}")
        return {}

async def update_order_status(websocket: WebSocket, data: dict, user_info: dict, db):
    """Update order status - FIXED for custom IDs"""
    try:
        order_id = data.get("order_id") or data.get("orderId") 
        new_status = data.get("status")
        # delivery_partner = data.get("delivery_partner")
        
        if not order_id or not new_status:
            await websocket.send_json({
                "type": "error", 
                "message": "Order ID and status are required"
            })
            return
        
        # Update with correct database field names
        # update_data = {
        #     "order_status": new_status,
        #     "updated_at": datetime.utcnow(),
        # }
        
        # if delivery_partner:
        #     update_data["delivery_partner"] = delivery_partner
        
        current_time = datetime.utcnow()

        result = await db.update_one(
            "orders", 
            {"id": order_id},
            {
                "$set": {
                    "order_status": new_status,
                    "updated_at": current_time,
                    "updated_at": current_time,
                    "status_message": f"Order is out for delivery"
                },
                "$push": {
                    "status_change_history": {
                        "status": new_status,
                        "changed_at": current_time,
                        # "changed_by": admin_name,
                        "message": f"Order is out for delivery"
                    }
                }
            }
        )
        if result:
            # Send success response
            await websocket.send_json({
                "type": "order_updated",
                "success": True,
                "order_id": order_id
            })
        else:
            await websocket.send_json({
                "type": "error",
                "message": "Failed to update order"
            })
        
    except Exception as e:
        logger.error(f"Error updating order status: {e}")
        await websocket.send_json({
            "type": "error",
            "message": f"Failed to update order status: {str(e)}"
        })

async def get_delivery_requests_for_order(websocket: WebSocket, data: dict, db):
    """Get delivery partners who requested a specific order - FIXED for custom IDs"""
    try:
        order_id = data.get("order_id")
        
        # ✅ Find order using custom 'id' field
        order = await db.find_one("orders", {"id": order_id})
        
        if not order:
            await websocket.send_json({
                "type": "error",
                "message": "Order not found"
            })
            return
        
        # ✅ Get accepted partners (custom IDs)
        partners = order.get("accepted_partners", [])
        partner_list = []

        # Batch fetch partner details using custom 'id' field
        if partners:
            partner_docs = await db.find_many("users", {"id": {"$in": partners}})
            partner_list = [
                {
                    "id": str(partner["id"]),  # Use custom ID
                    "name": partner.get("name", "Unknown"),
                    "email": partner.get("email", ""),
                    "phone": partner.get("phone", "")
                }
                for partner in partner_docs
            ]

        await websocket.send_json({
            "type": "delivery_requests_data",
            "delivery_requests": partner_list
        })
        
    except Exception as e:
        logger.error(f"Unable to get the requested partners: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        await websocket.send_json({
            "type": "error",
            "message": "Failed to get delivery requests"
        })

async def assign_delivery_partner(websocket: WebSocket, data: dict, db):
    """Assign a delivery partner to an order with timeline tracking"""
    try:
        order_id = data.get("order_id")
        partner_id = data.get("delivery_partner_id")
        admin_name = data.get("admin_name", "Admin")  # Get admin name from data
        
        if not order_id or not partner_id:
            await websocket.send_json({
                "type": "error",
                "message": "Order ID and delivery partner ID are required"
            })
            return

        # Get order first to check current status
        order = await db.find_one("orders", {"id": order_id})
        if not order:
            await websocket.send_json({
                "type": "error",
                "message": "Order not found"
            })
            return
        
        # Verify partner exists and is active
        partner = await db.find_one("users", {
            "id": partner_id,
            "role": "delivery_partner",
            "is_active": True
        })
        
        if not partner:
            await websocket.send_json({
                "type": "error",
                "message": "Delivery partner not found or inactive"
            })
            return

        current_time = datetime.utcnow()
        
        # Update order with delivery partner assignment and timeline
        result = await db.update_one(
            "orders", 
            {"id": order_id},
            {
                "$set": {
                    "delivery_partner": partner_id,
                    "order_status": "assigned",
                    "assigned_at": current_time,  # ✅ Add timestamp
                    "updated_at": current_time,
                    "status_message": f"Order assigned to {partner.get('name', 'delivery partner')}"
                },
                "$push": {
                    "status_change_history": {  # ✅ Add to timeline
                        "status": "assigned",
                        "changed_at": current_time,
                        "changed_by": admin_name,
                        "partner_id": partner_id,
                        "partner_name": partner.get("name"),
                        "message": f"Order assigned to {partner.get('name')} by {admin_name}"
                    }
                }
            }
        )
        
        if result:
            logger.info(f"✅ Assigned partner {partner_id} to order {order_id}")
            
            # Get updated order for broadcast
            updated_order = await db.find_one("orders", {"id": order_id})
            
            await websocket.send_json({
                "type": "order_assigned",
                "success": True,
                "data": {
                    "order_id": order_id,
                    "delivery_partner_id": partner_id,
                    "delivery_partner_name": partner.get("name"),
                    "status": "assigned",
                    "timestamp": current_time.isoformat()
                }
            })
            
        else:
            logger.error(f"❌ Failed to assign partner to order {order_id}")
            await websocket.send_json({
                "type": "error",
                "message": "Failed to assign delivery partner"
            })
        
    except Exception as e:
        logger.error(f"Failed to assign delivery partner: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        await websocket.send_json({
            "type": "error",
            "message": f"Failed to assign delivery partner: {str(e)}"
        })
        
async def get_orders_for_download(websocket: WebSocket, filters: dict, db):
    """Get orders for CSV download - FIXED for custom IDs"""
    try:
        # Check if WebSocket is still connected
        if hasattr(websocket, 'client_state') and websocket.client_state.value != 1:
            logger.warning("WebSocket connection is not active, skipping get_orders_for_download")
            return
        
        # Build MongoDB query from filters
        query = await build_orders_query(filters)
        
        logger.info(f"Download query: {query}")
        
        # Get all orders matching the criteria (no pagination for download)
        sort_criteria = [("created_at", -1)]
        
        # Limit to reasonable amount for download (max 10000 orders)
        limit = min(filters.get("limit", 10000), 10000)
        
        orders = await db.find_many(
            "orders", 
            query, 
            sort=sort_criteria,
            limit=limit
        )
        
        logger.info(f"Found {len(orders)} orders for download")
        
        # Process orders with optimized queries
        serialized_orders = []
        
        # ✅ Batch fetch users using custom ID field
        user_ids = [order.get("user") for order in orders if order.get("user")]
        delivery_partner_ids = [order.get("delivery_partner") for order in orders 
                             if order.get("delivery_partner")]
        
        # ✅ Fetch users in batch using custom 'id' field
        users_dict = {}
        if user_ids:
            users = await db.find_many("users", {"id": {"$in": user_ids}})
            users_dict = {str(user["id"]): user for user in users}
        
        # ✅ Fetch delivery partners using custom 'id' field
        delivery_partners_dict = {}
        if delivery_partner_ids:
            partners = await db.find_many("users", {"id": {"$in": delivery_partner_ids}})
            delivery_partners_dict = {str(partner["id"]): partner for partner in partners}
        
        # ✅ Batch fetch products using custom ID field
        product_ids = []
        for order in orders:
            if order.get("items"):
                for item in order["items"]:
                    if item.get("product"):
                        product_ids.append(item["product"])
        
        products_dict = {}
        if product_ids:
            products = await db.find_many("products", {"id": {"$in": product_ids}})
            products_dict = {str(product["id"]): product for product in products}
        
        # Process each order
        for order in orders:
            try:
                # ✅ Get user info using custom ID
                user_id = str(order.get("user", ""))
                user = users_dict.get(user_id, {})
                
                # ✅ Get delivery partner info using custom ID
                delivery_partner_id = str(order.get("delivery_partner", "")) if order.get("delivery_partner") else None
                delivery_partner = delivery_partners_dict.get(delivery_partner_id) if delivery_partner_id else None
                
                # ✅ Process order items using custom product IDs
                if order.get("items"):
                    for item in order["items"]:
                        product_id = str(item.get("product", ""))
                        product = products_dict.get(product_id, {})
                        item["product_name"] = product.get("name", "Unknown Product")
                        item["product_image"] = product.get("images", [])
                
                # Serialize the order
                serialized_order = serialize_document(order)
                
                # ✅ Use custom ID
                serialized_order["id"] = serialized_order.get("id", str(serialized_order.get("_id", "")))
                serialized_order["total"] = serialized_order.get("total_amount", 0)
                serialized_order["status"] = serialized_order.get("order_status", "pending")
                
                # Add user information
                serialized_order["user_name"] = user.get("name", "Unknown")
                serialized_order["user_email"] = user.get("email", "")
                serialized_order["user_phone"] = user.get("phone", "")
                
                # Add delivery partner information
                serialized_order["delivery_partner_name"] = (
                    delivery_partner.get("name") if delivery_partner else None
                )
                
                # Add delivery address for CSV
                if order.get("delivery_address"):
                    serialized_order["delivery_address"] = order["delivery_address"]
                
                serialized_orders.append(serialized_order)
                
            except Exception as serialize_error:
                logger.error(f"Error serializing order for download {order.get('id')}: {serialize_error}")
                continue
        
        logger.info(f"Sending {len(serialized_orders)} orders for download")

        await websocket.send_json({
            "type": "orders_download_data",
            "orders": serialized_orders,
            "total_count": len(serialized_orders)
        })
        
    except Exception as e:
        logger.error(f"Error getting orders for download: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": "Failed to fetch orders for download"
            })
        except:
            logger.info("Could not send error message - client disconnected")