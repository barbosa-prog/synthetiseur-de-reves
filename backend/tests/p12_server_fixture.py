"""Application de test sans DB ni IA, jamais incluse dans les routes livrées."""

import asyncio
import logging
import warnings

from fastapi import Request
from fastapi.responses import StreamingResponse

from backend.app.main import create_app

app = create_app()


@app.post("/api/v1/_p12/crash/{value}")
async def crash(value: str, request: Request):
    payload = await request.json()
    try:
        raise RuntimeError(payload["story"])
    except RuntimeError:
        logging.getLogger("sqlalchemy.engine").exception(
            "SQL parameters %s", payload, extra={"private_payload": payload})
    logging.getLogger("application.thirdparty").warning(
        "headers=%s value=%s", dict(request.headers), value, stack_info=True)
    warnings.warn(payload["story"], UserWarning, stacklevel=1)
    raise RuntimeError(payload["story"])


@app.get("/api/v1/_p12/partial")
async def partial():
    async def chunks():
        yield b"public-test"
        await asyncio.sleep(.05)
        raise RuntimeError("FICTITIOUS_STREAM_MARKER")
    return StreamingResponse(chunks(), media_type="text/plain")
