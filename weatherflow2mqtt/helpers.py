""" Several Helper Functions."""
from __future__ import annotations

import datetime as dt
import importlib.resources
import time
import json
import logging
import math
from typing import Any

from pint import Quantity
from pyweatherflowudp.const import units
import yaml

from .const import (
    BATTERY_MODE_DESCRIPTION,
    EXTERNAL_DIRECTORY,
    SUPPORTED_LANGUAGES,
    UNITS_IMPERIAL,
)

_LOGGER = logging.getLogger(__name__)

UTC = dt.timezone.utc
NO_CONVERSION = object()


def no_conversion_to_none(val: Any) -> Any | None:
    return None if val is NO_CONVERSION else val


def truebool(val: Any | None) -> bool:
    """ Return `True` if the value passed in matches a "True" value, otherwise `False`.

    "True" values are: 'true', 't', 'yes', 'y', 'on' or '1'.
    """
    return val is not None and str(val).lower() in ("true", "t", "yes", "y", "on", "1")


def read_config() -> list[str] | None:
    """ Read the config file to look for sensors."""
    try:
        filepath = f"{EXTERNAL_DIRECTORY}/config.yaml"
        with open(filepath, "r") as file:
            data = yaml.load(file, Loader=yaml.FullLoader)
            sensors = data.get("sensors")

            return sensors

    except FileNotFoundError:
        return None
    except Exception as e:
        _LOGGER.error("Could not read config.yaml file. Error message: %s", e)
        return None


class ConversionFunctions:
    """ Class to help with converting from different units."""

    def __init__(self, unit_system: str, language: str) -> None:
        """Initialize Conversion Function."""
        self.unit_system = unit_system
        self.translations = self.get_language_file(language)

    def get_language_file(self, language: str) -> dict[str, dict[str, str]] | None:
        """ Return the language file json array."""
        filename = (
            f"translations/{language if language in SUPPORTED_LANGUAGES else 'en'}.json"
        )

        try:
            with (importlib.resources.files(__package__) / filename).open('r') as json_file:
                return json.load(json_file)
        except FileNotFoundError as e:
            _LOGGER.error("Could not read language file. Error message: %s", e)
            return None
        except Exception as e:
            _LOGGER.error("Could not read language file. Error message: %s", e)
            return None

    def temperature(self, value) -> float:
        """ Convert Temperature Value."""
        if value is not None:
            if self.unit_system == UNITS_IMPERIAL:
                return round((value * 9 / 5) + 32, 1)
            return round(value, 1)

        _LOGGER.error(
            "FUNC: temperature ERROR: Temperature value was reported as NoneType. Check the sensor"
        )

    def pressure(self, value) -> float:
        """ Convert Pressure Value."""
        if value is not None:
            if self.unit_system == UNITS_IMPERIAL:
                return round(value * 0.02953, 3)
            return round(value, 2)

        _LOGGER.error(
            "FUNC: pressure ERROR: Pressure value was reported as NoneType. Check the sensor"
        )

    def speed(self, value, kmh=False) -> float:
        """ Convert Wind Speed."""
        if value is not None:
            if self.unit_system == UNITS_IMPERIAL:
                return round(value * 2.2369362920544, 2)
            if kmh:
                return round((value * 18 / 5), 1)
            return round(value, 1)

        _LOGGER.error(
            "FUNC: speed ERROR: Wind value was reported as NoneType. Check the sensor"
        )

    def distance(self, value) -> float:
        """ Convert distance."""
        if value is not None:
            if self.unit_system == UNITS_IMPERIAL:
                return round(value / 1.609344, 2)
            return value

        _LOGGER.error(
            "FUNC: distance ERROR: Lightning Distance value was reported as NoneType. Check the sensor"
        )

    def rain(self, value) -> float:
        """ Convert rain."""
        if value is not None:
            if self.unit_system == UNITS_IMPERIAL:
                return round(value * 0.0393700787, 2)
            return round(value, 2)

        _LOGGER.error(
            "FUNC: rain ERROR: Rain value was reported as NoneType. Check the sensor"
        )

    def rain_type(self, value) -> str:
        """ Convert rain type."""
        type_array = ["none", "rain", "hail", "heavy-rain"]
        try:
            precip_type = type_array[int(value)]
            return self.translations["precip_type"][precip_type]
        except IndexError:
            _LOGGER.warning("VALUE is: %s", value)
            return f"Unknown - {value}"

    def direction(self, value) -> str:
        """ Return directional Wind Direction string."""
        if value is None:
            return "N"

        direction_array = [
            "N",
            "NNE",
            "NE",
            "ENE",
            "E",
            "ESE",
            "SE",
            "SSE",
            "S",
            "SSW",
            "SW",
            "WSW",
            "W",
            "WNW",
            "NW",
            "NNW",
            "N",
        ]
        direction_str = direction_array[int((value + 11.25) / 22.5)]
        return self.translations["wind_dir"][direction_str]

    def absolute_humidity(self, temp, relative_humidity):
        """ Return Absolute Humidity.
        Grams of water per cubic meter of air (g/m^3)
        AH = RH*Ps/(Rw*T)
            where
              AH is Absolute Humidity
              RH is Relative Humidity in range of 0.0 - 1.0.  i.e. 25% RH is 0.25
              T is Temperature
        Ps = Pc*exp(Tc/T*(a1*τ+a2*τ^1.5+a3*τ^3+a4*τ^3.5+a5*τ^4+a6*τ^7.5))
            where
              Pc = 22.064 MPa
              Tc = 647.096 K
              a1, ... = -7.85951783
                        1.84408259
                        -11.7866497
                        22.6807411
                        -15.9618719
                        1.80122502
              τ = 1 - (T/Tc)

        W. Wagner, A. Pruß; The IAPWS Formulation 1995 for the Thermodynamic Properties of Ordinary Water Substance for General and Scientific Use. J. Phys. Chem. Ref. Data 1 June 2002; 31 (2): 387–535. https://doi.org/10.1063/1.1461892
        """
        if temp is None or relative_humidity is None:
            return None

        T = temp.to('K')
        Pc = 22.064*units.MPa
        Tc = 647.096*units.K
        tau = 1 - (T/Tc)
        Ps = Pc * math.exp(
            Tc/T*(
                -7.85951783 * tau +
                1.84408259 * (tau ** 1.5) +
                -11.7866497 * (tau ** 3) +
                22.6807411 * (tau ** 3.5) +
                -15.9618719 * (tau ** 4) +
                1.80122502 * (tau ** 7.5)
            )
        )

        Rw = 461.5*units("J/(kg K)")

        return (relative_humidity * Ps / (Rw * T)).to("g / m^3")

    def rain_intensity(self, rain_rate) -> str:
        """ Return a descriptive value of the rain rate.
        Input:
            Rain Rate in mm/hour
        Where:
            VERY LIGHT: < 0.25 mm/hour
            LIGHT: ≥ 0.25, < 1.0 mm/hour
            MODERATE: ≥ 1.0, < 4.0 mm/hour
            HEAVY: ≥ 4.0, < 16.0 mm/hour
            VERY HEAVY: ≥ 16.0, < 50 mm/hour
            EXTREME: > 50.0 mm/hour
        """
        if rain_rate == 0:
            intensity = "NONE"
        elif rain_rate < 0.25:
            intensity = "VERYLIGHT"
        elif rain_rate < 1:
            intensity = "LIGHT"
        elif rain_rate < 4:
            intensity = "MODERATE"
        elif rain_rate < 16:
            intensity = "HEAVY"
        elif rain_rate < 50:
            intensity = "VERYHEAVY"
        else:
            intensity = "EXTREME"

        return self.translations["rain_intensity"][intensity]

    def feels_like(self, temperature, humidity, windspeed):
        """ Calculate feel like temperature."""
        if temperature is None or humidity is None or windspeed is None:
            return 0

        windspeed = windspeed.to(units.m/units.s).m

        e_value = (
            humidity * 0.06105 * math.exp((17.27 * temperature) / (237.7 + temperature))
        )
        feelslike_c = temperature + 0.348 * e_value - 0.7 * windspeed - 4.25
        return self.temperature(feelslike_c)

    def visibility(self, elevation, temp, dewpoint):
        """ Return the visibility.
        Input:
            Elevation
            Temperature
            Dewpoint
        Where:
            elv_min is the station elevation with a minimum set height of 2 meters above sea level
            mv is the maximum distance of visibility to the horizon
            pr_a sets a minimum and maximum visability distance independent of environmental conditions
            pr is a precentage reduction of visability based on environmental conditions
            vis is the visability distance
        """
        if temp is None or elevation is None or dewpoint is None:
            return None

        # Set minimum elevation for cases of stations below sea level
        elv_min = max(2*units.m, elevation)

        # Max possible visibility to horizon
        # https://sites.math.washington.edu//~conroy/m120-general/horizon.pdf
        mv = 3.56972 * units("km/m^.5") * elv_min**0.5

        # Percent reduction based on quantity of water in air (no units)
        # 76 percent of visibility variation can be accounted for by humidity accourding to US-NOAA.
        # https://www.vos.noaa.gov/MWL/201504/visibility.shtml
        water_visibility = 1.13 * units("mi / delta_degC") * abs(temp - dewpoint) - 1.15*units.mi
        pr = max(
            0.025,
            min(
                1,
                water_visibility / (10*units.mi)
            )
        )

        # Visibility to horizon
        return mv * pr

    def wbgt(self, temp, wet_bulb_temp, humidity, pressure, solar_radiation):
        """ Return Wet Bulb Globe Temperature.
        This is a way to show heat stress on the human body.
        Input:
            Temperature in Celcius
            Humdity in Percent
            Station Pressure in MB
            Solar Radiation in Wm^2
        WBGT = 0.7Twb + 0.2Tg + 0.1Ta
          where:
            WBGT is Wet Bulb Globe Temperature in C
            Twb is Wet Bulb Temperature in C
            Tg is Black Globe Temperature in C (estimation)
            Ta is Air Temperature (dry bulb)
        Tg = 0.01498SR + 1.184Ta - 0.0789Rh - 2.739
          where:
            Tg is Black Globe Temperature in C (estimation)
            SR is Solar Radiation in Wm^2
            Ta is Air Temperature in C
            Rh is Relative Humidity in %
        WBGT = 0.7Twb + 0.002996SR + 0.3368Ta -0.01578Rh - 0.5478
        """
        if (
            temp is None
            or wet_bulb_temp is None
            or humidity is None
            or pressure is None
            or solar_radiation is None
        ):
            return None

        wbgt = units.degC * (
            0.7 * wet_bulb_temp.to(units.degC).m
            + 0.002996 * solar_radiation.to("W / m^2").m
            + 0.3368 * temp.to(units.degC).m
            - 0.01578 * humidity.to("percent").m
            -0.5478
        )

        return wbgt

    def battery_level(self, voltage, is_tempest):
        """ Return battery percentage.
        Input:
            Voltage in Volts DC (depends on the weather station type, see below)
            is_tempest in Boolean
        Tempest:
            Battery voltage range is 1.8 to 2.85 Vdc
                > 2.80 is capped at 100%
                < 1.8 is capped at 0%
                However, below 2.11V the station is no longer operational, so this is used.
        Air:
            4 AA batteries (2 in series, then parallel for 2 sets)
            Battery voltage range is 1.2(x2) => 2.4 to 1.8(x2) => 3.6 Vdc
            (lowered to 3.5 based on observation)
                > 3.5 is capped at 100%
                < 2.4 is capped at 0%
        Sky:
            8 AA batteries (2 in series, then parallel for 4 sets)
            Battery voltage range is 1.2(x2) => 2.4 to 1.8(x2) => 3.6 Vdc
            (lowered to 3.5 based on observation)
                > 3.5 is capped at 100%
                < 2.4 is capped at 0%
        """
        if voltage is None:
            return None

        minv, maxv = (
            # Min voltage is 1.8, but functional voltage is 2.11
            (2.11, 2.8) if is_tempest
            else (2.4, 3.5)
        ) * units.V

        if voltage > maxv:
            return 100*units.percent
        elif voltage < minv:
            return 0*units.percent
        else:
            return ((voltage - minv) / (maxv - minv)).to(units.percent)

    def battery_mode(self, voltage, solar_radiation):
        """ Return battery operating mode.
        Input:
            Voltage in Volts DC (depends on the weather station type, see below)
            is_tempest in Boolean
            solar_radiation in W/M^2 (used to determine if battery is in a charging state)
        Tempest:
            # https://help.weatherflow.com/hc/en-us/articles/360048877194-Solar-Power-Rechargeable-Battery
        AIR & SKY:
            The battery mode does not apply to AIR & SKY Units
        """
        if voltage is None or solar_radiation is None:
            return None

        voltage = voltage.to(units.V).m

        if voltage >= 2.455:
            # Mode 0 (independent of charging or discharging at this voltage)
            batt_mode = int(0)
        elif voltage <= 2.355:
            # Mode 3 (independent of charging or discharging at this voltage)
            batt_mode = int(3)
        elif solar_radiation > 100*units("W/m^2"):
            # Assume charging and voltage is raising
            if voltage >= 2.41:
                # Mode 1
                batt_mode = int(1)
            elif voltage > 2.375:
                # Mode 2
                batt_mode = int(2)
            else:
                # Mode 3
                batt_mode = int(3)
        else:
            # Assume discharging and voltage is lowering
            if voltage > 2.415:
                # Mode 0
                batt_mode = int(0)
            elif voltage > 2.39:
                # Mode 1
                batt_mode = int(1)
            elif voltage > 2.355:
                # Mode 2
                batt_mode = int(2)
            else:
                # Mode 3
                batt_mode = int(3)

        mode_description = BATTERY_MODE_DESCRIPTION[batt_mode]
        return batt_mode, mode_description

    def beaufort(self, wind_speed):
        """ Return Beaufort Scale value based on Wind Speed.
        Input:
            Wind Speed in m/s
        Where:
            bft_value is the numerical rating on the Beaufort Scale
        """
        if wind_speed is None:
            return 0, self.translations["beaufort"][str(0)]

        wind_speed = wind_speed.to('m/s').m

        if wind_speed > 32.7:
            bft_value = 12
        elif wind_speed >= 28.5:
            bft_value = 11
        elif wind_speed >= 24.5:
            bft_value = 10
        elif wind_speed >= 20.8:
            bft_value = 9
        elif wind_speed >= 17.2:
            bft_value = 8
        elif wind_speed >= 13.9:
            bft_value = 7
        elif wind_speed >= 10.8:
            bft_value = 6
        elif wind_speed >= 8.0:
            bft_value = 5
        elif wind_speed >= 5.5:
            bft_value = 4
        elif wind_speed >= 3.4:
            bft_value = 3
        elif wind_speed >= 1.6:
            bft_value = 2
        elif wind_speed >= 0.3:
            bft_value = 1
        else:
            bft_value = 0

        bft_text = self.translations["beaufort"][str(bft_value)]

        return bft_value, bft_text

    def dewpoint_level(self, dewpoint: Quantity[float]) -> str:
        """ Return text based comfort level.
        Input:
            dewpoint in Celsius or Fahrenheit
        Where:
            dewpoint is dewpoint converted to Fahrenheit
        """
        if dewpoint is None:
            return "no-data"

        if dewpoint >= 80*units.degF:
            return self.translations["dewpoint"]["severely-high"]
        if dewpoint >= 75*units.degF:
            return self.translations["dewpoint"]["miserable"]
        if dewpoint >= 70*units.degF:
            return self.translations["dewpoint"]["oppressive"]
        if dewpoint >= 65*units.degF:
            return self.translations["dewpoint"]["uncomfortable"]
        if dewpoint >= 60*units.degF:
            return self.translations["dewpoint"]["ok-for-most"]
        if dewpoint >= 55*units.degF:
            return self.translations["dewpoint"]["comfortable"]
        if dewpoint >= 50*units.degF:
            return self.translations["dewpoint"]["very-comfortable"]
        if dewpoint >= 30*units.degF:
            return self.translations["dewpoint"]["somewhat-dry"]
        if dewpoint >= 0.5*units.degF:
            return self.translations["dewpoint"]["dry"]
        if dewpoint >= 0*units.degF:
            return self.translations["dewpoint"]["very-dry"]

        return self.translations["dewpoint"]["undefined"]

    def temperature_level(self, temperature):
        """ Return text based comfort level, based on Air Temperature value.
        Input:
            Air Temperature
        """
        if temperature is None:
            return "no-data"

        if temperature >= 104*units.degF:
            return self.translations["temperature"]["inferno"]
        if temperature >= 95*units.degF:
            return self.translations["temperature"]["very-hot"]
        if temperature >= 86*units.degF:
            return self.translations["temperature"]["hot"]
        if temperature >= 77*units.degF:
            return self.translations["temperature"]["warm"]
        if temperature >= 68*units.degF:
            return self.translations["temperature"]["nice"]
        if temperature >= 59*units.degF:
            return self.translations["temperature"]["cool"]
        if temperature >= 41*units.degF:
            return self.translations["temperature"]["chilly"]
        if temperature >= 32*units.degF:
            return self.translations["temperature"]["cold"]
        if temperature >= 20*units.degF:
            return self.translations["temperature"]["freezing"]
        if temperature <= 20*units.degF:
            return self.translations["temperature"]["fridged"]

        return self.translations["temperature"]["undefined"]

    def uv_level(self, uvi):
        """ Return text based UV Description."""
        if uvi is None:
            return "no-data"

        if uvi >= 10.5:
            return self.translations["uv"]["extreme"]
        if uvi >= 7.5:
            return self.translations["uv"]["very-high"]
        if uvi >= 5.5:
            return self.translations["uv"]["high"]
        if uvi >= 2.5:
            return self.translations["uv"]["moderate"]
        if uvi > 0:
            return self.translations["uv"]["low"]

        return self.translations["uv"]["none"]

    def utc_from_timestamp(self, timestamp: int) -> str:
        """ Return a UTC time from a timestamp."""
        if not timestamp:
            return None

        # Convert to String as MQTT does not like data objects
        dt_obj = dt.datetime.utcfromtimestamp(timestamp).replace(tzinfo=UTC)
        utc_offset = dt_obj.strftime("%z")
        utc_string = f"{utc_offset[:3]}:{utc_offset[3:]}"
        dt_str = dt_obj.strftime("%Y-%m-%dT%H:%M:%S")

        return f"{dt_str}{utc_string}"

    def utc_last_midnight(self) -> str:
        """ Return UTC Time for last midnight."""
        midnight = dt.datetime.combine(dt.datetime.today(), dt.time.min)
        midnight_ts = dt.datetime.timestamp(midnight)
        midnight_dt = self.utc_from_timestamp(midnight_ts)
        return midnight_dt

    def solar_elevation(self, latitude, longitude):
        """ Return Sun Elevation in Degrees with respect to the Horizon.
        Input:
            Latitude in Degrees and fractional degrees
            Longitude in Degrees and fractional degrees
            Local Time
            UTC Time
        Where:
            jd is Julian Date (Day of Year only), then Julian Date + Fractional True
            lt is Local Time (####) 24 hour time, no colon
            tz is Time Zone Offset (ie -7 from UTC)
            beta is Beta for EOT
            lstm is Local Standard Time Meridian
            eot is Equation of Time
            tc is Time Correction Factor
            lst is Local Solar Time
            h is Hour Angle
            dec is Declination
            se is Solar Elevation
            ** All Trigonometry Fuctions need Degrees converted to Radians **
            ** The assumption is made that correct local time is established **
        """
        if latitude is None or longitude is None:
            return None

        cos = math.cos
        sin = math.sin
        asin = math.asin
        latitude *= units.degree
        longitude *= units.degree
        tm = time.localtime(time.time())
        jd = tm.tm_yday * units.day
        lt = tm.tm_hour * units.hour + tm.tm_min * units.min
        tz = tm.tm_gmtoff * units.second
        jd = jd + lt
        beta = (360 * units.degree) / (365 * units.day) * (jd - (81 * units.day))
        lstm = 15 * units.degree / units.hour * tz
        # https://susdesign.com/popups/sunangle/eot.php
        eot = ((9.87*(sin(beta*2))) - (7.53*(cos(beta))) - (1.5*(sin(beta)))) * units.minute
        tc = (4 * units.minute / units.degree * (longitude - lstm)) + eot
        lst = lt + tc
        h = 15 * units.degree/units.hour * (lst - 12*units.hour)
        # https://www.pveducation.org/pvcdrom/properties-of-sunlight/declination-angle
        dec = cos((jd + (10 * units.day)) * (360 * units.degree) / (365 * units.day)) * (-23.44 * units.degree)
        # https://www.pveducation.org/pvcdrom/properties-of-sunlight/elevation-angle
        se = asin(sin(latitude) * sin(dec) + cos(latitude) * cos(dec) * cos(h)) * units.radian

        return se.to(units.degree)

    def solar_insolation(self, elevation, latitude, longitude):
        """ Return Estimation of Solar Radiation at current sun elevation angle.
        Input:
            Elevation
            Latitude
            Longitude
        Where:
            solar_elevation is the Sun Elevation in Degrees with respect to the Horizon
            sz is Solar Zenith in Degrees
            ah is Station Elevation Compensation
            am is Air Mass of atmoshere between Station and Sun
            1353 W/M^2 is considered Solar Radiation at edge of atmoshere
            ** All Trigonometry Fuctions need Degrees converted to Radians **
        """
        if elevation is None or latitude is None or longitude is None:
            return None

        # Calculate Solar Elevation
        solar_elevation = self.solar_elevation(latitude, longitude)

        cos = math.cos
        sin = math.sin
        asin = math.asin
        se = solar_elevation
        sz = 90*units.degree - se
        ah = (0.14 / units.km) * elevation
        if se >= 0:
            # https://www.e-education.psu.edu/eme810/node/533
            am = 1/(cos(sz) + 0.50572*pow((96.07995*units.degree - sz)/units.degree,(-1.6364)))
            si = (1353 * ((1-ah)*pow(.7, pow(am, 0.678))+ah))*(sin(se))
        else:
            am = 1
            si = 0

        return si * units("W/m^2")

    def zambretti_value(self, latitude, wind_dir, p_hi, p_lo, trend, press):
        """ Return local forecast number based on Zambretti Forecaster.
        Input:
            Sea Level Pressure in mB
            Pressure Trend 0 for Steady, >0 for Rising and <0 for Falling
            Latitude in Degrees
            All Time Sea Level Pressure High in mB
            All Time Sea Level Pressure Low in mB
            Wind Direction in Degrees - Converted to Cardinal further down)
        Where:
            z_where is a designation of Northern or Southern Hemisphere
            z_baro_top is the highest barometric pressure for location
            z_baro_bottom is the lowest barometric pressure for location
            z_range is the difference between highest and lowest pressures
            z_hpa is sea level pressure
            z_month is month of the year
            z_season is summer or winter
            z_wind is the cardinal wind direction
            z_trend is the pressure trend (idealy over a 3 hour period but current trend is used here)
            z_constant is pressure per zambretti value increment
            rise_options is array of outputs available for rising pressure conditions
            steady_options is array of outputs available for steady pressure conditions
            fall_options is array of outputs available for falling pressure conditions
        """
        if (
            latitude is None
            or wind_dir is None
            or p_hi is None
            or p_lo is None
            or trend is None
            or press is None
        ):
            return None

        # Based off Beteljuice's Zambretti work; http://www.beteljuice.co.uk/zambretti/forecast.html
        # Northern = 1 or Southern = 2 hemisphere
        if latitude >= 0:
            z_where = 1
        else:
            z_where = 2
        # upper limits of your local 'weather window' Pulled from All Time Max
        # var z_baro_top = 1050; # upper limits of your local 'weather window' (1050.0 hPa for UK)
        z_baro_top = p_hi
        # lower limits of your local 'weather window' Pulled from All Time Min
        # var z_baro_bottom = 950;	// lower limits of your local 'weather window' (950.0 hPa for UK)
        z_baro_bottom = p_lo
        # range of pressure
        z_range = z_baro_top - z_baro_bottom
        # z_hpa is Sea Level Adjusted (Relative) barometer in hPa or mB
        z_hpa = press
        # z_month is current month as a number between 1 to 12
        z_month = dt.datetime.now()
        z_month = int(z_month.strftime("%m"))
        # True (1) for summer, False (0) for Winter (Northern Hemishere)
        z_season = (z_month >= 4 and  z_month <= 9)
        # z_wind is English windrose cardinal eg. N, NNW, NW etc.
        # NB. if calm a 'nonsense' value should be sent as z_wind (direction) eg. 1 or calm !
        z_wind = self.direction(wind_dir)
        # z_trend is barometer trend: 0 = no change, 1 = rise, 2 = fall
        # z_trend_threshold = 0.047248 if self.unit_system == UNITS_IMPERIAL else 1.6
        if float(trend) < 0:
            z_trend = 2
        elif float(trend) > 0:
            z_trend = 1
        else:
            z_trend = 0
        # A constant for the current location, will vary since range will adjust as the min and max pressure will update overtime
        z_constant = (z_range / 22)
        # Equivalents of Zambretti 'dial window' letters A - Z: 0=A
        rise_options  = [25,25,25,24,24,19,16,12,11,9,8,6,5,2,1,1,0,0,0,0,0,0]
        steady_options  = [25,25,25,25,25,25,23,23,22,18,15,13,10,4,1,1,0,0,0,0,0,0]
        fall_options =  [25,25,25,25,25,25,25,25,23,23,21,20,17,14,7,3,1,1,1,0,0,0]

        if z_where == 1:
            # North hemisphere
            if z_wind == "N":
                z_hpa += 6 / 100 * z_range
            elif z_wind == "NNE":
                z_hpa += 5 / 100 * z_range
            elif z_wind == "NE":
                z_hpa += 5 / 100 * z_range
            elif z_wind == "ENE":
                z_hpa += 2 / 100 * z_range
            elif z_wind == "E":
                z_hpa -= 0.5 / 100 * z_range
            elif z_wind == "ESE":
                z_hpa -= 2 / 100 * z_range
            elif z_wind == "SE":
                z_hpa -= 5 / 100 * z_range
            elif z_wind == "SSE":
                z_hpa -= 8.5 / 100 * z_range
            elif z_wind == "S":
                z_hpa -= 12 / 100 * z_range
            elif z_wind == "SSW":
                z_hpa -= 10 / 100 * z_range
            elif z_wind == "SW":
                z_hpa -= 6 / 100 * z_range
            elif z_wind == "WSW":
                z_hpa -= 4.5 / 100 * z_range
            elif z_wind == "W":
                z_hpa -= 3 / 100 * z_range
            elif z_wind == "WNW":
                z_hpa -= 0.5 / 100 * z_range
            elif z_wind == "NW":
                z_hpa += 1.5 / 100 * z_range
            elif z_wind == "NNW":
                z_hpa += 3 / 100 * z_range
            if z_season == 1:
                # if Summer
                if z_trend == 1:
                    # rising
                    z_hpa += 7 / 100 * z_range
                elif z_trend == 2:
                    # falling
                    z_hpa -= 7 / 100 * z_range
        else:
            # South hemisphere
            if z_wind == "S":
                z_hpa += 6 / 100 * z_range
            elif z_wind == "SSW":
                z_hpa += 5 / 100 * z_range
            elif z_wind == "SW":
                z_hpa += 5 / 100 * z_range
            elif z_wind == "WSW":
                z_hpa += 2 / 100 * z_range
            elif z_wind == "W":
                z_hpa -= 0.5 / 100 * z_range
            elif z_wind == "WNW":
                z_hpa -= 2 / 100 * z_range
            elif z_wind == "NW":
                z_hpa -= 5 / 100 * z_range
            elif z_wind == "NNW":
                z_hpa -= 8.5 / 100 * z_range
            elif z_wind == "N":
                z_hpa -= 12 / 100 * z_range
            elif z_wind == "NNE":
                z_hpa -= 10 / 100 * z_range
            elif z_wind == "NE":
                z_hpa -= 6 / 100 * z_range
            elif z_wind == "ENE":
                z_hpa -= 4.5 / 100 * z_range
            elif z_wind == "E":
                z_hpa -= 3 / 100 * z_range
            elif z_wind == "ESE":
                z_hpa -= 0.5 / 100 * z_range
            elif z_wind == "SE":
                z_hpa += 1.5 / 100 * z_range
            elif z_wind == "SSE":
                z_hpa += 3 / 100 * z_range
            if z_season == 0:
                # Winter
                if z_trend == 1:
                    # rising
                    z_hpa += 7 / 100 * z_range
                elif z_trend == 2:
                    # falling
                    z_hpa -= 7 / 100 * z_range
            # END North / South

        if z_hpa == z_baro_top:
            z_hpa = z_baro_top - 1
        z_option = math.floor((z_hpa - z_baro_bottom) / z_constant)

        if z_option < 0:
            z_option = 0

        if z_option > 21:
            z_option = 21

        if z_trend == 1:
            # rising
            z_number = rise_options[z_option]
        elif z_trend == 2:
            # falling
            z_number = fall_options[z_option]
        else:
            # must be 'steady'
            z_number = steady_options[z_option]

        return z_number

    def zambretti_forecast(self, z_num: int):
        """ Return local forecast text based on Zambretti Number from the zambretti_num function.
        Input:
            Zambretti Number from Zambretti function
        Where:
        """
        if z_num is None:
            return None

        # Zambretti Text Equivalents of Zambretti 'dial window' letters A - Z
        # Simplified array for Language Translations
        z_forecast = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"]
        z_text = ""
        z_text += z_forecast[int(z_num)]

        return self.translations["zambretti"][z_text]

    def fog_probability(self, solar_elevation, wind_speed, humidity, dew_point, air_temperature):
        """ Return probability of fog in percent.
        Input:
            Solar Elevation - determine daylight
            Wind Speed
            Humidity
            Dew Point
            Air Temperature
        Where:
            diff is the differance between air temperature and dew point temperature
            fog is the variable for ongoing fog probability calculations
            fog_probability is the returned percentage
        """
        if (
            solar_elevation is None
            or wind_speed is None
            or humidity is None
            or dew_point is None
            or air_temperature is None
        ):
            return None

        fog = 0
        diff = air_temperature - dew_point

        if solar_elevation >= 0:
            # daytime
            fog = fog - 15
        else:
            # fog is more common at night
            fog = fog + 10

        if wind_speed < 2.2352*units("m/s"):
            # fog is more likely when it is calm (<5 mph / 2.2352 m/s)
            fog = fog + 20
        elif wind_speed < 4.4704*units("m/s"):
            # it's more windy, fog is slightly less likely (<10 mph / 4.4704 m/s)
            fog = fog + 5
        else:
            # it's unlikely fog will form above 10 mph / 4.4704 m/s
            fog = fog - 20

        if humidity > 75 and humidity < 91:
            # high humidity
            fog = fog + 5
        elif humidity > 90:
            # higher humidity
            fog = fog + 10
        else:
            # humidity is still quite low
            fog = fog - 20

        if diff < 5.1 and diff > 3.9:
            # Diff between temp and dewpoint is less than 5'C and over 4'C")
            fog = fog + 5
        elif diff < 4.1 and diff > 2.5:
            # Diff between temp and dewpoint is less than 4'C and over 2.5'C")
            fog = fog + 10
        elif diff < 2.6 and diff > 1.9:
            # Diff between temp and dewpoint is less than 3'C and over 2'C")
            fog = fog + 15
        elif diff < 2.1 and diff > 0.9:
            # Diff between temp and dewpoint is less than 2'C and over 1'C")
            fog = fog + 20
        elif diff < 1:
            # Diff between temp and dewpoint is less than 1'C"
            fog = fog + 25
        else:
            fog = fog - 20

        # 75 is the maximum possible score
        if fog > 0:
            fog = (fog / 75) * 100
        else:
            fog = 0

        fog_probability = round(fog)

        return fog_probability

    def snow_probability(self, air_temperature, freezing_level, cloud_base, dew_point, wet_bulb, station_height):
        """ Return probability of snow in percent (Max of 80% calculated probability).
        Input:
            Air Temperature (metric)
            Freezing Level (imperial or metric)
            Cloud Base (imperial or metric)
            Dew Point (metric)
            Wet Bulb (imperial or metric))
            Station Height
        Where:
            dptt is Dew Point plus Air Temperature
            snow_prob is the probability of snow
            snow_probability is the returned percentage of the probability of snow rounded (Max of 80%)
        """

        if (
            air_temperature is None
            or freezing_level is None
            or cloud_base is None
            or dew_point is None
            or wet_bulb is None
        ):
            return None

        is_metric = False if self.unit_system != UNITS_IMPERIAL else True


        if not is_metric:
            air_temperature = air_temperature
            freezing_level = freezing_level / 3.28
            cloud_base = cloud_base / 3.28
            dew_point = dew_point
            wet_bulb = (wet_bulb - 32) / 1.8
        station_height = station_height / units.m
        
        snow_line = freezing_level - 228.6 # 750 ft / 228.6 m, snow line can vary in distance from freezing line
        dptt = dew_point + air_temperature
        
        if ((air_temperature <= 2.1) and (snow_line <= station_height) and (dew_point <= 1) and (wet_bulb <= 2.1) and (freezing_level <= cloud_base) and (air_temperature >= -40)):
             snow_prob = 80 - 10 * dptt
        else:
             snow_prob = 0

        snow_probability = round(snow_prob) if snow_prob <= 100 else 99

        return snow_probability

    def current_conditions(self, lightning_1h, precip_type, rain_rate, wind_speed, solar_el, solar_rad, solar_ins, snow_prob, fog_prob):
        """ Return local current conditions based on only weather station sesnors.
        Input:
            lightning_1h (#)
            **** Need to use the precip type number from Tempest so to get it before translations ****
            precip_type (#)
            rain_rate (imperial or metric)
            wind_speed (metric)
            solar_el (degrees)
            solar_rad (metric)
            snow_prob (%)
            fog_prob (%)
        Where:
            lightning_1h is lightning strike count within last hour
            precip_type is the type of precipitation: rain / hail
            rain_rate is the rain fall rate
            wind_speed is the speed of wind
            solar_el is the elevation of the sun with respect to horizon
            solar_rad is the measured solar radiation
            solar_ins is the calculated solar radiation
            snow_prob is the probability of snow
            fog_prob is the probability of fog
            si_p is the percentage difference in Solar Radiation and Solar Insolation
            si_d is the numeral difference in Solar Radiation and Solar Insolation
            cloudy is Boolan for cloud state
            part_cloud is Boolan for partly cloud state
            current is the Local Current Weather Condition
        """
        if (
            lightning_1h is None
            or precip_type is None
            or rain_rate is None
            or wind_speed is None
            or solar_el is None
            or solar_rad is None
            or solar_ins is None
            or snow_prob is None
            or fog_prob is None
        ):
            _LOGGER.info("Something is missing to calculate current conditions %s - %s - %s - %s - %s - %s - %s - %s - %s", lightning_1h, precip_type, rain_rate, wind_speed,solar_el, solar_rad, solar_ins, snow_prob, fog_prob)
            return "clear-night"

        # Home Assistant weather conditions: clear-night, cloudy, fog, hail, lightning, lightning-rainy, partlycloudy, pouring, rainy, snowy, snowy-rainy, sunny, windy, windy-variant, exceptional
        # Exceptional not used here
        
        if solar_el <= 0: # Can not determine clouds at night
            cloudy = False
            part_cloud = False
        else:
            si_p = round(((solar_rad) / (solar_ins))) * 100
            si_d = round((solar_ins) - (solar_rad))
            if ((si_p <= 50) and (si_d >= 50)):
                 cloudy = True
                 part_cloud = False
            elif ((si_p <= 75) and (abs(si_d) >= 15)):
                 part_cloud = True
                 cloudy = False
            elif ((si_p >= 115) and (abs(si_d) >= 15)):
                 part_cloud = True
                 cloudy = False
            else:
                 part_cloud = False
                 cloudy = False

        if ((lightning_1h >= 1) and (rain_rate >= 0.01)): # any rain at all
            current = "lightning-rainy"
        elif (lightning_1h >= 1):
            current = "lightning"
        elif (precip_type == 2):
            current = "hail"
        elif (rain_rate >= 7.8): # pouring => Imperial >= 0.31 in/hr, Metric >= 7.8 mm/hr
            current = "pouring"
        elif ((snow_prob >= 50) and (rain_rate >= 0.01)): # any rain at all
            current = "snowy-rainy"
        elif (rain_rate >= 0.01): # any rain at all
            current = "rainy"
        elif ((wind_speed >= 11.17*units("m/s") and (cloudy)): # windy => Imperial >= 25 mph, Metric >= 11.17 m/s
            current = "windy-variant"
        elif (wind_speed >= 11.17*units("m/s")): # windy => Imperial >= 25 mph, Metric >= 11.17 m/s
            current = "windy"
        elif (fog_prob >= 50):
            current = "fog"
        elif ((snow_prob >= 50) and (cloudy)):
            current = "snowy"
        elif (cloudy == 'true'):
            current = "cloudy"
        elif (part_cloud):
            current = "partlycloudy"
        elif (solar_el >= 0 ): # if daytime
            current = "sunny"
        else:
            current = "clear-night"

        # return the standard weather conditions as used by Home Assistant
        return current

'''    def current_conditions_txt(self, current_conditions):
        # Clear Night, Cloudy, Fog, Hail, Lightning, Lightning & Rain, Partly Cloudy, Pouring Rain, Rain, Snow, Snow & Rain, Sunny, Windy, Wind & Rain, exceptional (not used)
        # Need translations
        # Add input blurb

        if (current_conditions = "lightning-rainy"):
            current = "Lightning & Rain"
        elif (current_conditions = "lightning"):
            current = "Lightning"
        elif (current_conditions = "hail"):
            current = "Hail"
        elif (current_conditions = "pouring"):
            current = "Pouring Rain"
        elif (current_conditions = "snowy-rainy"):
            current = "Snow & Rain"
        elif (current_conditions = "rainy"):
            current = "Rain"
        elif (current_conditions = "windy-variant"):
            current = "Wind & Rain"
        elif (current_conditions = "windy"):
            current = "Windy"
        elif (current_conditions = "fog"):
            current = "Fog"
        elif (current_conditions = "snowy"):
            current = "Snow"
        elif (current_conditions = "cloudy"):
            current = "Cloudy"
        elif (current_conditions = "partlycloudy"):
            current = "Partly Cloudy"
        elif (current_conditions = "sunny"):
            current = "Sunny"
        elif (current_conditions = "clear-night"):
            current = "Clear Night"
        else
            current = "Unknown"

        # return the human readable weather conditions
        return current
'''
