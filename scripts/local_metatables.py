"""Launch the installed MetaTables local worker with the saved developer session."""

import argparse
import os
import socket
from pathlib import Path
from tempfile import TemporaryDirectory

from metatables.api.app.development import run_worker
from metatables.local_connection import (
    clear_development_client,
    publish_development_client,
    running_server,
    server_file,
)
from metatables.local_files import local_storage_root, process_lock
from metatables.sdk_compat import require_sdk_capabilities

from scripts.developer_session import configure_developer_session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    args = parser.parse_args()
    configure_developer_session()
    require_sdk_capabilities(server=True)
    with process_lock(local_storage_root() / "launcher.lock"):
        if running_server() is not None:
            parser.exit(
                1,
                "A local MetaTables runtime started concurrently; restart the Back Office launch to reuse it.\n",
            )
        with (
            socket.socket() as listener,
            TemporaryDirectory(prefix="backoffice-metatables-") as directory,
        ):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", args.port))
            listener.listen(128)
            path = server_file()
            import secrets

            token = secrets.token_urlsafe(48)
            launch_id = publish_development_client(path, port=args.port, token=token)
            try:
                # Reuse the package's actual local API entry point and runtime
                # controls. The duplicate listener is owned/closed by the worker.
                code = run_worker(
                    {
                        "configuration": str(args.configuration.resolve()),
                        "directory": directory,
                        "token": token,
                        "listener_fd": os.dup(listener.fileno()),
                        "admin_port": 19473,
                    }
                )
            finally:
                clear_development_client(path, launch_id)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
