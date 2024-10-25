from collections.abc import AsyncGenerator
from functools import cache

import gitlab

from panto.data_models.git import CommentType, GitPatchFile, PostedComment, PRComment, PRPatches
from panto.data_models.pr_review import PRSuggestions, Suggestion
from panto.logging import log
from panto.services.git.git_service import GitService
from panto.services.git.git_service_types import GitServiceType
from panto.utils.git import gitlab_diff_to_patch_files
from panto.utils.misc import repo_url_to_repo_name


class GitLabService(GitService):

  def __init__(self, repo_url: str):
    self.gitlab: gitlab.Gitlab = None  # type: ignore
    self.repo_name = repo_url_to_repo_name(repo_url)

  def get_provider(self) -> GitServiceType:
    return GitServiceType.GITLAB

  async def init_service(self, **kvargs):
    assert 'gitlab_ins_url' in kvargs, 'gitlab_ins_url is required'
    assert 'oauth_token' in kvargs, 'oauth_token is required'
    gitlab_ins_url = kvargs['gitlab_ins_url']
    oauth_token = kvargs['oauth_token']
    self.gitlab = gitlab.Gitlab(url=gitlab_ins_url, private_token=oauth_token)
    self.gitlab.auth()

  async def add_reaction(self,
                         pull_request_no: int,
                         reaction: str = 'rocket',
                         comment_id: int | None = None) -> None:
    try:
      if not comment_id:
        self._get_mr(pull_request_no).awardemojis.create({'name': reaction})
      else:
        self._get_mr(pull_request_no).notes.get(comment_id).awardemojis.create({'name': reaction})
    except gitlab.GitlabCreateError:
      pass

  async def add_review(self, pull_request_no: int,
                       suggestions: PRSuggestions) -> list[PostedComment]:
    return await self.add_review_comment(pull_request_no, suggestions)

  async def add_comment(self, pull_request_no: int, comment: str) -> PostedComment:
    res = self._get_mr(pull_request_no).notes.create({'body': comment})
    return PostedComment(id=str(res.id), type=CommentType.GENERAL)

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
        overall_msg += "Overall suggestion:\n - " + overall_comments[0].suggestion
      else:
        overall_msg += "Overall few points:\n" + "\n".join(
          [f" - {s.suggestion}" for s in overall_comments])

    mr = self._get_mr(pull_request_no)
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
        overall_msg += "\n\n -------------\n Few more points:\n"
      else:
        overall_msg += "Few points:\n"
      overall_msg += "\n".join([f" - {s.suggestion}" for s in failed_suggestions])

    if prsuggestions.level2_suggestions:
      level2_msgs = []
      level2_comments = [s for s in prsuggestions.level2_suggestions if s.start_line_number != -1]
      level2_overall_comments = [
        s for s in prsuggestions.level2_suggestions if s.start_line_number == -1
      ]

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

    if overall_msg:
      commented = mr.notes.create({'body': overall_msg})
      comment_id = str(commented.id)

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

  async def _create_review_comment(self, pull_request_no: int, suggestion: Suggestion):
    c = suggestion
    mr = self._get_mr(pull_request_no)
    is_multi_line = c.start_line_number != c.end_line_number
    comment_obj = {
      'body': c.suggestion,
      'position': {
        'base_sha': mr.diff_refs['base_sha'],
        'start_sha': mr.diff_refs['start_sha'],
        'head_sha': mr.diff_refs['head_sha'],
        'position_type': 'text',
        'new_path': c.file_path,
        'new_line': c.start_line_number if not is_multi_line else c.end_line_number,
      }
    }
    try:
      commented = mr.discussions.create(comment_obj)
      comment_id = str(commented.id)
      return True, comment_id
    except gitlab.GitlabCreateError as e:
      if is_multi_line:
        try:
          comment_obj['position']['new_line'] = c.end_line_number  # type: ignore
          commented = mr.discussions.create(comment_obj)
          comment_id = str(commented.id)
          return True, comment_id
        except gitlab.GitlabCreateError:
          pass
      log.error(f"Error while creating comment: {e}")
      return False, None

  async def clear_all_my_comment(self, pull_request_no: int) -> None:
    assert self.gitlab.user, "User not found"
    own_id = self.gitlab.user.id
    for note in self._get_mr(pull_request_no).notes.list():
      if note.author['id'] == own_id:
        note.delete()

  async def get_pr_head(self, pull_request_no: int) -> str:
    return self._get_mr(pull_request_no).diff_refs['head_sha']

  async def get_pr_description(self, pr_no: int) -> str:
    return self._get_mr(pr_no).description

  async def get_pr_title(self, pr_no: int) -> str:
    return self._get_mr(pr_no).title

  async def get_diff_two_commits(self, base: str, head: str) -> list[GitPatchFile]:
    compare = self._get_project().repository_compare(base, head)
    return gitlab_diff_to_patch_files(compare['diffs'])

  async def get_file_content(self, filename: str, ref: str) -> str:
    content = self._get_project().files.get(file_path=filename, ref=ref)
    return content.decode().decode('utf-8')

  async def get_pr_patches(self, pr_no: int) -> PRPatches:
    mr = self._get_mr(pr_no)
    changes = mr.changes()
    patch_files = gitlab_diff_to_patch_files(changes['changes'])
    return PRPatches(
      url=mr.web_url,
      number=mr.iid,
      base=mr.diff_refs['base_sha'],
      head=mr.diff_refs['head_sha'],
      files=patch_files,
    )

  async def get_comments(self, pull_request_no: int) -> AsyncGenerator[PRComment, None]:
    assert self.gitlab.user, "User not found"
    for note in self._get_mr(pull_request_no).notes.list():
      yield PRComment(
        id=str(note.id),
        user=note.author['username'],
        body=note.body,
        created_at=note.created_at,
        updated_at=note.updated_at,
        is_our_bot=note.author['id'] == self.gitlab.user.id,
      )

  async def is_valid_pr_commit(self, pr_no: int, commit_id: str):
    commits = self._get_mr(pr_no).commits()
    for c in commits:
      if c.id == commit_id:
        return True
    return False

  @cache
  def _get_mr(self, pr_no: int):
    return self._get_project().mergerequests.get(pr_no)

  @cache
  def _get_project(self):
    return self.gitlab.projects.get(self.repo_name)
