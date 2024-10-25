from fastapi import APIRouter, BackgroundTasks, Request
from gitlab.exceptions import GitlabError

from panto.config import MY_GL_ACCESS_TOKEN, MY_GL_WEBHOOK_SECRET
from panto.data_models.git import PRStatus
from panto.logging import log
from panto.ops.pr_review_actions import PRActions
from panto.services.config_storage.config_storage import create_config_storage_service
from panto.services.git.git_service import GitService, GitServiceType, create_git_service
from panto.services.metrics.metrics import create_metrics_service
from panto.services.notification.notification import (NotificationService,
                                                      create_notification_service)
from panto.utils.misc import in_next_tick, is_auto_review_enabled

router = APIRouter()


@router.post('/gitlab/webhook')
async def gitlab_webhook(request: Request, background_tasks: BackgroundTasks):
  # TODO: Move MY_GL_WEBHOOK_SECRET & MY_GL_ACCESS_TOKEN to NOOPConfigStorage
  if MY_GL_WEBHOOK_SECRET:
    gl_secret = request.headers.get('X-Gitlab-Token')
    if gl_secret != MY_GL_WEBHOOK_SECRET:
      log.error("Invalid GitLab webhook secret")
      return {"message": "not processed"}

  oauth_token = request.headers.get('X-PANTO-ACCESS-TOKEN') or MY_GL_ACCESS_TOKEN

  data = await request.json()

  repo = data.get('repository', {})
  project = data.get('project', {})
  repo_url = repo.get('git_http_url') or project.get('git_http_url')
  event_type = data.get('event_type')
  object_kind = data.get('object_kind')
  gitlab_ins_url = request.headers.get('X-Gitlab-Instance')

  assert gitlab_ins_url, "X-Gitlab-Instance header is required"

  log.info(f"Received gitlab webhook: {event_type}. object_kind: {object_kind}."
           f" repo: {repo_url}")

  if not oauth_token:
    notification_srv = create_notification_service()
    await notification_srv.emit(
      f"🤦🏻‍♂️ No access token provided for repo. Token not passed \n\n{repo_url}")
    log.error(f"No access token provided for repo: {repo_url}")
    return {"message": "not processed"}

  object_attributes = data.get('object_attributes', {})

  if event_type == 'merge_request' and object_kind == 'merge_request':
    object_attributes_action = object_attributes.get('action')

    if object_attributes_action in ['merge', 'close']:
      notification_srv = create_notification_service()
      pr_no = object_attributes.get('iid')
      metric_srv = await create_metrics_service()
      pr_status = PRStatus.CLOSED if object_attributes_action == 'close' else PRStatus.MERGED
      repo_id = data['project']['id']
      await PRActions.on_pr_fullfilled(
        notification_srv=notification_srv,
        metric_srv=metric_srv,
        repo_url=repo_url,
        repo_id=repo_id,
        gitsrv_type=GitServiceType.GITLAB,
        pr_no=pr_no,
        pr_status=pr_status,
      )
      return {"message": "processed"}

    if object_attributes_action in ['open', 'reopen']:
      background_tasks.add_task(on_mr_open, data, repo_url, oauth_token, gitlab_ins_url)
      print("returning")
      return {"message": "processed"}

    return {"message": "no action"}

  if event_type == 'note' and object_kind == 'note':
    noteable_type = object_attributes.get('noteable_type')
    object_attributes_action = object_attributes.get('action')
    project_id = data.get('project_id', '')
    is_bot = data.get('user', {}).get('username', '').startswith(f'project_{project_id}_bot')

    if not is_bot and noteable_type == 'MergeRequest' and object_attributes_action == 'create':
      object_attributes = data.get('object_attributes', {})
      comment_body = object_attributes.get('note').strip()

      if PRActions.is_review_pr_command(comment_body) or PRActions.is_delete_review_command(
          comment_body):
        background_tasks.add_task(on_mr_comment, data, repo_url, oauth_token, gitlab_ins_url)
        return {"message": "processed"}

  return {"message": "no action"}


@in_next_tick
async def on_mr_comment(data: dict, repo_url: str, oauth_token: str, gitlab_ins_url: str):
  object_attributes = data.get('object_attributes', {})
  comment_id = object_attributes.get('id')
  comment_body = object_attributes.get('note').strip()
  notification_srv = create_notification_service()

  merge_request = data.get('merge_request', {})
  pr_no = merge_request.get('iid')
  pr_title = merge_request.get('title', '')

  if PRActions.is_review_pr_command(comment_body):
    # TODO: Filter out own bot's own comments
    try:
      gitsrv = await _get_gitlab_service(
        repo_url=repo_url,
        oauth_token=oauth_token,
        gitlab_ins_url=gitlab_ins_url,
      )
      await gitsrv.get_pr_description(pr_no)  # dummy call to check if we have access to the repo
    except GitlabError as e:
      await handle_gitlab_error(e, repo_url, notification_srv)
      raise

    repo_http_url = merge_request.get('target').get('git_http_url')
    repo_id = str(data['project']['id'])
    metric_srv = await create_metrics_service()
    config_storage_srv = await create_config_storage_service()
    await PRActions.on_review_request(
      gitsrv=gitsrv,
      pr_no=pr_no,
      pr_title=pr_title,
      repo_id=repo_id,
      notification_srv=notification_srv,
      comment_body=comment_body,
      repo_url=repo_http_url,
      comment_id=comment_id,
      metric_srv=metric_srv,
      config_storage_srv=config_storage_srv,
    )
    return

  if PRActions.is_delete_review_command(comment_body):
    log.info("GitLab. Delete review command received")
    try:
      gitsrv = await _get_gitlab_service(
        repo_url=repo_url,
        oauth_token=oauth_token,
        gitlab_ins_url=gitlab_ins_url,
      )
      await gitsrv.get_pr_description(pr_no)  # dummy call to check if we have access to the repo
    except GitlabError as e:
      await handle_gitlab_error(e, repo_url, notification_srv)
      raise
    await PRActions.delete_all_comments(gitsrv, pr_no, comment_id)
    return


@in_next_tick
async def on_mr_open(data: dict, repo_url: str, oauth_token: str, gitlab_ins_url: str):
  opject_attributes = data.get('object_attributes', {})
  action = opject_attributes.get('action', '')
  notification_srv = create_notification_service()
  pr_no = opject_attributes.get('iid')
  pr_title = opject_attributes.get('title')
  log.info(f"MR opened for repo: {repo_url}")
  try:
    gitsrv = await _get_gitlab_service(
      repo_url=repo_url,
      oauth_token=oauth_token,
      gitlab_ins_url=gitlab_ins_url,
    )
    await gitsrv.get_pr_description(pr_no)  # dummy call to check if we have access to the repo
  except GitlabError as e:
    await handle_gitlab_error(e, repo_url, notification_srv)
    raise

  config_storage_srv = await create_config_storage_service()

  auto_review = False
  if action == 'open':
    auto_review = await is_auto_review_enabled(repo_url, config_storage_srv, gitsrv.get_provider())

  metrics_srv = await create_metrics_service()
  repo_id = data['project']['id']

  await PRActions.on_pr_open(
    gitsrv=gitsrv,
    pr_no=pr_no,
    repo_url=repo_url,
    notification_srv=notification_srv,
    metrics_srv=metrics_srv,
    auto_review=auto_review,
    pr_title=pr_title,
    repo_id=repo_id,
    is_reopen=action == 'reopen',
    config_storage_srv=config_storage_srv,
  )


async def handle_gitlab_error(err: Exception, repo_url: str,
                              notification_srv: NotificationService):
  if isinstance(err, GitlabError) and err.response_code == 403:
    await notification_srv.emit(
      f"🤦🏻‍♂️ No access to repo - Invalid token or revoked \n\n{repo_url}")
    return
  log.error(f"GitLab unknown error: {err}")


async def _get_gitlab_service(*, repo_url: str, oauth_token: str,
                              gitlab_ins_url: str) -> GitService:
  srv = create_git_service(GitServiceType.GITLAB, repo_url=repo_url)
  await srv.init_service(oauth_token=oauth_token, gitlab_ins_url=gitlab_ins_url)
  return srv
