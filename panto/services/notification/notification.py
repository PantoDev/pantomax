import abc
import enum

from panto.config import DEFAULT_NOTIFICATION_SRV, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from panto.services.llm.llm_service import LLMUsage


class NotificationService(abc.ABC):

  @abc.abstractmethod
  async def emit_new_installation(self, user: str, whitelisted: str, installation_type: str):
    pass

  @abc.abstractmethod
  async def emit_pr_open(self, repo_url: str, pr_no: str | int):
    pass

  @abc.abstractmethod
  async def emit_pr_fullfilled(self, repo_url: str, pr_no: str | int, fullfilled_type: str):
    pass

  @abc.abstractmethod
  async def emit(self, msg: str):
    pass

  @abc.abstractmethod
  async def emit_installation_removed(self, user: str):
    pass

  @abc.abstractmethod
  async def emit_installation_suspend(self, user: str):
    pass

  @abc.abstractmethod
  async def emit_installation_unsuspend(self, user: str):
    pass

  @abc.abstractmethod
  async def emit_new_pr_review_request(self, repo_url: str, pr_no: str | int):
    pass

  @abc.abstractmethod
  async def emit_not_whitelisted_request(self, repo_url: str):
    pass

  @abc.abstractmethod
  async def emit_consumtion_limit_reached(self, error_msg: str | None = None):
    pass

  @abc.abstractmethod
  async def emit_usages(self,
                        repo_url: str,
                        usages: LLMUsage,
                        request_id: str | None = None,
                        purpose: str | None = None):
    pass

  @abc.abstractmethod
  async def emit_suggestions_generated(self,
                                       repo_url: str,
                                       inital_count: int,
                                       final_count: int,
                                       level2_count: int,
                                       request_id: str | None = None):
    pass


class NotificationServiceType(str, enum.Enum):
  TELEGRAM = "TELEGRAM"
  NOOP = "NOOP"


def create_notification_service(type: NotificationServiceType | None = None,
                                **kwargs) -> NotificationService:

  if not type:
    type = NotificationServiceType(DEFAULT_NOTIFICATION_SRV)

  if isinstance(type, str):
    type = NotificationServiceType(type)

  if type == NotificationServiceType.NOOP:
    from .noop import NoopNotificationService
    return NoopNotificationService()

  if type == NotificationServiceType.TELEGRAM:
    from .telegram import TelegramNotificationService
    assert TELEGRAM_BOT_TOKEN, "TELEGRAM_BOT_TOKEN is not set"
    chat_id = kwargs.get("chat_id") or TELEGRAM_CHAT_ID
    assert chat_id, "TELEGRAM_CHAT_ID is not set"
    return TelegramNotificationService(
      bot_token=TELEGRAM_BOT_TOKEN,
      chat_id=chat_id,
    )

  raise ValueError(f"Unknown notification service type: {type}")
