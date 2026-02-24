import os
import uvicorn

from main import app


def _get_port() -> int:
    value = os.environ.get("CATCHUP_DESKTOP_PORT", "4177")
    try:
        return int(value)
    except ValueError:
        return 4177


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("CATCHUP_DESKTOP_HOST", "127.0.0.1"),
        port=_get_port(),
        reload=False,
        access_log=False,
    )
