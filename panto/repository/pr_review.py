import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from panto.data_models.git import ReviewStatus
from panto.models.pr import PRReviewDataModel, PRReviewModel
from panto.services.git.git_service_types import GitServiceType


class PRReviewRepository:

  def __init__(self, db_session: AsyncSession):
    self.db_session = db_session

  def _db_model(self):
    return PRReviewModel

  async def create(
    self,
    repo_id: str,
    pr_no: str,
    pr_id: str | None,
    provider: GitServiceType,
    review_type: str,
    status: ReviewStatus,
  ) -> PRReviewModel:
    pr_review_model = PRReviewModel(
      id=str(uuid.uuid4()),
      repo_id=repo_id,
      pr_no=pr_no,
      provider=provider,
      pr_id=pr_id,
      review_type=review_type,
      status=status,
    )
    self.db_session.add(pr_review_model)
    await self.db_session.commit()
    await self.db_session.refresh(pr_review_model)
    return pr_review_model

  async def get_last_reviews(
    self,
    pr_no: str,
    repo_id: str,
    provider: GitServiceType | str,
    review_type: str | None = None,
    reviewed_to: str | None = None,
  ):
    provider = provider.value if isinstance(provider, GitServiceType) else provider.upper()
    model = self._db_model()
    stmt = select(model).filter_by(pr_no=pr_no, repo_id=repo_id, provider=provider)
    stmt = stmt.filter(
      or_(model.status == ReviewStatus.SOFT_REVIEWED, model.status == ReviewStatus.REVIEWED))
    if review_type:
      stmt = stmt.filter_by(review_type=review_type)

    if reviewed_to:
      stmt = stmt.filter(model.reviewed_to == reviewed_to)

    stmt = stmt.order_by(model.created_at.desc()).limit(1)
    result = await self.db_session.execute(stmt)
    return result.scalar()

  async def get_review_data_by_id(self, review_id: str) -> PRReviewDataModel | None:
    stmt = select(PRReviewDataModel).filter_by(pr_review_id=review_id)
    result = await self.db_session.execute(stmt)
    data = result.scalar()
    return data
