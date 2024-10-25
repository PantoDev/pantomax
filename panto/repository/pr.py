from uuid import uuid4

from sqlalchemy import Result, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from panto.data_models.git import PRStatus, ReviewStatus
from panto.models.pr import PRModel
from panto.services.git.git_service_types import GitServiceType


class PRRepository:

  def __init__(self, db_session: AsyncSession):
    self.db_session = db_session

  def _db_model(self):
    return PRModel

  async def create(
    self,
    *,
    repo_id: str,
    repo_url: str,
    provider: GitServiceType | str,
    pr_no: str,
    title: str,
    pr_status: PRStatus,
    review_status=ReviewStatus.PENDING,
  ):
    if isinstance(provider, GitServiceType):
      provider = provider.value
    pr = PRModel(
      id=str(uuid4()),
      repo_id=repo_id,
      provider=provider,
      pr_no=pr_no,
      title=title,
      pr_status=pr_status,
      repo_url=repo_url,
      review_status=review_status,
    )
    self.db_session.add(pr)
    await self.db_session.commit()
    await self.db_session.refresh(pr)
    return pr

  async def get_by_repo(self, repo_id: str, provider: GitServiceType | str,
                        pr_no: str) -> PRModel | None:
    assert repo_id and provider and pr_no, "repo_id, provider and pr_no must be provided"

    if isinstance(provider, GitServiceType):
      provider = provider.value

    stmt = select(self._db_model())
    stmt = stmt.filter_by(repo_id=repo_id, provider=provider, pr_no=pr_no)
    result: Result = await self.db_session.execute(stmt)
    return result.scalar()

  async def get_many_by_repo(self, repo_id: str, provider: GitServiceType | str,
                             group_id: str) -> list[PRModel]:
    assert repo_id and provider and group_id, "repo_id, provider and group_id must be provided"

    if isinstance(provider, GitServiceType):
      provider = provider.value

    provider = provider.upper()

    stmt = select(self._db_model())
    stmt = stmt.filter_by(repo_id=repo_id, provider=provider)
    result = await self.db_session.execute(stmt)
    return result.scalars()

  async def update(self, pr: PRModel) -> PRModel:
    self.db_session.add(pr)
    await self.db_session.commit()
    return pr

  async def update_pr_status(
    self,
    *,
    pr_status: PRStatus,
    id: str | None = None,
    repo_id: str | None = None,
    provider: GitServiceType | str | None = None,
    pr_no: str | None = None,
  ):

    if isinstance(provider, GitServiceType):
      provider = provider.value

    assert id or (repo_id and provider
                  and pr_no), "id or (repo_id, provider and pr_no) must be provided"

    model = self._db_model()
    stmt = update(model)
    if id:
      stmt = stmt.where(model.id == id)
    else:
      stmt = stmt.where(
        model.repo_id == repo_id,
        model.provider == provider,
        model.pr_no == pr_no,
      )
    stmt = stmt.values(pr_status=pr_status)
    await self.db_session.execute(stmt)
    await self.db_session.commit()
