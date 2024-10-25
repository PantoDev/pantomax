import asyncio
import copy
import fnmatch
import hashlib
import hmac
import ipaddress
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import wraps
from threading import Thread
from urllib.parse import urlparse

from panto.config import (BRANDING_PREFIX, ENABLE_AUTO_PR_REVIEW, ENABLE_BRANDING,
                          LLM_LOG_INPUT_OUTPUT, LLM_LOG_PATH, LLM_LOG_USAGES)
from panto.logging import log
from panto.services.config_storage.config_storage import ConfigStorageService
from panto.services.git.git_service_types import GitServiceType
from panto.services.llm.llm_service import LLMUsage


def repo_url_to_repo_name(git_url: str) -> str:
  if not git_url:
    return ""

  if git_url.startswith("git@"):
    ssh_pattern = r'git@(?:[\w\.]+):([\w-]+(?:/[\w-]+)*)/([\w-]+)\.git'
    ssh_match = re.match(ssh_pattern, git_url)
    if ssh_match:
      user_org, repo = ssh_match.groups()
      return f"{user_org}/{repo}"

    return ""

  if git_url.startswith("https://") or git_url.startswith("http://"):
    if not git_url.endswith(".git"):
      git_url = git_url + ".git"

    http_pattern = r'https?://(?:[\w\.]+)/([\w-]+(?:/[\w-]+)*)/([\w-]+)\.git'
    http_match = re.match(http_pattern, git_url)

    if http_match:
      user_org, repo = http_match.groups()
      return f"{user_org}/{repo}"

    return ""

  return ""


def threaded(fn):
  """
    This method makes wrapped function run in a thread
    """

  @wraps(fn)
  def wrapper(*args, **kwargs):
    log.info("starting wrapped func in thread")
    thread = Thread(target=fn, args=args, kwargs=kwargs)
    thread.start()
    return thread

  return wrapper


restricted_extensions = [
  '*.png',
  '*.jpg',
  '*.jpeg',
  '*.gif',
  '*.bmp',
  '*.ico',
  '*.svg',
  '*.webp',
  '*.tif',
  '*.tiff',
  '*.psd',
  '*.raw',
  '*.heic',
  '*.indd',
  '*.ai',
  '*.eps',
  '*.pdf',
  '*.zip',
  '*.tar',
  '*.gz',
  '*.rar',
  '*.7z',
  '*.dmg',
  '*.iso',
  '*.apk',
  '*.exe',
  '*.dll',
  '*.so',
  '*.bin',
  '*.app',
  '*.deb',
  '*.rpm',
  '*.msi',
  '*.cab',
  '*.tar.gz',
  '*.tar.bz2',
  '*.tar.xz',
  '*.tar.zst',
  '*.exe',
  '*.dll',
  '*.so',
  '*.bin',
  '*.dmg',
  '*.iso',
  '*.apk',
  '*.app',
  '*.deb',
  '*.rpm',
  '*.pdf',
  '*.doc',
  '*.docx',
  '*.xls',
  '*.xlsx',
  '*.ppt',
  '*.pptx',
  '*.mp3',
  '*.wav',
  '*.flac',
  '*.aac',
  '*.mp4',
  '*.mkv',
  '*.avi',
  '*.mov',
  '*.wmv',
  '*.woff',
  '*.woff2',
  '*.ttf',
  '*.otf',
  "*.lock",
  "*.pem",
  ".*",
  "*-lock.yaml",
  "*-lock.json",
  ".env",
  "*.env",
  "*.env.*",
  ".envrc",
  ".envrc.*"
  "*.envrc.*",
  "go.sum",
  "npm-shrinkwrap.json",
  "!.gitlab-ci.yml",
  "!.github/workflows/*",
]


def is_file_include(filename: str, exlude_patterns: list[str], default_value=True) -> bool:
  result = default_value

  for p in exlude_patterns:
    is_include_rule = p.startswith('!')
    if is_include_rule:
      p = p[1:]

    if fnmatch.fnmatch(filename, p):
      result = is_include_rule

  return result


async def async_sleep(seconds: int):
  await asyncio.sleep(seconds)


def delayed_async(timeout: int = 1):

  def decorator(func):

    @wraps(func)
    async def wrapper(*args, **kwargs):
      await asyncio.sleep(timeout)
      return await func(*args, **kwargs)

    return wrapper

  return decorator


class AsyncThreadPool:
  _async_thread_pool: ThreadPoolExecutor | None = None

  @staticmethod
  def get() -> ThreadPoolExecutor:
    if not AsyncThreadPool._async_thread_pool:
      AsyncThreadPool._async_thread_pool = ThreadPoolExecutor(max_workers=5)
    return AsyncThreadPool._async_thread_pool


def in_next_tick(async_func):

  async def wrapper(*args, **kwargs):  # DO NOT CHANGE THIS SIGNATURE
    try:
      loop = asyncio.get_event_loop()
    except RuntimeError:
      log.error("No event loop found", exc_info=True)
      raise Exception("No event loop found")
    loop.call_soon(asyncio.create_task, async_func(*args, **kwargs))

  return wrapper


def merge_dict(dict1: dict, dict2: dict) -> dict:
  merged = copy.deepcopy(dict1)
  for key, value in dict2.items():
    if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
      merged[key] = merge_dict(merged.get(key, {}), value)
    else:
      merged[key] = copy.deepcopy(value)
  for key, value in dict1.items():
    if key not in merged:
      merged[key] = copy.deepcopy(value)
  return merged


def verify_github_signature(payload_body: str | bytes, secret_token: str,
                            signature_header: str | None) -> bool:
  if not signature_header:
    raise Exception("x-hub-signature-256 header is missing!")

  if isinstance(payload_body, str):
    payload_body = payload_body.encode('utf-8')

  hash_object = hmac.new(secret_token.encode('utf-8'), msg=payload_body, digestmod=hashlib.sha256)
  expected_signature = "sha256=" + hash_object.hexdigest()

  if not hmac.compare_digest(expected_signature, signature_header):
    raise Exception("Request signatures didn't match!")

  return True


async def is_whitelisted_repo(
  repo_url: str,
  config_storage_srv: ConfigStorageService,
  provider: GitServiceType,
) -> bool:
  # TODO: Remove this method and use config_storage_srv.is_whitelisted_account instead
  res = await config_storage_srv.is_whitelisted_account(
    provider=provider.value,
    repo_url=repo_url,
  )
  return res


def ssh_to_http_url(git_url: str) -> str:
  if git_url.startswith('git@'):
    http_url = git_url.replace(':', '/').replace('git@', 'https://')
    return http_url
  else:
    return git_url


def convert_http_to_ssh(http_url):
  parsed_url = urlparse(http_url)
  domain = parsed_url.netloc
  path = parsed_url.path.strip("/")
  ssh_url = f"git@{domain}:{path}"
  if not ssh_url.endswith(".git"):
    ssh_url += ".git"
  return ssh_url


def is_gitlab_whitelisted_ip(ip):
  gitlab_cidrs = [
    "34.74.90.64/28",
    "34.74.226.0/24",
  ]
  ip = ipaddress.ip_network(ip + "/32")
  for cidr in gitlab_cidrs:
    network = ipaddress.ip_network(cidr)
    result = network.supernet_of(ip)
    if result:
      return True
  return False


async def is_auto_review_enabled(
  repo_url: str,
  config_storage_srv: ConfigStorageService,
  provider: GitServiceType,
) -> bool:
  if ENABLE_AUTO_PR_REVIEW:
    return True

  repo_url = repo_url.lower()
  account_config = await config_storage_srv.get_account_config(provider.value, repo_url)
  if not account_config:
    return False

  autoreview_config = account_config.get("autoreview")
  if not autoreview_config:
    return False

  autoreview_repos = autoreview_config.get("repos", [])
  for repo in autoreview_repos:
    repo = repo.lower()
    if repo.endswith("/*"):
      repo = repo[:-2]
    if repo in repo_url:
      return True

  return False


async def enable_auto_review(
  repo_url: str,
  config_storage_srv: ConfigStorageService,
  provider: GitServiceType,
):
  repo_url = repo_url.lower()
  account_config = await config_storage_srv.get_account_config(provider.value, repo_url)
  if not account_config:
    account_config = {}

  if not account_config.get("autoreview"):
    account_config["autoreview"] = {}

  exitsing_repos = set(account_config["autoreview"].get("repos") or [])
  exitsing_repos.add(repo_url)
  account_config["autoreview"]['repos'] = list(exitsing_repos)
  await config_storage_srv.update_account_config(provider.value, repo_url, account_config)


async def disable_auto_review(
  repo_url: str,
  config_storage_srv: ConfigStorageService,
  provider: GitServiceType,
):
  repo_url = repo_url.lower()
  account_config = await config_storage_srv.get_account_config(provider.value, repo_url)
  if not account_config:
    account_config = {}

  if not account_config.get("autoreview"):
    account_config["autoreview"] = {}

  exitsing_repos = set(account_config["autoreview"].get("repos") or [])
  exitsing_repos.discard(repo_url)
  account_config["autoreview"]['repos'] = list(exitsing_repos)
  await config_storage_srv.update_account_config(provider.value, repo_url, account_config)


class Branding:

  def __init__(self, *, prefix: str = BRANDING_PREFIX, gitsrv_type: GitServiceType | None = None):
    self.prefix = prefix
    self.gitsrv_type = gitsrv_type

  def mark(self, text: str) -> str:
    if not ENABLE_BRANDING:
      return text

    if not self.gitsrv_type:
      return text

    if self.gitsrv_type == GitServiceType.BITBUCKET:
      # Bitbucket is shit, doesn't support simple markdown feature.
      return text

    if self.gitsrv_type == GitServiceType.GITHUB:
      return f"{self.prefix}\n{text}"

    if self.gitsrv_type == GitServiceType.GITLAB:
      return f"{self.prefix}\n\n{text}"

    return text


def _ensure_log_dir(dir: str):
  try:
    os.makedirs(dir, exist_ok=True)
  except Exception:
    pass


if LLM_LOG_INPUT_OUTPUT:
  _ensure_log_dir(f"{LLM_LOG_PATH}/llmlogs")


def log_llm_io(*, req_id: str, name: str, msg: str, silent=True):
  if not LLM_LOG_INPUT_OUTPUT:
    return
  try:
    dir = f"{LLM_LOG_PATH}/llmlogs/{req_id}"
    _ensure_log_dir(dir)
    with open(f'{dir}/.{name}.txt', 'w+') as f:
      f.write(msg)
  except Exception:
    if not silent:
      raise


if LLM_LOG_USAGES:
  _ensure_log_dir(f"{LLM_LOG_PATH}/usages")


def log_llm_usage(*, txn_id: str, review_usage: LLMUsage, silent=True):
  if not LLM_LOG_USAGES:
    return
  datestamp = datetime.now().strftime('%Y-%m-%d')
  log_path = f'{LLM_LOG_PATH}/usages/.usage_{datestamp}.json'
  try:
    with open(log_path, 'a+') as f:
      usages_dict = review_usage.model_dump()
      usages_dict['txn_id'] = txn_id
      f.write(json.dumps(usages_dict) + "\n")
  except Exception:
    if not silent:
      raise
