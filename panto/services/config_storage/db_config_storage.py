import uuid
from urllib.parse import urlparse

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from panto.data_models.review_config import ConfigRule
from panto.models.whitelistedaccount import GitAccountProvider, WhitelistedAccount
from panto.services.config_storage.config_storage import ConfigStorageService


class DBConfigStorageService(ConfigStorageService):

  def __init__(self, get_session: async_sessionmaker[AsyncSession]) -> None:
    self.get_session = get_session

  async def whitelist_account(self, provider: str, account: str):
    async with self.get_session() as db_session:
      account = account.lower()
      stmt = select(WhitelistedAccount)
      stmt = stmt.filter_by(provider=provider,
                            account=account).order_by(WhitelistedAccount.created_at.desc())
      result = await db_session.execute(stmt)
      w_account = result.scalar()
      if not w_account:
        w_account = WhitelistedAccount(
          id=str(uuid.uuid4()),
          provider=provider,
          account=account,
          enabled=True,
        )
      w_account.enabled = True
      db_session.add(w_account)
      await db_session.commit()

  async def get_whitelisted_accounts(self, provider: str) -> list[str]:
    async with self.get_session() as db_session:
      stmt = select(WhitelistedAccount)
      stmt = stmt.filter_by(provider=provider, enabled=True)
      result = await db_session.execute(stmt)
      data = [row.account for row in result.scalars()]
      return data

  async def is_whitelisted_account(self, provider: str, repo_url: str) -> bool:
    async with self.get_session() as db_session:
      whitelisted_account = await self._repo_url_to_account(db_session=db_session,
                                                            provider=provider,
                                                            repo_url=repo_url)
      return True if whitelisted_account else False

  async def remove_whitelisted_account(self, provider: str, account: str):
    async with self.get_session() as db_session:
      stmt = update(WhitelistedAccount).filter_by(provider=provider,
                                                  account=account).values(enabled=False)
      await db_session.execute(stmt)
      await db_session.commit()

  async def store_providers_creds(
    self,
    provider: str,
    account_id: str,
    creds: dict,
    account_url: str | None = None,
    account_name: str | None = None,
    account_slug: str | None = None,
  ):
    async with self.get_session() as db_session:
      stmt = select(GitAccountProvider).filter_by(provider_name=provider, provider_id=account_id)
      result = await db_session.execute(stmt)
      account = result.scalar()
      if account:
        if not account.config:
          account.config = {}

        if account_url:
          account.url = account_url

        if account_name:
          account.name = account_name

        if account_slug:
          account.slug = account_slug

        if account.config.get('creds'):
          creds = {**account.config.get('creds'), **creds}
        account.config = {**account.config, 'creds': creds}
        await db_session.commit()
        return

      stmt2 = GitAccountProvider(
        id=str(uuid.uuid4()),
        provider_name=provider,
        provider_id=account_id,
        config={'creds': creds},
        url=account_url,
        name=account_name,
        slug=account_slug,
      )
      db_session.add(stmt2)
      await db_session.commit()

  async def get_providers_creds(self, provider: str, account_id: str) -> dict | None:
    async with self.get_session() as db_session:
      stmt = select(GitAccountProvider).filter_by(provider_name=provider, provider_id=account_id)
      result = await db_session.execute(stmt)
      account = result.scalar()
      return account.config.get('creds') if account and account.config else None

  async def get_review_rules_configs(self, provider: str, repo_url: str) -> list[ConfigRule]:
    async with self.get_session() as db_session:
      account_model = await self._repo_url_to_account(db_session=db_session,
                                                      provider=provider,
                                                      repo_url=repo_url)
      if not account_model:
        raise ValueError(f'Account for {repo_url} not found')

      if not account_model.config:
        return []

      review_rules = account_model.config.get('review_rules') or []
      return [ConfigRule.model_validate(rule) for rule in review_rules]

  async def store_review_rules_configs(self, provider: str, repo_url: str,
                                       rules: list[ConfigRule]):
    async with self.get_session() as db_session:
      account_model = await self._repo_url_to_account(db_session=db_session,
                                                      provider=provider,
                                                      repo_url=repo_url)
      if not account_model:
        raise ValueError(f'Account for {repo_url} not found')

      account_model.config = account_model.config or {}
      exitsing_rules = account_model.config.get('review_rules') or []
      exitsing_rules_model = [ConfigRule.model_validate(rule) for rule in exitsing_rules]
      merged = exitsing_rules_model + rules
      account_model.config['review_rules'] = [rule.model_dump() for rule in merged]

  async def get_account_config(self, provider: str, repo_url: str) -> dict | None:
    async with self.get_session() as db_session:
      account_model = await self._repo_url_to_account(db_session=db_session,
                                                      provider=provider,
                                                      repo_url=repo_url)
      return account_model.config if account_model else None

  async def update_account_config(self, provider: str, repo_url: str, config: dict):
    async with self.get_session() as db_session:
      account_model = await self._repo_url_to_account(db_session=db_session,
                                                      provider=provider,
                                                      repo_url=repo_url)
      if not account_model:
        raise ValueError(f'Account for {repo_url} not found')

      if not account_model.config:
        account_model.config = {}

      account_model.config = {**account_model.config, **config}
      await db_session.commit()

  async def _repo_url_to_account(self,
                                 db_session: AsyncSession,
                                 provider: str,
                                 repo_url: str,
                                 onlyEnabled=True) -> WhitelistedAccount | None:
    org_url = _get_org_url(repo_url).lower()
    git_provider_url = _get_base_url(repo_url).lower() + "/*"
    stmt = select(WhitelistedAccount)
    stmt = stmt.filter_by(provider=provider, enabled=onlyEnabled).filter(
      or_(
        WhitelistedAccount.account.ilike(org_url + '/%'),
        WhitelistedAccount.account == git_provider_url,
      ), )
    dbresult = await db_session.execute(stmt)
    results = list(dbresult.scalars())
    return _select_best_matched_account(results, repo_url)


def _select_best_matched_account(accounts: list[WhitelistedAccount],
                                 account: str) -> WhitelistedAccount | None:

  def match_score(pattern: str, target: str) -> int:
    pattern = pattern.lower()
    target = target.lower()
    if pattern.endswith('*'):
      pattern = pattern[:-1]

    if pattern.endswith("/"):
      pattern = pattern[:-1]

    if target.startswith(pattern):
      return len(pattern)
    return 0

  best_match = None
  highest_score = 0

  if account.endswith(".git"):
    account = account[:-4]

  for acc in accounts:
    score = match_score(acc.account, account)
    if score > highest_score:
      highest_score = score
      best_match = acc

  return best_match


def _get_org_url(url: str):
  parsed_url = urlparse(url)
  domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
  path_parts = parsed_url.path.split('/')
  first_part = path_parts[1] if len(path_parts) > 1 else ''
  if not first_part:
    return domain
  return f"{domain}/{first_part}"


def _get_base_url(url: str):
  parsed_url = urlparse(url)
  return f"{parsed_url.scheme}://{parsed_url.netloc}"
