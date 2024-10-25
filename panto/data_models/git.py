import enum
from datetime import datetime

from pydantic import BaseModel


class GitPatchStatus(str, enum.Enum):
  ADDED = "ADDED"
  MODIFIED = "MODIFIED"
  REMOVED = "REMOVED"
  RENAMED = "RENAMED"


class GitPatchFile(BaseModel):
  filename: str
  status: GitPatchStatus
  patch: str
  old_filename: str | None = None


class PRPatches(BaseModel):
  url: str | None
  number: int
  base: str
  head: str
  files: list[GitPatchFile]


class PRComment(BaseModel):
  id: str
  body: str
  created_at: datetime
  updated_at: datetime
  user: str
  is_our_bot: bool


class PRStatus(str, enum.Enum):
  OPEN = "OPEN"
  REOPEN = "REOPEN"
  MERGED = "MERGED"
  DRAFT = "DRAFT"
  CLOSED = "CLOSED"


class ReviewStatus(str, enum.Enum):
  PENDING = "PENDING"
  REQUESTED = "REQUESTED"
  SOFT_REVIEWED = "SOFT_REVIEWED"
  REVIEWED = "REVIEWED"
  FAILED = "FAILED"


class CommentType(str, enum.Enum):
  REVIEW = "REVIEW"
  INLINE = "INLINE"
  GENERAL = "GENERAL"


class PostedComment(BaseModel):
  id: str
  type: CommentType
  cid: str | None = None  # Our Comment ID
  info: str | None = None
