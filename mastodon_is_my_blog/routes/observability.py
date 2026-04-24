from fastapi.routing import APIRouter

from mastodon_is_my_blog import duck

router = APIRouter(prefix="/api/observability", tags=["observability"])


@router.get("/summary")
async def get_summary(days: int = 7) -> dict:
    data7 = await duck.api_summary(days=7)
    data30 = await duck.api_summary(days=30)
    data90 = await duck.api_summary(days=90)
    return {"7d": data7, "30d": data30, "90d": data90}


@router.get("/volume")
async def get_volume(bucket: str = "day", days: int = 30) -> list:
    return await duck.api_call_volume(bucket=bucket, days=days)


@router.get("/by-method")
async def get_by_method(days: int = 30, limit: int = 30) -> list:
    return await duck.api_call_by_method(days=days, limit=limit)


@router.get("/latency")
async def get_latency(
    method: str | None = None,
    bucket: str = "day",
    days: int = 30,
) -> list:
    return await duck.api_latency_trend(method_name=method, bucket=bucket, days=days)


@router.get("/throttles")
async def get_throttles(days: int = 30) -> list:
    return await duck.api_throttle_events(days=days)


@router.get("/data-volume")
async def get_data_volume(days: int = 30) -> list:
    return await duck.api_data_volume(days=days)


@router.get("/errors")
async def get_errors(days: int = 30) -> list:
    return await duck.api_error_rate(days=days)
