"""GET /events — Server-Sent Events from Redis pub/sub channel user:{id}.
EventSource cannot send headers, so ?token=<JWT> is accepted too."""
import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
import redis.asyncio as aredis

from app.config import settings
from app.deps import current_user_or_query_token
from app.services.cache import user_channel

router = APIRouter(tags=["events"])


@router.get("/events")
async def events(request: Request, user: dict = Depends(current_user_or_query_token)):
    async def stream():
        client = aredis.Redis.from_url(settings.redis_url, decode_responses=True)
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(user_channel(user["id"]))
            yield ": connected\n\n"
            idle = 0
            while not await request.is_disconnected():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("type") == "message":
                    idle = 0
                    data = json.loads(msg["data"])
                    yield f"event: {data['type']}\ndata: {json.dumps(data)}\n\n"
                else:
                    idle += 1
                    if idle >= 15:                     # keep-alive for proxies
                        idle = 0
                        yield ": ping\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:                              # Redis down -> end stream, browser reconnects
            return
        finally:
            try:
                await pubsub.close()
                await client.close()
            except Exception:                          # noqa: BLE001
                pass

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
