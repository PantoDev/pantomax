import time

from anthropic import AsyncAnthropic

from .llm_service import LLMService, LLMServiceType, LLMUsage

anthropic_models_max_tokens_map = {
  "claude-3-5-sonnet-latest": 200_000,
}


class AnthropicService(LLMService):

  def __init__(self, api_key: str, model: str, max_tokens: int | None = None):
    if max_tokens is None:
      max_tokens = anthropic_models_max_tokens_map.get(model)
      assert max_tokens is not None, f"Unknown model max_token: {model}"
    super().__init__(max_tokens=max_tokens)
    self.client = AsyncAnthropic(api_key=api_key, )
    self.model = model

  async def get_encode(self, text: str) -> list[int]:
    tokenizer = await self.client.get_tokenizer()
    encoded_text = tokenizer.encode(text)
    return encoded_text.ids

  async def ask(self,
                system_msg: str,
                user_msgs: str | list[str],
                temperature: float = 0) -> tuple[str, LLMUsage]:
    if isinstance(user_msgs, str):
      user_msgs = [user_msgs]

    timer_start = time.time()

    messages = [{
      "role": "user",
      "content": msg,
    } for msg in user_msgs]

    message = await self.client.messages.create(
      model=self.model,
      system=system_msg,
      messages=messages,
      temperature=temperature,
      max_tokens=4096,
    )

    response = ''.join(c.text for c in message.content)

    system_token = len(await self.get_encode(system_msg))
    user_token = sum([len(await self.get_encode(msg)) for msg in user_msgs])

    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens

    total_tokens = input_tokens + output_tokens

    timer_end = time.time()
    usages = LLMUsage(
      system_token=system_token,
      user_token=user_token,
      output_token=output_tokens,
      total_input_token=input_tokens,
      total_token=total_tokens,
      latency=int(timer_end - timer_start),
      llm=self.get_type(),
    )

    return response, usages

  def get_type(self) -> LLMServiceType:
    return LLMServiceType.ANTHROPIC
