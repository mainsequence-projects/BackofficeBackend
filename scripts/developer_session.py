"""Use the Main Sequence CLI's renewing saved session in local SDK clients."""

from mainsequence.cli.api import current_access_token, refresh_access
from mainsequence.client.utils import JWTAuthProvider, loaders
from requests.structures import CaseInsensitiveDict


class DeveloperSessionAuthProvider(JWTAuthProvider):
    """SDK 9.0.29 otherwise expects exported tokens instead of reading the CLI session."""

    def refresh(self, *, force=False, session=None):
        if force:
            refresh_access()

    def get_headers(self):
        access, _ = current_access_token()
        return CaseInsensitiveDict({"Authorization": f"Bearer {access}"})


def configure_developer_session():
    """The CLI owns credential storage and renewal; tokens are never returned to a browser."""
    loaders.provider = DeveloperSessionAuthProvider()
