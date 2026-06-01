"""API deployment entrypoint.

Exposes the ASGI ``app`` (for ``uvicorn commands.api:app`` in prod) and a
``main()`` runner wired to the ``doci-api`` console script.
"""

import os

import uvicorn

from doci.api import create_app

app = create_app()


def main() -> None:
    uvicorn.run(
        app,
        host=os.getenv("HOST", "localhost"),
        port=int(os.getenv("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
