from sqlalchemy import Column, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped

from .base import AuditMixin, Base


class PRModel(Base, AuditMixin):
  __tablename__ = 'prs'
  id: Mapped[str] = Column(String, primary_key=True, nullable=False)
  repo_id = Column(String, nullable=False)
  provider = Column(String, nullable=False)
  pr_no = Column(String, nullable=False)
  title = Column(String, nullable=True)
  pr_status = Column(String, nullable=True)
  review_status = Column(String, nullable=True)
  review_status_reason = Column(String, nullable=True)
  last_review_id = Column(String, nullable=True)
  repo_url = Column(String, nullable=True)


class PRReviewModel(Base, AuditMixin):
  __tablename__ = 'pr_reviews'
  id: Mapped[str] = Column(String, primary_key=True, nullable=False)
  repo_id = Column(String, nullable=False)
  pr_no = Column(String, nullable=False)
  provider = Column(String, nullable=False)
  status = Column(String, nullable=True)
  reason = Column(String, nullable=True)
  no_of_files = Column(Integer, nullable=True)
  pr_id = Column(String, nullable=True)  # pr.id from PR table
  review_type = Column(String, nullable=True)  # full, incremental
  reviewed_from = Column(String, nullable=True)  # sha
  reviewed_to = Column(String, nullable=True)  # sha
  unfiltered_review_count = Column(Integer, nullable=True)
  final_review_count = Column(Integer, nullable=True)
  lvl2_review_count = Column(Integer, nullable=True)
  review_system_token = Column(Integer, nullable=True)
  review_user_token = Column(Integer, nullable=True)
  review_output_token = Column(Integer, nullable=True)
  review_latency = Column(Integer, nullable=True)
  correction_system_token = Column(Integer, nullable=True)
  correction_user_token = Column(Integer, nullable=True)
  correction_output_token = Column(Integer, nullable=True)
  correction_latency = Column(Integer, nullable=True)


class PRReviewDataModel(Base, AuditMixin):
  __tablename__ = 'pr_review_data'
  pr_review_id = Column(String, nullable=False, primary_key=True)
  review_json = Column(JSONB, nullable=True)
  comment_json = Column(JSONB, nullable=True)


class PRReviewStats(Base, AuditMixin):
  __tablename__ = 'pr_review_stats'
  id: Mapped[str] = Column(String, primary_key=True, nullable=False)
  repo_id = Column(String, nullable=False)
  pr_no = Column(String, nullable=False)
  provider = Column(String, nullable=False)
  pr_id = Column(String, nullable=False)
  pr_no = Column(String, nullable=False)
  comment_id = Column(String, nullable=False)
  comment = Column(String, nullable=True)
  like_count = Column(Integer, nullable=True)
  dislike_count = Column(Integer, nullable=True)


Index("idx_prs_repo_id_pr_no_provider",
      PRModel.repo_id,
      PRModel.pr_no,
      PRModel.provider,
      unique=True)
Index("idx_pr_reviews_repo_id_pr_no_provider", PRReviewModel.repo_id, PRReviewModel.pr_no,
      PRReviewModel.provider)
Index("idx_pr_review_stats_repo_id_pr_no_provider", PRReviewStats.repo_id, PRReviewStats.pr_no,
      PRReviewStats.provider)
