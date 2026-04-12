from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.service import BydConsoleService


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
service = BydConsoleService(settings)
app = FastAPI(title=settings.app_title)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _display_metric(value: object, suffix: str = "") -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, float):
        return f"{value:.1f}{suffix}"
    return f"{value}{suffix}"


def _eta_text(minutes: object) -> str:
    if minutes in (None, ""):
        return "-"
    try:
        total = int(float(minutes))
    except (TypeError, ValueError):
        return str(minutes)
    return f"{total // 60}h {total % 60}m"


def _map_embed(latitude: object, longitude: object) -> str | None:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return None
    delta = 0.015
    return (
        "https://www.openstreetmap.org/export/embed.html?"
        + urlencode(
            {
                "bbox": f"{lon - delta:.6f},{lat - delta:.6f},{lon + delta:.6f},{lat + delta:.6f}",
                "layer": "mapnik",
                "marker": f"{lat:.6f},{lon:.6f}",
            }
        )
    )


def _view_model(snapshot: dict[str, object]) -> dict[str, object]:
    return {
        **snapshot,
        "soc_display": _display_metric(snapshot.get("soc_percent"), "%"),
        "range_display": _display_metric(snapshot.get("range_km"), " km"),
        "power_display": _display_metric(snapshot.get("tracked_power_w") or snapshot.get("power_w"), " W"),
        "eta_display": _eta_text(snapshot.get("time_to_full_minutes")),
        "inside_temp_display": _display_metric(snapshot.get("inside_temp_c"), " C"),
        "outside_temp_display": _display_metric(snapshot.get("outside_temp_c"), " C"),
        "odometer_display": _display_metric(snapshot.get("total_mileage_km"), " km"),
        "charging_display": "Charging" if snapshot.get("is_charging") is True else ("Idle" if snapshot.get("is_charging") is False else "-"),
        "connected_display": "Connected" if snapshot.get("is_connected") is True else ("Disconnected" if snapshot.get("is_connected") is False else "-"),
        "climate_display": "On" if snapshot.get("climate_on") is True else ("Off" if snapshot.get("climate_on") is False else "-"),
        "steering_heat_display": "On" if snapshot.get("steering_heat_on") is True else ("Off" if snapshot.get("steering_heat_on") is False else "-"),
        "battery_heat_display": "On" if snapshot.get("battery_heat_on") is True else ("Off" if snapshot.get("battery_heat_on") is False else "-"),
    }


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    notice: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    snapshot = _view_model((await service.fetch_snapshot()).payload)
    capabilities = snapshot.get("capabilities") if isinstance(snapshot.get("capabilities"), dict) else {}
    capability_rows = [
        {"label": label, "value": "Yes" if capabilities.get(key) else "No"}
        for key, label in [
            ("lock", "Lock"),
            ("unlock", "Unlock"),
            ("climate", "Climate"),
            ("find_car", "Find car"),
            ("flash_lights", "Flash lights"),
            ("close_windows", "Close windows"),
            ("battery_heat", "Battery heat"),
            ("steering_wheel_heat", "Steering heat"),
            ("driver_seat_heat", "Driver seat heat"),
            ("passenger_seat_heat", "Passenger seat heat"),
        ]
    ]
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "app_title": settings.app_title,
            "snapshot": snapshot,
            "notice": notice,
            "error": error,
            "commands_enabled": service.commands_enabled(),
            "map_embed_url": _map_embed(snapshot.get("latitude"), snapshot.get("longitude")),
            "capability_rows": capability_rows,
            "climate_temperatures": list(range(17, 31)),
            "climate_durations": [10, 15, 20, 25, 30],
            "seat_levels": [
                {"value": "off", "label": "Off"},
                {"value": "low", "label": "Low"},
                {"value": "high", "label": "High"},
            ],
            "raw_payload_json": json.dumps(snapshot, indent=2, default=str),
        },
    )


@app.post("/command")
async def command(
    action: str = Form(...),
    temperature: str = Form(default="21"),
    duration: str = Form(default="20"),
    level: str = Form(default="off"),
) -> RedirectResponse:
    try:
        await service.run_command(
            action,
            {
                "temperature": temperature,
                "duration": duration,
                "level": level,
            },
        )
    except Exception as exc:
        return RedirectResponse("/?" + urlencode({"error": str(exc)}), status_code=303)
    return RedirectResponse("/?" + urlencode({"notice": f"Action completed: {action}"}), status_code=303)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
