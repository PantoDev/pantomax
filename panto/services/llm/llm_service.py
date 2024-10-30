import abc
import enum

from pydantic import BaseModel


class LLMServiceType(str, enum.Enum):
  OPENAI = "OPENAI"
  ANTHROPIC = "ANTHROPIC"
  NOOP = "NOOP"


class LLMUsage(BaseModel):
  llm: LLMServiceType = LLMServiceType.OPENAI
  system_token: int
  user_token: int
  total_input_token: int
  output_token: int
  total_token: int
  latency: int


class LLMService(abc.ABC):

  def __init__(self, max_tokens: int = 4096):
    self.max_tokens = max_tokens

  async def get_encode_length(self, text: str) -> int:
    return len(await self.get_encode(text))

  @abc.abstractmethod
  async def get_encode(self, text: str) -> list[int]:
    pass

  @abc.abstractmethod
  async def ask(self,
                system_msg: str,
                user_msgs: str | list[str],
                temperature: float = 0) -> tuple[str, LLMUsage]:
    pass

  @abc.abstractmethod
  def get_type(self) -> LLMServiceType:
    pass


async def create_llm_service(
  *,
  service_name: LLMServiceType,
  max_tokens: int | None = None,
  api_key: str | None = None,
  model: str | None = None,
  **kwargs,
) -> LLMService:

  args = {
    **kwargs,
  }

  if api_key is not None:
    args['api_key'] = api_key

  if model is not None:
    args['model'] = model

  if max_tokens is not None:
    args['max_tokens'] = max_tokens

  if service_name == LLMServiceType.OPENAI:
    from .openai import OpenAIService
    return OpenAIService(**args)

  if service_name == LLMServiceType.NOOP:
    from .noopgpt import NoopGPTService
    return NoopGPTService(**args)

  if service_name == LLMServiceType.ANTHROPIC:
    from .anthropic import AnthropicService
    return AnthropicService(**args)

  raise Exception(f"Unknown service: {service_name}")
