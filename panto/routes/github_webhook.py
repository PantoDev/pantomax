from fastapi import APIRouter, BackgroundTasks, Request

from panto.config import (GH_PERSONAL_ACCESS_TOKEN, GH_WEBHOOK_SECRET,
                          SKIP_WHITLISTING_FOR_OSS_REPOS)
from panto.data_models.git import PRStatus
from panto.logging import log
from panto.ops.pr_review_actions import PRActions
from panto.services.config_storage.config_storage import create_config_storage_service
from panto.services.git.git_service import GitService, create_git_service
from panto.services.git.git_service_types import GitServiceType
from panto.services.git.github_service import GitHubService
from panto.services.metrics.metrics import create_metrics_service
from panto.services.notification import create_notification_service
from panto.utils.misc import (Branding, in_next_tick, is_auto_review_enabled, is_whitelisted_repo,
                              verify_github_signature)

router = APIRouter()


@router.post('/github/webhook')
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
  if GH_WEBHOOK_SECRET:
    raw_data = await request.body()
    sig_header = request.headers.get('X-Hub-Signature-256')
    assert verify_github_signature(raw_data, GH_WEBHOOK_SECRET, sig_header)

  event_type = request.headers.get('X-GitHub-Event')
  data = await request.json()
  action = data.get('action')

  installation_id = data.get('installation', {}).get('id')
  repo_url = data.get('repository', {}).get('html_url')

  log.info(f"Received github webhook: {event_type}. Action: {action}. "
           f"installation_id={installation_id} "
           f"repo: {repo_url}")

  if event_type == 'ping':
    return {"message": "pong"}

  if event_type == 'installation':
    await handle_installation_event(data)
    return {"message": "processed"}

  if event_type == 'issue_comment' and action == 'created':
    is_pull_request = 'pull_request' in data['issue']

    if not is_pull_request:
      return {"message": "no need to process"}

    sender_login: str = data['sender']['login']

    if sender_login.endswith('[bot]'):
      return {"message": "no need to process"}

    comment = data['comment']
    comment_body = comment['body'].strip()

    if PRActions.is_review_pr_command(comment_body) or PRActions.is_delete_review_command(
        comment_body):
      background_tasks.add_task(on_pr_comment, data, repo_url, installation_id)
      return {"message": "processed"}

    return {"message": "Event not processed"}

  if event_type == 'pull_request' and action in ['opened', 'reopened']:
    background_tasks.add_task(on_pr_open, data, repo_url, installation_id)
    return {"message": "processed"}

  if event_type == 'pull_request' and action == 'closed':
    action = data.get('action', {})
    pr = data['pull_request']
    pr_no = pr['number']
    merged = pr.get("merged", False)
    repo_id = pr['base']['repo']['id']
    notification_srv = create_notification_service()
    metric_srv = await create_metrics_service()
    pr_status = PRStatus.MERGED if merged else PRStatus.CLOSED
    await PRActions.on_pr_fullfilled(
      notification_srv=notification_srv,
      metric_srv=metric_srv,
      repo_url=repo_url,
      repo_id=repo_id,
      gitsrv_type=GitServiceType.GITHUB,
      pr_no=pr_no,
      pr_status=pr_status,
    )
    return {"message": "processed"}

  return {"message": "Event not processed"}


async def handle_installation_event(data: dict):
  action = data.get('action')
  user = data.get('installation', {}).get('account', {}).get('html_url', "")

  notification_srv = create_notification_service()

  if action == 'created':
    repos = data.get('repositories', [])
    selection = data.get('repository_selection') or "unknown"
    log.info(f"Installed by {user} for {len(repos)} repos. selection: {selection}")
    config_storage_srv = await create_config_storage_service()
    is_whitelisted = await is_whitelisted_repo(user + '/xyz', config_storage_srv,
                                               GitServiceType.GITHUB)
    await notification_srv.emit_new_installation(
      user=user,
      whitelisted='Yes' if is_whitelisted else 'No',
      installation_type=selection,
    )
    return

  if action == 'deleted':
    log.info(f"Uninstalled by {user}.")
    await notification_srv.emit_installation_removed(user)
    return

  if action == 'suspend':
    log.info(f"suspended by {user}")
    await notification_srv.emit_installation_suspend(user)
    return

  if action == 'unsuspend':
    log.info(f"unsuspended by {user}")
    await notification_srv.emit_installation_unsuspend(user)
    return

  log.info(f"Unknown installation action: {action}")


@in_next_tick
async def on_pr_open(data, repo_url, installation_id):
  action = data.get('action')
  pr = data['pull_request']
  pr_no = pr['number']
  pr_title = pr['title']
  repo_id = pr['base']['repo']['id']
  gitsrv = await _get_github_service(
    repo_url=repo_url,
    installation_id=installation_id,
  )
  notification_srv = create_notification_service()
  config_storage_srv = await create_config_storage_service()

  auto_review = False
  if action == 'opened':
    auto_review = await is_auto_review_enabled(repo_url, config_storage_srv, gitsrv.get_provider())

  metrics_srv = await create_metrics_service()
  await PRActions.on_pr_open(
    gitsrv=gitsrv,
    pr_no=pr_no,
    pr_title=pr_title,
    repo_url=repo_url,
    notification_srv=notification_srv,
    metrics_srv=metrics_srv,
    auto_review=auto_review,
    repo_id=repo_id,
    is_reopen=action == 'reopened',
    config_storage_srv=config_storage_srv,
  )


@in_next_tick
async def on_pr_comment(data, repo_url, installation_id):
  notification_srv = create_notification_service()
  comment = data['comment']
  repository = data['repository']
  comment_body = comment['body'].strip()
  sender_login: str = data['sender']['login']  # type: ignore
  is_pull_request = 'pull_request' in data['issue']

  if not is_pull_request:
    log.info(f"Ignoring issue comment. {comment_body}")
    return

  if sender_login.endswith('[bot]'):
    log.info(f"Ignoring bot comment. {comment_body}")
    return

  if PRActions.is_review_pr_command(comment_body):
    issue = data['issue']
    pr_no = issue['number']
    comment_id = comment['id']
    repo_http_url = repository['html_url']
    repo_id = repository['id']

    gitsrv = await _get_github_service(
      repo_url=repo_url,
      installation_id=installation_id,
    )

    is_open_source = repository['private'] is False

    pr_title = issue['title']
    metric_srv = await create_metrics_service()
    config_storage_srv = await create_config_storage_service()
    await PRActions.on_review_request(
      gitsrv=gitsrv,
      pr_no=pr_no,
      repo_id=str(repo_id),
      notification_srv=notification_srv,
      comment_body=comment_body,
      repo_url=repo_http_url,
      comment_id=comment_id,
      pr_title=pr_title,
      skip_whitelist_check=SKIP_WHITLISTING_FOR_OSS_REPOS and is_open_source,
      metric_srv=metric_srv,
      config_storage_srv=config_storage_srv,
    )
    return

  if PRActions.is_delete_review_command(comment_body):
    log.info("Delete review command received")
    issue = data['issue']
    pr_no = issue['number']
    comment_id = comment['id']
    gitsrv = await _get_github_service(
      repo_url=repo_url,
      installation_id=installation_id,
    )
    await PRActions.delete_all_comments(gitsrv, pr_no, comment_id)
    return


async def github_trigger_oss_pr_review(repo_http_url: str, pr_no: int):
  notification_srv = create_notification_service()

  if not GH_PERSONAL_ACCESS_TOKEN:
    await notification_srv.emit("GH_PERSONAL_ACCESS_TOKEN is not set.")
    return

  gitsrv = GitHubService(repo_url=repo_http_url)
  await gitsrv.init_service(personal_access_token=GH_PERSONAL_ACCESS_TOKEN)
  pr_title = await gitsrv.get_pr_title(pr_no)
  repo_id = gitsrv.repo.id
  metric_srv = await create_metrics_service()
  config_storage_srv = await create_config_storage_service()
  await PRActions.on_review_request(
    gitsrv=gitsrv,
    pr_no=pr_no,
    notification_srv=notification_srv,
    comment_body="/review",
    repo_url=repo_http_url,
    repo_id=str(repo_id),
    comment_id=None,
    pr_title=pr_title,
    skip_whitelist_check=True,
    skip_empty_review_suggestion=True,
    metric_srv=metric_srv,
    config_storage_srv=config_storage_srv,
  )
  promo_msg = f"""Panto has reviewed this pull request and provided key insights to improve your code.
Panto delivers highly relevant, noise-free code reviews for developers' repositories.

Need more in-depth reviews or have questions? Reach out to us at [pantomax.co](https://www.pantomax.co) or via email at hello@pantomax.co 🚀
"""  # noqa
  promo_msg = Branding(gitsrv_type=GitServiceType.GITHUB).mark(promo_msg)
  await gitsrv.add_comment(pr_no, promo_msg)


async def github_delete_oss_pr_review(repo_http_url: str, pr_no: int):
  notification_srv = create_notification_service()

  if not GH_PERSONAL_ACCESS_TOKEN:
    await notification_srv.emit("GH_PERSONAL_ACCESS_TOKEN is not set.")
    return

  gitsrv = GitHubService(repo_url=repo_http_url)
  await gitsrv.init_service(personal_access_token=GH_PERSONAL_ACCESS_TOKEN)
  await gitsrv.clear_all_my_comment(pr_no)
  log.info("Deleted all comments")


async def _get_github_service(*, repo_url: str, installation_id: int) -> GitService:
  srv = create_git_service(GitServiceType.GITHUB, repo_url=repo_url)
  await srv.init_service(installation_id=installation_id)
  return srv
