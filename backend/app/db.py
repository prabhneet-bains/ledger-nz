from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


@lru_cache
def service_client() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def user_client(access_token: str) -> Client:
    """Supabase client authenticated as the end user so RLS applies."""
    settings = get_settings()
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    client.postgrest.auth(access_token)
    return client
