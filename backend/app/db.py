from tortoise import Tortoise

from app.config import get_settings

settings = get_settings()

TORTOISE_ORM = {
    "connections": {"default": settings.database_url},
    "apps": {
        "models": {
            "models": ["app.models", "aerich.models"],
            "default_connection": "default",
        }
    },
    "use_tz": True,
    "timezone": "UTC",
}


async def init_db() -> None:
    await Tortoise.init(config=TORTOISE_ORM, _enable_global_fallback=True)
    if settings.auto_create_tables:
        await Tortoise.generate_schemas(safe=True)


async def close_db() -> None:
    await Tortoise.close_connections()
