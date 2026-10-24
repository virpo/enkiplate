import asyncio
import hmac
import ipaddress
import logging
import re
import tempfile
from pathlib import Path
from starlette.background import BackgroundTask
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .config import Config
from .device import DeviceBridge
from .context import ContextService
from .render import Renderer
from .store import Store
from .designs import DESIGNS, IDS, hits as design_hits

LOG = logging.getLogger("enki")


class Reviews(BaseModel):
    events: list[dict] = Field(max_length=200)


class Settings(BaseModel):
    display_style: str | None = None
    start_stage: int | None = Field(default=None, ge=0, le=4)
    max_stage: int | None = Field(default=None, ge=0, le=4)
    auto_advance: bool | None = None
    new_per_day: int | None = Field(default=None, ge=1, le=60)
    calendar_url: str | None = Field(default=None, max_length=2048)
    calendar_exclude: list[str] | None = Field(default=None, max_length=100)
    calendar_labels: dict[str, str] | None = None

    @field_validator("display_style")
    @classmethod
    def screen_style(cls, value):
        if value is not None and value not in ("cutout", *IDS):
            raise ValueError("Unknown screen style")
        return value

    @field_validator("calendar_url")
    @classmethod
    def feed_url(cls, value):
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use an HTTPS .ics feed URL, without embedded login credentials")
        return value


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config.load()
    store = Store(config)
    context = ContextService(store)
    renderer = Renderer(config)
    token = config.token()
    bridge = DeviceBridge(store, context, renderer)

    @asynccontextmanager
    async def lifespan(app):
        async def refresh():
            while True:
                try:
                    await asyncio.to_thread(store.daily_backup)
                    await asyncio.to_thread(context.refresh)
                except Exception:
                    LOG.exception("Background context refresh failed")
                await asyncio.sleep(60)

        bridge.restore()
        task = asyncio.create_task(refresh())
        yield
        bridge.close()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="enki", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.context, app.state.renderer = store, context, renderer
    app.state.wifi_seen = {}

    @app.middleware("http")
    async def trust_boundary(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return Response("Cross-origin requests are not accepted", status_code=403)
            local = False
            try:
                client_ip = ipaddress.ip_address(request.client.host)
                host = request.url.hostname
                local = client_ip.is_loopback and (
                    host == "localhost" or ipaddress.ip_address(host).is_loopback
                )
            except (ValueError, AttributeError):
                pass
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
            supplied = supplied or request.cookies.get("enki_session", "")
            authenticated = bool(supplied) and hmac.compare_digest(supplied, token)
            if not local and not authenticated and request.url.path != "/api/login":
                return Response("Connect with your device key", status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.post("/api/login")
    async def login(request: Request):
        try:
            body = await request.json()
        except ValueError as error:
            raise HTTPException(400, "Expected a JSON object") from error
        if not isinstance(body, dict):
            raise HTTPException(400, "Expected a JSON object")
        if not isinstance(body.get("token"), str) or not hmac.compare_digest(body["token"], token):
            raise HTTPException(401, "Device key is not correct")
        response = Response(status_code=204)
        response.set_cookie(
            "enki_session",
            token,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=86400 * 365,
        )
        return response

    @app.get("/health")
    def health():
        return {"ok": True, "version": "0.1.0"}

    @app.get("/sw.js")
    def service_worker():
        return FileResponse(
            config.root / "web" / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/web/font")
    def web_font():
        return FileResponse(renderer.font_dir / "Manrope.ttf", media_type="font/ttf")

    @app.post("/api/device/connect")
    def connect_device():
        try:
            bridge.start()
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"message": bridge.message}

    class WiFiConfig(BaseModel):
        ssid: str = Field(min_length=1, max_length=32)
        password: str = Field(max_length=63)

    @app.post("/api/device/configure")
    def configure_device(value: WiFiConfig, request: Request):
        try:
            bridge.configure(value.ssid, value.password, request.url.port or 80)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"queued": True}

    @app.get("/api/time")
    def server_clock(request: Request):
        identity = request.headers.get("x-enki-device", "")
        if re.fullmatch(r"inkplate-[a-f0-9]{1,16}", identity):

            def number(name):
                value = request.headers.get(name, "")
                return int(value) if re.fullmatch(r"[0-9]{1,8}", value) else None

            frame = request.headers.get("x-enki-frame", "")
            app.state.wifi_seen = {
                "wifi_seen_at": datetime.now(UTC).timestamp(),
                "wifi_seen_ip": request.client.host,
                "wifi_style": request.headers.get("x-enki-style", "cutout")[:30],
                "wifi_study_revision": request.headers.get("x-enki-revision", "0")[:20],
                "wifi_remaining": number("x-enki-remaining"),
                "wifi_pending": number("x-enki-pending"),
                "wifi_fetching": request.headers.get("x-enki-fetching") == "1",
                "wifi_firmware": request.headers.get("x-enki-firmware", "")[:20],
                "wifi_error": request.headers.get("x-enki-error", "")[:100],
                "wifi_frame": frame if re.fullmatch(r"[a-f0-9]{64}", frame) else None,
                "wifi_fs_used": number("x-enki-fs-used"),
                "wifi_uptime_s": number("x-enki-uptime"),
            }
        return {
            "epoch": int(datetime.now(UTC).timestamp()),
            "study_revision": store.settings()["study_revision"],
        }

    @app.post("/api/device/disconnect")
    def disconnect_device():
        try:
            bridge.disconnect()
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"disconnected": True}

    @app.get("/api/status")
    def status():
        return {
            "stats": store.stats(),
            "settings": store.settings(),
            "context": context.snapshot(),
            "server_time": datetime.now(UTC).isoformat(),
            "device": {
                "message": bridge.message,
                "connected": bridge.identified,
                **bridge.last_status,
                **app.state.wifi_seen,
            },
        }

    @app.get("/api/settings")
    def settings():
        return store.settings()

    @app.patch("/api/settings")
    def change_settings(value: Settings):
        return store.update_settings(value.model_dump(exclude_none=True))

    @app.post("/api/context/refresh")
    def refresh_context():
        return context.refresh(force=True)

    @app.get("/api/study")
    def study(count: int = 4, keep: list[str] = Query(default=[])):
        if not 1 <= count <= 16 or len(keep) > 16 or any(len(i) > 100 for i in keep):
            raise HTTPException(422, "Invalid study batch")
        ctx = context.snapshot()
        study_settings = store.settings()
        revision = study_settings["study_revision"]
        style = study_settings["display_style"]
        cards = store.study_cards(count, keep)
        bundles = []
        for card in cards:
            try:
                front, back = (
                    renderer.frame(card, "front", ctx, style),
                    renderer.frame(card, "back", ctx, style),
                )
            except (OSError, ValueError) as error:
                LOG.error("Card render failed for %s: %s", card["id"], type(error).__name__)
                raise HTTPException(503, "Card assets are not ready. Run enki setup.") from error
            bundles.append({"id": card["id"], "front": front, "back": back})
        idle = renderer.frame(None, "front", ctx, style)
        return {
            "study_revision": revision,
            "display_style": style,
            "cards": bundles,
            "idle": idle,
            "context": ctx,
            "server_epoch": int(datetime.now(UTC).timestamp()),
            "protocol": 1,
        }

    @app.post("/api/reviews")
    def reviews(batch: Reviews):
        accepted, rejected = [], []
        for event in batch.events:
            result = store.receive_review(event)
            (rejected if result.get("rejected") else accepted).append(result)
        return {"accepted": accepted, "rejected": rejected}

    @app.get("/api/recovery")
    def recovery():
        return JSONResponse(
            store.recovery(),
            headers={"Content-Disposition": 'attachment; filename="enki-review-recovery.json"'},
        )

    @app.get("/api/frames/{name}")
    def frame(name: str):
        if not re.fullmatch(r"[a-f0-9]{64}\.(png|raw|z)", name):
            raise HTTPException(404)
        path = renderer.frames / name
        if not path.is_file():
            raise HTTPException(404, "Frame expired; request a new study batch")
        return FileResponse(
            path, media_type="image/png" if name.endswith(".png") else "application/octet-stream"
        )

    @app.get("/api/backup")
    def backup():
        with tempfile.NamedTemporaryFile(
            dir=config.data, suffix=".sqlite3", prefix="download-", delete=False
        ) as stream:
            destination = Path(stream.name)
        store.backup(destination)
        return FileResponse(
            destination,
            filename="enki-backup.sqlite3",
            media_type="application/octet-stream",
            background=BackgroundTask(destination.unlink, missing_ok=True),
        )

    @app.get("/designs")
    def design_picker():
        return FileResponse(config.root / "web" / "designs.html")

    @app.get("/api/designs")
    def design_list():
        return {
            "designs": [
                {**d, "hits": {side: design_hits(d["id"], side) for side in ("front", "back")}}
                for d in DESIGNS
            ],
            "selected": store.settings()["display_style"],
        }

    @app.get("/api/designs/{style}/{side}.png")
    def design_preview(style: str, side: str):
        if style not in IDS or side not in ("front", "back", "idle"):
            raise HTTPException(404)
        fixture = {
            "date": "2026-10-24",
            "weather": {"min": 7, "max": 14, "symbol": "sun"},
            "events": [
                {"title": title, "start": "2026-10-24T" + clock + ":00+02:00"}
                for title, clock in [
                    ("Coffee break", "16:00"),
                    ("Japanese", "18:30"),
                    ("Walk", "20:00"),
                ]
            ],
        }
        card = {"id": "preview:neko", "jp": "ねこ", "kanji": "猫", "reading": "neko", "meaning": "cat"}
        f = renderer.frame(
            None if side == "idle" else card, "front" if side == "idle" else side, fixture, style
        )
        return FileResponse(renderer.frames / (f["id"] + ".png"), media_type="image/png")

    @app.get("/")
    def index():
        return FileResponse(config.root / "web" / "index.html")

    app.mount("/web", StaticFiles(directory=config.root / "web"), name="web")
    return app
