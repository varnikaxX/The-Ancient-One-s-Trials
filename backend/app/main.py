"""FastAPI app. Every error leaves in the contract shape {"error": {"code", "message"}}."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import db
from app.config import settings
from app.errors import ApiError
from app.routers import auth, calendar, companies, coordinator, events, interviewer, me, notifications, student


@asynccontextmanager
async def lifespan(_app):
    db.get_pool()
    yield
    db.close_pool()


app = FastAPI(title="The Ancient One's Trials API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

for r in (auth, me, companies, interviewer, student, coordinator, calendar, notifications, events):
    app.include_router(r.router, prefix="/api")


def _err(code: str, message: str, status: int):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(ApiError)
async def api_error(_req: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content=exc.body())


@app.exception_handler(RequestValidationError)
async def validation_error(_req: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    return _err("VALIDATION", f"{where}: {first.get('msg', 'invalid request')}".strip(": "), 400)


@app.exception_handler(StarletteHTTPException)
async def http_error(_req: Request, exc: StarletteHTTPException):
    code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND"}.get(exc.status_code, "VALIDATION")
    return _err(code, str(exc.detail), exc.status_code)


@app.exception_handler(Exception)
async def unhandled(_req: Request, exc: Exception):
    import logging
    logging.getLogger("trials").exception("unhandled error", exc_info=exc)
    if db.is_integrity_error(exc):
        return _err("SLOT_TAKEN", "Slot just taken, please pick another", 409)
    return _err("VALIDATION", "Unexpected server error", 500)


@app.get("/api/health")
def health():
    return {"ok": True}
