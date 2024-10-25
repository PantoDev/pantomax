from fastapi import APIRouter, BackgroundTasks, Request

from panto.config import (IS_PROD, TELEGRAM_CHAT_ID, TELEGRAM_WEBHOOK_SECRET_KEY,
                          TELEGRAM_WEBHOOK_SECRET_VALUE)
from panto.routes.github_webhook import github_delete_oss_pr_review, github_trigger_oss_pr_review
from panto.services.config_storage.config_storage import create_config_storage_service
from panto.services.git.git_service_types import GitServiceType
from panto.services.notification.notification import (NotificationServiceType,
                                                      create_notification_service)
from panto.utils.misc import (disable_auto_review, enable_auto_review, in_next_tick,
                              is_auto_review_enabled, is_whitelisted_repo)

router = APIRouter()


@router.post('/telegram/webhook')
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
  queryparams = request.query_params

  # some hacky way to verify the request is coming from telegram
  assert TELEGRAM_WEBHOOK_SECRET_KEY, "TELEGRAM_WEBHOOK_SECRET_KEY is not set"
  query_value = queryparams.get(TELEGRAM_WEBHOOK_SECRET_KEY)
  if query_value is None or query_value != TELEGRAM_WEBHOOK_SECRET_VALUE:
    if IS_PROD:
      return {"message": "ok"}
    return {"message": "webhook secret didn't match"}

  data = await request.json()
  await _process_msg(data, background_tasks)


@router.post('/telegram/dev')
async def telegram_dev(request: Request, background_tasks: BackgroundTasks):
  if IS_PROD:
    return {"message": "not allowed"}
  body = await request.body()
  txt = body.decode('utf-8')
  telegram_msg = {
    "message": {
      "chat": {
        "id": TELEGRAM_CHAT_ID,
        "type": "group"
      },
      "text": txt
    },
  }
  processed_res = await _process_msg(telegram_msg, background_tasks)
  return processed_res


async def _process_msg(data: dict, background_tasks: BackgroundTasks):
  message = data.get('message')
  if not message:
    return {"message": "not processed"}

  chat_id = str(message['chat']['id'])
  is_private = message['chat']['type'] == 'private'

  if is_private:
    await _send_telegram_message(chat_id, "Direct messages are not supported.")
    return {"message": "processed"}

  msg: str = message.get('text', "").strip().lower()
  commands = {
    '/whitelist': _whitelisting_handler,
    '/test-whitelist': _test_whitelist_handler,
    '/unwhitelist': _whitelisting_handler,
    '/promo-review': _handle_promo_review,
    '/delete-promo-review': _handle_delete_promo_review,
    "/autoreview": _handle_autoreview,
    "/test-autoreview": _handle_test_autoreview,
  }
  if not any(msg.startswith(cmd) for cmd in commands):
    return {"message": "processed"}

  whitelisted_groups = [TELEGRAM_CHAT_ID]
  if chat_id not in whitelisted_groups:
    await _send_telegram_message(chat_id, "You are not authorized to use this bot.")
    return {"message": "processed"}

  for cmd, handler in commands.items():
    if msg.startswith(cmd):
      background_tasks.add_task(handler, msg, chat_id)
      break

  return {"message": "processed"}


@in_next_tick
async def _handle_promo_review(msg: str, chat_id: str):
  example_msg = "Usage: /promo-review <repo_url> <pr_no>"
  msgsplit = [x for x in msg.split(' ') if x]
  if len(msgsplit) != 3:
    await _send_telegram_message(chat_id, f"Invalid command. {example_msg}")
    return {"message": "processed"}

  command = msgsplit[0].strip()
  giturl = msgsplit[1].strip()
  pr_no_str = msgsplit[2].strip()

  if command != '/promo-review':
    await _send_telegram_message(chat_id, f"Invalid command. {example_msg}")
    return {"message": "processed"}

  if not giturl.startswith('https://'):
    await _send_telegram_message(chat_id, "Invalid url. Should start with https://")
    return {"message": "processed"}

  if not pr_no_str.isdigit():
    await _send_telegram_message(chat_id, "Invalid PR number.")
    return {"message": "processed"}

  pr_no = int(pr_no_str)

  await _send_telegram_message(chat_id, "👍🏻")
  await github_trigger_oss_pr_review(giturl, pr_no)
  return {"message": "processed"}


@in_next_tick
async def _handle_delete_promo_review(msg: str, chat_id: str):
  example_msg = "Usage: /delete-promo-review <repo_url> <pr_no>"
  msgsplit = [x for x in msg.split(' ') if x]
  if len(msgsplit) != 3:
    await _send_telegram_message(chat_id, f"Invalid command. {example_msg}")
    return {"message": "processed"}

  command = msgsplit[0].strip()
  giturl = msgsplit[1].strip()
  pr_no_str = msgsplit[2].strip()

  if command != '/delete-promo-review':
    await _send_telegram_message(chat_id, f"Invalid command. {example_msg}")
    return {"message": "processed"}

  if not giturl.startswith('https://'):
    await _send_telegram_message(chat_id, "Invalid url. Should start with https://")
    return {"message": "processed"}

  if not pr_no_str.isdigit():
    await _send_telegram_message(chat_id, "Invalid PR number.")
    return {"message": "processed"}

  pr_no = int(pr_no_str)

  await _send_telegram_message(chat_id, "👍🏻")
  await github_delete_oss_pr_review(giturl, pr_no)
  return {"message": "processed"}


@in_next_tick
async def _handle_autoreview(msg: str, chat_id: str):
  example_msg = "Usage: /autoreview <action> <provider> <repo_url>"
  msgsplit = [x for x in msg.split(' ') if x]
  if len(msgsplit) != 4:
    await _send_telegram_message(chat_id, example_msg)
    return {"message": "processed"}

  command = msgsplit[0].strip()
  action = msgsplit[1].strip()
  provider_str = msgsplit[2].strip()
  url = msgsplit[3].strip()

  if command != '/autoreview':
    await _send_telegram_message(chat_id, f"Invalid command.\n{example_msg}")
    return {"message": "processed"}

  if action not in ['add', 'remove']:
    await _send_telegram_message(chat_id, "Invalid action. Supported actions are add, remove")
    return {"message": "processed"}

  if provider_str not in ['github', 'gitlab', 'bitbucket']:
    await _send_telegram_message(
      chat_id, "Invalid provider. Supported providers are github, gitlab, bitbucket")
    return {"message": "processed"}

  if not url.startswith('https://'):
    await _send_telegram_message(chat_id, "Invalid url. Should start with https://")
    return {"message": "processed"}

  provider = GitServiceType(provider_str.upper())
  config_storage_srv = await create_config_storage_service()
  try:
    if action == 'add':
      await enable_auto_review(url, config_storage_srv, provider)
      await _send_telegram_message(chat_id, f"Added {url} for auto review.")
      return {"message": "processed"}
    if action == 'remove':
      await disable_auto_review(url, config_storage_srv, provider)
      await _send_telegram_message(chat_id, f"Removed {url} from auto review.")
      return {"message": "processed"}
  except Exception as e:
    await _send_telegram_message(chat_id, f"Error: {str(e)}")
    return {"message": "processed"}

  return {"message": "processed"}


@in_next_tick
async def _handle_test_autoreview(msg: str, chat_id: str):
  example_msg = "Usage: /test-autoreview <provider> <repo_url>"
  msgsplit = [x for x in msg.split(' ') if x]
  if len(msgsplit) != 3:
    await _send_telegram_message(chat_id, example_msg)
    return {"message": "processed"}

  command = msgsplit[0].strip()
  provider_str = msgsplit[1].strip()
  url = msgsplit[2].strip()

  if command != '/test-autoreview':
    await _send_telegram_message(chat_id, f"Invalid command.\n{example_msg}")
    return {"message": "processed"}

  if provider_str not in ['github', 'gitlab', 'bitbucket']:
    await _send_telegram_message(
      chat_id, "Invalid provider. Supported providers are github, gitlab, bitbucket")
    return {"message": "processed"}

  provider = GitServiceType(provider_str.upper())
  config_storage_srv = await create_config_storage_service()
  enabled = await is_auto_review_enabled(url, config_storage_srv, provider)
  await _send_telegram_message(chat_id, f"URL:{url}\nAuto review enabled? {enabled}")


@in_next_tick
async def _test_whitelist_handler(msg: str, chat_id: str):
  example_msg = "Usage: /test-whitelist <provider> <url>"

  msgsplit = [x for x in msg.split(' ') if x]
  if len(msgsplit) != 3:
    await _send_telegram_message(chat_id, example_msg)
    return {"message": "processed"}

  command = msgsplit[0].strip()
  provider_str = msgsplit[1].strip()
  url = msgsplit[2].strip()

  if command != '/test-whitelist':
    await _send_telegram_message(chat_id, f"Invalid command.\n{example_msg}")
    return {"message": "processed"}

  if provider_str not in ['github', 'gitlab', 'bitbucket']:
    await _send_telegram_message(
      chat_id, "Invalid provider. Supported providers are github, gitlab, bitbucket")
    return {"message": "processed"}

  provider = GitServiceType(provider_str.upper())

  config_storage_srv = await create_config_storage_service()

  is_whitlisted = await is_whitelisted_repo(repo_url=url,
                                            config_storage_srv=config_storage_srv,
                                            provider=provider)

  await _send_telegram_message(chat_id, f"URL:{url}\nWhitelisted? {is_whitlisted}")
  return {"message": "processed"}


@in_next_tick
async def _whitelisting_handler(msg: str, chat_id: str):
  example_msg = """
Usage:
  - /whitelist <provider> list
  - /whitelist <provider> <url>
  - /unwhitelist <provider> <url>

Example:
- /whitelist github list
- /whitelist github https://github.com/org_name/*
- /unwhitelist gitlab https://gitlab.com/org_name/*

provider: github, gitlab, bitbucket

url: must be a valid url with a wildcard at the end.
  """

  msgsplit = [x for x in msg.split(' ') if x]
  if len(msgsplit) != 3:
    await _send_telegram_message(chat_id, example_msg)
    return {"message": "processed"}

  command = msgsplit[0].strip()
  provider = msgsplit[1].strip()
  urlOrList = msgsplit[2].strip()

  commands = ['/whitelist', '/unwhitelist']
  if command not in commands:
    await _send_telegram_message(chat_id,
                                 f"Invalid command. Supported commands are {', '.join(commands)}")
    await _send_telegram_message(chat_id, example_msg)
    return {"message": "processed"}

  if provider not in ['github', 'gitlab', 'bitbucket']:
    await _send_telegram_message(
      chat_id, "Invalid provider. Supported providers are github, gitlab, bitbucket")
    return {"message": "processed"}

  if urlOrList == 'list':
    storage = await create_config_storage_service()
    listed_data = await storage.get_whitelisted_accounts(provider.upper())
    if len(listed_data) != 0:
      msgs = f"List of whitelisted repos for {provider}:\n\n {'\n'.join(listed_data)}"
    else:
      msgs = f"No whitelisted repos for {provider}"
    await _send_telegram_message(chat_id, msgs)
    return {"message": "processed"}

  if not urlOrList.startswith('https://'):
    await _send_telegram_message(chat_id, "Invalid url. Should start with https://")
    return {"message": "processed"}

  # if urlOrList.startswith('https://*') or urlOrList in [
  #     'https://github.com/*', 'https://gitlab.com/*', 'https://bitbucket.org/*'
  # ]:
  #   await _send_telegram_message(chat_id, "Full wildcard url is not allowed through telegram.")
  #   return {"message": "processed"}

  if provider == 'github' and not urlOrList.startswith('https://github.com/'):
    await _send_telegram_message(chat_id, "Invalid url for github")
    return {"message": "processed"}

  if provider == 'gitlab' and not urlOrList.startswith('https://gitlab.com/'):
    await _send_telegram_message(chat_id, "Invalid url for gitlab")
    return {"message": "processed"}

  if provider == 'bitbucket' and not urlOrList.startswith('https://bitbucket.org/'):
    await _send_telegram_message(chat_id, "Invalid url for bitbucket")
    return {"message": "processed"}

  if not urlOrList.endswith('*'):
    await _send_telegram_message(chat_id, "Url should end with a wildcard (*).")
    return {"message": "processed"}

  if msg.startswith('/whitelist'):
    storage = await create_config_storage_service()
    await storage.whitelist_account(provider.upper(), urlOrList)
    await _send_telegram_message(chat_id, f"Whitelisted ✌🏻.\n\n{urlOrList}")
    return {"message": "processed"}

  if msg.startswith('/unwhitelist'):
    storage = await create_config_storage_service()
    await storage.remove_whitelisted_account(provider.upper(), urlOrList)
    await _send_telegram_message(chat_id, f"Unwhitelisted 😰.\n\n{urlOrList}")
    return {"message": "processed"}


async def _send_telegram_message(chat_id: str, msg: str):
  srv = create_notification_service(NotificationServiceType.TELEGRAM, chat_id=chat_id)
  await srv.emit(msg)
  return {"message": "processed"}
