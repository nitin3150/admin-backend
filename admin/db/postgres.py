import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

POSTGRES_URL = os.getenv(
    "POSTGRES_URL",
    "postgresql+asyncpg://user:password@localhost:5432/smartbag_inventory",
)

engine = create_async_engine(POSTGRES_URL, echo=False, pool_size=10, max_overflow=20)

async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_pg_db() -> AsyncSession:
    """FastAPI dependency that yields an async PostgreSQL session."""
    async with async_session_factory() as session:
        yield session


async def init_pg():
    """Called on app startup to verify the connection."""
    async with engine.begin() as conn:
        pass  # connection pool warms up


async def close_pg():
    """Called on app shutdown."""
    await engine.dispose()
