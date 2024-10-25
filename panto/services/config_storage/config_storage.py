import abc
import enum

from panto.config import DEFAULT_CONFIG_STORAGE_SRV
from panto.data_models.review_config import ConfigRule


class ConfigStorageService(abc.ABC):

  @abc.abstractmethod
  async def whitelist_account(self, provider: str, account: str):
    pass

  @abc.abstractmethod
  async def is_whitelisted_account(self, provider: str, repo_url: str) -> bool:
    pass

  @abc.abstractmethod
  async def get_whitelisted_accounts(self, provider: str) -> list[str]:
    pass

  @abc.abstractmethod
  async def remove_whitelisted_account(self, provider: str, account: str):
    pass

  @abc.abstractmethod
  async def store_providers_creds(
    self,
    provider: str,
    account_id: str,
    creds: dict,
    account_url: str | None = None,
    account_name: str | None = None,
    account_slug: str | None = None,
  ):
    pass

  @abc.abstractmethod
  async def get_providers_creds(self, provider: str, account_id: str) -> dict | None:
    pass

  @abc.abstractmethod
  async def store_review_rules_configs(self, provider: str, repo_url: str,
                                       rules: list[ConfigRule]):
    pass

  @abc.abstractmethod
  async def get_review_rules_configs(self, provider: str, repo_url: str) -> list[ConfigRule]:
    pass

  @abc.abstractmethod
  async def get_account_config(self, provider: str, repo_url: str) -> dict | None:
    return None

  @abc.abstractmethod
  async def update_account_config(self, provider: str, repo_url: str, config: dict):
    pass


class ConfigStorageServiceType(str, enum.Enum):
  FIRESTORE = "FIRESTORE"
  DB = "DB"
  NOOP = "NOOP"


async def create_config_storage_service(
    type: ConfigStorageServiceType | None = None) -> ConfigStorageService:

  if not type:
    type = ConfigStorageServiceType(DEFAULT_CONFIG_STORAGE_SRV)

  if type == ConfigStorageServiceType.NOOP:
    from .noop_config_storage import NoopConfigStorageService
    return NoopConfigStorageService()

  if type == ConfigStorageServiceType.FIRESTORE:
    from .firestore_config_storage import FirebaseClient, FirestoreStorageService
    return FirestoreStorageService(client=FirebaseClient.get())

  if type == ConfigStorageServiceType.DB:
    from panto.models.db import db_manager

    from .db_config_storage import DBConfigStorageService
    return DBConfigStorageService(get_session=db_manager.scoped_session_factory)

  raise ValueError(f"Unknown storage service type: {type}")
