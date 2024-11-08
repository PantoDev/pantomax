from panto.logging import log
from panto.services.llm.llm_service import LLMUsage

from .notification import NotificationService


class NoopNotificationService(NotificationService):

  async def emit_new_installation(self, user: str, whitelisted: str, installation_type: str):
    log.info(
      f"[NOTIFICATION]New installation 🎉 \n\nUser: {user}\nWhitelisted: {whitelisted}\nInstallation_type: {installation_type}"  # noqa
    )

  async def emit_pr_open(self, repo_url: str, pr_no: str | int):
    log.info(f"[NOTIFICATION]New PR Opened ✌🏻 \nRepo: {repo_url}\nPR URL: {pr_no}")

  async def emit_pr_fullfilled(self, repo_url: str, pr_no: str | int, fullfilled_type: str):
    log.info(
      f"[NOTIFICATION]PR Fullfilled. \nRepo: {repo_url}\nPR URL: {pr_no}\nFullfilled Type: {fullfilled_type}"  # noqa
    )

  async def emit(self, msg: str):
    log.info(f"[NOTIFICATION]📢 {msg}")

  async def emit_installation_removed(self, user: str):
    log.info(f"[NOTIFICATION]Installation Removed 🚨 \nUser: {user}")

  async def emit_installation_suspend(self, user: str):
    log.info(f"[NOTIFICATION]Installation Suspended 🚨 \nUser: {user}")

  async def emit_installation_unsuspend(self, user: str):
    log.info(f"[NOTIFICATION]Installation Unsuspended 🎉 \nUser: {user}")

  async def emit_new_pr_review_request(self, repo_url: str, pr_no: str | int):
    log.info(f"[NOTIFICATION]New PR Review Request✌🏻 \nUser: {repo_url}\nPR URL: {pr_no}")

  async def emit_not_whitelisted_request(self, repo_url: str):
    log.info(f"[NOTIFICATION]PR Review Request from non-whitelisted repo 👀 \nUser: {repo_url}")

  async def emit_consumtion_limit_reached(self, error_msg: str | None = None):
    log.info("[NOTIFICATION]🚨consumption limit reached.")

  async def emit_usages(self,
                        repo_url: str,
                        usages: LLMUsage,
                        request_id: str | None = None,
                        purpose: str | None = None):
    log.info(
      f"[NOTIFICATION]📊 Usages: \nSystem Token: {usages.system_token}\nUser Token: {usages.user_token}\nOutput Token: {usages.output_token}\nTotal Token: {usages.total_token}\nLatency: {usages.latency}s\n\nRepo: {repo_url}"  # noqa
    )

  async def emit_suggestions_generated(self,
                                       repo_url: str,
                                       inital_count: int,
                                       final_count: int,
                                       level2_count: int,
                                       tools_count: int,
                                       request_id: str | None = None):
    log.info(
      f"[NOTIFICATION]Suggestions generated for {repo_url}: {inital_count} -> {final_count} + {level2_count}. Request ID: {request_id}"  # noqa
    )
