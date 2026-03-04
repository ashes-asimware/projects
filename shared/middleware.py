import json
import logging
import os
import time
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

try:  # OpenTelemetry is optional; degrade gracefully if missing
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

    _otel_available = True
except Exception:  # pragma: no cover - exercised when OTEL is not installed
    trace = None
    TracerProvider = None
    SimpleSpanProcessor = None
    ConsoleSpanExporter = None
    _otel_available = False

_CORRELATION_HEADER = "x-correlation-id"
_API_KEY_HEADER = "x-api-key"
_correlation_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatting
        payload: dict[str, object] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        correlation_id = _correlation_ctx.get()
        if correlation_id:
            payload["correlation_id"] = correlation_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "http_method"):
            payload["http_method"] = getattr(record, "http_method")
        if hasattr(record, "path"):
            payload["path"] = getattr(record, "path")
        if hasattr(record, "status_code"):
            payload["status_code"] = getattr(record, "status_code")
        if hasattr(record, "duration_ms"):
            payload["duration_ms"] = getattr(record, "duration_ms")
        return json.dumps(payload)


def _configure_logging() -> None:
    root = logging.getLogger()
    if any(isinstance(handler.formatter, _JSONFormatter) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(_JSONFormatter())
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    logging.getLogger("structured").propagate = True


def _configure_tracer() -> None:
    if not _otel_available or trace is None or TracerProvider is None or SimpleSpanProcessor is None:
        return
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)


class _RequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get(_CORRELATION_HEADER) or str(uuid.uuid4())
        _correlation_ctx.set(correlation_id)
        request.state.correlation_id = correlation_id

        required_api_key = os.getenv("API_KEY") or os.getenv("SERVICE_API_KEY")
        provided_api_key = request.headers.get(_API_KEY_HEADER)
        if required_api_key and provided_api_key != required_api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
                headers={_CORRELATION_HEADER: correlation_id},
            )

        start = time.perf_counter()
        tracer = trace.get_tracer("service.middleware") if _otel_available and trace else None
        if tracer:
            with tracer.start_as_current_span(f"{request.method} {request.url.path}") as span:
                span.set_attribute("correlation_id", correlation_id)
                span.set_attribute("http.method", request.method)
                span.set_attribute("http.route", request.url.path)
                response = await call_next(request)
                span.set_attribute("http.status_code", response.status_code)
        else:
            response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers[_CORRELATION_HEADER] = correlation_id
        logging.getLogger("structured").info(
            "",
            extra={
                "http_method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(elapsed_ms, 2),
                "correlation_id": correlation_id,
            },
        )
        return response


def apply_common_middleware(app: FastAPI) -> None:
    """Attach correlation id, structured logging, API key auth, and tracing middleware."""
    _configure_logging()
    _configure_tracer()
    app.add_middleware(_RequestMiddleware)
