import functools
import os

import click

from panto.config import DB_URI, GPT_MAX_TOKENS, OPENAI_API_KEY, OPENAI_MODEL
from panto.logging import log
from panto.ops.pr_review_actions import PRActions
from panto.services.config_storage.config_storage import create_config_storage_service
from panto.services.git.git_service import GitService, create_git_service
from panto.services.git.git_service_types import GitServiceType
from panto.services.llm.llm_service import LLMService, LLMServiceType, create_llm_service
from panto.services.metrics.metrics import MetricsCollectionType, create_metrics_service
from panto.services.notification import create_notification_service
from panto.services.notification.notification import NotificationServiceType
from panto.utils.misc import ssh_to_http_url

# sample config
DEFAULT_REPO_SSH_URL = os.getenv("DEFAULT_REPO_SSH_URL")
DEFAULT_PR_NO = os.getenv("DEFAULT_PR_NO")
DEFAULT_FEATURE_BRANCH = os.getenv("DEFAULT_FEATURE_BRANCH")
DEFAULT_MAIN_BRANCH = os.getenv("DEFAULT_MAIN_BRANCH")
GITHUB_INSTALLATION_ID = os.getenv("GITHUB_INSTALLATION_ID")


def make_sync(func):

  @functools.wraps(func)
  def wrapper(*args, **kwargs):
    import asyncio
    return asyncio.run(func(*args, **kwargs))

  return wrapper


async def _init_gitsrv(gitsrv_type: GitServiceType,
                       repo: str,
                       feature_branch: str = "",
                       base_branch: str = "",
                       skip_init=False) -> GitService:

  if gitsrv_type == GitServiceType.GITHUB:
    gitsrv = create_git_service(GitServiceType.GITHUB, repo_url=repo)
    if not skip_init:
      await gitsrv.init_service(installation_id=GITHUB_INSTALLATION_ID)
  elif gitsrv_type == GitServiceType.LOCAL:
    gitsrv = create_git_service(GitServiceType.LOCAL, repo_url=repo)
    if not skip_init:
      await gitsrv.init_service(feature_branch=feature_branch, base_branch=base_branch)
  else:
    raise NotImplementedError(f"Unspported gitsrv_type: {gitsrv_type}")

  return gitsrv


async def _init_llmsrv(llm_type: LLMServiceType) -> LLMService:
  if llm_type == LLMServiceType.NOOP:
    llmsrv = await create_llm_service(service_name=LLMServiceType.NOOP)
  elif llm_type == LLMServiceType.OPENAI:
    llmsrv = await create_llm_service(
      service_name=LLMServiceType.OPENAI,
      max_tokens=GPT_MAX_TOKENS,
      api_key=OPENAI_API_KEY,
      model=OPENAI_MODEL,
    )
  else:
    raise NotImplementedError(f"Unspported llm_type: {llm_type}")

  return llmsrv


async def run_review(repo_ssh_url,
                     pr_no,
                     feature_branch,
                     base_branch,
                     llm_type=LLMServiceType.NOOP,
                     gitsrv_type=GitServiceType.LOCAL):
  notification_srv = create_notification_service(NotificationServiceType.NOOP)
  gitsrv = await _init_gitsrv(gitsrv_type, repo_ssh_url, feature_branch, base_branch)
  llmsrv = await _init_llmsrv(llm_type)
  repo_http_url = ssh_to_http_url(repo_ssh_url)
  repo_ssh_url = repo_ssh_url
  comment_body = "review"
  comment_id = 1
  metric_srv = await create_metrics_service(MetricsCollectionType.NOOP)
  config_storage_srv = await create_config_storage_service()
  await PRActions.on_review_request(
    gitsrv=gitsrv,
    pr_no=pr_no,
    pr_title="This is PR TITLE",
    repo_url=repo_http_url,
    notification_srv=notification_srv,
    comment_body=comment_body,
    comment_id=comment_id,
    llmsrv=llmsrv,
    repo_id="000",
    metric_srv=metric_srv,
    config_storage_srv=config_storage_srv,
  )


async def run_clear_comments(repo_url: str, pr_no: int, gitsrv_type: GitServiceType):
  gitsrv = await _init_gitsrv(gitsrv_type, repo_url, skip_init=gitsrv_type == GitServiceType.LOCAL)
  await PRActions.delete_all_comments(gitsrv, pr_no, comment_id=0)
  log.info("All comments cleared")


@click.group()
def cli():
  pass


@cli.command()
@click.option('--repo', default=DEFAULT_REPO_SSH_URL, help='SSH Repository URL')
@click.option('--pr-no', default=DEFAULT_PR_NO, help='Pull Request number')
@click.option('--feature-branch', default=DEFAULT_FEATURE_BRANCH, help='Feature branch')
@click.option('--base-branch', default=DEFAULT_MAIN_BRANCH, help='Base branch')
@click.option(
  '--llmsrv-type',
  type=click.Choice(LLMServiceType),  # type: ignore
  default=LLMServiceType.NOOP,
  help='LLM Type')
@click.option(
  '--gitsrv-type',
  type=click.Choice(GitServiceType),  # type: ignore
  default=GitServiceType.LOCAL,
  help='Git Service Type')
@make_sync
async def review(repo, pr_no, feature_branch, base_branch, llmsrv_type, gitsrv_type):
  await run_review(repo, pr_no, feature_branch, base_branch, llmsrv_type, gitsrv_type)


@cli.command()
@click.option('--repo', default=DEFAULT_REPO_SSH_URL, help='Repository URL')
@click.option('--pr-no', default=DEFAULT_PR_NO, help='Pull Request number')
@click.option(
  '--gitsrv-type',
  type=click.Choice(GitServiceType),  # type: ignore
  default=GitServiceType.LOCAL,
  help='Git Service Type')
@make_sync
async def clear(repo, pr_no, gitsrv_type):
  await run_clear_comments(repo, pr_no, gitsrv_type)


if __name__ == '__main__':
  if DB_URI:
    from panto.models.db import db_manager
    db_manager.init(DB_URI)
  cli()
