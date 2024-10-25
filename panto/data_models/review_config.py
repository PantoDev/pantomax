from pydantic import BaseModel


class ReviewScanConfig(BaseModel):
  includes: list[str] | None = None
  findings: list[str] | None = None


class ReviewConfigProject(BaseModel):
  name: str | None = None
  languages: list[str] | None = None


class ConfigRule(BaseModel):
  lang: list[str]
  rule: str


class ReviewConfig(BaseModel):
  enabled: bool = True
  more_info: str | None = None
  scan: ReviewScanConfig = ReviewScanConfig()
  project: ReviewConfigProject = ReviewConfigProject()
  review_rules: list[ConfigRule] | None = None
