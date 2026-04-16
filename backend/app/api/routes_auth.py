from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import datetime, timedelta
from jose import jwt
import os
from app.schemas.auth_schema import UserRegister, UserLogin, TokenResponse, UserResponse
from app.db.supabase_client import supabase

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Настройки JWT
SECRET_KEY = os.getenv("SECRET_KEY", "local-development-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 дней

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

@router.post("/register", response_model=TokenResponse)
async def register(user_data: UserRegister):
    if len(user_data.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters"
        )
    
    # Проверка существующего пользователя (через таблицу users)
    existing = supabase.table("users").select("*").eq("email", user_data.email).execute()
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    existing_username = supabase.table("users").select("*").eq("username", user_data.username).execute()
    if existing_username.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken"
        )
    
    # Регистрация через Supabase Auth
    try:
        auth_response = supabase.auth.sign_up({
            "email": user_data.email,
            "password": user_data.password,
            "options": {
                "data": {
                    "username": user_data.username
                }
            }
        })
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Auth error: {str(e)}"
        )
    
    if not auth_response.user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user"
        )
    
    # Получаем пользователя из Auth
    auth_user = auth_response.user
    
    # Триггер должен был создать запись в таблице users
    # Ждём немного и получаем данные
    import time
    time.sleep(1)
    
    result = supabase.table("users").select("*").eq("email", user_data.email).execute()
    if not result.data:
        # Если триггер не сработал, создаём вручную
        supabase.table("users").insert({
            "id": auth_user.id,
            "email": user_data.email,
            "username": user_data.username,
            "hashed_password": "auth-managed"
        }).execute()
        result = supabase.table("users").select("*").eq("email", user_data.email).execute()
    
    user = result.data[0]
    
    # Создание JWT токена
    access_token = create_access_token(data={"sub": user["email"]})
    
    return TokenResponse(
        access_token=access_token,
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            username=user["username"],
            created_at=datetime.fromisoformat(user["created_at"].replace("Z", "+00:00"))
        )
    )

@router.post("/login", response_model=TokenResponse)
async def login(user_data: UserLogin):
    # Аутентификация через Supabase Auth
    try:
        auth_response = supabase.auth.sign_in_with_password({
            "email": user_data.email,
            "password": user_data.password
        })
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    if not auth_response.user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Получаем данные пользователя из таблицы users
    result = supabase.table("users").select("*").eq("email", user_data.email).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in database"
        )
    
    user = result.data[0]
    
    # Создание JWT токена
    access_token = create_access_token(data={"sub": user["email"]})
    
    return TokenResponse(
        access_token=access_token,
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            username=user["username"],
            created_at=datetime.fromisoformat(user["created_at"].replace("Z", "+00:00"))
        )
    )

@router.post("/token")
async def login_for_swagger(form_data: OAuth2PasswordRequestForm = Depends()):
    try:
        auth_response = supabase.auth.sign_in_with_password({
            "email": form_data.username,
            "password": form_data.password
        })
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    if not auth_response.user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    access_token = create_access_token(data={"sub": auth_response.user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me")
async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except jwt.JWTError:
        raise credentials_exception
    
    result = supabase.table("users").select("*").eq("email", email).execute()
    if not result.data:
        raise credentials_exception
    
    user = result.data[0]
    return UserResponse(
        id=user["id"],
        email=user["email"],
        username=user["username"],
        created_at=datetime.fromisoformat(user["created_at"].replace("Z", "+00:00"))
    )