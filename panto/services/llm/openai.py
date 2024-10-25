import time

import tiktoken
from openai import APIError as OpenAIAPIError
from openai import OpenAI

from .llm_service import LLMService, LLMUsage

openai_models_max_tokens_map = {
  "gpt-4o": 128000,
  "gpt-4o-mini": 128000,
  "gpt-4-turbo": 128000,
  "gpt-4": 8192,
  "gpt-3.5-turbo": 16385,
}


class OpenAIService(LLMService):

  def __init__(self, api_key: str, model: str, max_tokens: int | None = None):
    if max_tokens is None:
      max_tokens = openai_models_max_tokens_map.get(model)
      assert max_tokens is not None, f"Unknown model max_token: {model}"
    super().__init__(max_tokens=max_tokens)
    self.openai = OpenAI(api_key=api_key)
    self.model = model
    self.encoder = tiktoken.encoding_for_model(model)

  async def get_encode(self, text: str) -> list[int]:
    return self.encoder.encode(text)

  async def ask(self,
                system_msg: str,
                user_msgs: str | list[str],
                temperature: float = 0) -> tuple[str, LLMUsage]:
    if isinstance(user_msgs, str):
      user_msgs = [user_msgs]

    latency_start = time.time()

    messages = [{
      "role": "system",
      "content": system_msg,
    }, *[{
      "role": "user",
      "content": msg,
    } for msg in user_msgs]]

    response = ""
    try:
      stream = self.openai.chat.completions.create(
        model=self.model,
        messages=messages,  # type: ignore
        stream=True,
        temperature=temperature,
      )
      for chunk in stream:
        if chunk.choices[0].delta.content is not None:  # type: ignore
          response += chunk.choices[0].delta.content  # type: ignore
    except OpenAIAPIError:
      raise

    system_token = len(await self.get_encode(system_msg))
    user_token = sum([len(await self.get_encode(msg)) for msg in user_msgs])
    output_token = len(await self.get_encode(response))
    total_token = system_token + user_token + output_token

    latency_end = time.time()
    usages = LLMUsage(
      system_token=system_token,
      user_token=user_token,
      output_token=output_token,
      total_input_token=system_token + user_token,
      total_token=total_token,
      latency=int(latency_end - latency_start),
    )

    return response, usages
