"""Start the host even during initial setup, without exposing unconfigured tools."""
import os
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from .config import settings


def configured_server(cfg):
    from .app import create_server
    if cfg.mcp_auth_enabled:
        from .auth import build_auth
        return create_server(build_auth(cfg))
    return create_server()


def run_host():
    from threading import Thread
    try:
        cfg = settings()
        server = configured_server(cfg)
    except Exception:
        print('DietMCP host is running; private configuration is incomplete. MCP tools are unavailable until configured.', flush=True)
        async def health(request):
            return JSONResponse({'status': 'configuration_required', 'mcp_ready': False})
        async def unavailable(request):
            return JSONResponse({'error': 'Private server configuration is required.'}, status_code=503)
        app = Starlette(routes=[Route('/health', health), Route('/', health),
                                Route('/mcp', unavailable, methods=['GET', 'POST', 'DELETE'])])
        uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
        return
    if cfg.weekly_email_enabled:
        from .delivery import scheduler
        Thread(target=scheduler, name='weekly-email', daemon=True).start()
    server.run(transport='http', host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
