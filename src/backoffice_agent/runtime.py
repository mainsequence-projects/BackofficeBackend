"""Keep Tau's resumed engine on the model authorized by the SDK bootstrap.

ms-tau-sdk 2.0.18 passes the selected model to Tau 0.4.2, which can replace it
with a model replayed from history. The SDK's session-model route then reports
the new selection while inference still uses the old model. This compatibility
guard uses Tau's public setter; authentication, provider hydration, history and
turn persistence remain owned by the SDK. Recheck it when upgrading the SDK.
"""

import structlog
from ms_tau_sdk.application import ApplicationServices
from ms_tau_sdk.errors import BackendConflictError, ConfigurationError
from ms_tau_sdk.runtime.manager import SessionRuntimeManager
from ms_tau_sdk.runtime.session import ActiveSessionRuntime
from ms_tau_sdk.settings import TauSDKSettings

logger = structlog.get_logger(__name__)


class SelectedModelRuntime(SessionRuntimeManager):
    async def get(self, session_uid: str) -> ActiveSessionRuntime:
        runtime = await super().get(session_uid)
        engine = runtime.coding_session
        if engine.provider_name != runtime.provider_name:
            raise ConfigurationError("Resumed provider differs from the SDK-authorized provider")
        if engine.model != runtime.model:
            if engine.is_running or runtime.lock.locked():
                raise BackendConflictError("Cannot change the model of a running session")
            previous_model = engine.model
            engine.set_model(runtime.model)
            logger.info(
                "backoffice.session.model_reconciled",
                session_uid=session_uid,
                previous_model=previous_model,
                model=runtime.model,
                provider=runtime.provider_name,
            )
        return runtime


def create_services(settings: TauSDKSettings) -> ApplicationServices:
    services = ApplicationServices.create(settings)
    services.runtime = SelectedModelRuntime(
        settings=settings, backend=services.backend, providers=services.providers
    )
    return services
