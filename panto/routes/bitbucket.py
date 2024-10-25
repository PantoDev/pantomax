import hashlib
import time

import aiohttp
import jwt
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from panto.config import BITBUCKET_APP_BASE_URL, BITBUCKET_APP_KEY, IS_PROD
from panto.data_models.git import PRStatus
from panto.logging import log
from panto.ops.pr_review_actions import PRActions
from panto.services.config_storage.config_storage import (ConfigStorageService,
                                                          create_config_storage_service)
from panto.services.git.git_service import GitService, create_git_service
from panto.services.git.git_service_types import GitServiceType
from panto.services.metrics.metrics import create_metrics_service
from panto.services.notification.notification import create_notification_service
from panto.utils.misc import in_next_tick, is_auto_review_enabled, is_whitelisted_repo

router = APIRouter()

_WEBHOOK_ENDPOINT = "/webhook"


@router.post("/bitbucket/webhook")
async def bitbucket_webhook(request: Request, background_tasks: BackgroundTasks):
  body = await request.json()
  supported_events = [
    "pullrequest:comment_created",
    "pullrequest:created",
    "pullrequest:fulfilled",
    "pullrequest:rejected",
  ]
  event_type = body.get("event")
  log.info(f"Received Bitbucket event: {event_type}")

  if event_type not in supported_events:
    return {"message": "processed"}

  jwt_token = request.headers["Authorization"]

  if event_type in ["pullrequest:fulfilled", "pullrequest:rejected"]:
    pr_no = body['data']['pullrequest']['id']
    repo_url = body['data']['repository']['links']['html']['href']
    notification_srv = create_notification_service()
    metric_srv = await create_metrics_service()
    repo_id = body['data']['repository']['uuid']
    pr_status = PRStatus.MERGED if event_type == "pullrequest:fulfilled" else PRStatus.CLOSED
    await PRActions.on_pr_fullfilled(
      notification_srv=notification_srv,
      metric_srv=metric_srv,
      repo_url=repo_url,
      repo_id=repo_id,
      gitsrv_type=GitServiceType.BITBUCKET,
      pr_no=pr_no,
      pr_status=pr_status,
    )
    return {"message": "processed"}

  if event_type in ["pullrequest:created"]:
    background_tasks.add_task(on_process_pull_request_created, body, jwt_token)
    return {"message": "processed"}

  if event_type in ["pullrequest:comment_created"]:
    comment_id = body['data']['comment']['id']
    comment_body = body['data']['comment']['content']['raw'].strip()
    pr_id = body['data']['pullrequest']['id']
    repo_url = body['data']['repository']['links']['html']['href']
    if PRActions.is_review_pr_command(comment_body) or PRActions.is_delete_review_command(
        comment_body):
      log.info(f"Received comment id: {comment_id}, comment_body: {comment_body}")
      background_tasks.add_task(on_process_pull_request_comment_created, body, jwt_token)
      log.info("processing in background task."
               f"repo: {repo_url}, pr: {pr_id}, comment_id: {comment_id}")
      return {"message": "processed"}

  return {"message": "not processed"}


@router.post("/bitbucket/installed")
async def bitbucket_installed(request: Request):
  body = await request.json()
  event_type = body.get("eventType")
  if event_type != "installed":
    log.error(f"Received unexpected event type: {event_type}")
    raise HTTPException(status_code=400, detail="Not able to process this request")

  client_key = body.get("clientKey")
  shared_secret = body.get("sharedSecret")

  if not client_key or not shared_secret:
    log.error("clientKey or sharedSecret is missing in the request")
    raise HTTPException(status_code=400, detail="Not able to process this request")

  auth_tokens = await _get_bitbucket_access_token(client_key, shared_secret)

  workspace = await _get_workspace_access(auth_tokens['access_token'])
  workspace_url = workspace.get('links', {}).get('html', {}).get('href', "N/A")
  workspace_type = workspace.get('type', "N/A")
  workspace_slug = workspace.get('slug', "N/A")
  gitsrv_type = GitServiceType.BITBUCKET

  notiffication_srv = create_notification_service()
  config_storage_srv = await create_config_storage_service()
  is_whitelisted = await is_whitelisted_repo(workspace_url + '/xyz', config_storage_srv,
                                             gitsrv_type)

  await notiffication_srv.emit_new_installation(
    user=workspace_url,
    whitelisted='Yes' if is_whitelisted else 'No',
    installation_type=gitsrv_type,
  )

  new_creds = {
    "client_key": client_key,
    "shared_secret": shared_secret,
    "is_disabled": False,
    "workspace": workspace_url,
    "workspace_type": workspace_type,
    "workspace_slug": workspace_slug,
  }
  storage = await create_config_storage_service()
  older_creds = await storage.get_providers_creds(GitServiceType.BITBUCKET.value, client_key)

  if not older_creds or not older_creds.get('shared_secret'):
    # New installation
    await storage.store_providers_creds(
      GitServiceType.BITBUCKET.value,
      client_key,
      new_creds,
      account_url=workspace_url,
      account_name=workspace_type,
      account_slug=workspace_slug,
    )
    return {"message": "installed"}

  if new_creds.get('shared_secret') == older_creds.get('shared_secret'):
    # Already installed
    await storage.store_providers_creds(
      GitServiceType.BITBUCKET.value,
      client_key,
      new_creds,
      account_url=workspace_url,
      account_name=workspace_type,
      account_slug=workspace_slug,
    )
    return {"message": "installed"}

  await _verify_bitbucket_jwt(request.headers.get("Authorization"), older_creds['shared_secret'])
  await storage.store_providers_creds(
    GitServiceType.BITBUCKET.value,
    client_key,
    new_creds,
    account_url=workspace_url,
    account_name=workspace_type,
    account_slug=workspace_slug,
  )
  return {"message": "installed"}


@router.post("/bitbucket/uninstalled")
async def bitbucket_uninstalled(request: Request):
  authrization_header = request.headers.get("Authorization")

  if not authrization_header or not authrization_header.startswith("JWT "):
    raise HTTPException(status_code=401, detail="Unauthorized")

  body = await request.json()
  event_type = body.get("eventType")
  if event_type != "uninstalled":
    log.error(f"Received unexpected event type: {event_type}")
    raise HTTPException(status_code=400, detail="Not able to process this request")

  client_key = body.get("clientKey")
  if not client_key:
    log.error("clientKey is missing in the request")
    raise HTTPException(status_code=400, detail="Not able to process this request")

  storage = await create_config_storage_service()
  creds = await storage.get_providers_creds(GitServiceType.BITBUCKET.value, client_key)

  workspace = body.get("principal", {}).get("username", "N/A")
  notiffication_srv = create_notification_service()
  await notiffication_srv.emit_installation_removed("BITBUCKET" + " " + workspace)

  if not creds or not creds.get('shared_secret'):
    log.error(f"Credentials not found for clientKey: {client_key}")
    return {"message": "uninstalled"}

  await _verify_bitbucket_jwt(authrization_header, creds['shared_secret'])

  creds = {"client_key": client_key, "is_disabled": True}
  await storage.store_providers_creds(GitServiceType.BITBUCKET.value, client_key, creds)

  return {"message": "uninstalled"}


@router.get("/bitbucket/atlassian-connect.json")
async def atlassian_connect():
  assert BITBUCKET_APP_KEY, "BITBUCKET_APP_KEY is not set"
  assert BITBUCKET_APP_BASE_URL, "BITBUCKET_APP_BASE_URL is not set"
  manifest = {
    "key": BITBUCKET_APP_KEY,
    "name": "Panto Bot" if IS_PROD else "Panto Bot (Dev)",
    "description": "Code meets context",
    "vendor": {
      "name": "Panto",
      "url": "https://pantomax.co"
    },
    "baseUrl": BITBUCKET_APP_BASE_URL + "/bitbucket",
    "authentication": {
      "type": "jwt"
    },
    "lifecycle": {
      "installed": "/installed",
      "uninstalled": "/uninstalled"
    },
    "modules": {
      "webhooks": [
        {
          "event": "pullrequest:created",
          "url": _WEBHOOK_ENDPOINT
        },
        {
          "event": "pullrequest:comment_created",
          "url": _WEBHOOK_ENDPOINT
        },
        {
          "event": "pullrequest:comment_reopened",
          "url": _WEBHOOK_ENDPOINT
        },
        {
          "event": "pullrequest:comment_resolved",
          "url": _WEBHOOK_ENDPOINT
        },
        {
          "event": "pullrequest:comment_deleted",
          "url": _WEBHOOK_ENDPOINT
        },
        {
          "event": "pullrequest:updated",
          "url": _WEBHOOK_ENDPOINT
        },
        {
          "event": "pullrequest:fulfilled",
          "url": _WEBHOOK_ENDPOINT
        },
        {
          "event": "pullrequest:unapproved",
          "url": _WEBHOOK_ENDPOINT
        },
        {
          "event": "pullrequest:rejected",
          "url": _WEBHOOK_ENDPOINT
        },
        {
          "event": "pullrequest:approved",
          "url": _WEBHOOK_ENDPOINT
        },
        {
          "event": "pullrequest:push",
          "url": _WEBHOOK_ENDPOINT
        },
        {
          "event": "pullrequest:changes_request_removed",
          "url": _WEBHOOK_ENDPOINT
        },
        {
          "event": "pullrequest:superseded",
          "url": _WEBHOOK_ENDPOINT
        },
      ]
    },
    "scopes": ["account", "repository", "pullrequest"],
    "contexts": ["account"]
  }
  return manifest


@in_next_tick
async def on_process_pull_request_created(body: dict, jwt_token: str):
  pr_no = body['data']['pullrequest']['id']
  repo_url = body['data']['repository']['links']['html']['href']
  storage = await create_config_storage_service()
  auth_tokens = await _bitbucket_verify_jwt_and_get_access_token(jwt_token, storage)
  access_token = auth_tokens['access_token']
  gitsrv = await _get_bitbucket_service(repo_url, access_token)
  notification_srv = create_notification_service()
  pr_title = body['data']['pullrequest']['title']

  metric_srv = await create_metrics_service()
  config_storage_srv = await create_config_storage_service()
  repo_id = body['data']['repository']['uuid']
  auto_review = await is_auto_review_enabled(repo_url, config_storage_srv, gitsrv.get_provider())
  await PRActions.on_pr_open(
    gitsrv=gitsrv,
    pr_no=pr_no,
    repo_url=repo_url,
    notification_srv=notification_srv,
    config_storage_srv=config_storage_srv,
    auto_review=auto_review,
    metrics_srv=metric_srv,
    pr_title=pr_title,
    repo_id=repo_id,
    is_reopen=False,  # bitbucket does not have reopen PR
  )


@in_next_tick
async def on_process_pull_request_comment_created(body: dict, jwt_token: str):
  repo_url = body['data']['repository']['links']['html']['href']
  pr_no = body['data']['pullrequest']['id']
  pr_title = body['data']['pullrequest']['title']
  comment_id = body['data']['comment']['id']
  comment_body = body['data']['comment']['content']['raw'].strip()

  if PRActions.is_review_pr_command(comment_body):
    log.info(f"Processing review command for PR: {pr_no}")
    storage = await create_config_storage_service()
    auth_tokens = await _bitbucket_verify_jwt_and_get_access_token(jwt_token, storage)
    access_token = auth_tokens['access_token']
    gitsrv = await _get_bitbucket_service(repo_url, access_token)
    notification_srv = create_notification_service()
    repo_id = str(body['data']['repository']['uuid'])
    metric_srv = await create_metrics_service()
    config_storage_srv = await create_config_storage_service()
    await PRActions.on_review_request(
      gitsrv=gitsrv,
      pr_no=pr_no,
      repo_id=repo_id,
      pr_title=pr_title,
      notification_srv=notification_srv,
      comment_body=comment_body,
      repo_url=repo_url,
      comment_id=comment_id,
      metric_srv=metric_srv,
      config_storage_srv=config_storage_srv,
    )
    return

  if PRActions.is_delete_review_command(comment_body):
    log.info(f"Bitbucket. Delete review command received. PR: {pr_no}")
    storage = await create_config_storage_service()
    auth_tokens = await _bitbucket_verify_jwt_and_get_access_token(jwt_token, storage)
    access_token = auth_tokens['access_token']
    gitsrv = await _get_bitbucket_service(repo_url, access_token)
    await PRActions.delete_all_comments(gitsrv, pr_no, comment_id)
    return


async def _get_bitbucket_service(repo_url: str, access_token: str) -> GitService:
  srv = create_git_service(GitServiceType.BITBUCKET, repo_url=repo_url)
  await srv.init_service(access_token=access_token)
  return srv


async def _verify_bitbucket_jwt(jwt_token: str | None, secret: str) -> dict:
  if not jwt_token:
    raise HTTPException(status_code=401, detail="Unauthorized")

  if not jwt_token.startswith("JWT "):
    raise HTTPException(status_code=401, detail="Unauthorized")

  jwt_token = jwt_token.replace("JWT ", "")

  try:
    decoded_data: dict = jwt.decode(jwt_token,
                                    secret,
                                    algorithms=["HS256"],
                                    options={"verify_aud": False})
    return decoded_data
  except jwt.PyJWTError as e:
    log.error(f"Failed to decode JWT: {e}")
    raise HTTPException(status_code=401, detail="Unauthorized")


async def _verify_bitbucket_webhook_jwt(jwt_token: str | None,
                                        storage: ConfigStorageService) -> dict:
  if not jwt_token:
    raise HTTPException(status_code=401, detail="Unauthorized")

  if not jwt_token.startswith("JWT "):
    raise HTTPException(status_code=401, detail="Unauthorized")

  jwt_token = jwt_token.replace("JWT ", "")

  # https://developer.atlassian.com/cloud/bitbucket/authentication-for-apps/#exposing-a-service-1
  unverifed_jwt_data = jwt.decode(jwt_token, options={"verify_signature": False})
  client_key = unverifed_jwt_data['iss']

  creds = await storage.get_providers_creds(GitServiceType.BITBUCKET.value, client_key)
  if not creds:
    raise HTTPException(status_code=401, detail="Unauthorized")

  shared_secret = creds.get('shared_secret')
  if not shared_secret:
    raise HTTPException(status_code=401, detail="Unauthorized")

  verified_jwt_data = jwt.decode(jwt_token,
                                 shared_secret,
                                 algorithms=["HS256"],
                                 audience=client_key)

  canonical_url = f"POST&{_WEBHOOK_ENDPOINT}&"
  if hashlib.sha256(canonical_url.encode()).hexdigest() != verified_jwt_data['qsh']:
    log.error("Failed to verify JWT: qsh does not match")
    raise HTTPException(status_code=401, detail="Unauthorized")

  return creds


async def _get_bitbucket_access_token(client_key: str, shared_secret: str) -> dict:
  bitbucket_base_url = "https://bitbucket.org"
  access_token_url = "/site/oauth2/access_token"
  access_token_canonical_url = f"POST&{access_token_url}&"
  jwt_payload = {
    "iss": client_key,
    "iat": int(time.time()),
    "exp": int(time.time()) + 600,
    "qsh": hashlib.sha256(access_token_canonical_url.encode()).hexdigest(),
    "sub": client_key
  }
  jwt_token = jwt.encode(jwt_payload, shared_secret, algorithm="HS256")
  grant_type = "urn:bitbucket:oauth2:jwt"
  endpoint = f"{bitbucket_base_url}{access_token_url}"
  req_headers = {
    "Authorization": f"JWT {jwt_token}",
    "Content-Type": "application/x-www-form-urlencoded"
  }
  payload = {"grant_type": grant_type}
  async with aiohttp.ClientSession() as session:
    async with session.post(endpoint, headers=req_headers, data=payload) as res:
      res.raise_for_status()
      res_data = await res.json()
      return res_data


async def _get_workspace_access(access_token: str) -> dict:
  endpoint = "https://api.bitbucket.org/2.0/workspaces"
  req_headers = {"Authorization": f"Bearer {access_token}"}
  async with aiohttp.ClientSession() as session:
    async with session.get(endpoint, headers=req_headers) as res:
      res.raise_for_status()
      res_data = await res.json()
      workspace = res_data.get('values', [])[0]
      return workspace


async def _bitbucket_verify_jwt_and_get_access_token(jwt_token: str,
                                                     storage: ConfigStorageService) -> dict:
  creds = await _verify_bitbucket_webhook_jwt(jwt_token, storage)
  client_key = creds['client_key']
  shared_secret = creds['shared_secret']
  auth_tokens = await _get_bitbucket_access_token(client_key, shared_secret)
  return auth_tokens
