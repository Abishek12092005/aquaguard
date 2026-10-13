"""AquaGuard AI — root configuration shim.

The real configuration lives in `app/config.py`, alongside the rest of the
application package. This module re-exports it so the conventional
`from config import DevelopmentConfig` import style also works.

Keeping one implementation matters: if this file defined its own settings, the
app could be started two different ways and behave differently depending on
which entrypoint was used.
"""

from app.config import (  # noqa: F401
    BACKEND_DIR,
    BaseConfig,
    DevelopmentConfig,
    ProductionConfig,
    PROJECT_ROOT,
    TestingConfig,
    config_by_name,
    get_config,
)

__all__ = [
    "BACKEND_DIR",
    "PROJECT_ROOT",
    "BaseConfig",
    "DevelopmentConfig",
    "TestingConfig",
    "ProductionConfig",
    "config_by_name",
    "get_config",
]


def load_config(name: str | None = None) -> BaseConfig:
    """Alias for `get_config`, matching the `load_config()` naming convention."""
    return get_config(name)


if __name__ == "__main__":
    # `python config.py` prints the resolved configuration — with the database
    # password masked, since this output often ends up pasted into a bug report.
    config = get_config()
    uri = config.SQLALCHEMY_DATABASE_URI
    if "://" in uri and "@" in uri:
        scheme, rest = uri.split("://", 1)
        credentials, host = rest.split("@", 1)
        uri = f"{scheme}://{credentials.split(':', 1)[0]}:***@{host}"

    print("\n  AquaGuard AI — resolved configuration")
    print("  " + "-" * 52)
    print(f"  ENV              {config.ENV}")
    print(f"  DEBUG            {config.DEBUG}")
    print(f"  Database         {uri}")
    print(f"  CORS origins     {', '.join(config.CORS_ORIGINS)}")
    print(f"  JWT expires      {config.JWT_ACCESS_TOKEN_EXPIRES}")
    print(f"  Bcrypt rounds    {config.BCRYPT_LOG_ROUNDS}")
    print(f"  Aqua AI model    {config.AI_MODEL}")
    print(f"  Aqua AI key      {'set' if config.AI_API_KEY else 'NOT SET'}")
    print("  " + "-" * 52 + "\n")
