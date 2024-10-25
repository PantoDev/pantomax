from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (AsyncEngine, AsyncSession, async_scoped_session,
                                    async_sessionmaker, create_async_engine)
from sqlalchemy.pool import AsyncAdaptedQueuePool


class DBManager():

  def __init__(self):
    self.DB_URI: str | None = None
    self.engine: AsyncEngine | None = None
    self.scoped_session_factory: async_scoped_session[AsyncSession] | None = None

  def init(self, DB_URI: str) -> None:
    self.DB_URI = DB_URI
    self.engine = create_async_engine(
      self.DB_URI,
      poolclass=AsyncAdaptedQueuePool,
      echo=False,
      pool_pre_ping=True,
      # pool_size=1,
      # max_overflow=0,
    )
    self.scoped_session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

  async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
    """
      Dependency function that yields db sessions
    """
    async with self.scoped_session_factory() as session:  # type: ignore
      yield session


db_manager = DBManager()
