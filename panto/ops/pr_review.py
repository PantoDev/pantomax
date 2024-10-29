import re
import uuid
from datetime import datetime
from typing import TypedDict

from openai import APIError as OpenAIAPIError

from panto.config import (FF_ENABLE_AST_DIFF, LLM_TWO_WAY_CORRECTION_ENABLED,
                          LLM_TWO_WAY_CORRECTION_SOFT_THRESHOLD, LLM_TWO_WAY_CORRECTION_THRESHOLD,
                          jinja_env)
from panto.data_models.git import GitPatchFile, GitPatchStatus, PRPatches
from panto.data_models.pr_review import PRSuggestions, Suggestion
from panto.data_models.review_config import ConfigRule, ReviewConfig
from panto.logging import log
from panto.services.git.git_service import GitService
from panto.services.llm.llm_service import LLMService, LLMUsage
from panto.services.notification import NotificationService
from panto.utils.git import (ParsedDiff, drop_empty_patches, make_diff, make_old_file_content,
                             omit_no_endlines_from_patch, parse_hunk_diff, parsed_hunk_to_string)
from panto.utils.misc import is_file_include, log_llm_io, log_llm_usage, restricted_extensions

_review_system_template = jinja_env.get_template('pr_review/system.jinja')
_review_user_template = jinja_env.get_template('pr_review/user.jinja')
_correction_system_template = jinja_env.get_template('review_corrections/system.jinja')
_correction_user_template = jinja_env.get_template('review_corrections/user.jinja')
_no_issues_msg = "@no_issues_found@"
TOKEN_ADJUSTMENT = 100


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
    from panto_ast import expand_diff_with_ast, get_ast_helper
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


class PRReview():

  def __init__(self,
               *,
               repo_name: str,
               pr_no: int,
               gitsrv: GitService,
               llmsrv: LLMService,
               notification_srv: NotificationService,
               review_config: ReviewConfig,
               pr_title: str = "",
               expanded_diff_lines: int = 10,
               max_budget_token: int | None = None) -> None:
    self.repo_name = repo_name
    self.pr_no = pr_no
    self.gitsrv = gitsrv
    self.llmsrv = llmsrv
    self.notification_srv = notification_srv
    self.review_files: list[GitReviewFile] = []
    self.review_config = review_config
    self.expanded_diff_lines = expanded_diff_lines
    self.pr_title = pr_title
    self.pr_patches: PRPatches = None  # type: ignore
    self.max_budget_token = max_budget_token
    n_repo = self.repo_name.replace("/", "__")
    self.req_id = f"{int(datetime.now().timestamp())}.{n_repo}.{self.pr_no}.{str(uuid.uuid4().hex)[-6:]}"  # noqa: E501

  async def incremental_prepare(self):
    base_commit = await self._get_last_reviewed_commit()
    if not base_commit:
      log.info("No previous review found. Preparing from scratch")
      self.prepare()
      return

    pr_head = await self.gitsrv.get_pr_head(self.pr_no)
    if base_commit == pr_head:
      log.info("No new commits found. Skipping review")
      return

    log.info(f"Preparing incremental review from base commit: {base_commit}")
    await self._prepare(base_commit, pr_head)

  async def prepare(self):
    await self._prepare()

  async def _prepare(self, base_commit: str | None = None, pr_head: str | None = None):

    if pr_head is None:
      pr_head = await self.gitsrv.get_pr_head(self.pr_no)

    if not base_commit:
      self.pr_patches = await self.gitsrv.get_pr_patches(self.pr_no)
    else:
      self.pr_patches = PRPatches(
        url="",
        number=self.pr_no,
        base=base_commit,
        head=pr_head,
        files=await self.gitsrv.get_diff_two_commits(base_commit, pr_head),
      )

    for patchfile in self.pr_patches.files:
      patchfile.patch = omit_no_endlines_from_patch(patchfile.patch)

    filtered_patches = self._filter_patches(self.pr_patches.files, self.review_config)

    review_files: list[GitReviewFile] = []

    for patchfile in filtered_patches:
      if patchfile.status == GitPatchStatus.RENAMED and not patchfile.patch:
        continue
      review_file = await self._read_file_content_and_diff(patchfile, self.pr_patches.head)
      await review_file.prepare(
        max_diff_lines=self.expanded_diff_lines,
        ast_diff=FF_ENABLE_AST_DIFF,
      )
      review_files.append(review_file)

    if FF_ENABLE_AST_DIFF:
      from panto_ast import expand_review_files_with_ast
      review_files = await expand_review_files_with_ast(review_files, self)

    self.review_files = review_files

  async def get_suggetions(
      self) -> tuple[PRSuggestions, list[Suggestion], list[LLMUsage], list[LLMUsage] | None]:
    review_files = self.review_files
    splited_files, tokens = await self._split_review_files(review_files)

    log.info(f"Total files chunk: {len(splited_files)}")
    unfiltered_suggestions: list[Suggestion] = []

    i = -1
    review_usages: list[LLMUsage] = []
    for chunk in splited_files:
      i += 1
      tokens_used = tokens[i]
      log.info(
        f"procssing chunk files: {[file.filename for file in chunk]} with tokens: {tokens_used}")
      system_prompt, user_prompt = self._build_review_prompt(chunk, self.review_config)

      log_msg = f"System:\n{system_prompt}"
      log_msg += f"\n\nUser:\n{user_prompt}"
      log_llm_io(
        req_id=self.req_id,
        name=f'prompt.{i}',
        msg=log_msg,
      )

      try:
        answer_str, review_usage = await self.llmsrv.ask(system_prompt,
                                                         user_prompt,
                                                         temperature=0.2)
        review_usages.append(review_usage)
      except OpenAIAPIError as e:
        log.error(f"Error while asking LLM: {e}")
        await self.notification_srv.emit_consumtion_limit_reached(e.message)
        raise

      log_llm_io(
        req_id=self.req_id,
        name=f'answer.{i}',
        msg=answer_str,
      )

      log_llm_usage(
        txn_id=f'{self.req_id}.{i}',
        review_usage=review_usage,
      )

      await self.notification_srv.emit_usages(self.repo_name, review_usage, self.req_id, "review")

      suggestions = self._parse_llm_review_response(answer_str)
      if suggestions:
        unfiltered_suggestions.extend(suggestions)

    last_reviewed_commit = self.pr_patches.head

    refined = await self._refine_suggestions(unfiltered_suggestions)

    [
      level1_refined_suggestions,
      level2_refined_suggestions,
      discarded_suggestions,
    ], correction_llm_usages = refined

    level1_count = len(level1_refined_suggestions)
    level2_count = len(level2_refined_suggestions)
    removed_count = len(discarded_suggestions)

    log.info(f"Total: {len(unfiltered_suggestions)}"
             f" -> Level1: {level1_count},"
             f" Level2: {level2_count}, Removed: {removed_count}")

    await self.notification_srv.emit_suggestions_generated(
      repo_url=self.repo_name,
      inital_count=len(unfiltered_suggestions),
      final_count=level1_count,
      level2_count=level2_count,
      request_id=self.req_id,
    )

    review_comment = f"Reviewed up to commit:{last_reviewed_commit}"

    return PRSuggestions(
      suggestions=level1_refined_suggestions,
      level2_suggestions=level2_refined_suggestions,
      review_comment=review_comment,
    ), unfiltered_suggestions, review_usages, correction_llm_usages

  async def _refine_suggestions(
    self, suggestions: list[Suggestion]
  ) -> tuple[tuple[list[Suggestion], list[Suggestion], list[Suggestion]], (list[LLMUsage] | None)]:
    #
    unique_suggestions = self._drop_duplicate_suggestions(suggestions)

    if not LLM_TWO_WAY_CORRECTION_ENABLED:
      return (unique_suggestions, [], []), None

    correction_llm_usages: list[LLMUsage] = []
    try:
      refined_suggestions, correction_llm_usage = await self._drop_suggestion_by_llm(
        unique_suggestions)
      correction_llm_usages.append(correction_llm_usage)
      [
        level1_refined_suggestions,
        level2_refined_suggestions,
        discarded_suggestions,
      ] = refined_suggestions

      # TODO: This function should not call notification service
      await self.notification_srv.emit_usages(self.repo_name, correction_llm_usage, self.req_id,
                                              "correction")
      return (
        level1_refined_suggestions,
        level2_refined_suggestions,
        discarded_suggestions,
      ), correction_llm_usages
    except Exception as e:
      log.error(f"Error while asking LLM for correction: {e}")
      await self.notification_srv.emit(f"Error while asking LLM for correction.\nid={self.req_id}")
      return (unique_suggestions, [], []), correction_llm_usages

  async def _get_last_reviewed_commit(self) -> str | None:
    async for comment in self.gitsrv.get_comments(self.pr_no):
      if comment.is_our_bot and "Reviewed up to commit:" in comment.body:
        match = re.search(r"Reviewed up to commit:\s*([a-f0-9]{40})", comment.body.strip())
        if not match:
          continue
        commit_id = match.group(1)
        if not await self.gitsrv.is_valid_pr_commit(self.pr_no, commit_id):
          log.warning(f"Invalid commit_id: {commit_id}")
          return None

        log.info(f"Last reviewed commit: {commit_id}")
        return commit_id

    return None

  async def _split_review_files(
      self, review_files: list[GitReviewFile]) -> tuple[list[list[GitReviewFile]], list[int]]:
    if not review_files:
      return [], []

    system_prompt, user_prompt = self._build_review_prompt(review_files, self.review_config)
    full_len = await self.llmsrv.get_encode_length(system_prompt + user_prompt) + TOKEN_ADJUSTMENT

    if self.max_budget_token and full_len > self.max_budget_token:
      raise LargeTokenException(required_token=full_len, max_budget_token=self.max_budget_token)

    max_token_len = self.llmsrv.max_tokens
    # happy path
    if full_len < max_token_len:
      log.info(f"Token length: Happy path : {full_len} < {max_token_len}")
      return [review_files], [full_len]

    log.info(f"Token length : need splitting : {full_len} > {max_token_len}")

    # If the prompt is too long, we split the user prompt into smaller chunks
    system_prompt_token = await self.llmsrv.get_encode_length(system_prompt)

    class ReviewFileWiseTokens(TypedDict):
      review_file: GitReviewFile
      tokens: int

    review_file_wise_tokens: list[ReviewFileWiseTokens] = [{
      "review_file": review_file,
      "tokens": await self.llmsrv.get_encode_length(
        self._build_review_prompt([review_file], self.review_config)[1]),
    } for review_file in review_files]

    greedy_split: list[list[GitReviewFile]] = []
    greedy_selections: list[GitReviewFile] = []
    tokens_used: list[int] = []
    consumed_token = system_prompt_token + TOKEN_ADJUSTMENT

    for review_file_info in review_file_wise_tokens:
      review_file: GitReviewFile = review_file_info['review_file']
      review_file_token: int = review_file_info['tokens']

      if system_prompt_token + review_file_token + TOKEN_ADJUSTMENT >= max_token_len:
        log.info(
          f"Skipping file: {review_file.filename} as it exceeds token limit for a single prompt. {review_file_token}+{system_prompt_token}"  # noqa: E501
        )
        continue

      if consumed_token + review_file_token >= max_token_len:
        log.info(f"Beanpack tokens: {consumed_token}")
        tokens_used.append(consumed_token)
        greedy_split.append(greedy_selections)
        greedy_selections = []
        consumed_token = system_prompt_token + TOKEN_ADJUSTMENT

      greedy_selections.append(review_file)
      consumed_token += review_file_token

    if greedy_selections:
      log.info(f"Beanpack token: {consumed_token}")
      tokens_used.append(consumed_token)
      greedy_split.append(greedy_selections)

    return greedy_split, tokens_used

  def _parse_llm_review_response(self, answer_str: str) -> list[Suggestion]:
    answers = answer_str.split('\n')
    suggestions: list[Suggestion] = []
    for answer in answers:
      answer = answer.strip()
      if answer == _no_issues_msg or not answer:
        continue
      log.info(f"Answer: \"{answer}\"")
      try:
        splitted = answer.split(' : ')
        file_path = splitted[0]
        line_number = splitted[1]
        suggestion_txt = " : ".join(splitted[2:]).strip()
        if suggestion_txt == _no_issues_msg:
          continue
        line_no_str = line_number.strip()
        start_line_no = -1
        end_line_no = None
      except Exception:
        log.error(f"Error parsing answer: {answer}")
        continue

      if line_no_str.isdigit():
        start_line_no = int(line_no_str)
      elif line_no_str == '-1' or line_no_str == '-':
        start_line_no = -1
      elif '-' in line_no_str:
        splitted_lines = line_no_str.split('-')
        if len(splitted_lines) != 2:
          log.info(f"Invalid line number: {line_no_str}")
          continue
        start_line_no = int(splitted_lines[0].strip())
        end_line_no = int(splitted_lines[1].strip())
      else:
        log.info(f"Invalid line number: {line_no_str}")
        continue

      suggestion = Suggestion(
        id=str(uuid.uuid4()),
        file_path=file_path.strip(),
        start_line_number=start_line_no,
        end_line_number=end_line_no if end_line_no is not None else start_line_no,
        suggestion=suggestion_txt,
      )
      suggestions.append(suggestion)

    return suggestions

  def _generate_diff_content(self, review_file: GitReviewFile) -> list[str]:
    diff_contents = []

    diff = review_file.expanded_parsed_diff or review_file.parsed_diff
    if diff:
      for hunk in diff.hunks:
        diff_content = parsed_hunk_to_string(hunk)
        diff_contents.append(diff_content)

    return diff_contents

  def _get_change_type(self, patchfile: GitPatchFile) -> str:
    change_type = patchfile.status.value
    if patchfile.status == GitPatchStatus.ADDED:
      change_type = "NEWLY ADDED"
    if patchfile.status == GitPatchStatus.RENAMED:
      if patchfile.patch:
        change_type = f"RENAMED AND MODIFIED (renamed from {patchfile.old_filename})"
      else:
        change_type = f"ONLY RENAMED (renamed from {patchfile.old_filename})"
    return change_type

  def _build_review_prompt(self, review_files: list[GitReviewFile],
                           review_config: ReviewConfig | None) -> tuple[str, str]:
    code_diffs = ""
    for review_file in review_files:
      file_path = review_file.filename
      raw_diff_content = "\n\n".join(self._generate_diff_content(review_file))
      change_type = self._get_change_type(review_file.patchfile)

      code_diffs += f"### FILE PATH: {file_path}"
      code_diffs += f"\n##CHANGE TYPE: {change_type}"
      code_diffs += f"\n## DIFF:\n{raw_diff_content or 'No Diff'}"
      code_diffs += "\n\n"

    template_args = {
      "no_error_msg": _no_issues_msg,
      "code_diffs": code_diffs,
      "review_config": self._attach_only_required_review_rules(review_config, review_files)
                       if review_config else None,  # noqa: E131
      "pr_title": self.pr_title,
    }
    system_template = _review_system_template.render(template_args)
    user_template = _review_user_template.render(template_args)
    return system_template, user_template

  async def _read_file_content_and_diff(self, patchfile: GitPatchFile, head: str) -> GitReviewFile:
    if patchfile.status == GitPatchStatus.REMOVED:
      content = ""
    elif patchfile.status == GitPatchStatus.RENAMED and not patchfile.patch:
      content = ""
    else:
      content = await self.gitsrv.get_file_content(patchfile.filename, head)

    return GitReviewFile(
      filename=patchfile.filename,
      content=content,
      patchfile=patchfile,
    )

  def _attach_only_required_review_rules(self, review_config: ReviewConfig,
                                         files: list[GitReviewFile]) -> ReviewConfig:
    if not review_config.review_rules:
      return review_config

    new_config = review_config.model_copy(deep=True)
    new_config.review_rules = []
    file_exts = {file.filename.split('.')[-1] for file in files}
    eligible_rules: list[ConfigRule] = []
    for rule in review_config.review_rules:
      for lang in rule.lang:
        if lang in file_exts:
          eligible_rules.append(rule)
          break

    if eligible_rules:
      new_config.review_rules = eligible_rules
    return new_config

  def _filter_patches(self, patches: list[GitPatchFile],
                      review_config: ReviewConfig) -> list[GitPatchFile]:
    exclude_globs = [ext for ext in restricted_extensions]

    if review_config.scan.includes:
      for include in review_config.scan.includes:
        include = include.strip()
        if include.startswith('!'):
          exclude_globs.append(include[1:])
        else:
          exclude_globs.append(f"!{include}")

    filted_patches: list[GitPatchFile] = []
    for patch in patches:
      filename = patch.filename

      result = is_file_include(filename, exclude_globs)
      if result:
        filted_patches.append(patch)

    new_filted_patches = drop_empty_patches(filted_patches)
    return new_filted_patches

  def _drop_duplicate_suggestions(self, suggestions: list[Suggestion]) -> list[Suggestion]:
    refined_suggestions: list[Suggestion] = []

    older_suggestions = {}

    for suggestion in suggestions:
      if suggestion.suggestion in older_suggestions:
        continue
      refined_suggestions.append(suggestion)
      older_suggestions[suggestion.suggestion] = True

    return refined_suggestions

  async def _drop_suggestion_by_llm(
      self, suggestions: list[Suggestion]) -> tuple[list[list[Suggestion]], LLMUsage]:
    level1_suggestions: list[Suggestion] = []
    level2_suggestions: list[Suggestion] = []
    discarded_suggestions: list[Suggestion] = []

    filewise_suggestions: dict[str, list[Suggestion]] = {}
    llm_usages = LLMUsage(
      system_token=0,
      user_token=0,
      output_token=0,
      total_token=0,
      latency=0,
      total_input_token=0,
      llm=self.llmsrv.get_type(),
    )
    for suggestion in suggestions:
      file_path = suggestion.file_path or "$$NO_FILE$$"
      if file_path not in filewise_suggestions:
        filewise_suggestions[file_path] = []
      filewise_suggestions[file_path].append(suggestion)

    loop_index = 0

    for file_path, suggestions in filewise_suggestions.items():
      if file_path == "$$NO_FILE$$":
        for s in suggestions:
          level1_suggestions.append(s)
        continue

      review_files = self.review_files
      code_diffs = ""
      for review_file in review_files:
        if review_file.filename != file_path:
          continue
        file_path = review_file.filename
        raw_diff_content = "\n\n".join(self._generate_diff_content(review_file))
        change_type = self._get_change_type(review_file.patchfile)

        code_diffs += f"### FILE PATH: {file_path}"
        code_diffs += f"\n##CHANGE TYPE: {change_type}"
        code_diffs += f"\n## DIFF:\n{raw_diff_content or 'No Diff'}"
        code_diffs += "\n\n"

      formattted_reviews = ""
      for i, s in enumerate(suggestions):
        line_no = str(s.start_line_number)
        if s.end_line_number and s.end_line_number != s.start_line_number:
          line_no += f"-{s.end_line_number}"
        formattted_reviews += f"{i}. {file_path} : {line_no} : {s.suggestion}\n"

      render_args = {
        "review_config": self._attach_only_required_review_rules(self.review_config, review_files),
        "formattted_reviews": formattted_reviews,
        "code_diffs": code_diffs,
        "pr_title": self.pr_title,
      }
      system_msg = _correction_system_template.render(render_args)
      user_msg = _correction_user_template.render(render_args)

      output_str, usages = await self.llmsrv.ask(system_msg=system_msg,
                                                 user_msgs=user_msg,
                                                 temperature=0.2)

      log_msg = f"System:\n{system_msg}"
      log_msg += f"\n\nUser:\n{user_msg}  "
      log_msg += f"\n\nOutput:\n\n\n{output_str}"
      log_llm_io(
        req_id=self.req_id,
        name=f'correction.{loop_index}',
        msg=log_msg,
      )

      loop_index += 1
      llm_usages.system_token += usages.system_token
      llm_usages.user_token += usages.user_token
      llm_usages.output_token += usages.output_token
      llm_usages.total_token += usages.total_token
      llm_usages.total_input_token += usages.total_input_token
      llm_usages.latency += usages.latency

      try:
        corrections_list = self._parse_llm_corrections_response(output_str)
        min_acceptable_score = min(LLM_TWO_WAY_CORRECTION_THRESHOLD,
                                   LLM_TWO_WAY_CORRECTION_SOFT_THRESHOLD)
        for correction in corrections_list:
          if correction['status'] != 'VALID':
            discarded_suggestions.append(suggestions[correction['index']])
            continue
          relevance_score = correction['relevance_score']

          if relevance_score < min_acceptable_score:
            discarded_suggestions.append(suggestions[correction['index']])
            continue

          new_s: Suggestion = suggestions[correction['index']]
          example_suggestion = correction.get('example_suggestion', "")
          if example_suggestion:
            new_s.suggestion += f"\n\n{example_suggestion}"
          if relevance_score >= LLM_TWO_WAY_CORRECTION_THRESHOLD:
            level1_suggestions.append(new_s)
          elif relevance_score >= LLM_TWO_WAY_CORRECTION_SOFT_THRESHOLD:
            level2_suggestions.append(new_s)

      except Exception:
        log.error("Error parsing correction response. fallback to original suggestions")
        for s in suggestions:
          level1_suggestions.append(s)

    log_llm_usage(
      txn_id=self.req_id,
      review_usage=llm_usages,
    )

    return [level1_suggestions, level2_suggestions, discarded_suggestions], llm_usages

  def _parse_llm_corrections_response(self, correction_txt: str) -> list[dict]:
    output: list[dict] = []
    for c in correction_txt.split('||||'):
      c = c.strip()
      if not c:
        continue
      try:
        index_str, status, relevance_score_str, *rest = c.split(':')
        index = int(index_str.strip())
        status = status.strip()
        relevance_score = int(relevance_score_str.strip())

        example_suggestion: str = ":".join(rest).strip() if rest else ""
        if example_suggestion.lower() == 'n/a':
          example_suggestion = ""

        output.append({
          "index": index,
          "status": status,
          "relevance_score": relevance_score,
          "example_suggestion": example_suggestion,
        })
      except Exception as e:
        log.error(f"Error parsing correction response: {c}. Error: {e}")

    return output


class LargeTokenException(Exception):

  def __init__(self, required_token: int, max_budget_token: int) -> None:
    self.required_tokens = required_token
    self.max_budget_token = max_budget_token
    super().__init__(
      f"PR is too large to review. Required tokens: {required_token}, Max budget: {max_budget_token}"  # noqa
    )
