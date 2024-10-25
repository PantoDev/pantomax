from sqlalchemy import Boolean, Column, Index, String
from sqlalchemy.dialects.postgresql import JSONB

from .base import AuditMixin, Base


class WhitelistedAccount(Base, AuditMixin):
  __tablename__ = 'accounts'
  id: str = Column(String, primary_key=True, nullable=False)
  provider = Column(String, nullable=False)
  account = Column(String, nullable=False)
  enabled = Column(Boolean, nullable=False)
  config = Column(JSONB, nullable=True)


Index('idx_accounts_whitelistprovider_account', WhitelistedAccount.provider,
      WhitelistedAccount.account)


class GitAccountProvider(Base, AuditMixin):
  __tablename__ = 'git_account_providers'
  id: str = Column(String, primary_key=True, nullable=False)
  provider_name = Column(String, nullable=False)
  provider_id = Column(String, nullable=False)
  config = Column(JSONB, nullable=True)
  url = Column(String, nullable=True)
  name = Column(String, nullable=True)
  slug = Column(String, nullable=True)


Index('idx_git_account_providers_provider_name_provider_id', GitAccountProvider.provider_name,
      GitAccountProvider.provider_id)
