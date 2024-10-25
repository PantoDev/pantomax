import enum


class GitServiceType(str, enum.Enum):
  GITHUB = 'GITHUB'
  GITLAB = 'GITLAB'
  BITBUCKET = 'BITBUCKET'
  LOCAL = 'LOCAL'
