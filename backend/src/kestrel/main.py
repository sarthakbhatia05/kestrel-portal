from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from kestrel.ask.router import router as ask_router
from kestrel.config import get_settings
from kestrel.exceptions import AppError
from kestrel.service.router import router as service_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Kestrel Control Tower", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {"code": exc.code, "message": exc.message, "detail": exc.detail}
            },
        )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(service_router)
    app.include_router(ask_router)

    return app


app = create_app()

