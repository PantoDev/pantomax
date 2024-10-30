import base64
import os
from typing import overload

import jinja2
from dotenv import load_dotenv

load_dotenv(
  dotenv_path=".envrc",
  verbose=True,
)


# yapf: disable
@overload
def _load_base64_key(key: str, *, required: bool) -> str | None: ...  # noqa
@overload
def _load_base64_key(key: str) -> str: ...  # noqa


# yapf: enable
def _load_base64_key(key: str, *, required: bool = True) -> str | None:
  base64value = os.getenv(key)

  if not base64value and required:
    raise ValueError(f'{key} must be set')

  if not base64value:
    return None

  return base64.b64decode(base64value).decode()


TRUTH_VALUES = {'true', '1', 'yes', 'y', 'on'}

# General Configs
ENV = os.getenv('ENV') or 'DEV'
IS_PROD = ENV == 'PRODUCTION'
APP_VERSION = os.getenv('APP_VERSION') or 'unknown'

# OpenAI Configs
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL")
GPT_MAX_TOKENS = int(
  os.getenv("GPT_MAX_TOKENS")) if os.getenv("GPT_MAX_TOKENS") else None  # type: ignore

# Anthropic Configs
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

DEFAULT_REVIEW_LLM_SRV = os.getenv('DEFAULT_REVIEW_LLM_SRV') or 'OPENAI'

# GitHub Configs
GH_APP_ID = os.getenv('GH_APP_ID')
GH_APP_PRIVATE_KEY = _load_base64_key('GH_APP_PRIVATE_KEY_BASE64', required=False)
GH_WEBHOOK_SECRET = os.getenv('GH_WEBHOOK_SECRET')
GH_BOT_NAME = os.getenv('GH_BOT_NAME') or 'pantomaxbot[bot]'
if GH_BOT_NAME and not GH_BOT_NAME.endswith('[bot]'):
  GH_BOT_NAME += '[bot]'

# Bitbucket Configs
BITBUCKET_APP_BASE_URL = os.getenv('BITBUCKET_APP_BASE_URL')
BITBUCKET_APP_KEY = os.getenv('BITBUCKET_APP_KEY')

# GitLab Configs (only for self-hosted panto)
MY_GL_WEBHOOK_SECRET = os.getenv('MY_GL_WEBHOOK_SECRET')
MY_GL_ACCESS_TOKEN = os.getenv('MY_GL_ACCESS_TOKEN')

# Optional Configs
EXPANDED_DIFF_LINES = int(os.getenv('EXPANDED_DIFF_LINES') or 10)
FF_ENABLE_AST_DIFF = os.getenv('FF_ENABLE_AST_DIFF', 'false').lower() in TRUTH_VALUES
LLM_TWO_WAY_CORRECTION_ENABLED = (os.getenv('LLM_TWO_WAY_CORRECTION_ENABLED')
                                  or 'true').lower() in TRUTH_VALUES
LLM_TWO_WAY_CORRECTION_THRESHOLD = int(os.getenv('LLM_TWO_WAY_CORRECTION_THRESHOLD') or 90)
LLM_TWO_WAY_CORRECTION_SOFT_THRESHOLD = int(
  os.getenv('LLM_TWO_WAY_CORRECTION_SOFT_THRESHOLD') or 80)
LLM_LOG_INPUT_OUTPUT = (os.getenv('LLM_LOG_INPUT_OUTPUT') or 'false').lower() in TRUTH_VALUES
LLM_LOG_USAGES = (os.getenv('LLM_LOG_USAGES') or 'false').lower() in TRUTH_VALUES
LLM_LOG_PATH = os.getenv('LLM_LOG_PATH') or ''

ENABLE_AUTO_PR_REVIEW = (os.getenv('ENABLE_AUTO_PR_REVIEW') or 'false').lower() in TRUTH_VALUES
SKIP_WHITLISTING_FOR_OSS_REPOS = (os.getenv('SKIP_WHITLISTING_FOR_OSS_REPOS')
                                  or 'false').lower() in TRUTH_VALUES
GH_PERSONAL_ACCESS_TOKEN = os.getenv('GH_PERSONAL_ACCESS_TOKEN')

FIREBASE_CREDENTIALS = _load_base64_key('FIREBASE_CREDENTIALS_BASE64', required=False)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TELEGRAM_WEBHOOK_SECRET_KEY = os.getenv(
  'TELEGRAM_WEBHOOK_SECRET_KEY')  # Telegram webhook query parameter key
TELEGRAM_WEBHOOK_SECRET_VALUE = os.getenv(
  'TELEGRAM_WEBHOOK_SECRET_VALUE')  # Telegram webhook query parameter value

BRANDING_PREFIX = "[![Panto Max](https://raw.githubusercontent.com/pantomaxdotco/assets/refs/heads/main/pr-comment-branding-50.png)](https://www.pantomax.co)"  # noqa
ENABLE_BRANDING = (os.getenv('ENABLE_BRANDING') or 'false').lower() in TRUTH_VALUES
jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader('panto/prompts'))

MAX_TOKEN_BUDGET_FOR_REVIEW = int(os.getenv('MAX_TOKEN_BUDGET_FOR_REVIEW', 100000))
MAX_TOKEN_BUDGET_FOR_AUTO_REVIEW = int(os.getenv('MAX_TOKEN_BUDGET_FOR_AUTO_REVIEW', 50000))

PGHOST = os.getenv("PGHOST")
PGPORT = os.getenv("PGPORT")
PGDATABASE = os.getenv("PGDATABASE")
PGUSER = os.getenv("PGUSER")
PGPASSWORD = os.getenv("PGPASSWORD")

DB_URI = f"postgresql+asyncpg://{PGUSER}:{PGPASSWORD}@{PGHOST}:{PGPORT}/{PGDATABASE}" \
            if PGHOST and PGPORT and PGDATABASE and PGUSER and PGPASSWORD else None

DEFAULT_NOTIFICATION_SRV = os.getenv('DEFAULT_NOTIFICATION_SRV') or 'NOOP'
DEFAULT_METRICS_COLLECTION_SRV = os.getenv('DEFAULT_METRICS_COLLECTION_SRV') or 'NOOP'
DEFAULT_CONFIG_STORAGE_SRV = os.getenv('DEFAULT_CONFIG_STORAGE_SRV') or 'NOOP'
