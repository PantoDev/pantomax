import aiohttp

from panto.logging import log
from panto.services.llm.llm_service import LLMUsage
from panto.services.notification.notification import NotificationService


class TelegramNotificationService(NotificationService):

  def __init__(self, bot_token: str, chat_id: str) -> None:
    self.bot_token = bot_token
    self.chat_id = chat_id

  async def _emit(self, msg: str):
    try:
      url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
      payload = {"chat_id": self.chat_id, "text": msg}
      async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as res:
          if res.status != 200:
            log.error(f"Error while sending message to telegram: {await res.text()}")
            res.raise_for_status()
    except Exception as e:
      log.error(f"Error while sending message to telegram: {str(e)}")

  async def emit(self, msg: str):
    await self._emit(msg)

  async def emit_pr_open(self, repo_url: str, pr_no: str | int):
    msg = f"New PR Opened ✌🏻 \nRepo: {repo_url}\nPR URL: {pr_no}"
    await self._emit(msg)

  async def emit_pr_fullfilled(self, repo_url: str, pr_no: str | int, fullfilled_type: str):
    msg = f"PR Fullfilled. \nRepo: {repo_url}\nPR URL: {pr_no}\nFullfilled Type: {fullfilled_type}"
    await self._emit(msg)

  async def emit_new_installation(self, user: str, whitelisted: str, installation_type: str):
    msg = f"New installation 🎉 \n\nUser: {user}\nWhitelisted: {whitelisted}\nInstallation_type: {installation_type}"  # noqa
    await self._emit(msg)

  async def emit_installation_removed(self, user: str):
    msg = f"Installation Removed 🚨 \nUser: {user}"
    await self._emit(msg)

  async def emit_installation_suspend(self, user: str):
    msg = f"Installation Suspended 🚨 \nUser: {user}"
    await self._emit(msg)

  async def emit_installation_unsuspend(self, user: str):
    msg = f"Installation Unsuspended 🎉 \nUser: {user}"
    await self._emit(msg)

  async def emit_new_pr_review_request(self, repo_url: str, pr_no: str | int):
    msg = f"New PR Review Request✌🏻 \nUser: {repo_url}\nPR URL: {pr_no}"
    await self._emit(msg)

  async def emit_not_whitelisted_request(self, repo_url: str):
    msg = f"PR Review Request from non-whitelisted repo 👀 \nUser: {repo_url}"
    await self._emit(msg)

  async def emit_consumtion_limit_reached(self, error_msg: str | None = None):
    msg = "🚨consumption limit reached."
    if error_msg:
      msg += f"\nError: {error_msg}"
    await self._emit(msg)

  async def emit_usages(self,
                        repo_url: str,
                        usages: LLMUsage,
                        request_id: str | None = None,
                        purpose: str | None = None):
    msg = f"📊 Usages: \nSystem Token: {usages.system_token}\nUser Token: {usages.user_token}\nOutput Token: {usages.output_token}\nTotal Token: {usages.total_token}\nLatency: {usages.latency}s\n\nRepo: {repo_url}"  # noqa
    if request_id:
      msg += f"\nRequest ID: {request_id}"
    if purpose:
      msg += f"\nPurpose: {purpose}"
    await self._emit(msg)

  async def emit_suggestions_generated(self,
                                       repo_url: str,
                                       inital_count: int,
                                       final_count: int,
                                       level2_count: int,
                                       tools_count: int,
                                       request_id: str | None = None):
    msg = (f"📝 Suggestions Generated: \nInitial Count: {inital_count}"
           f"\nFinal Count: {final_count}\nLevel2 Count: {level2_count}"
           f"\nTools Count: {tools_count}\nRepo: {repo_url}")
    if request_id:
      msg += f"\nRequest ID: {request_id}"
    await self._emit(msg)
