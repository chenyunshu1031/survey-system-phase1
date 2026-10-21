from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.db import get_db
from app.models import LoginInput, RegisterInput
from app.security import current_user, issue_token, password_hash


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterInput, db: Database = Depends(get_db)) -> dict:
    username_key = payload.username.casefold()
    if db.users.find_one({"usernameKey": username_key}):
        raise HTTPException(status_code=409, detail="用户名已存在")
    document = {
        "username": payload.username,
        "usernameKey": username_key,
        "passwordHash": password_hash.hash(payload.password),
        "createdAt": datetime.now(timezone.utc),
        "schemaVersion": 1,
    }
    try:
        result = db.users.insert_one(document)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="用户名已存在") from None
    return {"id": str(result.inserted_id), "username": document["username"], "createdAt": document["createdAt"]}


@router.post("/login")
def login(payload: LoginInput, db: Database = Depends(get_db)) -> dict:
    user = db.users.find_one({"usernameKey": payload.username.strip().casefold()})
    if user is None or not password_hash.verify(payload.password, user["passwordHash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"accessToken": issue_token(user["_id"]), "tokenType": "bearer"}


@router.get("/me")
def me(user: dict = Depends(current_user)) -> dict:
    return {"id": str(user["_id"]), "username": user["username"], "createdAt": user["createdAt"]}
