# Use an official Python image as the base
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app code
COPY . .

# Expose Flask default port
EXPOSE 7078

# Set environment variables with defaults (can be overridden at runtime)
ENV FLASK_APP=server.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=7078
ENV ENABLE_PHOTO_CACHE=False

# Note: UNSPLASH_ACCESS_KEY is not given a default because it's optional

# Start Flask in development mode
CMD ["flask", "run"]
