import os
from collections.abc import AsyncGenerator
from datetime import datetime

import git

from panto.data_models.git import CommentType, GitPatchFile, PostedComment, PRComment, PRPatches
from panto.data_models.pr_review import PRSuggestions
from panto.logging import log
from panto.services.git.git_service import GitService
from panto.services.git.git_service_types import GitServiceType
from panto.utils.git import diff_str_to_patchfiles


class GitLocalService(GitService):

  def __init__(self, repo_url: str) -> None:
    self.repo_url = repo_url
    self.feature_branch: str = None  # type: ignore
    self.base_branch: str = None  # type: ignore
    self.repo: git.Repo = None  # type: ignore

  def get_provider(self) -> GitServiceType:
    return GitServiceType.LOCAL

  async def init_service(self, **kvargs) -> None:
    assert 'feature_branch' in kvargs, "feature_branch is required"
    assert 'base_branch' in kvargs, "base_branch is required"
    self.feature_branch = kvargs['feature_branch']
    self.base_branch = kvargs['base_branch']
    clone_folder_path = _get_clone_folder_path(self.repo_url)
    self.repo = _git_checkout_repo(self.repo_url, clone_folder_path, self.feature_branch,
                                   self.base_branch)

  async def get_diff_two_commits(self, base: str, head: str) -> list[GitPatchFile]:
    return self._git_diff(base, head)

  async def add_reaction(self,
                         pull_request_no: int,
                         reaction: str = 'rocket',
                         comment_id: int | None = None) -> None:
    log.info(f"Adding reaction {reaction} to PR {pull_request_no}. Comment ID: {comment_id}")

  async def is_valid_pr_commit(self, pr_no: int, commit_id: str):
    commits = list(self.repo.iter_commits(f'{self.base_branch}..{self.feature_branch}'))
    commit_ids = [commit.hexsha for commit in commits]
    return commit_id in commit_ids

  async def add_review(self, pull_request_no: int,
                       suggestions: PRSuggestions) -> list[PostedComment]:
    log.info(f"Adding review to PR {pull_request_no}")
    result: list[PostedComment] = []
    idx = 0
    for s in suggestions.suggestions:
      log.info(
        f"{s.suggestion} on {s.file_path} from line {s.start_line_number} to {s.end_line_number}")
      result.append(PostedComment(
        id=str(idx + 1),
        type=CommentType.INLINE,
      ))
    return result

  async def add_comment(self, pull_request_no: int, comment: str) -> PostedComment:
    log.info(f"Adding comment to PR {pull_request_no}: {comment}")
    return PostedComment(id="-1", type=CommentType.GENERAL)

  async def add_review_comment(self, pull_request_no: int,
                               suggestions: PRSuggestions) -> list[PostedComment]:
    log.info(f"Adding comments to PR {pull_request_no}")
    idx = 0
    result: list[PostedComment] = []
    for s in suggestions.suggestions:
      log.info(
        f"{s.suggestion} on {s.file_path} from line {s.start_line_number} to {s.end_line_number}")
      result.append(PostedComment(
        id=str(idx + 1),
        type=CommentType.INLINE,
      ))

    return result

  async def clear_all_my_comment(self, pull_request_no: int) -> None:
    log.info(f"Clearing all comments on PR {pull_request_no}")

  async def get_pr_head(self, pull_request_no: int) -> str:
    return self.feature_branch

  async def get_pr_description(self, pr_no: int) -> str:
    return ""

  async def get_pr_title(self, pr_no: int) -> str:
    return ""

  async def get_file_content(self, filename: str, ref: str) -> str:
    return self.repo.git.show(f"{ref}:{filename}")

  async def get_pr_patches(self, pr_no: int) -> PRPatches:
    files = self._git_diff(self.base_branch, self.feature_branch)
    pr_patch = PRPatches(url="",
                         number=pr_no,
                         base=self.base_branch,
                         head=self.feature_branch,
                         files=files)
    return pr_patch

  async def get_comments(self, pull_request_no: int) -> AsyncGenerator[PRComment, None]:
    yield PRComment(
      id=str(2),
      body="Comment 1",
      created_at=datetime.now(),
      updated_at=datetime.now(),
      user="user1",
      is_our_bot=False,
    )
    yield PRComment(
      id=str(2),
      body="Comment 2",
      created_at=datetime.now(),
      updated_at=datetime.now(),
      user="user2",
      is_our_bot=False,
    )

  def _git_diff(self, base, head) -> list[GitPatchFile]:
    diff_str = self.repo.git.diff(base, head)
    return diff_str_to_patchfiles(diff_str)


def _git_checkout_repo(repo_url: str,
                       folder: str,
                       feature_branch: str,
                       base_branch='main') -> git.Repo:
  log.info(f"Cloning repo {repo_url}:{feature_branch} to {folder}")
  if not os.path.exists(folder):
    repo = git.Repo.clone_from(repo_url, folder, branch=feature_branch)
  else:
    repo = git.Repo(folder)

  _git_remote_pull(repo)
  repo.git.checkout(base_branch)
  _get_pull(repo)
  repo.git.checkout(feature_branch)
  _get_pull(repo)

  return repo


def _git_remote_pull(repo: git.Repo, raise_exception: bool = False):
  try:
    remote_name = _git_remote_name(repo)
    repo.remotes[remote_name].pull()
  except Exception as e:
    if raise_exception:
      raise e


def _get_pull(repo: git.Repo, raise_exception: bool = False):
  try:
    return repo.git.pull()
  except Exception as e:
    if raise_exception:
      raise e
    return None


def _git_remote_name(repo: git.Repo):
  return repo.remotes[0].name


def _get_clone_folder_path(repo_url: str):
  root_clone_path = "tmp"
  subpath = _get_repo_name_and_owner(repo_url)
  return os.path.join(root_clone_path, subpath)


def _get_repo_name_and_owner(repo_url):
  repo_name_with_owner = repo_url.split(':')[1].replace('.git', '')
  return repo_name_with_owner
