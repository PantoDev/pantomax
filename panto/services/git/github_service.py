from collections.abc import AsyncGenerator
from functools import cache

import github
import github.Commit
import github.File
import github.IssueComment
import github.PullRequestComment
import github.Repository

from panto.config import GH_APP_ID, GH_APP_PRIVATE_KEY, GH_BOT_NAME
from panto.data_models.git import (CommentType, GitPatchFile, GitPatchStatus, PostedComment,
                                   PRComment, PRPatches)
from panto.data_models.pr_review import PRSuggestions
from panto.logging import log
from panto.services.git.git_service_types import GitServiceType
from panto.utils.misc import repo_url_to_repo_name

from .git_service import GitService


class GitHubService(GitService):

  def __init__(self, repo_url: str):
    self.repo_name = repo_url_to_repo_name(repo_url)
    self.github: github.Github = None  # type: ignore
    self.repo: github.Repository.Repository = None  # type: ignore
    self.is_app = False

  async def init_service(self, **kvargs):
    installation_id = kvargs.get("installation_id")
    personal_access_token = kvargs.get("personal_access_token")

    assert installation_id or personal_access_token, "Either installation_id or personal_access_token should be provided"  # noqa

    if installation_id:
      # integration = github.GithubIntegration(GITHUB_APP_ID, GITHUB_PRIVATE_KEY)
      # token = integration.get_access_token(installation_id).token
      app_auth = github.Auth.AppAuth(GH_APP_ID, GH_APP_PRIVATE_KEY)
      self.github = github.Github(auth=github.Auth.AppInstallationAuth(app_auth, installation_id))
      self.is_app = True
    else:
      self.github = github.Github(auth=github.Auth.Token(personal_access_token))
      self.is_app = False

    self.repo = self.github.get_repo(self.repo_name)

  async def get_comments(self, pull_request_no: int) -> AsyncGenerator[PRComment, None]:
    pull_request = self._get_pull(pull_request_no)
    comments = pull_request.get_issue_comments().reversed
    for comment in comments:
      is_my_comment = self._is_my_comment(comment)
      yield PRComment(
        id=str(comment.id),
        body=comment.body,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        user=comment.user.login,
        is_our_bot=is_my_comment,
      )

  async def add_reaction(
    self,
    pull_request_no: int,
    reaction: str = 'rocket',
    comment_id: int | None = None,
  ):
    log.info(f"Adding reaction {reaction} to PR {pull_request_no}. Comment ID: {comment_id}")
    issue = self._get_issue(pull_request_no)
    if comment_id:
      comment = issue.get_comment(comment_id)
      comment.create_reaction(reaction)
    else:
      issue.create_reaction(reaction)

  def get_provider(self) -> GitServiceType:
    return GitServiceType.GITHUB

  async def is_valid_pr_commit(self, pr_no: int, commit_id: str):
    pull_request = self._get_pull(pr_no)
    commits = pull_request.get_commits()
    for commit in commits:
      if commit.sha == commit_id:
        return True
    return False

  async def add_review(self, pull_request_no: int,
                       suggestions: PRSuggestions) -> list[PostedComment]:
    suggestions_dict = _feedback_to_github_review_model(suggestions)
    return await self._add_review(pull_request_no, suggestions_dict)

  async def add_review_comment(self, pull_request_no: int,
                               suggestions: PRSuggestions) -> list[PostedComment]:
    suggestions_dict = _feedback_to_github_review_model(suggestions)
    return self._add_review_comment(pull_request_no, suggestions_dict)

  async def add_comment(self, pull_request_no: int, comment: str) -> PostedComment:
    pr = self._get_pull(pull_request_no)
    commented = pr.create_issue_comment(comment)
    return PostedComment(
      id=str(commented.id),
      type=CommentType.GENERAL,
      cid=None,
    )

  async def get_pr_title(self, pr_no: int) -> str:
    return self._get_pull(pr_no).title

  async def _add_review(self, pull_request_no: int, review: dict):
    pull_request = self._get_pull(pull_request_no)
    overall_msg = review.get('overall_msg') or ""
    comments = review['comments']
    github_comments = []
    postedcomments_map: dict[str, PostedComment] = {}

    for comment in comments:
      if comment['start_position'] == comment['end_position']:
        github_comments.append({
          "body": comment['body'],
          "path": comment['path'],
          "position": comment['start_position'],
        })
      else:
        github_comments.append({
          "body": comment['body'],
          "path": comment['path'],
          "start_line": comment['start_position'],
          "line": comment['end_position'],
        })

    log.info(f"Adding review to PR \n\n{github_comments}\n\n")

    try:
      if github_comments:
        commented = pull_request.create_review(
          event="COMMENT",
          comments=github_comments,
        )
        gh_comment_id = str(commented.id)
        for comment in comments:
          postedcomments_map[comment['comment_id']] = PostedComment(
            id=gh_comment_id,
            type=CommentType.REVIEW,
            cid=comment['comment_id'],
          )

      if overall_msg:
        issue = self._get_issue(pull_request_no)
        commented = issue.create_comment(overall_msg)
        gh_comment_id = str(commented.id)
        postedcomments_map['__overall'] = PostedComment(
          id=gh_comment_id,
          type=CommentType.GENERAL,
          cid=None,
          info="overall",
        )
      return list(postedcomments_map.values())
    except Exception as e:
      log.info(f"Error adding review. fallback to adding comments. {e}")
      return self._add_review_comment(pull_request_no, review)

  @cache
  def _get_last_commit(self, pull_request_no: int) -> github.Commit.Commit:
    pull_request = self._get_pull(pull_request_no)
    return pull_request.get_commits().reversed[0]

  def _add_review_comment(self, pull_request_no: int, review: dict) -> list[PostedComment]:
    postedcomments_map: dict[str, PostedComment] = {}
    pull_request = self._get_pull(pull_request_no)
    commit = self._get_last_commit(pull_request_no)
    comments = review.get('comments') or []
    overall_msg = review.get('overall_msg') or ""
    overall_msg_ids = review.get('overall_msg_ids') or []
    level2_msg_ids = review.get('level2_msg_ids') or []

    failed_comments: list = []
    for comment in comments:
      try:
        body = comment['body']
        path = comment['path']
        start_position = comment['start_position']
        end_position = comment['end_position']
        log.info(
          f"Adding comment to PR {pull_request_no} at {path}:{start_position}:{end_position}")
        if start_position == end_position:
          commented = pull_request.create_review_comment(body, commit, path, end_position)
        else:
          commented = pull_request.create_review_comment(body,
                                                         commit,
                                                         path,
                                                         start_line=start_position,
                                                         line=end_position)
        gh_comment_id = str(commented.id)
        postedcomments_map[comment['comment_id']] = PostedComment(
          id=gh_comment_id,
          type=CommentType.INLINE,
          cid=comment['comment_id'],
        )

      except Exception as e:
        log.info(f"Error adding comment: {e}")
        failed_comments.append(comment)

    if failed_comments:
      if overall_msg:
        overall_msg += "\n\n -------------\n Few more points:\n"
      else:
        overall_msg += "Few points:\n"
      overall_msg += "\n".join([f" - {s['body']}" for s in failed_comments])

    if overall_msg:
      issue = self._get_issue(pull_request_no)
      commented = issue.create_comment(overall_msg)
      gh_comment_id = str(commented.id)
      postedcomments_map['__review_notes'] = PostedComment(
        id=gh_comment_id,
        type=CommentType.GENERAL,
        cid=None,
        info="review_notes",
      )
      for i in overall_msg_ids:
        postedcomments_map[i] = PostedComment(
          id=gh_comment_id,
          type=CommentType.GENERAL,
          cid=i,
          info="overall",
        )
      for i in level2_msg_ids:
        postedcomments_map[i] = PostedComment(
          id=gh_comment_id,
          type=CommentType.GENERAL,
          cid=i,
          info="level2",
        )
      if failed_comments:
        for i in failed_comments:
          postedcomments_map[i["comment_id"]] = PostedComment(
            id=gh_comment_id,
            type=CommentType.GENERAL,
            cid=i["comment_id"],
            info="success_after_retry",
          )

    return list(postedcomments_map.values())

  async def clear_all_my_comment(self, pull_request_no):
    pull_request = self._get_pull(pull_request_no)
    comments = pull_request.get_review_comments()
    # current_user_id = self._get_token_user_id()

    for comment in comments:
      if self._is_my_comment(comment):
        comment.delete()

    issues = self._get_issue(pull_request_no)
    comments = issues.get_comments()
    for comment in comments:
      if self._is_my_comment(comment):
        comment.delete()

  async def get_pr_head(self, pull_request_no: int) -> str:
    pr = self._get_pull(pull_request_no)
    return pr.head.sha

  async def get_pr_description(self, pr_no: int) -> str:
    return self._get_pull(pr_no).body

  @cache
  async def get_file_content(self, filename: str, ref: str) -> str:
    content = self.repo.get_contents(filename, ref)
    return content.decoded_content.decode('utf-8')  # type: ignore

  async def get_diff_two_commits(self, base: str, head: str) -> list[GitPatchFile]:
    compare = self.repo.compare(base, head)
    return _map_github_files_to_patch_files(compare.files)

  async def get_pr_patches(self, pr_no: int) -> PRPatches:
    pr = self._get_pull(pr_no)
    patch_files: list[GitPatchFile] = []

    github_files = list(pr.get_files())
    patch_files = _map_github_files_to_patch_files(github_files)

    return PRPatches(
      url=pr.diff_url,
      number=pr.number,
      base=pr.base.sha,
      head=pr.head.sha,
      files=patch_files,
    )

  @cache
  def _get_pull(self, pr_no: int):
    return self.repo.get_pull(pr_no)

  @cache
  def _get_issue(self, issue_no: int):
    return self.repo.get_issue(issue_no)

  def _is_my_comment(self, comment: github.IssueComment.IssueComment
                     | github.PullRequestComment.PullRequestComment):
    if self.is_app:
      return comment.user.login.lower() == GH_BOT_NAME.lower()
    current_user_id = self._get_token_user_id()
    return comment.user.id == current_user_id

  @cache
  def _get_token_user_id(self):
    return self.github.get_user().id


def _map_github_files_to_patch_files(github_files: list[github.File.File]) -> list[GitPatchFile]:
  patch_files: list[GitPatchFile] = []
  status_map = {
    'added': GitPatchStatus.ADDED,
    'modified': GitPatchStatus.MODIFIED,
    'removed': GitPatchStatus.REMOVED,
    'renamed': GitPatchStatus.RENAMED,
  }
  for file in github_files:
    if file.status not in status_map:
      log.info(f"Skipping file {file.filename} with status {file.status} as unknown status")
      continue

    status = status_map[file.status]

    git_file = GitPatchFile(
      filename=file.filename,
      status=status,
      patch=file.patch or "",
      old_filename=file.previous_filename,
    )

    patch_files.append(git_file)

  return patch_files


def _feedback_to_github_review_model(prsuggestions: PRSuggestions):
  comments = [s for s in prsuggestions.suggestions if s.start_line_number != -1]
  overall_suggestions = [s for s in prsuggestions.suggestions if s.start_line_number == -1]
  overall_msg = ""
  overall_msg_ids = []
  level2_msg_ids = []

  if prsuggestions.review_comment:
    overall_msg += prsuggestions.review_comment + "\n\n"

  if overall_suggestions:
    if len(overall_suggestions) == 1:
      overall_msg += "Overall suggestion:\n - " + overall_suggestions[0].suggestion
    else:
      overall_msg += "Overall few points:\n" + "\n".join(
        [f" - {s.suggestion}" for s in overall_suggestions])
    overall_msg_ids += [s.id for s in overall_suggestions]

  if prsuggestions.level2_suggestions:
    level2_msgs = []
    level2_comments = [s for s in prsuggestions.level2_suggestions if s.start_line_number != -1]
    level2_overall_comments = [
      s for s in prsuggestions.level2_suggestions if s.start_line_number == -1
    ]
    level2_msg_ids += [s.id for s in prsuggestions.level2_suggestions]

    if level2_comments:
      for c in level2_comments:
        line_txt = f"{c.start_line_number}" \
          if c.start_line_number == c.end_line_number \
          else f"{c.start_line_number}-{c.end_line_number}"
        file_path_text = f"{c.file_path}, line:{line_txt}"
        level2_msgs.append(
          f"<details open> <summary>\n{file_path_text}\n</summary>\n{c.suggestion}\n</details>")

    if level2_overall_comments:
      txt = ""
      for c in level2_overall_comments:
        txt += f" - {c.suggestion}\n"
      level2_msgs.append(f"<details open> <summary>Others</summary>\n{txt}\n</details>")

    level2_points = f"""\n\
<details>
  <summary>Additional Suggestion</summary>
  {"\n".join(level2_msgs)}
</details>
""" if level2_msgs else None

    if level2_points:
      overall_msg += level2_points

  github_review = {
    "overall_msg": overall_msg if overall_msg else None,
    "overall_msg_ids": overall_msg_ids,
    "level2_msg_ids": level2_msg_ids,
    "comments": [{
      "body": c.suggestion,
      "path": c.file_path,
      "start_position": c.start_line_number,
      "end_position": c.end_line_number,
      "comment_id": c.id,
    } for c in comments]
  }
  return github_review
