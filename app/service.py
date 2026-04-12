from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable

from pybyd import BydClient, BydConfig, SeatLevel, SeatPosition
from pybyd.models.realtime import ChargingState, ConnectState, LockState, WindowState

from app.config import Settings


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class VehicleSnapshot:
    payload: dict[str, Any]
    vin: str


class BydConsoleService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def commands_enabled(self) -> bool:
        return bool(self.settings.byd_control_pin)

    def _config(self) -> BydConfig:
        if not self.settings.byd_username or not self.settings.byd_password:
            raise RuntimeError("BYD_USERNAME and BYD_PASSWORD are required")
        return BydConfig.from_env(
            username=self.settings.byd_username,
            password=self.settings.byd_password,
            control_pin=self.settings.byd_control_pin or None,
            time_zone=self.settings.byd_time_zone or self.settings.timezone_name,
        )

    async def fetch_snapshot(self) -> VehicleSnapshot:
        async with BydClient(self._config()) as client:
            vehicle, vin = await self._resolve_vehicle(client)
            car = await client.get_car(vin, vehicle=vehicle)
            realtime, gps, hvac, charging = await asyncio.gather(
                car.update_realtime(),
                car.update_gps(),
                car.update_hvac(),
                car.update_charging(),
                return_exceptions=True,
            )
            payload = self._build_payload(
                vehicle=vehicle,
                vin=vin,
                capabilities=car.capabilities.model_dump(mode="json"),
                realtime=realtime,
                gps=gps,
                hvac=hvac,
                charging=charging,
            )
            return VehicleSnapshot(payload=payload, vin=vin)

    async def run_command(self, action: str, options: dict[str, str] | None = None) -> str:
        options = options or {}
        async with BydClient(self._config()) as client:
            vehicle, vin = await self._resolve_vehicle(client)
            car = await client.get_car(vin, vehicle=vehicle)

            if action != "refresh":
                await client.verify_command_access(vin)

            handlers: dict[str, Callable[[], Any]] = {
                "refresh": lambda: self.fetch_snapshot(),
                "lock": car.lock.lock,
                "unlock": car.lock.unlock,
                "climate_start": lambda: car.hvac.start(
                    temperature=float(options.get("temperature", "21")),
                    duration=int(options.get("duration", "20")),
                ),
                "climate_stop": car.hvac.stop,
                "find_car": car.finder.find,
                "flash_lights": car.finder.flash_lights,
                "close_windows": car.windows.close,
                "battery_heat_on": lambda: car.battery.heat(on=True),
                "battery_heat_off": lambda: car.battery.heat(on=False),
                "steering_heat_on": lambda: car.steering.heat(on=True),
                "steering_heat_off": lambda: car.steering.heat(on=False),
                "driver_seat_heat": lambda: car.seat.heat(
                    SeatPosition.DRIVER,
                    _seat_level(options.get("level", "off")),
                ),
                "passenger_seat_heat": lambda: car.seat.heat(
                    SeatPosition.COPILOT,
                    _seat_level(options.get("level", "off")),
                ),
            }
            handler = handlers.get(action)
            if handler is None:
                raise ValueError(f"Unsupported action: {action}")
            await handler()
            return vin

    async def _resolve_vehicle(self, client: BydClient) -> tuple[Any, str]:
        vehicles = await client.get_vehicles()
        if not vehicles:
            raise RuntimeError("No BYD vehicles found for this account")
        requested_vin = self.settings.byd_vin.strip()
        if requested_vin:
            for vehicle in vehicles:
                if vehicle.vin == requested_vin:
                    return vehicle, vehicle.vin
            raise RuntimeError(f"Configured BYD_VIN was not found: {requested_vin}")
        vehicle = vehicles[0]
        return vehicle, vehicle.vin

    def _build_payload(
        self,
        *,
        vehicle: Any,
        vin: str,
        capabilities: dict[str, Any],
        realtime: Any,
        gps: Any,
        hvac: Any,
        charging: Any,
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}
        realtime_data = self._section("realtime", realtime, errors)
        gps_data = self._section("gps", gps, errors)
        hvac_data = self._section("hvac", hvac, errors)
        charging_data = self._section("charging", charging, errors)

        power_w = _pick(realtime_data.get("gl"), realtime_data.get("total_power"))
        speed_kph = realtime_data.get("speed")
        tracked_power_w = _tracked_power(power_w, speed_kph)

        return {
            "vin": vin,
            "model_name": getattr(vehicle, "model_name", None),
            "brand_name": getattr(vehicle, "brand_name", None),
            "auto_alias": getattr(vehicle, "auto_alias", None),
            "auto_plate": getattr(vehicle, "auto_plate", None),
            "soc_percent": _pick(realtime_data.get("elec_percent"), realtime_data.get("power_battery"), charging_data.get("soc")),
            "range_km": _pick(realtime_data.get("endurance_mileage"), realtime_data.get("ev_endurance"), realtime_data.get("endurance_mileage_v2")),
            "total_mileage_km": _pick(realtime_data.get("total_mileage_v2"), realtime_data.get("total_mileage"), getattr(vehicle, "total_mileage", None)),
            "power_w": power_w,
            "tracked_power_w": tracked_power_w,
            "vehicle_speed_kph": speed_kph,
            "time_to_full_minutes": _pick(
                charging_data.get("time_to_full_minutes"),
                _hours_minutes(realtime_data.get("remaining_hours"), realtime_data.get("remaining_minutes")),
                _hours_minutes(charging_data.get("full_hour"), charging_data.get("full_minute")),
            ),
            "is_connected": _connected(_pick(realtime_data.get("connect_state"), charging_data.get("connect_state")), charging_data.get("is_connected")),
            "is_charging": _charging(_pick(realtime_data.get("charge_state"), realtime_data.get("charging_state"), charging_data.get("charging_state")), charging_data.get("is_charging")),
            "climate_on": _hvac_on(hvac_data.get("status")),
            "inside_temp_c": _pick(hvac_data.get("temp_in_car"), realtime_data.get("temp_in_car")),
            "outside_temp_c": _pick(hvac_data.get("temp_out_car"), realtime_data.get("temp_out_car")),
            "battery_heat_on": _boolish(realtime_data.get("battery_heat_state")),
            "steering_heat_on": _enum_name(_pick(hvac_data.get("steering_wheel_heat_state"), realtime_data.get("steering_wheel_heat_state"))) == "ON",
            "driver_seat_heat": _enum_name(_pick(hvac_data.get("main_seat_heat_state"), realtime_data.get("main_seat_heat_state"))),
            "passenger_seat_heat": _enum_name(_pick(hvac_data.get("copilot_seat_heat_state"), realtime_data.get("copilot_seat_heat_state"))),
            "lock_state": _lock_state(realtime_data),
            "window_state": _window_state(realtime_data),
            "latitude": gps_data.get("latitude"),
            "longitude": gps_data.get("longitude"),
            "observed_at": _pick(realtime_data.get("timestamp"), charging_data.get("update_time"), gps_data.get("gps_timestamp")),
            "capabilities": capabilities,
            "vehicle": vehicle.model_dump(mode="json"),
            "realtime": realtime_data,
            "gps": gps_data,
            "hvac": hvac_data,
            "charging": charging_data,
            "errors": errors,
        }

    @staticmethod
    def _section(name: str, value: Any, errors: dict[str, str]) -> dict[str, Any]:
        if isinstance(value, Exception):
            errors[name] = str(value)
            LOGGER.debug("BYD %s fetch failed", name, exc_info=value)
            return {}
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value if isinstance(value, dict) else {}


def _pick(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _hours_minutes(hours: Any, minutes: Any) -> int | None:
    if hours in (None, "") and minutes in (None, ""):
        return None
    try:
        return int(hours or 0) * 60 + int(minutes or 0)
    except (TypeError, ValueError):
        return None


def _tracked_power(power_w: Any, speed_kph: Any) -> float:
    try:
        numeric_power = float(power_w) if power_w not in (None, "") else 0.0
    except (TypeError, ValueError):
        numeric_power = 0.0
    try:
        numeric_speed = float(speed_kph) if speed_kph not in (None, "") else 0.0
    except (TypeError, ValueError):
        numeric_speed = 0.0
    if numeric_speed > 0:
        return 0.0
    return max(0.0, numeric_power)


def _enum_name(value: Any) -> str | None:
    if value in (None, ""):
        return None
    name = getattr(value, "name", None)
    return name if isinstance(name, str) else str(value)


def _connected(connect_state: Any, fallback: Any) -> bool | None:
    if isinstance(fallback, bool):
        return fallback
    name = _enum_name(connect_state)
    if name == ConnectState.CONNECTED.name:
        return True
    if name == ConnectState.DISCONNECTED.name:
        return False
    return None


def _charging(charging_state: Any, fallback: Any) -> bool | None:
    if isinstance(fallback, bool):
        return fallback
    name = _enum_name(charging_state)
    if name == ChargingState.CHARGING.name:
        return True
    if name in {ChargingState.NOT_CHARGING.name, ChargingState.CONNECTED.name}:
        return False
    return None


def _hvac_on(value: Any) -> bool | None:
    name = _enum_name(value)
    if name == "ON":
        return True
    if name == "OFF":
        return False
    return None


def _boolish(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return bool(value)


def _lock_state(realtime_data: dict[str, Any]) -> str | None:
    names = {
        _enum_name(realtime_data.get(key))
        for key in ("left_front_door_lock", "right_front_door_lock", "left_rear_door_lock", "right_rear_door_lock")
        if realtime_data.get(key) not in (None, "")
    }
    if not names:
        return None
    if names == {LockState.LOCKED.name}:
        return "LOCKED"
    if names == {LockState.UNLOCKED.name}:
        return "UNLOCKED"
    return "MIXED"


def _window_state(realtime_data: dict[str, Any]) -> str | None:
    names = {
        _enum_name(realtime_data.get(key))
        for key in ("left_front_window", "right_front_window", "left_rear_window", "right_rear_window", "skylight")
        if realtime_data.get(key) not in (None, "")
    }
    if not names:
        return None
    if names == {WindowState.CLOSED.name}:
        return "CLOSED"
    if WindowState.OPEN.name in names:
        return "OPEN"
    return "MIXED"


def _seat_level(value: str) -> SeatLevel:
    normalized = (value or "").strip().lower()
    if normalized == "high":
        return SeatLevel.HIGH
    if normalized == "low":
        return SeatLevel.LOW
    return SeatLevel.OFF
