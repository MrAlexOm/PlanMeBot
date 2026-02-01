import requests
import config

def get_weather(city, date_str):
    try:
        # 1. Получаем координаты города (Lat/Lon)
        geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city}&limit=1&appid={config.WEATHER_KEY}"
        geo_res = requests.get(geo_url).json()
        
        if not geo_res:
            return "City not found"
        
        lat = geo_res[0]['lat']
        lon = geo_res[0]['lon']

        # 2. Получаем текущую погоду
        w_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={config.WEATHER_KEY}&units=metric"
        w_res = requests.get(w_url).json()
        temp = w_res['main']['temp']
        desc = w_res['weather'][0]['description']

        # 3. Получаем качество воздуха (AQI)
        air_url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={config.WEATHER_KEY}"
        a_res = requests.get(air_url).json()
        aqi = a_res['list'][0]['main']['aqi']

        # Расшифровка индекса AQI
        aqi_map = {
            1: "Good (🍃)",
            2: "Fair (🌤)",
            3: "Moderate (😷)",
            4: "Poor (🌫)",
            5: "Very Poor (🚨)"
        }
        air_status = aqi_map.get(aqi, "Unknown")

        # Возвращаем красивую строку
        return f"🌡 {temp}°C, {desc}\n🌬 Air Quality: {air_status}"

    except Exception as e:
        print(f"Weather Error: {e}")
        return "Weather/Air info unavailable"