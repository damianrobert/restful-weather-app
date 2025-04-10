import requests
import json
import os
import redis
from dotenv import load_dotenv
from datetime import datetime
from flask import Flask, render_template, request, flash

app = Flask(__name__)
app.secret_key = os.urandom(24)
load_dotenv()

redis_client = redis.Redis(
    host = "redis-18029.c293.eu-central-1-1.ec2.redns.redis-cloud.com",
    port = 18029,
    decode_responses = True,
    username = 'default',
    password = os.getenv("REDIS_PASSWORD")
        )

def get_weather(location, api_key):

    cache_key = f"weather:{location.lower()}"
    cache_ttl_seconds = 900

    cached_data_json = redis_client.get(cache_key)

    if cached_data_json:
        print(f"Cache hit for {location} ✅")
        return json.loads(cached_data_json)

    print(f"Cache miss for {location}. Fetching fresh data...")

    base_url = f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{location}"

    params = {
        'key': api_key,
        'unitGroup': 'metric',
        'include': 'current',
        'contentType': 'json'
    }

    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        fresh_weather_data = response.json()


        if 'currentConditions' not in fresh_weather_data:
            print(f"Warning: 'currentConditions' not found in response for {location}.")
            print(f"API Response: {fresh_weather_data}")
            error_message = "Weather data format error or location not found."

            if isinstance(fresh_weather_data, dict):
                error_message = fresh_weather_data.get('message', error_message)
            elif isinstance(fresh_weather_data, str): 
                if "error" in fresh_weather_data.lower(): 
                    error_message = fresh_weather_data

        
            return {"cod": 404, "message": error_message}
        
        fresh_weather_data['cod'] = 200

        try:
            # Ensure redis_client exists and is connected before using
            if redis_client:
                redis_client.setex(
                    name=cache_key,
                    time=cache_ttl_seconds,
                    value=json.dumps(fresh_weather_data) # Store the data *with* 'cod': 200
                )
                print(f"DEBUG: Stored validated data with 'cod' in cache for {location}")
            else:
                print("WARN: Redis client not available, skipping cache store.")
        except redis.exceptions.RedisError as e:
            # Log the error but don't let caching failure break the request
            print(f"WARN: Failed to cache data for {location} in Redis: {e}")
        except Exception as e:
            print(f"WARN: An unexpected error occurred during Redis caching: {e}")

        return fresh_weather_data
    
    except requests.exceptions.HTTPError as http_err:
        error_message = f"HTTP error occurred: {http_err} - {response.text}"
        print(error_message)

        try:
            error_json = response.json()
            message = error_json.get('message', response.text)
        except json.JSONDecodeError:
            message = response.text
        return {"cod": response.status_code, "message": message or f"HTTP error {response.status_code}"}
    
    except requests.exceptions.RequestException as e:
        print(f"Request Exception: {e}")
        return {"cod": 503, "message": f"Error connecting to weather service: {e}"} # Service Unavailable code

    except json.JSONDecodeError:
        print("Error: Could not parse API response.")
        return {"cod": 500, "message": "Invalid response format from weather service."}

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return {"cod": 500, "message": f"An unexpected error occurred: {e}"}



@app.route("/", methods=['GET', 'POST'])
def index():
    weather_display_data = None

    if request.method == 'POST':
        city = request.form.get('city')
        api_key = os.getenv('VISUAL_CROSSING_API_KEY')

        if not api_key:
            flash("Server configuration error: Visual Crossing API key not found.")
            return render_template('index.html')
        
        if not city:
            flash("Please enter a location name.", "warning")
        else:
            raw_data = get_weather(city, api_key)

            if raw_data and raw_data.get('cod') == 200 and 'currentConditions' in raw_data:
                current = raw_data.get('currentConditions', {}) 
                resolved_location = raw_data.get('resolvedAddress', city)

                try:
                    weather_display_data = {
                        # Using .get() provides None if key is missing, preventing KeyErrors
                        "city_name": resolved_location,
                        "temp": current.get('temp'),
                        "feels_like": current.get('feelslike'),
                        "humidity": current.get('humidity'),
                        "description": current.get('conditions', 'N/A'), # Main condition text
                        "icon": current.get('icon', ''), # Icon code (e.g., 'partly-cloudy-day')
                        "wind_speed": current.get('windspeed'), # Check units (likely km/h with metric)
                        "pressure": current.get('pressure'),
                        "sunrise": current.get('sunrise'),
                        "sunset": current.get('sunset'),
                        # Convert epoch seconds to datetime object
                        "report_time_utc": datetime.utcfromtimestamp(current.get('datetimeEpoch', 0))
                    }
                    return render_template('weather.html', weather=weather_display_data)

                except Exception as e:
                     # Catch potential errors during data extraction/formatting
                     flash(f"Error processing weather data: {e}", "error")
                     print(f"Error during data extraction: {e}") # Log for debugging
                     # Fall through to render index.html

            else:
                # API returned an error or connection failed
                error_message = raw_data.get('message', 'Could not retrieve weather data.')
                flash(error_message, "error")

    return render_template('index.html')


if __name__ == '__main__':
    app.run(debug=True)
