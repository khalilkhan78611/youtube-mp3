FROM python:3.9-slim

# Install curl and ffmpeg (required for yt_dlp)
RUN apt-get update && apt-get install -y curl ffmpeg mc && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .
RUN cp sw.js  /app/static/
RUN cp sw.js /
# Copy favicon files to the static root directory
COPY favicon-96x96.png /app/
COPY favicon.svg /app/
COPY favicon.ico /app/
COPY apple-touch-icon.png /app/
COPY site.webmanifest /app/
# Expose port 5001 (your app's port)
RUN chmod 700 temp_downloads config && \
    chmod 600 config/cookies.txt || true
EXPOSE 5001

# Define health check for Coolify
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl --fail http://localhost:5001/health || exit 1

# Run the app with gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "2", "--threads", "4", "app:app"]
