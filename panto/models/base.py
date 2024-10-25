from datetime import datetime

import pytz
from sqlalchemy import Column, DateTime
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
  pass


class AuditMixin:
  created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.UTC))
  updated_at = Column(DateTime(timezone=True),
                      default=lambda: datetime.now(pytz.UTC),
                      onupdate=lambda: datetime.now(pytz.UTC))
