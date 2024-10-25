import abc
import json
from collections.abc import AsyncGenerator

from panto.data_models.git import GitPatchFile, PostedComment, PRComment, PRPatches
from panto.data_models.pr_review import PRSuggestions
from panto.data_models.review_config import ReviewConfig
from panto.logging import log

from .git_service_types import GitServiceType


class GitService(abc.ABC):

  @abc.abstractmethod
  async def init_service(self, **kvargs):
    pass

  @abc.abstractmethod
  async def add_reaction(self,
                         pull_request_no: int,
                         reaction: str = 'rocket',
                         comment_id: int | None = None) -> None:
    pass

  @abc.abstractmethod
  async def add_review(self, pull_request_no: int,
                       suggestions: PRSuggestions) -> list[PostedComment]:
    pass

  @abc.abstractmethod
  async def add_comment(self, pull_request_no: int, comment: str) -> PostedComment:
    pass

  @abc.abstractmethod
  async def add_review_comment(self, pull_request_no: int,
                               suggestions: PRSuggestions) -> list[PostedComment]:
    pass

  @abc.abstractmethod
  async def clear_all_my_comment(self, pull_request_no: int) -> None:
    pass

  @abc.abstractmethod
  async def get_pr_head(self, pull_request_no: int) -> str:
    pass

  @abc.abstractmethod
  async def get_pr_description(self, pr_no: int) -> str:
    pass

  @abc.abstractmethod
  async def get_pr_title(self, pr_no: int) -> str:
    pass

  @abc.abstractmethod
  async def get_diff_two_commits(self, base: str, head: str) -> list[GitPatchFile]:
    pass

  @abc.abstractmethod
  async def get_file_content(self, filename: str, ref: str) -> str:
    pass

  @abc.abstractmethod
  async def get_pr_patches(self, pr_no: int) -> PRPatches:
    pass

  @abc.abstractmethod
  async def get_comments(self, pull_request_no: int) -> AsyncGenerator[PRComment, None]:
    raise NotImplementedError()
    if False:
      # https://github.com/python/mypy/issues/5070
      yield 0

  @abc.abstractmethod
  async def is_valid_pr_commit(self, pr_no: int, commit_id: str):
    pass

  async def get_review_config(self, ref: str, more_info: str = "") -> ReviewConfig | None:
    try:
      file_content = await self.get_file_content(".panto.json", ref)
      config = json.loads(file_content)
      return ReviewConfig.model_validate(config)
    except Exception as e:
      log.info(f"Error reading .panto.json: {str(e)}")
      return None

  @abc.abstractmethod
  def get_provider(self) -> GitServiceType:
    pass


def create_git_service(service_name: GitServiceType, repo_url: str) -> GitService:
  if service_name == GitServiceType.GITHUB:
    from panto.services.git.github_service import GitHubService
    return GitHubService(repo_url)
  elif service_name == GitServiceType.LOCAL:
    from panto.services.git.gitlocal_service import GitLocalService
    return GitLocalService(repo_url)
  elif service_name == GitServiceType.GITLAB:
    from panto.services.git.gitlab_service import GitLabService
    return GitLabService(repo_url)
  elif service_name == GitServiceType.BITBUCKET:
    from panto.services.git.bitbucket_service import BitBucketService
    return BitBucketService(repo_url)

  raise Exception(f"Unknown service: {service_name}")
