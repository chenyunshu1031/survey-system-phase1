from datetime import datetime, timedelta, timezone

import jwt
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, Header, HTTPException, status
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pymongo.database import Database

from app.config import get_settings
from app.db import get_db


password_hash = PasswordHash.recommended()


def issue_token(user_id: ObjectId) -> str:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode({"sub": str(user_id), "exp": expires}, settings.jwt_secret, algorithm="HS256")


def current_user(authorization: str | None = Header(default=None), db: Database = Depends(get_db)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    try:
        token = authorization.partition(" ")[2]
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], options={"require": ["sub", "exp"]})
        user_id = ObjectId(payload["sub"])
    except (InvalidTokenError, InvalidId, KeyError, ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效") from None
    user = db.users.find_one({"_id": user_id})
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效")
    return user
