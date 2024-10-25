from panto.config import (EXPANDED_DIFF_LINES, GPT_MAX_TOKENS, IS_PROD,
                          MAX_TOKEN_BUDGET_FOR_AUTO_REVIEW, MAX_TOKEN_BUDGET_FOR_REVIEW,
                          OPENAI_API_KEY, OPENAI_MODEL)
from panto.data_models.git import PRStatus
from panto.data_models.pr_review import PRSuggestions
from panto.logging import log
from panto.ops.pr_review import LargeTokenException, PRReview
from panto.repository.pr_review import PRReviewRepository
from panto.services.config_storage.config_storage import ConfigStorageService
from panto.services.git.git_service import GitService
from panto.services.git.git_service_types import GitServiceType
from panto.services.llm.llm_service import LLMService, LLMServiceType, LLMUsage, create_llm_service
from panto.services.metrics.metrics import MetricsCollectionService
from panto.services.notification.notification import NotificationService
from panto.utils.misc import Branding, is_whitelisted_repo, repo_url_to_repo_name
from panto.utils.review_config import get_review_config


class PRActions:

  @staticmethod
  async def on_pr_open(
    *,
    gitsrv: GitService,
    pr_no: int,
    pr_title: str,
    repo_id: str,
    repo_url: str,
    notification_srv: NotificationService,
    metrics_srv: MetricsCollectionService,
    config_storage_srv: ConfigStorageService,
    auto_review: bool = False,
    is_reopen: bool = False,
  ):
    gitsrv_type = gitsrv.get_provider()
    is_whitelisted = await is_whitelisted_repo(repo_url, config_storage_srv, gitsrv_type)

    if not is_whitelisted:
      return

    await gitsrv.add_reaction(pr_no, reaction='rocket')
    await notification_srv.emit_pr_open(repo_url, pr_no)
    await metrics_srv.pr_open(
      repo_id=repo_id,
      repo_url=repo_url,
      provider=gitsrv_type,
      pr_no=pr_no,
      title=pr_title,
      is_reopen=is_reopen,
    )
    branding = Branding(gitsrv_type=gitsrv_type)

    if not auto_review:
      cmd = "`/review `" if gitsrv_type != GitServiceType.BITBUCKET else "`!review `"
      await gitsrv.add_comment(
        pr_no,
        branding.mark(f"Do you want me to review this PR? Please comment {cmd}.")  # noqa,
      )
      return

    try:
      await PRActions.on_review_request(
        gitsrv=gitsrv,
        repo_id=repo_id,
        pr_no=pr_no,
        notification_srv=notification_srv,
        comment_body='/review ' if IS_PROD else '/dev review ',
        repo_url=repo_url,
        comment_id=None,
        pr_title=pr_title,
        max_budget_token=MAX_TOKEN_BUDGET_FOR_AUTO_REVIEW,
        metric_srv=metrics_srv,
        config_storage_srv=config_storage_srv,
      )
    except LargeTokenException:
      msg = "Auto review disabled due to large PR. If you still want me to review this PR? Please comment `/review `"  # noqa
      await gitsrv.add_comment(pr_no, branding.mark(msg))
      return

  @staticmethod
  async def on_pr_fullfilled(
    *,
    notification_srv: NotificationService,
    metric_srv: MetricsCollectionService,
    repo_url: str,
    repo_id: str,
    gitsrv_type: GitServiceType,
    pr_no: int | str,
    pr_status: PRStatus,
  ):
    await notification_srv.emit_pr_fullfilled(repo_url, pr_no, pr_status.value)
    await metric_srv.pr_status_update(
      repo_id=repo_id,
      provider=gitsrv_type,
      pr_no=pr_no,
      status=pr_status,
    )

  @staticmethod
  async def delete_all_comments(gitsrv: GitService, pr_no: int, comment_id: int):
    await gitsrv.add_reaction(pr_no, 'eyes', comment_id)
    await gitsrv.clear_all_my_comment(pr_no)

  @staticmethod
  async def on_review_request(*,
                              gitsrv: GitService,
                              repo_id: str,
                              pr_no: int,
                              repo_url: str,
                              notification_srv: NotificationService,
                              metric_srv: MetricsCollectionService,
                              config_storage_srv: ConfigStorageService,
                              comment_body: str,
                              pr_title: str = '',
                              comment_id: int | None = None,
                              llmsrv: LLMService | None = None,
                              skip_whitelist_check: bool = False,
                              skip_empty_review_suggestion: bool = False,
                              max_budget_token: int = MAX_TOKEN_BUDGET_FOR_REVIEW):
    gitsrv_type = gitsrv.get_provider()
    branding = Branding(gitsrv_type=gitsrv_type)

    is_whitelisted = True
    if not skip_whitelist_check:
      is_whitelisted = await is_whitelisted_repo(repo_url, config_storage_srv, gitsrv_type)

    if not is_whitelisted:
      await notification_srv.emit_not_whitelisted_request(repo_url)
      # msg = branding.mark(
      #   "Automated PR Review not enabled for this repo. Please contact with support `support@pantomax.co`\nThank you."  # noqa
      # )  # noqa
      # await gitsrv.add_comment(pr_no, msg)
      return

    comment_body = comment_body.strip().lower()
    is_incremental_review = 'incremental' in comment_body
    is_forced_review = 'force' in comment_body

    await notification_srv.emit_new_pr_review_request(repo_url, pr_no)

    if llmsrv is None:
      llm_srv_name = LLMServiceType.NOOP \
        if not IS_PROD and 'noop' in comment_body else LLMServiceType.OPENAI
      llmsrv = await create_llm_service(
        service_name=llm_srv_name,
        max_tokens=GPT_MAX_TOKENS,
        api_key=OPENAI_API_KEY,
        model=OPENAI_MODEL,
      )

    review_config = await get_review_config(gitsrv, config_storage_srv, pr_no, repo_url)
    if not review_config.enabled:
      log.info("Review disabled")
      await notification_srv.emit(f"Review disabled by config for {repo_url} PR {pr_no}")
      return

    repo_name = repo_url_to_repo_name(repo_url)

    if comment_id:
      try:
        await gitsrv.add_reaction(pr_no, 'eyes', comment_id)
      except Exception:
        # Ignore if reaction fails
        pass

    pr_review = PRReview(
      repo_name=repo_name,
      pr_no=pr_no,
      gitsrv=gitsrv,
      llmsrv=llmsrv,
      notification_srv=notification_srv,
      review_config=review_config,
      expanded_diff_lines=EXPANDED_DIFF_LINES,
      pr_title=pr_title,
      max_budget_token=max_budget_token,
    )
    req_id = pr_review.req_id
    if not review_config.enabled:
      log.info("Review disabled")
      await gitsrv.add_comment(
        pr_no,
        branding.mark("Automated PR Review is disabled for this PR. Please change the config."),
      )
      return

    if not is_forced_review:
      pr_head_hash = await gitsrv.get_pr_head(int(pr_no))
      last_reviewed_data = await _get_last_reviewed_data(
        provider=gitsrv_type,
        repo_id=repo_id,
        pr_no=pr_no,
        pr_head_hash=pr_head_hash,
        is_incremental_review=is_incremental_review,
      )
      if last_reviewed_data:
        prsuggestions, last_id = last_reviewed_data
        await notification_srv.emit(f"Review already done for {repo_name} PR {pr_no}."
                                    f"\n\nReusing from: {last_id} \n\n{req_id}")
        pr_suggestions_with_branding = _add_banding(prsuggestions, branding)
        await gitsrv.add_review(pr_no, pr_suggestions_with_branding)
        return

    await metric_srv.review_started(
      pr_no=pr_no,
      repo_id=repo_id,
      gitsrv_type=gitsrv_type,
      is_incremental_review=is_incremental_review,
    )

    if is_incremental_review:
      await pr_review.incremental_prepare()
      log.info("Incremental Review files prepared")
    else:
      await pr_review.prepare()
      log.info("Review files prepared")

    no_of_review_files = len(pr_review.review_files)
    log.info(f"Total patch files: {no_of_review_files}")

    if no_of_review_files > 20:
      await notification_srv.emit(f"‼️Too many files to review. {no_of_review_files}\nid={req_id}")

    if not pr_review.review_files:
      await notification_srv.emit(
        f"No meaningful review files found for {repo_name} PR {pr_no}\nid: {req_id}", )
      log.info("No review files found")
      if skip_empty_review_suggestion:
        return
      await gitsrv.add_comment(
        pr_no,
        branding.mark("Sorry, No meaningful review files are found. So, all good."),
      )
      return

    try:
      suggestion_result = await pr_review.get_suggetions()
    except LargeTokenException as e:
      max_budget = e.max_budget_token
      required_tokens = e.required_tokens
      msg = f"Aborting review due to large token exception. Required tokens: {required_tokens}, Max budget: {max_budget}\nid: {req_id}"  # noqa
      log.error(msg)
      await notification_srv.emit(msg)
      await metric_srv.review_failed(
        pr_no=pr_no,
        repo_id=repo_id,
        provider=gitsrv_type,
        reason="Large token exception",
        no_of_files=no_of_review_files,
      )
      raise e
    except Exception as e:
      msg = f"Error while generating suggestions\n{str(e)}\nid: {req_id}"
      log.error(msg)
      await notification_srv.emit(msg)
      await metric_srv.review_failed(
        pr_no=pr_no,
        repo_id=repo_id,
        provider=gitsrv_type,
        reason="Error while generating suggestions",
        no_of_files=no_of_review_files,
      )
      raise e

    prsuggestions, unfiltered_suggestions, review_usages, correction_llm_usages = suggestion_result

    unfiltered_suggestions_count = len(unfiltered_suggestions)
    prsuggestions_count = len(prsuggestions.suggestions)
    lvl2_suggestions_count = len(
      prsuggestions.level2_suggestions) if prsuggestions.level2_suggestions else 0
    net_review_llm_usages = sum_llm_usages(review_usages)
    net_correction_llm_usages = sum_llm_usages(
      correction_llm_usages) if correction_llm_usages else None

    if not prsuggestions.suggestions and skip_empty_review_suggestion:
      log.info("No suggestions generated")
      await notification_srv.emit(
        f"No suggestions generated for {repo_name} PR {pr_no}. Skipping default review comments.")
      return

    if not prsuggestions.suggestions:
      prsuggestions.review_comment += "\n\nLooks good to me! :+1:"

    reviewed_from = pr_review.pr_patches.base
    reviewed_to = pr_review.pr_patches.head
    pr_suggestions_with_branding = _add_banding(prsuggestions, branding)

    await metric_srv.review_completed(pr_no=pr_no,
                                      repo_id=repo_id,
                                      provider=gitsrv_type,
                                      no_of_files=no_of_review_files,
                                      prsuggestions=prsuggestions,
                                      unfiltered_review_count=unfiltered_suggestions_count,
                                      final_review_count=prsuggestions_count,
                                      lvl2_review_count=lvl2_suggestions_count,
                                      review_llm_usages=net_review_llm_usages,
                                      correction_llm_usages=net_correction_llm_usages,
                                      reviewed_from=reviewed_from,
                                      reviewed_to=reviewed_to,
                                      is_soft_review=False)
    posted_comments = await gitsrv.add_review(pr_no, pr_suggestions_with_branding)
    await metric_srv.review_commented(pr_no=pr_no,
                                      repo_id=repo_id,
                                      provider=gitsrv_type,
                                      posted_comments=posted_comments)

    log.info(f"{len(prsuggestions.suggestions)} Review(s) added.")

  @staticmethod
  def is_delete_review_command(comment_body: str) -> bool:
    comment_body = comment_body.strip().lower()
    if IS_PROD:
      keywords = ['!delete all review', '/delete all review']
    else:
      keywords = ['!dev delete all review', '/dev delete all review']

    for kw in keywords:
      if comment_body.startswith(kw):
        return True

    return False

  @staticmethod
  def is_review_pr_command(comment_body: str) -> bool:
    comment_body = comment_body.strip().lower()

    if IS_PROD:
      keywords = ['!review', '!incremental review', '/review', '/incremental review']
    else:
      keywords = [
        '!dev review', '!dev incremental review', '/dev review', '/dev incremental review'
      ]

    for kw in keywords:
      if comment_body.startswith(kw):
        return True

    return False


def sum_llm_usages(llm_usages: list[LLMUsage]) -> LLMUsage:
  net_usage = LLMUsage(
    system_token=0,
    user_token=0,
    total_input_token=0,
    output_token=0,
    total_token=0,
    latency=0,
  )
  for usage in llm_usages:
    net_usage.system_token += usage.system_token
    net_usage.user_token += usage.user_token
    net_usage.total_input_token += usage.total_input_token
    net_usage.output_token += usage.output_token
    net_usage.total_token += usage.total_token
    net_usage.latency += usage.latency
  return net_usage


def _add_banding(prsuggestions: PRSuggestions, branding: Branding) -> PRSuggestions:
  prsuggestions = prsuggestions.model_copy(deep=True)
  prsuggestions.review_comment = branding.mark(prsuggestions.review_comment)
  for s in prsuggestions.suggestions:
    if s.start_line_number != -1:
      s.suggestion = branding.mark(s.suggestion)
  return prsuggestions


async def _get_last_reviewed_data(
  provider: GitServiceType,
  repo_id: int | str,
  pr_no: int | str,
  is_incremental_review: bool,
  pr_head_hash: str,
) -> tuple[PRSuggestions, str] | None:
  from panto.models.db import db_manager

  if not db_manager.scoped_session_factory:
    return None
  async with db_manager.scoped_session_factory() as db_session:
    pr_no = str(pr_no)
    repo_id = str(repo_id)
    pr_review_repo = PRReviewRepository(db_session)
    last_review_session = await pr_review_repo.get_last_reviews(
      provider=provider,
      repo_id=repo_id,
      pr_no=pr_no,
      review_type='incremental' if is_incremental_review else 'full',
      reviewed_to=pr_head_hash,
    )
    if not last_review_session:
      return None
    review_data = await pr_review_repo.get_review_data_by_id(last_review_session.id)
    if not review_data or not review_data.review_json:
      return None
    review_data = review_data.review_json
    prsuggestions = PRSuggestions.model_validate(review_data)
    return prsuggestions, last_review_session.id
