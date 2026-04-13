from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from admin.handlers.unified_websocket import admin_websocket_handler
from admin.db.postgres import init_pg, close_pg
from admin.exceptions import register_exception_handlers
from admin.routers.warehouse import router as warehouse_router
from admin.routers.inventory import router as inventory_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pg()
    yield
    await close_pg()


def create_admin_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    # Register custom exception handlers
    register_exception_handlers(app)

    # REST API routers
    app.include_router(warehouse_router)
    app.include_router(inventory_router)

    @app.websocket("/ws")
    async def root(websocket: WebSocket):
        await admin_websocket_handler(websocket)

    return app
