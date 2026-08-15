"""Shared HTTP shape for the two HLS endpoints.

Downloads serve an HLS rendition of a finished recording; channels serve a
Converted preview of a live provider stream. The sources differ, but what a
player sees — the playlist, the segments, and the failure statuses — must not.
"""

from fastapi import HTTPException
from fastapi.responses import FileResponse

from services.hls_streamer import (
    HLSError,
    HLSLimitError,
    HLSSession,
    HLSUnavailableError,
)

# 429: the viewer can retry after closing another player.
# 503: the server is missing FFmpeg, which no retry fixes.
# 502: this particular stream could not be prepared.
_HLS_ERROR_STATUS = {
    HLSLimitError: 429,
    HLSUnavailableError: 503,
}


def hls_http_error(exc: HLSError) -> HTTPException:
    return HTTPException(status_code=_HLS_ERROR_STATUS.get(type(exc), 502), detail=str(exc))


def hls_playlist_response(session: HLSSession) -> FileResponse:
    return FileResponse(
        path=str(session.playlist_path),
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


def hls_asset_response(session: HLSSession, asset: str) -> FileResponse:
    """Serve one init/segment file. `asset` must already be pattern-validated,
    which is what keeps it from escaping the session directory."""
    asset_path = session.directory / asset
    if not asset_path.is_file():
        raise HTTPException(status_code=404, detail="Stream segment not found")
    return FileResponse(
        path=str(asset_path),
        media_type="video/mp4" if asset.endswith(".mp4") else "video/iso.segment",
        headers={"Cache-Control": "no-store"},
    )
