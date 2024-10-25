from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import Mapped

from .base import Base


class TokenConsumption(Base):
  __tablename__ = 'token_consumptions'
  id: Mapped[str] = Column(String, primary_key=True, nullable=False)
  system_token = Column(Integer, nullable=False)
  user_token = Column(Integer, nullable=False)
  output_token = Column(Integer, nullable=False)
  total_token = Column(Integer, nullable=False)
  consumed_at = Column(DateTime, nullable=False)
  consumed_by = Column(String, nullable=True)
  purpose = Column(String, nullable=True)
  var1 = Column(String, nullable=True)
  var2 = Column(String, nullable=True)
  var3 = Column(String, nullable=True)
