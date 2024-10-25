import base64
import fnmatch
import json

from google.cloud import firestore

from panto.config import ENV, FIREBASE_CREDENTIALS
from panto.data_models.review_config import ConfigRule
from panto.logging import log

from .config_storage import ConfigStorageService


class FirestoreStorageService(ConfigStorageService):

  def __init__(self, client: firestore.Client):
    self.db: firestore.Client = client.collection(f'panto-{ENV}').document('storage')

  async def whitelist_account(self, provider: str, account: str):
    self.db.collection('whitelisted_accounts').document(provider).set({account: True}, merge=True)

  async def is_whitelisted_account(self, provider: str, repo_url: str) -> bool:
    whitelisted_accounts = await self.get_whitelisted_accounts(provider)
    for account in whitelisted_accounts:
      if fnmatch.fnmatch(repo_url, account):
        return True
    return False

  async def remove_whitelisted_account(self, provider: str, account: str):
    self.db.collection('whitelisted_accounts').document(provider).set(
      {account: firestore.DELETE_FIELD}, merge=True)

  async def get_whitelisted_accounts(self, provider: str) -> list[str]:
    doc = self.db.collection('whitelisted_accounts').document(provider).get()
    return list(doc.to_dict().keys()) if doc.exists else []

  async def store_providers_creds(
    self,
    provider: str,
    account_id: str,
    creds: dict,
    account_url: str | None = None,
    account_name: str | None = None,
    account_slug: str | None = None,
  ):
    doc_id = base64.urlsafe_b64encode((provider + "." + account_id).encode()).decode()
    self.db.collection('providers_creds').document(doc_id).set({"creds": creds}, merge=True)

  async def get_providers_creds(self, provider: str, account_id: str) -> dict | None:
    doc_id = base64.urlsafe_b64encode((provider + "." + account_id).encode()).decode()
    doc = self.db.collection('providers_creds').document(doc_id).get()
    return doc.to_dict()["creds"] if doc.exists else None

  async def store_review_rules_configs(self, provider: str, repo_url: str,
                                       rules: list[ConfigRule]):
    log.warning("store_rules_configs not implemented for FirestoreStorageService")

  async def get_review_rules_configs(self, provider: str, repo_url: str) -> list[ConfigRule]:
    log.warning("get_rules_configs not implemented for FirestoreStorageService")
    return []

  async def get_account_config(self, provider: str, repo_url: str) -> dict | None:
    log.warning("get_account_config not implemented for FirestoreStorageService")
    return None

  async def update_account_config(self, provider: str, repo_url: str, config: dict):
    log.warning("update_account_config not implemented for FirestoreStorageService")


class FirebaseClient:
  _firebase_client: firestore.Client | None = None

  @staticmethod
  def init() -> None:
    if FirebaseClient._firebase_client is None:
      assert FIREBASE_CREDENTIALS, "FIREBASE_CREDENTIALS must be set"
      creds = json.loads(FIREBASE_CREDENTIALS)
      FirebaseClient._firebase_client = firestore.Client.from_service_account_info(creds)

  @staticmethod
  def get() -> firestore.Client:
    if FirebaseClient._firebase_client is None:
      FirebaseClient.init()
    return FirebaseClient._firebase_client
