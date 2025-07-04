"""Module to get forecast using REST from WeatherFlow."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, OrderedDict, Optional

from aiohttp import ClientSession, ClientTimeout
from aiohttp.client_exceptions import ClientError
from pint import Quantity
from pyweatherflowudp.const import units

from .const import (
    ATTR_ATTRIBUTION,
    ATTR_FORECAST_CONDITION,
    ATTR_FORECAST_HUMIDITY,
    ATTR_FORECAST_PRECIPITATION,
    ATTR_FORECAST_PRECIPITATION_PROBABILITY,
    ATTR_FORECAST_PRESSURE,
    ATTR_FORECAST_APPARENT_TEMP,
    ATTR_FORECAST_TEMP,
    ATTR_FORECAST_TEMP_LOW,
    ATTR_FORECAST_TIME,
    ATTR_FORECAST_UV_INDEX,
    ATTR_FORECAST_WIND_BEARING,
    ATTR_FORECAST_WIND_GUST_SPEED,
    ATTR_FORECAST_WIND_SPEED,
    ATTRIBUTION,
    BASE_URL,
    CONDITION_CLASSES,
    DEFAULT_TIMEOUT,
    FORECAST_HOURLY_HOURS,
    FORECAST_TYPE_DAILY,
    FORECAST_TYPE_HOURLY,
    LANGUAGE_ENGLISH,
    UNITS_IMPERIAL,
    UNITS_METRIC,
    TEMP_CELSIUS,
    TEMP_FAHRENHEIT,
    UnitSystem,
)
from .helpers import ConversionFunctions

_LOGGER = logging.getLogger(__name__)


WEATHERFLOW_UNITS = {
    "kg/m3": "kg/m3",
    "lux": "lux",
    "km": "km",
    "mm": "mm",
    "mb": "hPa",
    "w/m2": "W/m^2",
    "c": "degC",
    "mps": "m/s",
}


@dataclass
class ForecastConfig:
    """Forecast config."""

    station_id: str
    token: str
    interval: int = 30


class Forecast:
    """Forecast."""

    def __init__(
        self,
        station_id: str,
        token: str,
        unit_system: UnitSystem = UNITS_METRIC,
        interval: int = 30,
        conversions: ConversionFunctions = ConversionFunctions(
            unit_system=UNITS_METRIC, language=LANGUAGE_ENGLISH
        ),
        session: ClientSession | None = None,
    ):
        """Initialize a Forecast object."""
        self.station_id = station_id
        self.token = token
        self.interval = interval
        self.unit_system = unit_system
        self.conversions = conversions
        self._session: ClientSession = session

    @classmethod
    def from_config(
        cls,
        config: ForecastConfig,
        unit_system: UnitSystem = UNITS_METRIC,
        conversions: ConversionFunctions = ConversionFunctions(
            unit_system=UNITS_METRIC, language=LANGUAGE_ENGLISH
        ),
        session: ClientSession | None = None,
    ) -> Forecast:
        """Create a Forecast from a Forecast Config."""
        return cls(
            station_id=config.station_id,
            token=config.token,
            interval=config.interval,
            conversions=conversions,
            unit_system=unit_system,
            session=session,
        )

    async def update_forecast(self):
        """Return the formatted forecast data."""
        json_data = await self.async_request(
            method="get",
            endpoint=f"better_forecast?station_id={self.station_id}&token={self.token}",
        )
        items = []

        if json_data is not None:
            # Calculate the correct units
            pint_units = {
                key: units.parse_units(WEATHERFLOW_UNITS[value])
                for key, value in json_data.get("units", {}).items()
                if value in WEATHERFLOW_UNITS
            }
            forecast_field_units = {
                "air_temp_high": pint_units["units_temp"],
                "air_temp_low": pint_units["units_temp"],
                "precip_probability": "%",
                "air_temperature": pint_units["units_temp"],
                "sea_level_pressure": pint_units["units_pressure"],
                "relative_humidity": "%",
                "precip": pint_units["units_precip"],
                "wind_avg": pint_units["units_wind"],
                "wind_direction": "°",
                "wind_gust": pint_units["units_wind"],
                "feels_like": pint_units["units_temp"],
            }
            def get(forecast, field, default=None):
                if field not in forecast_field_units:
                    return forecast.get(field, default)
                return units.Quantity(forecast.get(field, default), forecast_field_units[field])

            # We need a few Items from the Current Conditions section
            current_cond = json_data.get("current_conditions")
            current_icon = current_cond["icon"]
            today = datetime.date(datetime.now())

            # Prepare for MQTT
            condition_data = OrderedDict()
            condition_state = self.ha_condition_value(current_icon)
            condition_data["weather"] = condition_state

            forecast_data = json_data.get("forecast")

            # We also need Day hign and low Temp from Today
            temp_high_today = get(forecast_data[FORECAST_TYPE_DAILY][0], "air_temp_high")
            temp_low_today = get(forecast_data[FORECAST_TYPE_DAILY][0], "air_temp_low")

            # Process Daily Forecast
            fcst_data = OrderedDict()
            fcst_data[ATTR_ATTRIBUTION] = ATTRIBUTION
            fcst_data["temp_high_today"] = self.unit_system.temperature.m_from(temp_high_today)
            fcst_data["temp_low_today"] = self.unit_system.temperature.m_from(temp_low_today)

            for row in forecast_data[FORECAST_TYPE_DAILY]:
                # Skip over past forecasts - seems the API sometimes returns old forecasts
                forecast_time = datetime.date(
                    datetime.fromtimestamp(row["day_start_local"])
                )
                if today > forecast_time:
                    continue

                # Calculate data from hourly that's not summed up in the daily.
                precip = 0
                wind_avg = []
                wind_bearing = []
                for hourly in forecast_data["hourly"]:
                    if hourly["local_day"] == row["day_num"]:
                        precip += get(hourly, "precip")
                        wind_avg.append(get(hourly, "wind_avg"))
                        wind_bearing.append(get(hourly, "wind_direction"))
                sum_wind_avg = sum(wind_avg) / len(wind_avg)
                sum_wind_bearing = sum(wind_bearing) / len(wind_bearing) % 360

                item = {
                    ATTR_FORECAST_TIME: self.conversions.utc_from_timestamp(
                        row["day_start_local"]
                    ),
                    ATTR_FORECAST_CONDITION: "cloudy" if row.get("icon") is None else self.ha_condition_value(row["icon"]),
                    ATTR_FORECAST_TEMP: self.unit_system.temperature.m_from(get(row, "air_temp_high")),
                    ATTR_FORECAST_TEMP_LOW: self.unit_system.temperature.m_from(get(row, "air_temp_low")),
                    ATTR_FORECAST_PRECIPITATION: self.unit_system.rain.m_from(precip),
                    ATTR_FORECAST_PRECIPITATION_PROBABILITY: row["precip_probability"],
                    ATTR_FORECAST_WIND_SPEED: self.unit_system.forecast_wind_speed.m_from(sum_wind_avg),
                    ATTR_FORECAST_WIND_BEARING: int(sum_wind_bearing),
                    # "conditions": row["conditions"],
                    # "precip_icon": row.get("precip_icon", ""),
                    # "precip_type": row.get("precip_type", ""),
                    # "wind_direction_cardinal": self.conversions.direction(
                    #     int(sum_wind_bearing)
                    # ),
                }
                items.append(item)
            fcst_data["daily_forecast"] = items

            cnt = 0
            items = []
            for row in forecast_data[FORECAST_TYPE_HOURLY]:
                # Skip over past forecasts - seems the API sometimes returns old forecasts
                forecast_time = datetime.fromtimestamp(row["time"])
                if datetime.now() > forecast_time:
                    continue

                item = {
                    ATTR_FORECAST_TIME: self.conversions.utc_from_timestamp(
                        row["time"]
                    ),
                    ATTR_FORECAST_CONDITION: self.ha_condition_value(row.get("icon")),
                    ATTR_FORECAST_TEMP: self.unit_system.temperature.m_from(get(row, "air_temperature")),
                    ATTR_FORECAST_PRESSURE: self.unit_system.pressure.m_from(get(row, "sea_level_pressure", 0)),
                    ATTR_FORECAST_HUMIDITY: row["relative_humidity"],
                    ATTR_FORECAST_PRECIPITATION: self.unit_system.rain.m_from(get(row, "precip")),
                    ATTR_FORECAST_PRECIPITATION_PROBABILITY: row["precip_probability"],
                    ATTR_FORECAST_WIND_SPEED: self.unit_system.forecast_wind_speed.m_from(get(row, "wind_avg")),
                    ATTR_FORECAST_WIND_GUST_SPEED: self.unit_system.forecast_wind_speed.m_from(get(row, "wind_gust")),
                    ATTR_FORECAST_WIND_BEARING: row["wind_direction"],
                    ATTR_FORECAST_UV_INDEX: row.get("uv", 0),
                    ATTR_FORECAST_APPARENT_TEMP: self.unit_system.temperature.m_from(get(row, "feels_like")),
                    # "conditions": row["conditions"],
                    # "precip_icon": row.get("precip_icon", ""),
                    # "precip_type": row.get("precip_type", ""),
                    # "wind_direction_cardinal": self.conversions.translations[
                    #     "wind_dir"
                    # ][row["wind_direction_cardinal"]],
                }
                items.append(item)
                # Limit number of Hours
                cnt += 1
                if cnt >= FORECAST_HOURLY_HOURS:
                    break
            fcst_data["hourly_forecast"] = items

            return condition_data, fcst_data

        # Return None if we could not retrieve data
        _LOGGER.warning("Forecast Server was unresponsive. Skipping forecast update")
        return None, None

    async def async_request(self, method: str, endpoint: str) -> Optional[dict[str, Any]]:
        """Request data from the WeatherFlow API."""
        use_running_session = self._session and not self._session.closed

        if use_running_session:
            session = self._session
        else:
            session = ClientSession(timeout=ClientTimeout(total=DEFAULT_TIMEOUT))

        try:
            async with session.request(method, f"{BASE_URL}/{endpoint}") as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data
        except asyncio.TimeoutError:
            _LOGGER.debug("Request to endpoint timed out: %s", endpoint)
        except ClientError as err:
            if "Unauthorized" in str(err):
                _LOGGER.error(
                    "Your API Key is invalid or does not support this operation"
                )
            if "Not Found" in str(err):
                _LOGGER.error("The Station ID does not exist")
        except Exception as exc:
            _LOGGER.debug("Error requesting data from %s Error: %s", endpoint, exc)

        finally:
            if not use_running_session:
                await session.close()

    def ha_condition_value(self, value: str) -> str | None:
        """Return Home Assistant Condition."""
        try:
            return next(
                (k for k, v in CONDITION_CLASSES.items() if value in v),
                None,
            )
        except Exception as exc:
            _LOGGER.debug(
                "Could not find icon with value: %s. Error message: %s", value, exc
            )
            return None
