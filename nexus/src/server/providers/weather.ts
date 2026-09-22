import type { ModuleFeed, SkyCondition, WeatherData } from '@/modules/types';

/**
 * Weather, from Open-Meteo.
 *
 * No API key, no attribution requirement, no rate limit worth worrying about.
 * The important part downstream is `condition`: the 3D environment actually
 * changes weather to match, so this mapping is not cosmetic metadata - it is
 * the instruction that makes it rain in the room.
 */

const ENDPOINT = 'https://api.open-meteo.com/v1/forecast';

/** WMO 4677 weather codes, collapsed to what the renderer can express. */
function toCondition(code: number): SkyCondition {
  if (code === 0) return 'clear';
  if (code <= 3) return 'cloud';
  if (code === 45 || code === 48) return 'fog';
  if (code >= 51 && code <= 67) return 'rain';
  if (code >= 71 && code <= 77) return 'snow';
  if (code >= 80 && code <= 82) return 'rain';
  if (code === 85 || code === 86) return 'snow';
  if (code >= 95) return 'storm';
  return 'cloud';
}

const DESCRIPTIONS: Record<number, string> = {
  0: 'Clear sky',
  1: 'Mainly clear',
  2: 'Partly cloudy',
  3: 'Overcast',
  45: 'Fog',
  48: 'Depositing rime fog',
  51: 'Light drizzle',
  53: 'Drizzle',
  55: 'Dense drizzle',
  61: 'Slight rain',
  63: 'Rain',
  65: 'Heavy rain',
  71: 'Slight snow',
  73: 'Snow',
  75: 'Heavy snow',
  80: 'Rain showers',
  81: 'Rain showers',
  82: 'Violent rain showers',
  95: 'Thunderstorm',
  96: 'Thunderstorm with hail',
  99: 'Thunderstorm with heavy hail',
};

interface OpenMeteo {
  timezone: string;
  current: {
    temperature_2m: number;
    apparent_temperature: number;
    relative_humidity_2m: number;
    precipitation: number;
    weather_code: number;
    wind_speed_10m: number;
    cloud_cover: number;
    surface_pressure: number;
    is_day: number;
  };
  hourly: { time: string[]; temperature_2m: number[]; precipitation: number[] };
  daily: {
    time: string[];
    weather_code: number[];
    temperature_2m_max: number[];
    temperature_2m_min: number[];
  };
}

export async function fetchWeather(
  params: URLSearchParams,
  signal: AbortSignal,
): Promise<ModuleFeed<WeatherData>> {
  // Browser geolocation when the user granted it, env fallback otherwise.
  const lat = params.get('lat') ?? process.env.NEXUS_LAT ?? '48.8566';
  const lon = params.get('lon') ?? process.env.NEXUS_LON ?? '2.3522';

  const url = new URL(ENDPOINT);
  url.searchParams.set('latitude', lat);
  url.searchParams.set('longitude', lon);
  url.searchParams.set(
    'current',
    'temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,cloud_cover,surface_pressure,is_day',
  );
  url.searchParams.set('hourly', 'temperature_2m,precipitation');
  url.searchParams.set('daily', 'weather_code,temperature_2m_max,temperature_2m_min');
  url.searchParams.set('forecast_days', '5');
  url.searchParams.set('timezone', 'auto');

  const response = await fetch(url, { signal, next: { revalidate: 300 } });
  if (!response.ok) throw new Error(`Open-Meteo returned ${response.status}`);
  const raw = (await response.json()) as OpenMeteo;

  const now = Date.now();
  const hourly = raw.hourly.time
    .map((t, i) => ({ t, temp: raw.hourly.temperature_2m[i]!, precip: raw.hourly.precipitation[i]! }))
    // Only the hours still ahead of us; a forecast of the past is clutter.
    .filter((h) => new Date(h.t).getTime() >= now - 3600_000)
    .slice(0, 24);

  const daily = raw.daily.time.map((day, i) => ({
    day,
    min: raw.daily.temperature_2m_min[i]!,
    max: raw.daily.temperature_2m_max[i]!,
    condition: toCondition(raw.daily.weather_code[i]!),
  }));

  const code = raw.current.weather_code;

  return {
    status: 'live',
    error: null,
    fetchedAt: now,
    source: 'Open-Meteo',
    data: {
      place: params.get('place') ?? raw.timezone.split('/').pop()?.replace(/_/g, ' ') ?? 'Local',
      temperature: raw.current.temperature_2m,
      feelsLike: raw.current.apparent_temperature,
      humidity: raw.current.relative_humidity_2m,
      wind: raw.current.wind_speed_10m,
      pressure: raw.current.surface_pressure,
      cloudCover: raw.current.cloud_cover,
      precipitation: raw.current.precipitation,
      isDay: raw.current.is_day === 1,
      condition: toCondition(code),
      description: DESCRIPTIONS[code] ?? 'Unknown',
      hourly,
      daily,
    },
  };
}
