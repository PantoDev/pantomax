import importlib

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import asynccontextmanager
from fastapi.responses import ORJSONResponse

from panto.config import DB_URI
from panto.logging import log
from panto.routes.bitbucket import router as bitbucket_router
from panto.routes.github_webhook import router as github_router
from panto.routes.gitlab_webhook import router as gitlab_router
from panto.routes.misc import router as misc_router
from panto.routes.telegram import router as telegramrouter


def create_app():

  @asynccontextmanager
  async def lifespan(app: FastAPI):
    if DB_URI:
      log.info("Initializing db_manager")
      from panto.models.db import db_manager
      db_manager.init(DB_URI)
    yield

  app = FastAPI(lifespan=lifespan)

  init_app(app)

  try:
    panto_dashboard = importlib.import_module('panto_dashboard')
    panto_dashboard.init_app(app)
  except ImportError:
    pass

  return app


def init_app(app: FastAPI):
  app.include_router(misc_router)
  app.include_router(telegramrouter)
  app.include_router(github_router)
  app.include_router(gitlab_router)
  app.include_router(bitbucket_router)

  @app.exception_handler(HTTPException)
  async def http_exception_handler(request: Request, exc: HTTPException):
    return ORJSONResponse(status_code=exc.status_code, content={"error": exc.detail})

  @app.exception_handler(Exception)
  async def exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled exception", exc_info=exc)
    return ORJSONResponse(status_code=500, content={"error": "Internal Server Error"})


app = create_app()

if __name__ == '__main__':
  import uvicorn
  uvicorn.run(app, host="0.0.0.0", port=5001)
