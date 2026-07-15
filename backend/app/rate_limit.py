"""Shared slowapi limiter — importable by every router without circular imports."""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
