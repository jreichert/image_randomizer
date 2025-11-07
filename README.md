````markdown
# Flask Wallpaper API

A simple Flask API that serves random wallpapers from multiple providers (Unsplash and Lorem Picsum). This can be useful for applications
such as Lively Wallpaper that require a static url to fetch wallpapers. If desired, caching can be
enabled to continue serving the same image for some length of time before fetching a new one (and/or to
prevent excessive network usage).

---

## 🚀 Installation

### Using Docker

```bash
# Build the image
docker build -t wallpaper-api .

# Run the container (with optional environment variables)
docker run -p 7078:7078 \
    -e ENABLE_CACHE=True \
    -e UNSPLASH_ACCESS_KEY=your_unsplash_key \
    wallpaper-api
```

The API will be accessible at: `http://localhost:7078`.

### Running the Application Locally

```bash
# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables and run
export FLASK_APP=server.py
export ENABLE_CACHE=True
export UNSPLASH_ACCESS_KEY=your_unsplash_key
flask run
```

Environment variables can also be added to a .env file in the project root.

---

## ⚙️ Environment Variables

| Variable              | Description                   | Required               | Default |
| --------------------- | ----------------------------- | ---------------------- | ------- |
| `UNSPLASH_ACCESS_KEY` | API key for Unsplash provider | Only if using Unsplash | None    |
| `ENABLE_CACHE`        | Toggle caching of images      | No                     | `False` |

---

## 📦 Caching Behavior

- **Enabled**: Fetched images are cached per provider for faster subsequent requests.
- **Disabled**: Images are fetched fresh from the provider each request.

The cache is in-memory and per container instance.

---

## 🌐 API Endpoints

### `GET /picture/<provider>`

Fetch a random image from the specified provider. Supports query parameter overrides.

- **Providers**:

  - `unsplash`
  - `lorem_picsum`

- **Query Parameters**:

#### Unsplash

| Parameter | Description                        |
| --------- | ---------------------------------- |
| `theme`   | Search query for the type of image |

#### Lorem Picsum

| Parameter   | Description                                                            |
| ----------- | ---------------------------------------------------------------------- |
| `w`         | Width of the image (default: `1920`)                                   |
| `h`         | Height of the image (default: `1080`)                                  |
| `grayscale` | If present, image is returned in grayscale (`true` or any value)       |
| `blur`      | Blur the image (`1-10`) or just include without value for default blur |
| `webp`      | Return image in WebP format (any value will enable)                    |

**Example request:**

```http
GET /picture/lorem_picsum?w=1280&h=720&grayscale=true&blur=3
```

This will return an image from Lorem Picsum with a width of 1280, height of 720, in grayscale, and
with a blur level of 3.

---

## 📌 Notes

- Unsplash requires a valid API key added as the environment variable `UNSPLASH_ACCESS_KEY`. API
  keys are available for free by creating an account on the Unsplash Developer portal. Note that
  by default you will be limited to 50 requests per hour; if you submit your application for
  approval, this limit can be increased to 5,000 requests per hour. Lorem Picsum does **not** require a key.
- Image transformations (width, height) are only supported by Lorem Picsum.
- The API returns raw image bytes with the correct MIME type (`image/jpeg` or `image/webp`).

---

## 📝 License

MIT License
````
