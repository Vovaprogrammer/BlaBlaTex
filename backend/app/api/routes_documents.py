from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime
from jose import jwt
import os
from pydantic import BaseModel
from typing import List, Optional
from app.db.supabase_client import supabase

router = APIRouter(prefix="/documents", tags=["Documents"])

# Настройки JWT (используем переменные окружения)
SECRET_KEY = os.getenv("SECRET_KEY", "local-development-secret-key")
ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Модели
class DocumentCreate(BaseModel):
    title: str
    content: str

class DocumentUpdate(BaseModel):
    title: str
    content: str

class DocumentResponse(BaseModel):
    id: str
    user_id: str
    title: str
    content: str
    created_at: datetime
    updated_at: datetime

def get_current_user(token: str = Depends(oauth2_scheme)):
    """Получение текущего пользователя из токена"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return email
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_user_id_by_email(email: str):
    """Получение user_id по email"""
    result = supabase.table("users").select("id").eq("email", email).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="User not found")
    return result.data[0]["id"]

@router.get("/", response_model=List[DocumentResponse])
async def get_all_documents(current_email: str = Depends(get_current_user)):
    """Получить все документы текущего пользователя"""
    user_id = get_user_id_by_email(current_email)
    result = supabase.table("documents").select("*").eq("user_id", user_id).order("updated_at", desc=True).execute()
    return result.data

@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str, current_email: str = Depends(get_current_user)):
    """Получить конкретный документ"""
    user_id = get_user_id_by_email(current_email)
    result = supabase.table("documents").select("*").eq("id", doc_id).eq("user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Document not found")
    return result.data[0]

@router.post("/", response_model=DocumentResponse)
async def create_document(doc: DocumentCreate, current_email: str = Depends(get_current_user)):
    """Создать новый документ"""
    user_id = get_user_id_by_email(current_email)
    result = supabase.table("documents").insert({
        "user_id": user_id,
        "title": doc.title,
        "content": doc.content
    }).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create document")
    return result.data[0]

@router.put("/{doc_id}", response_model=DocumentResponse)
async def update_document(doc_id: str, doc: DocumentUpdate, current_email: str = Depends(get_current_user)):
    """Обновить документ"""
    user_id = get_user_id_by_email(current_email)

    # Проверяем, что документ принадлежит пользователю
    check = supabase.table("documents").select("*").eq("id", doc_id).eq("user_id", user_id).execute()
    if not check.data:
        raise HTTPException(status_code=404, detail="Document not found")

    result = supabase.table("documents").update({
        "title": doc.title,
        "content": doc.content,
        "updated_at": datetime.utcnow().isoformat()
    }).eq("id", doc_id).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update document")
    return result.data[0]

@router.delete("/{doc_id}")
async def delete_document(doc_id: str, current_email: str = Depends(get_current_user)):
    """Удалить документ"""
    user_id = get_user_id_by_email(current_email)

    result = supabase.table("documents").delete().eq("id", doc_id).eq("user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"message": "Document deleted"}