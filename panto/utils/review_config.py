from typing import TYPE_CHECKING

from panto.data_models.review_config import ReviewConfig, ReviewConfigProject, ReviewScanConfig

if TYPE_CHECKING:
  from panto.services.config_storage.config_storage import ConfigStorageService
  from panto.services.git.git_service import GitService

from .misc import merge_dict


def get_default_review_config(more_info=None) -> ReviewConfig:
  review_config = ReviewConfig(
    enabled=True,
    more_info=more_info,
    scan=ReviewScanConfig(
      includes=[],
      findings=[
        "errors, issues, mistakes, unefficient code, naming conventions, code duplication",
        "security issues",
        "memory leaks, performance issues, null conditions, connection not closed",
        "code complexity",
        'missing buesiness requirements',
      ],
    ),
    project=ReviewConfigProject(languages=[], ),
    review_rules=[],
  )
  return review_config


async def get_review_config(
  gitsrv: "GitService",
  config_storage_srv: "ConfigStorageService",
  pr_no: int,
  repo_url: str,
) -> ReviewConfig:
  repo_url = repo_url.lower()
  pr_description = await gitsrv.get_pr_description(pr_no)
  pr_head_hash = await gitsrv.get_pr_head(pr_no)
  project_review_config = await gitsrv.get_review_config(pr_head_hash, pr_description)
  default_config = get_default_review_config(pr_description)

  if project_review_config and not project_review_config.scan.findings:
    project_review_config.scan.findings = default_config.scan.findings

  review_config_dict = project_review_config.model_dump() if project_review_config else {}
  merged = merge_dict(default_config.model_dump(), review_config_dict)

  merged_model = ReviewConfig.model_validate(merged)
  review_rules = await config_storage_srv.get_review_rules_configs(gitsrv.get_provider(), repo_url)

  if review_rules:
    if not merged_model.review_rules:
      merged_model.review_rules = []
    merged_model.review_rules.extend(review_rules)

  return merged_model
