from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from auth import require_admin, require_admin_websocket
from services.log_stream import backend_log_stream


router = APIRouter()


@router.get("/logs")
async def get_logs(
    limit: int = Query(300, ge=1, le=2000),
    source: str | None = Query(None),
    level: str | None = Query(None),
    _admin: None = Depends(require_admin),
):
    return await backend_log_stream.list_entries(limit=limit, source=source, level=level)


@router.websocket("/logs/ws")
async def logs_websocket(
    websocket: WebSocket,
    _admin: None = Depends(require_admin_websocket),
):
    await websocket.accept()
    await backend_log_stream.register_websocket(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await backend_log_stream.unregister_websocket(websocket)
