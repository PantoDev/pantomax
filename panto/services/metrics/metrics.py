import abc
import enum

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session

from panto.config import DEFAULT_METRICS_COLLECTION_SRV
from panto.data_models.git import PostedComment, PRStatus, ReviewStatus
from panto.data_models.pr_review import PRSuggestions
from panto.logging import log
from panto.models.pr import PRReviewDataModel, PRReviewModel
from panto.repository.pr import PRRepository
from panto.repository.pr_review import PRReviewRepository
from panto.services.git.git_service_types import GitServiceType
from panto.services.llm.llm_service import LLMUsage


class MetricsCollectionService(abc.ABC):

  @abc.abstractmethod
  async def pr_open(
    self,
    *,
    repo_id: str | int,
    repo_url: str,
    provider: GitServiceType,
    pr_no: str | int,
    title: str,
    is_reopen: bool,
  ):
    pass

  @abc.abstractmethod
  async def pr_closed(self, repo_id: str | int, provider: GitServiceType, pr_no: str | int):
    pass

  @abc.abstractmethod
  async def pr_status_update(self, repo_id: str | int, provider: GitServiceType, pr_no: str | int,
                             status: PRStatus):
    pass

  @abc.abstractmethod
  async def review_started(
    self,
    *,
    repo_id: str | int,
    gitsrv_type: GitServiceType,
    pr_no: str | int,
    is_incremental_review: bool,
  ):
    pass

  @abc.abstractmethod
  async def review_failed(
    self,
    *,
    repo_id: str | int,
    provider: GitServiceType,
    pr_no: str | int,
    reason: str,
    no_of_files: int,
  ):
    pass

  @abc.abstractmethod
  async def review_completed(
    self,
    pr_no: str | int,
    repo_id: str | int,
    provider: GitServiceType,
    no_of_files: int,
    prsuggestions: PRSuggestions,
    unfiltered_review_count: int,
    final_review_count: int,
    lvl2_review_count: int,
    review_llm_usages: LLMUsage,
    correction_llm_usages: LLMUsage | None,
    reviewed_from: str,
    reviewed_to: str,
    is_soft_review: bool = False,
  ):
    pass

  @abc.abstractmethod
  async def review_commented(
    self,
    pr_no: str | int,
    repo_id: str | int,
    provider: GitServiceType,
    posted_comments: list[PostedComment],
    reviewed_id: str | None = None,
  ):
    pass


class MetricsCollectionType(str, enum.Enum):
  DB = "DB"
  NOOP = "NOOP"


class DBMetricsCollectionService(MetricsCollectionService):

  def __init__(self, get_session: async_scoped_session[AsyncSession]):
    self.get_session = get_session
    self.pr_review_model_id_map: dict[str, str] = {}

  async def pr_open(
    self,
    *,
    repo_id: str | int,
    repo_url: str,
    provider: GitServiceType,
    pr_no: str | int,
    title: str,
    is_reopen: bool,
  ):
    async with self.get_session() as db_session:
      pr_repository = PRRepository(db_session)
      if is_reopen:
        pr = await pr_repository.get_by_repo(repo_id=str(repo_id),
                                             provider=provider,
                                             pr_no=str(pr_no))
        if pr:
          await pr_repository.update_pr_status(pr_status=PRStatus.REOPEN, id=pr.id)
          return

      await pr_repository.create(
        repo_id=str(repo_id),
        repo_url=repo_url,
        provider=provider,
        pr_no=str(pr_no),
        title=title,
        pr_status=PRStatus.REOPEN if is_reopen else PRStatus.OPEN,
      )

  async def pr_closed(self, repo_id: str | int, provider: GitServiceType, pr_no: str | int):
    await self.pr_status_update(
      repo_id=repo_id,
      provider=provider,
      pr_no=pr_no,
      status=PRStatus.CLOSED,
    )

  async def pr_status_update(self, repo_id: str | int, provider: GitServiceType, pr_no: str | int,
                             status: PRStatus):
    async with self.get_session() as db_session:
      pr_repository = PRRepository(db_session)
      await pr_repository.update_pr_status(
        pr_status=status,
        repo_id=str(repo_id),
        provider=provider,
        pr_no=str(pr_no),
      )

  async def review_started(
    self,
    *,
    repo_id: str | int,
    gitsrv_type: GitServiceType,
    pr_no: str | int,
    is_incremental_review: bool,
  ):
    async with self.get_session() as db_session:
      pr_repository = PRRepository(db_session)
      pr_review_repository = PRReviewRepository(db_session)
      pr_no = str(pr_no)
      repo_id = str(repo_id)
      pr = await pr_repository.get_by_repo(repo_id, gitsrv_type, pr_no)
      pr_id = None

      if pr:
        pr.review_status = ReviewStatus.REQUESTED
        pr_id = pr.id
        db_session.add(pr)

      pr_review_model = await pr_review_repository.create(
        repo_id=repo_id,
        pr_no=pr_no,
        pr_id=pr_id,
        provider=gitsrv_type,
        review_type='full' if not is_incremental_review else 'incremental',
        status=ReviewStatus.REQUESTED,
      )
      db_session.add(pr_review_model)
      await db_session.commit()
      await self._set_cached_pr_review_id(repo_id, gitsrv_type, pr_no, pr_review_model.id)

  async def review_failed(
    self,
    repo_id: str | int,
    provider: GitServiceType,
    pr_no: str | int,
    reason: str,
    no_of_files: int,
  ):
    async with self.get_session() as db_session:
      pr_repository = PRRepository(db_session)
      repo_id = str(repo_id)
      pr_no = str(pr_no)
      last_pr_review = await self._get_last_pr_review(repo_id, provider, pr_no)
      assert last_pr_review, "Last PR Review not found"

      pr = await pr_repository.get_by_repo(repo_id, provider, pr_no)
      if pr:
        pr.review_status = ReviewStatus.FAILED
        pr.review_status_reason = reason
        pr.last_review_id = last_pr_review.id
        db_session.add(pr)

      last_pr_review.status = ReviewStatus.FAILED
      last_pr_review.reason = reason
      last_pr_review.no_of_files = no_of_files
      db_session.add(last_pr_review)
      await db_session.commit()

  async def review_completed(
    self,
    pr_no: str | int,
    repo_id: str | int,
    provider: GitServiceType,
    no_of_files: int,
    prsuggestions: PRSuggestions,
    unfiltered_review_count: int,
    final_review_count: int,
    lvl2_review_count: int,
    review_llm_usages: LLMUsage,
    correction_llm_usages: LLMUsage | None,
    reviewed_from: str,
    reviewed_to: str,
    is_soft_review: bool = False,
  ):
    async with self.get_session() as db_session:
      pr_repository = PRRepository(db_session)
      repo_id = str(repo_id)
      pr_no = str(pr_no)
      review_status = ReviewStatus.REVIEWED if not is_soft_review else ReviewStatus.SOFT_REVIEWED
      last_pr_review = await self._get_last_pr_review(repo_id, provider, pr_no)
      assert last_pr_review, "Last PR Review not found"

      pr = await pr_repository.get_by_repo(repo_id, provider, pr_no)
      if pr:
        pr.review_status = review_status
        pr.last_review_id = last_pr_review.id
        db_session.add(pr)

      last_pr_review.status = review_status
      last_pr_review.reviewed_from = reviewed_from
      last_pr_review.reviewed_to = reviewed_to
      last_pr_review.no_of_files = no_of_files
      last_pr_review.unfiltered_review_count = unfiltered_review_count
      last_pr_review.final_review_count = final_review_count
      last_pr_review.lvl2_review_count = lvl2_review_count

      last_pr_review.review_system_token = review_llm_usages.system_token
      last_pr_review.review_user_token = review_llm_usages.user_token
      last_pr_review.review_output_token = review_llm_usages.output_token
      last_pr_review.review_latency = review_llm_usages.latency

      if correction_llm_usages:
        last_pr_review.correction_system_token = correction_llm_usages.system_token
        last_pr_review.correction_user_token = correction_llm_usages.user_token
        last_pr_review.correction_output_token = correction_llm_usages.output_token
        last_pr_review.correction_latency = correction_llm_usages.latency

      db_session.add(last_pr_review)

      if prsuggestions:
        pr_review_data = PRReviewDataModel(
          pr_review_id=last_pr_review.id,
          review_json=prsuggestions.model_dump(),
        )
        db_session.add(pr_review_data)

      await db_session.commit()

  async def review_commented(
    self,
    pr_no: str | int,
    repo_id: str | int,
    provider: GitServiceType,
    posted_comments: list[PostedComment],
    reviewed_id: str | None = None,
  ):
    async with self.get_session() as db_session:
      repo_id = str(repo_id)
      pr_no = str(pr_no)

      if not reviewed_id:
        last_pr_review = await self._get_last_pr_review(repo_id, provider, pr_no)
        assert last_pr_review, "Last PR Review not found"
        reviewed_id = last_pr_review.id

      comments_json = [c.model_dump() for c in posted_comments]
      stmt = update(PRReviewDataModel).filter_by(pr_review_id=reviewed_id).values(
        comment_json=comments_json)
      await db_session.execute(stmt)
      await db_session.commit()

  async def _get_cached_pr_review_id(self, repo_id: str | int, provider: GitServiceType,
                                     pr_no: str | int) -> str | None:
    return self.pr_review_model_id_map.get(f"{repo_id}_{provider}_{pr_no}")

  async def _set_cached_pr_review_id(self, repo_id: str | int, provider: GitServiceType,
                                     pr_no: str | int, pr_review_id: str):
    self.pr_review_model_id_map[f"{repo_id}_{provider}_{pr_no}"] = pr_review_id

  async def _get_last_pr_review(
    self,
    repo_id: str | int,
    provider: GitServiceType,
    pr_no: str | int,
  ) -> PRReviewModel | None:
    async with self.get_session() as db_session:
      last_review_id = await self._get_cached_pr_review_id(repo_id, provider, pr_no)

      if last_review_id:
        stmt = select(PRReviewModel).filter_by(id=last_review_id)
      else:
        stmt = select(PRReviewModel).filter_by(repo_id=repo_id, provider=provider,
                                               pr_no=pr_no).order_by(
                                                 PRReviewModel.created_at.desc()).limit(1)
      result = await db_session.execute(stmt)
      return result.scalar()


class NoopMetricsCollectionService(MetricsCollectionService):

  async def pr_open(
    self,
    *,
    repo_id: str | int,
    repo_url: str,
    provider: GitServiceType,
    pr_no: str | int,
    title: str,
    is_reopen: bool,
  ):
    log.info(f"[metrics]PR Opened: {repo_id} {provider} {pr_no} {title} {is_reopen} {repo_url}")

  async def pr_closed(self, repo_id: str | int, provider: GitServiceType, pr_no: str | int):
    log.info(f"[metrics]PR Closed: {repo_id} {provider} {pr_no}")

  async def pr_status_update(self, repo_id: str | int, provider: GitServiceType, pr_no: str | int,
                             status: PRStatus):
    log.info(f"[metrics]PR Status Update: {repo_id} {provider} {pr_no} {status}")

  async def review_started(
    self,
    *,
    repo_id: str | int,
    gitsrv_type: GitServiceType,
    pr_no: str | int,
    is_incremental_review: bool,
  ):
    log.info(f"[metrics]Review Started: {repo_id} {gitsrv_type} {pr_no} {is_incremental_review}")

  async def review_failed(
    self,
    repo_id: str | int,
    provider: GitServiceType,
    pr_no: str | int,
    reason: str,
    no_of_files: int,
  ):
    log.info(f"[metrics]Review Failed: {repo_id} {provider}"
             f"{pr_no} {reason}, {no_of_files}")

  async def review_completed(
    self,
    pr_no: str | int,
    repo_id: str | int,
    provider: GitServiceType,
    no_of_files: int,
    prsuggestions: PRSuggestions,
    unfiltered_review_count: int,
    final_review_count: int,
    lvl2_review_count: int,
    review_llm_usages: LLMUsage,
    correction_llm_usages: LLMUsage | None,
    reviewed_from: str,
    reviewed_to: str,
    is_soft_review: bool = False,
  ):
    log.info(f"[metrics]Review Completed: {repo_id} {provider}"
             f"{pr_no} {no_of_files} {prsuggestions} {unfiltered_review_count}"
             f"{final_review_count} {lvl2_review_count} {review_llm_usages}"
             f"{correction_llm_usages} {reviewed_from} {reviewed_to}")

  async def review_commented(
    self,
    pr_no: str | int,
    repo_id: str | int,
    provider: GitServiceType,
    posted_comments: list[PostedComment],
    reviewed_id: str | None = None,
  ):
    log.info(f"[metrics]Review Commented: {repo_id} {provider} {pr_no} {posted_comments}")


async def create_metrics_service(
    type: MetricsCollectionType | None = None) -> MetricsCollectionService:
  if not type:
    type = MetricsCollectionType(DEFAULT_METRICS_COLLECTION_SRV)

  if type == MetricsCollectionType.NOOP:
    return NoopMetricsCollectionService()

  if type == MetricsCollectionType.DB:
    from panto.models.db import db_manager
    assert db_manager.scoped_session_factory, "DBManager not initialized"
    return DBMetricsCollectionService(get_session=db_manager.scoped_session_factory)

  raise ValueError(f"Unknown metrics collection type: {type}")
