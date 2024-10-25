from collections.abc import AsyncGenerator
from functools import cache

import aiohttp
from atlassian.bitbucket import Cloud as BitbucketCloud

from panto.data_models.git import CommentType, GitPatchFile, PostedComment, PRComment, PRPatches
from panto.data_models.pr_review import PRSuggestions, Suggestion
from panto.logging import log
from panto.services.git.git_service import GitService
from panto.services.git.git_service_types import GitServiceType
from panto.utils.git import diff_str_to_patchfiles
from panto.utils.misc import repo_url_to_repo_name


class BitBucketService(GitService):

  def __init__(self, repo_url: str):
    self.repo_name = repo_url_to_repo_name(repo_url)
    self.workspace = self.repo_name.split('/')[0]
    self.repo_slug = self.repo_name.split('/')[1]
    self.access_token: str = None  # type: ignore
    self.bitbucket: BitbucketCloud = None  # type: ignore
    self.bitbucket_base_url = "https://api.bitbucket.org/2.0"
    self._this_user_id: str | None = None

  def get_provider(self) -> GitServiceType:
    return GitServiceType.BITBUCKET

  async def init_service(self, **kvargs):
    assert 'access_token' in kvargs, 'access_token is required'
    self.access_token = kvargs['access_token']
    self.bitbucket = BitbucketCloud(token=self.access_token)

  async def add_reaction(self,
                         pull_request_no: int,
                         reaction: str = 'rocket',
                         comment_id: int | None = None) -> None:
    # Bitbucket doesn't support reactions
    if not comment_id:
      return

    reaction_map = {
      'rocket': '🚀',
      'eyes': '👍',
    }
    data = {
      'parent': {
        'id': comment_id
      },
      'content': {
        'raw': reaction_map.get(reaction, '👍')
      },
    }
    url = f'{self.bitbucket_base_url}/repositories/{self.workspace}/{self.repo_slug}/pullrequests/{pull_request_no}/comments'  # noqa

    async with aiohttp.ClientSession() as session:
      self._attach_auth_header_to_session(session)
      async with session.post(url, json=data) as res:
        res.raise_for_status()

  async def add_review(self, pull_request_no: int,
                       suggestions: PRSuggestions) -> list[PostedComment]:
    return await self.add_review_comment(pull_request_no, suggestions)

  async def add_comment(self, pull_request_no: int, comment: str) -> PostedComment:
    pr = self._get_pr(pull_request_no)
    res = pr.comment(comment)
    return PostedComment(id=str(res['id']), type=CommentType.GENERAL)

  async def add_review_comment(self, pull_request_no: int,
                               prsuggestions: PRSuggestions) -> list[PostedComment]:
    postedcomments_map: dict[str, PostedComment] = {}
    comments = [s for s in prsuggestions.suggestions if s.start_line_number != -1]
    overall_comments = [s for s in prsuggestions.suggestions if s.start_line_number == -1]
    overall_msg = ""
    level2_suggestions_ids = [s.id for s in prsuggestions.level2_suggestions
                              ] if prsuggestions.level2_suggestions else []
    if prsuggestions.review_comment:
      overall_msg += prsuggestions.review_comment + "\n\n"

    if overall_comments:
      if len(overall_comments) == 1:
        overall_msg += "**Overall suggestion:** \n\n - " + overall_comments[0].suggestion
      else:
        overall_msg += "**Overall few points:** \n\n" + "\n".join(
          [f" - {s.suggestion}" for s in overall_comments])

    pr = self._get_pr(pull_request_no)
    failed_suggestions: list[Suggestion] = []
    for s in comments:
      successful, comment_id = await self._create_review_comment(pull_request_no, s)
      if successful and comment_id:
        postedcomments_map[s.id] = PostedComment(
          id=comment_id,
          type=CommentType.INLINE,
          cid=s.id,
        )
      if not successful:
        failed_suggestions.append(s)

    if failed_suggestions:
      if overall_msg:
        overall_msg += "\n\n -------------\n**Few more points:**\n"
      else:
        overall_msg += "**Few points:**\n"
      overall_msg += "\n".join([
        f" - {s.file_path} Line:{s.start_line_number} - {s.suggestion}" for s in failed_suggestions
      ])

    if prsuggestions.level2_suggestions:
      overall_msg += "\n--------------\n**Additional Points**\n\n"
      level2_msgs = []
      level2_comments = [s for s in prsuggestions.level2_suggestions if s.start_line_number != -1]
      level2_overall_comments = [
        s for s in prsuggestions.level2_suggestions if s.start_line_number == -1
      ]
      for c in level2_comments:
        line_txt = f"{c.start_line_number}" \
          if c.start_line_number == c.end_line_number \
          else f"{c.start_line_number}-{c.end_line_number}"
        file_path_text = f"{c.file_path}, line:{line_txt}"
        level2_msgs.append(f" - {file_path_text} - {c.suggestion}")

      for c in level2_overall_comments:
        level2_msgs.append(f" - {c.suggestion}")

      overall_msg += "\n".join(level2_msgs)

    if overall_msg:
      commented_res = pr.comment(overall_msg)
      comment_id = str(commented_res['id'])
      postedcomments_map['__review_notes'] = PostedComment(
        id=comment_id,
        type=CommentType.GENERAL,
        cid=None,
        info="review_notes",
      )
      for cid in level2_suggestions_ids:
        postedcomments_map[cid] = PostedComment(
          id=comment_id,
          type=CommentType.GENERAL,
          cid=cid,
          info="level2",
        )
      for c in overall_comments:
        postedcomments_map[c.id] = PostedComment(
          id=comment_id,
          type=CommentType.GENERAL,
          cid=c.id,
          info="overall",
        )
      for c in failed_suggestions:
        postedcomments_map[c.id] = PostedComment(
          id=comment_id,
          type=CommentType.GENERAL,
          cid=c.id,
          info="success_after_retry",
        )

    return list(postedcomments_map.values())

  async def _comment_on_line_number(self, pull_request_no: int, comment: str, file_name: str,
                                    line_number: int) -> dict:
    endpoint = f'{self.bitbucket_base_url}/repositories/{self.workspace}/{self.repo_slug}/pullrequests/{pull_request_no}/comments'  # noqa
    payload = {'content': {'raw': comment}, 'inline': {'path': file_name, 'to': line_number}}
    async with aiohttp.ClientSession() as session:
      self._attach_auth_header_to_session(session)
      async with session.post(endpoint, json=payload) as res:
        res.raise_for_status()
        return await res.json()

  async def _create_review_comment(self, pull_request_no: int, suggestion: Suggestion):
    c = suggestion
    comment_text = c.suggestion
    file_name = c.file_path
    line_number = c.end_line_number
    try:
      res = await self._comment_on_line_number(pull_request_no, comment_text, file_name,
                                               line_number)
      comment_id: str = res['id']
      return True, str(comment_id)
    except Exception as e:
      log.error(f"Error while creating comment: {e}")
      return False, None

  async def clear_all_my_comment(self, pull_request_no: int) -> None:
    my_user_id = await self._get_own_user_id()
    pr = self._get_pr(pull_request_no)
    for comment in pr.comments():
      if comment.user.uuid == my_user_id:
        comment.delete()

  async def get_pr_head(self, pull_request_no: int) -> str:
    pr = self._get_pr(pull_request_no)
    return pr.source_commit

  async def get_pr_description(self, pr_no: int) -> str:
    pr = self._get_pr(pr_no)
    return pr.description

  async def get_diff_two_commits(self, base: str, head: str) -> list[GitPatchFile]:
    url = f'{self.bitbucket_base_url}/repositories/{self.workspace}/{self.repo_slug}/diff/{head}..{base}'  # noqa
    async with aiohttp.ClientSession() as session:
      self._attach_auth_header_to_session(session)
      async with session.get(url) as res:
        res.raise_for_status()
        diff_str = await res.text()
        return diff_str_to_patchfiles(diff_str)

  async def get_file_content(self, filename: str, ref: str) -> str:
    endpoint = f'{self.bitbucket_base_url}/repositories/{self.workspace}/{self.repo_slug}/src/{ref}/{filename}'  # noqa
    async with aiohttp.ClientSession() as session:
      self._attach_auth_header_to_session(session)
      async with session.get(endpoint) as res:
        res.raise_for_status()
        return await res.text()

  async def get_pr_patches(self, pr_no: int) -> PRPatches:
    pr = self._get_pr(pr_no)
    diff_str = pr.diff()
    pathfiles = diff_str_to_patchfiles(diff_str)
    return PRPatches(
      url=pr.url,
      number=pr.id,
      base=pr.destination_commit,
      head=pr.source_commit,
      files=pathfiles,
    )

  async def get_comments(self, pull_request_no: int) -> AsyncGenerator[PRComment, None]:
    own_id = await self._get_own_user_id()
    pr = self._get_pr(pull_request_no)
    for comment in pr.comments():
      is_deleted = comment.data.get('deleted', False)
      if is_deleted:
        continue
      comment_id = comment.data.get('id')
      created_on = comment.data.get('created_on')
      if not comment_id:
        continue
      yield PRComment(
        id=str(comment_id),
        user=comment.user.nickname,
        body=comment.raw,
        created_at=created_on,
        is_our_bot=comment.user.uuid == own_id,
        updated_at=created_on,
      )

  async def get_pr_title(self, pr_no: int) -> str:
    pr = self._get_pr(pr_no)
    return pr.title

  async def is_valid_pr_commit(self, pr_no: int, commit_id: str):
    pr = self._get_pr(pr_no)
    for commit in pr.commits:
      if commit_id == commit['hash']:
        return True

  @cache
  def _get_pr(self, pr_no: int):
    repo = self._get_repo()
    return repo.pullrequests.get(pr_no)

  @cache
  def _get_repo(self):
    workspace = self._get_workspace()
    return workspace.repositories.get(self.repo_slug)

  @cache
  def _get_workspace(self):
    return self.bitbucket.workspaces.get(self.workspace)

  async def _get_own_user_id(self) -> str:
    if self._this_user_id:
      return self._this_user_id
    endpoint = f'{self.bitbucket_base_url}/2.0/user'
    async with aiohttp.ClientSession() as session:
      self._attach_auth_header_to_session(session)
      async with session.get(endpoint) as res:
        res.raise_for_status()
        res_json = await res.json()
        this_user_id = res_json['uuid']
        self._this_user_id = this_user_id
        return this_user_id

  def _attach_auth_header_to_session(self, session: aiohttp.ClientSession):
    session.headers['Authorization'] = f'Bearer {self.access_token}'
    session.headers['Content-Type'] = 'application/json'
    return session
