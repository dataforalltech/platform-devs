import httpx
from ..config.settings import settings

api_client: httpx.AsyncClient | None = None

async def get_api_client() -> httpx.AsyncClient:
    global api_client
    if api_client is None:
        api_client = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=settings.timeout,
            headers={"X-Internal-Token": settings.internal_token}
        )
    return api_client
