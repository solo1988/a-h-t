from fastapi import APIRouter, Form, Request
from fastapi_login.exceptions import InvalidCredentialsException
from fastapi.responses import RedirectResponse
from datetime import timedelta
from app.core.auth import manager, pwd_context, load_user

router = APIRouter()

@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = await load_user(username)
    if not user or not pwd_context.verify(password, user.hashed_password):
        raise InvalidCredentialsException
    token = manager.create_access_token(data={"sub": username}, expires=timedelta(days=365))
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(key=manager.cookie_name, value=token, httponly=True, max_age=31536000, samesite="lax",
                        secure=False)
    return response
