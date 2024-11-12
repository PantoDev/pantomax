from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

from panto.config import APP_VERSION, IS_PROD
from panto.services.config_storage.config_storage import create_config_storage_service
from panto.services.git.git_service_types import GitServiceType

router = APIRouter()


@router.get('/')
async def root():
  return RedirectResponse(url="/hello")


@router.get("/hello", response_class=HTMLResponse)
async def hello():
  hello_txt = """<pre>
{
    "message": "Hello Panto! 🤖",
    "installation": {
      "github": "https://github.com/apps/pantomaxbot",
      "bitbucket": "https://app.pantomax.co/bitbucket/atlassian-connect.json",
      "gitlab": "Contact us at hello@pantomax.co"
    }
}
</pre>"""
  return hello_txt


@router.get('/health')
async def health():
  return {
    "status": "ok",
    "version": APP_VERSION,
  }


@router.get('/jasusi')
async def jasusi():
  if IS_PROD:
    return {"message": "not allowed"}
  storage = await create_config_storage_service()
  github_whitelisted = await storage.get_whitelisted_accounts(GitServiceType.GITHUB)
  gitlab_whitelisted = await storage.get_whitelisted_accounts(GitServiceType.GITLAB)
  bitbucket_whitelisted = await storage.get_whitelisted_accounts(GitServiceType.BITBUCKET)
  return {
    "status": "ok",
    "version": APP_VERSION,
    "whitelisted": {
      GitServiceType.GITHUB: github_whitelisted,
      GitServiceType.GITLAB: gitlab_whitelisted,
      GitServiceType.BITBUCKET: bitbucket_whitelisted
    },
  }
