import random

from panto.services.llm.llm_service import LLMService, LLMServiceType, LLMUsage


class NoopGPTService(LLMService):

  def __init__(self, max_tokens: int = 4000, **kwargs):
    super().__init__(max_tokens=max_tokens)

  async def get_encode(self, text: str) -> list[int]:
    return [random.randint(1000, 9999) for _ in text.split(' ')]

  async def ask(self,
                system_msg: str,
                user_msgs: str | list[str],
                temperature: float = 0) -> tuple[str, LLMUsage]:
    if isinstance(user_msgs, str):
      user_msgs = [user_msgs]
    response = "random_file : -1 : @no_issues_found@"
    system_token = len(await self.get_encode(system_msg))
    user_token = sum([len(await self.get_encode(msg)) for msg in user_msgs])
    output_token = len(await self.get_encode(response))
    total_token = system_token + user_token + output_token
    return response, LLMUsage(
      system_token=system_token,
      user_token=user_token,
      output_token=output_token,
      total_input_token=system_token + user_token,
      total_token=total_token,
      latency=0,
      llm=self.get_type(),
    )

  def get_type(self) -> LLMServiceType:
    return LLMServiceType.NOOP
