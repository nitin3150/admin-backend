from fastapi import Request
from fastapi.responses import JSONResponse


class InsufficientStockError(Exception):
    def __init__(self, sku_id: str, requested: int, available: int):
        self.sku_id = sku_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient stock for {sku_id}: requested={requested}, available={available}"
        )


class WarehouseNotFoundError(Exception):
    def __init__(self, warehouse_id: str):
        self.warehouse_id = warehouse_id
        super().__init__(f"Warehouse not found: {warehouse_id}")


class PincodeNotServicedError(Exception):
    def __init__(self, pincode: str):
        self.pincode = pincode
        super().__init__(f"Pincode not serviced: {pincode}")


class DuplicatePriorityError(Exception):
    def __init__(self, pincode: str, priority: int, existing_warehouse: str):
        self.pincode = pincode
        self.priority = priority
        self.existing_warehouse = existing_warehouse
        super().__init__(
            f"Priority {priority} already assigned to warehouse {existing_warehouse} "
            f"for pincode {pincode}"
        )


class OrderAlreadyProcessedError(Exception):
    def __init__(self, order_id: str, current_status: str):
        self.order_id = order_id
        self.current_status = current_status
        super().__init__(
            f"Order {order_id} already processed with status: {current_status}"
        )


# ── FastAPI exception handlers ───────────────────────────────────────


async def insufficient_stock_handler(_request: Request, exc: InsufficientStockError):
    return JSONResponse(
        status_code=409,
        content={
            "error": "INSUFFICIENT_STOCK",
            "detail": {
                "sku_id": exc.sku_id,
                "requested": exc.requested,
                "available": exc.available,
            },
        },
    )


async def warehouse_not_found_handler(_request: Request, exc: WarehouseNotFoundError):
    return JSONResponse(
        status_code=404,
        content={
            "error": "WAREHOUSE_NOT_FOUND",
            "detail": {"warehouse_id": exc.warehouse_id},
        },
    )


async def pincode_not_serviced_handler(
    _request: Request, exc: PincodeNotServicedError
):
    return JSONResponse(
        status_code=422,
        content={
            "error": "PINCODE_NOT_SERVICED",
            "detail": {"pincode": exc.pincode},
        },
    )


async def duplicate_priority_handler(_request: Request, exc: DuplicatePriorityError):
    return JSONResponse(
        status_code=409,
        content={
            "error": "DUPLICATE_PRIORITY",
            "detail": {
                "pincode": exc.pincode,
                "priority": exc.priority,
                "existing_warehouse": exc.existing_warehouse,
            },
        },
    )


async def order_already_processed_handler(
    _request: Request, exc: OrderAlreadyProcessedError
):
    return JSONResponse(
        status_code=409,
        content={
            "error": "ORDER_ALREADY_PROCESSED",
            "detail": {
                "order_id": exc.order_id,
                "current_status": exc.current_status,
            },
        },
    )


def register_exception_handlers(app):
    """Register all custom exception handlers on the FastAPI app."""
    app.add_exception_handler(InsufficientStockError, insufficient_stock_handler)
    app.add_exception_handler(WarehouseNotFoundError, warehouse_not_found_handler)
    app.add_exception_handler(PincodeNotServicedError, pincode_not_serviced_handler)
    app.add_exception_handler(DuplicatePriorityError, duplicate_priority_handler)
    app.add_exception_handler(
        OrderAlreadyProcessedError, order_already_processed_handler
    )
