"""Weather context input for EdgeBot using Open-Meteo API."""
import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, Any, Callable, Optional, Tuple
import httpx
import structlog

logger = structlog.get_logger(__name__)

# Open-Meteo API base URL (no API key required)
OPENMETEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"

# Geocoding API for city name to coordinates
GEOCODING_API_URL = "https://geocoding-api.open-meteo.com/v1/search"


class WeatherPoller:
    """Weather data poller using Open-Meteo API."""
    
    def __init__(self, config: Dict[str, Any], message_callback: Callable):
        self.config = config
        self.message_callback = message_callback
        self.running = False
        self.poll_task = None
        self.last_poll = 0
        self.coordinates = None
        self.consecutive_failures = 0
        self.max_failures = 10
        
        # HTTP client configuration
        self.http_timeout = config.get('api_timeout', 30)
        self.client = None
    
    async def start(self):
        """Start the weather poller."""
        if not self.config.get('enabled', False):
            logger.info("Weather input disabled")
            return
        
        # Validate configuration and get coordinates
        try:
            self.coordinates = await self._get_coordinates()
            if not self.coordinates:
                logger.error("Could not determine coordinates for weather polling")
                return
        except Exception as e:
            logger.error("Failed to initialize weather poller", error=str(e))
            return
        
        # Create HTTP client
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.http_timeout),
            follow_redirects=True,
            headers={'User-Agent': 'EdgeBot-WeatherPoller/1.0'}
        )
        
        self.running = True
        self.poll_task = asyncio.create_task(self._poll_loop())
        
        logger.info("Weather poller started",
                   latitude=self.coordinates[0],
                   longitude=self.coordinates[1],
                   interval=self.config.get('interval', 3600))
    
    async def stop(self):
        """Stop the weather poller."""
        if not self.running:
            return
        
        self.running = False
        
        if self.poll_task:
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass
        
        if self.client:
            await self.client.aclose()
        
        logger.info("Weather poller stopped")
    
    async def _get_coordinates(self) -> Optional[Tuple[float, float]]:
        """Get latitude and longitude coordinates."""
        # Check if coordinates are directly provided
        lat = self.config.get('latitude')
        lon = self.config.get('longitude')
        
        if lat is not None and lon is not None:
            return (float(lat), float(lon))
        
        # Try to geocode city name
        city = self.config.get('city')
        if city:
            return await self._geocode_city(city)
        
        return None
    
    async def _geocode_city(self, city: str) -> Optional[Tuple[float, float]]:
        """Geocode a city name to coordinates."""
        temp_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.http_timeout),
            follow_redirects=True,
            headers={'User-Agent': 'EdgeBot-WeatherPoller/1.0'}
        )
        
        try:
            params = {
                'name': city,
                'count': 1,
                'language': 'en',
                'format': 'json'
            }
            
            response = await temp_client.get(GEOCODING_API_URL, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('results') and len(data['results']) > 0:
                result = data['results'][0]
                lat = result.get('latitude')
                lon = result.get('longitude')
                
                if lat is not None and lon is not None:
                    logger.info("Geocoded city successfully",
                              city=city, latitude=lat, longitude=lon,
                              country=result.get('country', 'unknown'))
                    return (float(lat), float(lon))
            
            logger.warning("Could not geocode city", city=city)
            return None
            
        except Exception as e:
            logger.error("Error geocoding city", city=city, error=str(e))
            return None
        finally:
            await temp_client.aclose()
    
    async def _poll_loop(self):
        """Main weather polling loop."""
        interval = self.config.get('interval', 3600)  # Default 1 hour
        
        while self.running:
            try:
                current_time = time.time()
                
                # Check if it's time to poll
                if current_time - self.last_poll >= interval:
                    await self._poll_weather()
                
                # Sleep for 60 seconds before checking again
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                logger.info("Weather poll loop cancelled")
                break
            except Exception as e:
                logger.error("Error in weather poll loop", error=str(e))
                await asyncio.sleep(300)  # Back off on error (5 minutes)
    
    async def _poll_weather(self):
        """Poll weather data from Open-Meteo API."""
        if not self.coordinates:
            logger.error("No coordinates available for weather polling")
            return
        
        try:
            lat, lon = self.coordinates
            
            # Prepare API parameters
            params = {
                'latitude': lat,
                'longitude': lon,
                'current': [
                    'temperature_2m',
                    'relative_humidity_2m',
                    'apparent_temperature',
                    'is_day',
                    'precipitation',
                    'rain',
                    'showers',
                    'snowfall',
                    'weather_code',
                    'cloud_cover',
                    'pressure_msl',
                    'surface_pressure',
                    'wind_speed_10m',
                    'wind_direction_10m',
                    'wind_gusts_10m'
                ],
                'timezone': 'UTC',
                'forecast_days': 1
            }
            
            logger.debug("Polling weather data", latitude=lat, longitude=lon)
            
            response = await self.client.get(OPENMETEO_BASE_URL, params=params)
            response.raise_for_status()
            
            weather_data = response.json()
            
            # Extract current weather
            current = weather_data.get('current', {})
            
            # Create structured message
            message = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'type': 'weather',
                'source': 'open-meteo',
                'location': {
                    'latitude': lat,
                    'longitude': lon,
                    'timezone': weather_data.get('timezone', 'UTC'),
                    'elevation': weather_data.get('elevation')
                },
                'current_weather': {
                    'time': current.get('time'),
                    'temperature_celsius': current.get('temperature_2m'),
                    'humidity_percent': current.get('relative_humidity_2m'),
                    'apparent_temperature_celsius': current.get('apparent_temperature'),
                    'is_day': current.get('is_day') == 1,
                    'precipitation_mm': current.get('precipitation'),
                    'rain_mm': current.get('rain'),
                    'showers_mm': current.get('showers'),
                    'snowfall_mm': current.get('snowfall'),
                    'weather_code': current.get('weather_code'),
                    'cloud_cover_percent': current.get('cloud_cover'),
                    'pressure_hpa': current.get('pressure_msl'),
                    'surface_pressure_hpa': current.get('surface_pressure'),
                    'wind_speed_kmh': current.get('wind_speed_10m'),
                    'wind_direction_degrees': current.get('wind_direction_10m'),
                    'wind_gusts_kmh': current.get('wind_gusts_10m')
                },
                'weather_description': self._get_weather_description(current.get('weather_code', 0)),
                'poll_interval': self.config.get('interval', 3600),
                'units': weather_data.get('current_units', {})
            }
            
            # Add city name if available
            if self.config.get('city'):
                message['location']['city'] = self.config['city']
            
            await self.message_callback(message)
            
            self.last_poll = time.time()
            self.consecutive_failures = 0
            
            logger.debug("Weather poll successful",
                        temperature=current.get('temperature_2m'),
                        humidity=current.get('relative_humidity_2m'),
                        weather_code=current.get('weather_code'))
            
        except httpx.HTTPStatusError as e:
            self.consecutive_failures += 1
            logger.error("Weather API HTTP error",
                        status_code=e.response.status_code,
                        error=str(e), failures=self.consecutive_failures)
            
            # Create error message
            await self._send_error_message(f"HTTP {e.response.status_code}: {str(e)}")
            
        except httpx.RequestError as e:
            self.consecutive_failures += 1
            logger.error("Weather API request error",
                        error=str(e), failures=self.consecutive_failures)
            
            await self._send_error_message(f"Request error: {str(e)}")
            
        except Exception as e:
            self.consecutive_failures += 1
            logger.error("Error polling weather data",
                        error=str(e), failures=self.consecutive_failures)
            
            await self._send_error_message(f"Polling error: {str(e)}")
    
    async def _send_error_message(self, error: str):
        """Send an error message through the callback."""
        try:
            error_message = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'type': 'weather_error',
                'source': 'open-meteo',
                'error': error,
                'consecutive_failures': self.consecutive_failures,
                'location': {
                    'latitude': self.coordinates[0] if self.coordinates else None,
                    'longitude': self.coordinates[1] if self.coordinates else None
                }
            }
            
            if self.config.get('city'):
                error_message['location']['city'] = self.config['city']
            
            await self.message_callback(error_message)
            
        except Exception as callback_error:
            logger.error("Error sending weather error message",
                        error=str(callback_error))
    
    @staticmethod
    def _get_weather_description(code: int) -> str:
        """Get weather description from WMO weather code."""
        descriptions = {
            0: "Clear sky",
            1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Fog", 48: "Depositing rime fog",
            51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
            56: "Light freezing drizzle", 57: "Dense freezing drizzle",
            61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
            66: "Light freezing rain", 67: "Heavy freezing rain",
            71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
            77: "Snow grains",
            80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
            85: "Slight snow showers", 86: "Heavy snow showers",
            95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail"
        }
        return descriptions.get(code, f"Unknown weather code: {code}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get status information about the weather poller."""
        return {
            'enabled': self.config.get('enabled', False),
            'running': self.running,
            'coordinates': self.coordinates,
            'city': self.config.get('city'),
            'last_poll': self.last_poll,
            'consecutive_failures': self.consecutive_failures,
            'is_healthy': self.consecutive_failures < self.max_failures,
            'interval': self.config.get('interval', 3600),
            'next_poll': self.last_poll + self.config.get('interval', 3600) if self.last_poll > 0 else None
        }


# Factory function for creating weather poller
def create_weather_poller(config: Dict[str, Any], message_callback: Callable) -> WeatherPoller:
    """Create a weather poller instance."""
    return WeatherPoller(config, message_callback)