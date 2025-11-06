from dotenv import load_dotenv
import os
import threading
import requests
from flask import Flask, request, jsonify, Response
from typing import Dict, Tuple, FrozenSet, Any
import logging

# Load environment variables from .env file
load_dotenv()

# Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global cache toggle
ENABLE_PHOTO_CACHE = os.getenv("ENABLE_PHOTO_CACHE", "").lower() in {"1", "true", "yes"}

# Global cache + lock
cache_lock = threading.Lock()
photo_cache: Dict[Tuple[str, FrozenSet[Tuple[str, Any]]], Tuple[bytes, str]] = {}

# Provider configurations
PROVIDER_CONFIGS = {
    'unsplash': {
        'api_url': 'https://api.unsplash.com/photos/random',
        'headers': {
            'Authorization': f'Client-ID {os.getenv("UNSPLASH_ACCESS_KEY")}'
        },
        'body_params': {
            'orientation': 'landscape',
            'w': '1920',
            'h': '1080'
        }
    },
    'lorem_picsum': {
        'api_url': 'https://picsum.photos/1920/1080',
        'headers': {},
        'body_params': {}
    }
}


def _build_request_params(provider_cfg: dict, overrides: dict) -> dict:
    """Build request parameters for a provider, applying overrides and theme.

    Args:
        provider_cfg (dict): Provider-specific configuration dictionary.
        overrides (dict): User-supplied query/body parameter overrides.

    Returns:
        dict: Final merged request parameters for the API call.
    """
    params = provider_cfg['body_params'].copy()
    params.update(overrides)
    theme = overrides.get('theme')
    if theme:
        params['query'] = theme
    return params


def _fetch_from_provider(provider_cfg: dict, params: dict) -> tuple[bytes, str]:
    """Perform a network request to a photo provider.

    Args:
        provider_cfg (dict): Provider configuration dictionary.
        params (dict): Request parameters to pass to the API.

    Returns:
        tuple[bytes, str]: Tuple of (photo_binary_data, photo_mime_type).

    Raises:
        requests.RequestException: If the HTTP request fails.
    """
    response = requests.get(
        provider_cfg['api_url'],
        headers=provider_cfg['headers'],
        params=params,
        timeout=10
    )
    response.raise_for_status()
    # photo_data = response.content
    photo_data = response.json()
    photo_url = photo_data['urls']['full']
    img_resp = requests.get(photo_url)
    img_resp.raise_for_status()
    photo_bytes = img_resp.content
    mime_type = img_resp.headers.get('Content-Type', 'image/jpeg')
    logger.info(f"Fetched photo: {len(photo_bytes)} bytes, MIME type: {mime_type}")
    return photo_bytes, mime_type


def _get_from_cache(provider: str, overrides: dict) -> tuple[bytes, str] | None:
    """Retrieve a cached photo if available.

    Args:
        provider (str): Provider key (e.g., 'unsplash', 'lorem_picsum').
        overrides (dict): Query parameter overrides used as cache key.

    Returns:
        tuple[bytes, str] | None: Cached (photo_binary_data, photo_mime_type)
            if present, otherwise None.
    """
    if not ENABLE_PHOTO_CACHE:
        return None
    cache_key = (provider, frozenset(overrides.items()))
    with cache_lock:
        return photo_cache.get(cache_key)


def _store_in_cache(provider: str, overrides: dict, value: tuple[bytes, str]):
    """Store a photo result in the cache.

    Args:
        provider (str): Provider key.
        overrides (dict): Query parameter overrides used as cache key.
        value (tuple[bytes, str]): Tuple of (photo_binary_data, photo_mime_type).
    """
    if not ENABLE_PHOTO_CACHE:
        return
    cache_key = (provider, frozenset(overrides.items()))
    with cache_lock:
        photo_cache[cache_key] = value


def fetch_photo(provider: str, **overrides) -> tuple[bytes, str]:
    """Fetch a photo from a provider with optional caching.

    Args:
        provider (str): The photo provider key (e.g., 'unsplash', 'lorem_picsum').
        **overrides: Arbitrary keyword arguments to override default provider
            parameters (e.g., theme='nature').

    Returns:
        tuple[bytes, str]: (photo_binary_data, photo_mime_type)

    Raises:
        ValueError: If the provider is unknown.
        RuntimeError: If fetching the photo from the provider fails.
    """
    provider_cfg = PROVIDER_CONFIGS.get(provider)
    if not provider_cfg:
        raise ValueError(f"Unknown provider: {provider}")

    params = _build_request_params(provider_cfg, overrides)

    cached = _get_from_cache(provider, overrides)
    if cached:
        logger.info(f"Cache hit for {provider} {overrides}")
        return cached

    try:
        logger.info(f"Cache miss for {provider} {overrides}")
        photo_data, mime_type = _fetch_from_provider(provider_cfg, params)
        _store_in_cache(provider, overrides, (photo_data, mime_type))
        return photo_data, mime_type
    except requests.RequestException as e:
        logger.error(f"Error fetching from provider '{provider}': {e}")
        raise RuntimeError(f"Failed to fetch photo from {provider}") from e


# --- Flask Routes ---

@app.route("/")
def index():
    """Return JSON describing all available routes.

    Returns:
        Response: JSON response listing all routes and their descriptions.
    """
    routes = [
        {"route": "/", "methods": ["GET"], "description": "List all routes"},
        {"route": "/picture/<provider>", "methods": ["GET"], "description": "Fetch picture from provider with optional query params"}
    ]
    return jsonify(routes)


@app.route("/picture/<provider>", methods=["GET"])
def picture(provider):
    """Fetch a picture from a specific provider.

    Query parameters are treated as overrides to the provider configuration.

    Args:
        provider (str): Provider key from the URL path.

    Returns:
        Response: Flask Response containing the image data with correct MIME type.

    HTTP Status Codes:
        200: Successfully retrieved image.
        400: Invalid provider requested.
        502: Failed to fetch image from provider.
        500: Unexpected internal error.
    """
    overrides = request.args.to_dict()
    try:
        photo_data, mime_type = fetch_photo(provider, **overrides)
        return Response(photo_data, mimetype=mime_type)
    except ValueError as ve:
        logger.warning(f"Invalid provider requested: {ve}")
        return jsonify({"error": str(ve)}), 400
    except RuntimeError as re:
        logger.error(f"Failed to fetch photo: {re}")
        return jsonify({"error": str(re)}), 502
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return jsonify({"error": "Internal server error"}), 500


# --- Run Flask app ---
if __name__ == "__main__":
    app.run(debug=True, host='127.0.0.1', port=7078)
