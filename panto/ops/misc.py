import abc
import importlib

from panto.data_models.git import GitPatchFile
from panto.data_models.pr_review import Suggestion
from panto.data_models.review_config import ReviewConfig
from panto.services.llm.llm_service import LLMService
from panto.utils.git import ParsedDiff, make_diff, make_old_file_content, parse_hunk_diff


class GitReviewFile():

  def __init__(
    self,
    filename: str,
    content: str,
    patchfile: GitPatchFile,
  ) -> None:
    self.filename = filename
    self.content = content
    self.patchfile = patchfile
    self.parsed_diff: ParsedDiff = None  # type: ignore
    self.expanded_parsed_diff: ParsedDiff | None = None

  async def prepare(self, max_diff_lines: int, ast_diff: bool):
    self.parsed_diff = parse_hunk_diff(self.patchfile.patch)
    await self._expand_diff(
      max_diff_lines=max_diff_lines,
      ast_diff=ast_diff,
    )

  async def _expand_diff(self, max_diff_lines: int, ast_diff: bool):
    if ast_diff:
      await self._expand_diff_with_ast(max_diff_lines)
      return

    self._expand_diff_with_git(max_diff_lines)

  async def _expand_diff_with_ast(self, max_diff_lines: int):
    panto_ast = importlib.import_module('panto_ast')
    expand_diff_with_ast = panto_ast.expand_diff_with_ast
    get_ast_helper = panto_ast.get_ast_helper
    if ast_helper := get_ast_helper(self.filename):
      new_diff = await expand_diff_with_ast(
        ast_helper,
        self.content,
        self.parsed_diff,
      )
      self.expanded_parsed_diff = new_diff

  def _expand_diff_with_git(self, max_diff_lines: int):
    if max_diff_lines <= 3:
      # If expand_lines is less than or equal to 3, we don't need to expand the diff
      self.expanded_parsed_diff = self.parsed_diff
      return
    old_file_content = make_old_file_content(self.content, self.parsed_diff)
    expanded_str_diff = make_diff(self.content, old_file_content, max_diff_lines)
    self.expanded_parsed_diff = parse_hunk_diff(expanded_str_diff)


class PantoReviewTool(abc.ABC):

  @classmethod
  def get_name(cls):
    return cls.__name__

  @abc.abstractmethod
  async def get_suggestions(
    self,
    review_files: list[GitReviewFile],
    review_config: ReviewConfig,
    llmsrv: LLMService,
  ) -> list[Suggestion]:
    pass
