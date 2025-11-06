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


def _get_provider_configs() -> dict[str, dict]:
    return {
        'unsplash': {
            'api_url': 'https://api.unsplash.com/photos/random',
            'headers': {
                'Authorization': f'Client-ID {os.getenv("UNSPLASH_ACCESS_KEY")}'
            },
            'body_params': {
                'orientation': 'landscape',
                'w': 1920,
                'h': 1080
            },
            'pre': _unsplash_pre,
            'post': _unsplash_post
        },
        'lorem_picsum': {
            'api_url': 'https://picsum.photos/1920/1080',
            'headers': {},
            'body_params': {
                'w': 1920,
                'h': 1080
            },
            'pre': _lorem_picsum_pre,
            'post': _lorem_picsum_post
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


def build_picsum_url(width: int = 1920, height: int = 1080,
                     grayscale: bool = False, blur: int | None = None, webp: bool = False) -> str:
    """
    Build a Lorem Picsum image URL with optional width, height, grayscale, blur, and webp format.
    """
    ext = ".webp" if webp else ""
    url = f"https://picsum.photos/{width}/{height}{ext}"

    query_parts = []
    if grayscale:
        query_parts.append("grayscale")
    if blur:
        query_parts.append(f"blur={blur}")

    if query_parts:
        url += "?" + "&".join(query_parts)

    return url


# ---- Unsplash ----
def _unsplash_pre(url: str, params: dict) -> tuple[str, dict]:
    """No-op for Unsplash pre-processing."""
    return url, params


def _unsplash_post(resp: requests.Response, params: dict) -> tuple[bytes, str]:
    """Extract the photo URL from Unsplash JSON and fetch its bytes."""
    photo_url = resp.json()['urls']['full']
    img_resp = requests.get(photo_url, timeout=10)
    img_resp.raise_for_status()
    return img_resp.content, img_resp.headers.get("Content-Type", "image/jpeg")


# ---- Lorem Picsum ----
def _lorem_picsum_pre(url: str, params: dict) -> tuple[str, dict]:
    """
    Build Picsum URL path and a brand-new query-params dict.

    - width/height -> path (defaults 1920x1080)
    - webp -> path suffix if present
    - grayscale -> presence-only flag added to query ('' value)
    - blur -> presence or numeric value added to query ('' if no value)
    - NO other keys from the input params are copied into the output
    """
    # read-only access to the input
    w = params.get("w", 1920)
    h = params.get("h", 1080)
    ext = ".webp" if "webp" in params else ""
    grayscale_present = "grayscale" in params
    blur_present = "blur" in params
    blur_val = params.get("blur")  # may be '', '3', or None

    final_url = f"https://picsum.photos/{w}/{h}{ext}"

    # build a brand-new output dict — do NOT reuse or re-insert unrelated input keys
    query_params: dict = {}
    if grayscale_present:
        query_params["grayscale"] = ""           # ?grayscale
    if blur_present:
        query_params["blur"] = blur_val or ""    # ?blur  or ?blur=3

    logger.info("Picsum URL: %s  params: %s", final_url, query_params)
    return final_url, query_params


def _lorem_picsum_post(resp: requests.Response, params: dict) -> tuple[bytes, str]:
    """No-op post-processing for Picsum."""
    return resp.content, resp.headers.get("Content-Type", "image/jpeg")


def _fetch_from_provider(provider_cfg: dict, params: dict) -> tuple[bytes, str]:
    """Fetch a photo from any provider using pre- and post-processing hooks."""
    pre_fn = provider_cfg.get("pre", lambda url, p: (url, p))
    post_fn = provider_cfg.get("post", lambda resp, _: (resp.content, resp.headers.get("Content-Type", "image/jpeg")))

    # Pre-processing
    url, processed_params = pre_fn(provider_cfg["api_url"], params.copy())

    # Request
    resp = requests.get(url, headers=provider_cfg.get("headers"), params=processed_params, timeout=10)
    resp.raise_for_status()

    # Post-processing
    return post_fn(resp, processed_params)


def _fetch_from_provider_old(provider_cfg: dict, params: dict) -> tuple[bytes, str]:
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
    provider_cfg = _get_provider_configs().get(provider)
    logger.debug(f"Provider config for '{provider}': {provider_cfg}")
    if not provider_cfg:
        raise ValueError(f"Unknown provider: {provider}")

    logger.debug(f"Fetching photo from provider '{provider}' with overrides: {overrides}")
    params = _build_request_params(provider_cfg, overrides)

    logger.debug(f"Built request params for provider '{provider}': {params}")
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
    logger.info(f"Received request for provider '{provider}' with overrides: {overrides}")
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
