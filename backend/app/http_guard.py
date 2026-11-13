"""Frontière ASGI : limites avant parsing JSON et protection des erreurs serveur."""

import asyncio
import time

from starlette.exceptions import HTTPException

from backend.app.audio_types import MAX_UPLOAD
from backend.app.errors import HTTP_ERRORS, error_response
from backend.app.safe_logging import event

SMALL_BODY = 8192
TEXT_BODY = 256 * 1024
AUDIO_BODY = MAX_UPLOAD


def policy(scope):
    path = scope["path"]
    if path in {"/web/audio", "/api/v1/dreams/audio"}:
        return AUDIO_BODY, 30, True
    if path.startswith("/api/v1/auth/") or path in {
        "/connexion", "/inscription", "/deconnexion", "/web/session",
    }:
        return SMALL_BODY, 10, False
    if path.startswith(("/api/v1/", "/reves/")):
        return TEXT_BODY, 10, False
    return SMALL_BODY, 10, False


class HTTPGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit, seconds, streaming = policy(scope)
        started = False
        failure = None

        async def reject(status):
            event("request_rejected")
            code, message = HTTP_ERRORS[status]
            response = error_response(status, code, message,
                                      {"Cache-Control": "no-store", "Connection": "close"})
            await response(scope, receive, send)

        try:
            headers = scope.get("headers", [])
            lengths = [v for k, v in headers if k.lower() == b"content-length"]
            encodings = [v.lower() for k, v in headers if k.lower() == b"content-encoding"]
            transfer = any(k.lower() == b"transfer-encoding" for k, _ in headers)
            if len(lengths) > 1 or (lengths and transfer):
                return await reject(400)
            if encodings and encodings != [b"identity"]:
                return await reject(415)
            declared = None
            if lengths:
                raw = lengths[0]
                if not raw or len(raw) > 20 or any(c < 48 or c > 57 for c in raw):
                    return await reject(400)
                declared = int(raw)
                if declared > limit:
                    return await reject(413)
            count = 0
            deadline = time.monotonic() + seconds

            async def bounded_receive():
                nonlocal count, failure
                try:
                    async with asyncio.timeout(max(0, deadline - time.monotonic())):
                        message = await receive()
                    if message["type"] == "http.disconnect":
                        failure = 408
                    else:
                        count += len(message.get("body", b""))
                        if count > limit:
                            failure = 413
                        elif declared is not None and (count > declared or (
                            not message.get("more_body", False) and count != declared
                        )):
                            failure = 400
                    if failure:
                        raise HTTPException(failure)
                    return message
                except TimeoutError:
                    failure = 408
                    raise HTTPException(408) from None

            if streaming:
                app_receive = bounded_receive
            else:
                body = bytearray()
                while True:
                    message = await bounded_receive()
                    body.extend(message.get("body", b""))
                    if not message.get("more_body", False):
                        break
                replayed = False

                async def app_receive():
                    nonlocal replayed
                    if not replayed:
                        replayed = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

            async def safe_send(message):
                nonlocal started
                if message["type"] == "http.response.start":
                    if failure:
                        raise HTTPException(failure)
                    started = True
                await send(message)

            await self.app(scope, app_receive, safe_send)
        except HTTPException as exc:
            if not started:
                status = exc.status_code if exc.status_code in HTTP_ERRORS else 400
                await reject(failure or status)
            else:
                event("response_interrupted")
        except Exception:
            # Les middlewares Starlette peuvent encapsuler l'erreur de réception.
            if failure and not started:
                return await reject(failure)
            event("response_interrupted" if started else "request_failed")
            if not started:
                await error_response(500, "internal_error", "Une erreur interne est survenue.",
                                     {"Cache-Control": "no-store"})(scope, receive, send)
