import os

import httpx
from fastapi import APIRouter, HTTPException, Response


router = APIRouter(prefix="/api/tiles", tags=["Tiles"])

CARTO_TILE_URL = "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png"
CARTO_API_KEY_ENV = "CARTO_API_KEY"


@router.get("/voyager/{z}/{x}/{y}.png")
async def get_voyager_tile(z: int, x: int, y: int):
    """
    Proxies one CARTO Voyager basemap tile, attaching the API key
    server-side.

    CARTO requires a key on every basemaps.cartocdn.com request as of
    their September 2026 policy change. The key lives only in this
    process's environment (CARTO_API_KEY, set on Render) - it's never
    sent to, or visible from, the client, so it never needs to sit in
    a committed file or ship inside the app itself.
    """

    api_key = os.environ.get(CARTO_API_KEY_ENV)
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=f"{CARTO_API_KEY_ENV} is not configured on the server.",
        )

    upstream_url = CARTO_TILE_URL.format(z=z, x=x, y=y)

    async with httpx.AsyncClient(timeout=8.0) as client:
        upstream = await client.get(upstream_url, params={"key": api_key})

    if upstream.status_code != 200:
        raise HTTPException(
            status_code=upstream.status_code,
            detail="CARTO tile request failed.",
        )

    return Response(
        content=upstream.content,
        media_type="image/png",
        # A given z/x/y tile is effectively static, so let the client's
        # own HTTP cache do the work instead of building one here - a
        # week is generous but harmless, and it means panning back over
        # the same area doesn't re-hit CARTO (or your Render quota).
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )