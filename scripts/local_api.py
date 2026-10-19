"""Loopback-only developer gateway around the real API; never a deployment entry point."""

import asyncio
import os

from mainsequence.client import User
from mainsequence.client.utils import get_authorization_headers
from metatables import configure_local_client, get_runtime_status
from starlette.responses import JSONResponse

from scripts.developer_session import configure_developer_session


def require_local_runtime(state: dict, *, ready: bool = True) -> str | None:
    """Refuse hosted storage, and require initialized SQLite before application writes."""
    if state.get("local_mode") is not True:
        raise RuntimeError("The development stack requires a local MetaTables runtime.")
    source = state.get("data_source") or {}
    bootstrap = state.get("bootstrap") or {}
    candidate = bootstrap.get("candidate") or {}
    if (source or candidate).get("class_type") != "sqlite":
        raise RuntimeError("The development stack requires a selected local SQLite source.")
    if ready and not (
        state.get("dialect") == "sqlite"
        and source.get("uid")
        and bootstrap.get("active") is True
        and bootstrap.get("status") == "ready"
        and not state.get("data_source_error")
    ):
        raise RuntimeError("Local MetaTables needs initialization before the API can start.")
    return source.get("uid")


class LocalDeveloperGateway:
    """Supply the SDK session server-side while retaining the API's identity verification."""

    def __init__(self, app, *, api_origin: str, site_origin: str, source_uid: str):
        self.app = app
        self.api_origin = api_origin
        self.origins = {api_origin, site_origin}
        self.source_uid = source_uid

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        client = scope.get("client")
        origin = headers.get(b"origin", b"").decode("latin-1")
        host = headers.get(b"host", b"").decode("latin-1")
        if (
            not client
            or client[0] not in {"127.0.0.1", "::1"}
            or f"http://{host}" != self.api_origin
            or (origin and origin not in self.origins)
            or headers.get(b"sec-fetch-site") == b"cross-site"
        ):
            await JSONResponse({"detail": "local_origin_required"}, status_code=403)(
                scope, receive, send
            )
            return
        if scope["path"] == "/healthz" and scope["method"] == "GET":
            try:
                state = await asyncio.to_thread(get_runtime_status)
                uid = require_local_runtime(state)
                if uid != self.source_uid:
                    raise RuntimeError("Local MetaTables source changed")
            except Exception:
                await JSONResponse({"detail": "local_metatables_unavailable"}, status_code=503)(
                    scope, receive, send
                )
                return
            await JSONResponse(
                {
                    "status": "ready",
                    "metatables": {"local_mode": True, "dialect": "sqlite", "data_source_uid": uid},
                }
            )(scope, receive, send)
            return
        try:
            authorization = (await asyncio.to_thread(get_authorization_headers)).get(
                "Authorization"
            )
            if not authorization:
                raise RuntimeError("No developer identity")
        except Exception:
            await JSONResponse({"detail": "identity_unavailable"}, status_code=503)(
                scope, receive, send
            )
            return
        # Browser-supplied identity never selects the local developer. The real
        # app still verifies the injected bearer with Main Sequence per request.
        scope = dict(scope)
        try:
            user = await asyncio.to_thread(User.get_authenticated_user_details)
            scope["state"] = {
                **scope.get("state", {}),
                "backoffice_local_admin_uid": user.uid
                if user.is_organization_admin is True
                else None,
            }
        except Exception:
            await JSONResponse({"detail": "organization_permissions_unavailable"}, status_code=503)(
                scope, receive, send
            )
            return
        scope["headers"] = [
            (key, value)
            for key, value in scope.get("headers", [])
            if key.lower()
            not in {
                b"authorization",
                b"x-user-id",
                b"x-user-uid",
                b"x-mainsequence-caller-assertion",
                b"x-public-ingress",
                b"x-websocket-ticket",
            }
        ] + [(b"authorization", authorization.encode("latin-1"))]
        await self.app(scope, receive, send)


def create_app():
    """Uvicorn factory used only by the explicit local development launcher."""
    if any(
        os.environ.get(name)
        for name in (
            "APP_NAME",
            "FASTAPI_PUBLIC_BASE_URL",
            "MAINSEQUENCE_CALLER_ASSERTION_ISSUER",
            "MAINSEQUENCE_CALLER_ASSERTION_JWKS_URL",
        )
    ):
        raise RuntimeError("The local developer gateway cannot run in a hosted environment.")
    configure_developer_session()
    configure_local_client()
    source_uid = require_local_runtime(get_runtime_status())
    if source_uid != os.environ["BACKOFFICE_LOCAL_SOURCE_UID"]:
        raise RuntimeError("Local MetaTables source changed since startup preparation.")
    from api.app.main import app

    return LocalDeveloperGateway(
        app,
        api_origin=os.environ["BACKOFFICE_API_ORIGIN"],
        site_origin=os.environ["BACKOFFICE_SITE_ORIGIN"],
        source_uid=source_uid,
    )
