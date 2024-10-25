import os

from panto.data_models.review_config import ConfigRule
from panto.logging import log
from panto.services.config_storage.config_storage import ConfigStorageService


class NoopConfigStorageService(ConfigStorageService):

  async def whitelist_account(self, provider: str, account: str):
    log.info(f"[NOOP]Whitelisting account {account} for provider {provider}")

  async def is_whitelisted_account(self, provider: str, repo_url: str) -> bool:
    log.info(f"[NOOP]Checking if account is whitelisted for provider {provider}")
    accounts = await self.get_whitelisted_accounts(provider)
    for account in accounts:
      if account.endswith("*"):
        account = account[:-1]
      if not account.endswith("/"):
        account = account + "/"
      if repo_url.startswith(account):
        return True
    return False

  async def get_whitelisted_accounts(self, provider: str) -> list[str]:
    log.info(f"[NOOP]Getting whitelisted accounts for provider {provider}")
    only_whitelisted_accounts = os.getenv("ONLY_WHITELISTED_ACCOUNTS")
    if only_whitelisted_accounts:
      return list(map(lambda x: x.strip(), only_whitelisted_accounts.split(",")))
    return []

  async def remove_whitelisted_account(self, provider: str, account: str):
    log.info(f"[NOOP]Removing whitelisted account {account} for provider {provider}")

  async def store_providers_creds(
    self,
    provider: str,
    account_id: str,
    creds: dict,
    account_url: str | None = None,
    account_name: str | None = None,
    account_slug: str | None = None,
  ):
    log.info(f"[NOOP]Storing credentials for provider {provider} and account {account_id}")

  async def get_providers_creds(self, provider: str, account_id: str) -> dict | None:
    log.info(f"[NOOP]Getting credentials for provider {provider} and account {account_id}")
    return None

  async def store_review_rules_configs(self, provider: str, repo_url: str,
                                       rules: list[ConfigRule]):
    log.info(f"[NOOP]Storing review rules for provider {provider} and repo {repo_url}")

  async def get_review_rules_configs(self, provider: str, repo_url: str) -> list[ConfigRule]:
    log.info(f"[NOOP]Getting review rules for provider {provider} and repo {repo_url}")
    return []

  async def get_account_config(self, provider: str, repo_url: str) -> dict | None:
    log.info(f"[NOOP]Getting account config for provider {provider} and repo {repo_url}")
    return None

  async def update_account_config(self, provider: str, repo_url: str, config: dict):
    log.info(f"[NOOP]Storing account config for provider {provider} and repo {repo_url}")
