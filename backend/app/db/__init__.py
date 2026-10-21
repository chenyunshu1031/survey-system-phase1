from functools import lru_cache

from pymongo import MongoClient
from pymongo.database import Database

from app.config import get_settings


@lru_cache
def get_client() -> MongoClient:
    return MongoClient(get_settings().mongodb_uri, serverSelectionTimeoutMS=3000)


def get_db() -> Database:
    settings = get_settings()
    return get_client()[settings.mongodb_db]
