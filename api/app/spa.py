"""本地构建演示：同一进程提供已构建前端，未知 API/资源保持 404。"""
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or path not in {"community", "explore", "cases", "isochrone", "plan"}:
                raise
            return await super().get_response("index.html", scope)
