from pydantic import BaseModel


class Suggestion(BaseModel):
  id: str = ""
  file_path: str
  start_line_number: int
  end_line_number: int
  suggestion: str


class PRSuggestions(BaseModel):
  suggestions: list[Suggestion]
  level2_suggestions: list[Suggestion] | None = None
  review_comment: str
