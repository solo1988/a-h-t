from fastapi import Request
from starlette.responses import  RedirectResponse

def register_middleware(app, manager):
    @app.middleware("http")
    async def redirect_unauthed(request: Request, call_next):
        if request.url.path == "/" and not request.cookies.get(manager.cookie_name):
            return RedirectResponse(url="/login")
        response = await call_next(request)
        return response