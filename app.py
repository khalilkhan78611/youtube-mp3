from flask import Flask, render_template, request, send_file, url_for, redirect, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import uuid
import re
import subprocess
import shutil
import logging
import threading
import time
from urllib.parse import urlparse

# Set up logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("app.log"),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', template_folder='templates')
limiter = Limiter(app, key_func=get_remote_address, default_limits=["200 per day", "50 per hour"])

@app.route('/sw.js')
def serve_sw():
    return app.send_static_file('sw.js')

# Create directories
TEMP_DIR = "temp_downloads"
CONFIG_DIR = "config"
for directory in [TEMP_DIR, CONFIG_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)
        os.chmod(directory, 0o700)  # Restrict directory access

# Use system-installed yt-dlp
YT_DLP_CMD = "yt-dlp"

# Store download progress and status
download_status = {}

def sanitize_filename(title):
    """Remove invalid characters from filename"""
    return re.sub(r'[\\/*?:"<>|]', "", title)

def is_valid_youtube_url(url):
    """Validate YouTube URL"""
    try:
        parsed = urlparse(url)
        return parsed.netloc in ('www.youtube.com', 'youtu.be', 'youtube.com')
    except Exception:
        return False

def download_with_yt_dlp(youtube_url, download_id, cookies_path=None):
    """Download audio using system yt-dlp with cookies.txt"""
    try:
        file_id = str(uuid.uuid4())
        output_template = os.path.join(TEMP_DIR, f"{file_id}.%(ext)s")

        download_status[download_id] = {
            'status': 'downloading',
            'progress': 0,
            'message': 'Starting download...',
            'filename': None
        }

        # Initialize yt-dlp command
        command = [
            YT_DLP_CMD,
            '-x',  # Extract audio
            '--audio-format', 'mp3',
            '--audio-quality', '0',  # Best quality
            '--newline',  # Get progress updates
            '--progress',  # Show progress
            '-o', output_template,
            youtube_url
        ]

        # Use user-uploaded cookies if provided, else fall back to config/cookies.txt
        # NEW: Explicitly include --cookies in the command
        static_cookies = os.path.join(CONFIG_DIR, "cookies.txt")
        if cookies_path and os.path.exists(cookies_path):
            command.extend(['--cookies', cookies_path])
            logger.info(f"Using user-uploaded cookies: {cookies_path}")
        elif os.path.exists(static_cookies):
            command.extend(['--cookies', static_cookies])
            logger.info(f"Using static cookies: {static_cookies}")
        else:
            logger.warning("No cookies.txt found; proceeding without cookies")
            download_status[download_id]['message'] = 'No cookies provided, restricted content may fail'

        logger.info(f"Running yt-dlp command: {' '.join(command)}")

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            universal_newlines=True,
            bufsize=1
        )

        for line in process.stdout:
            line = line.strip()
            logger.debug(f"yt-dlp stdout: {line}")
            if '[download]' in line:
                if 'Destination:' in line:
                    download_status[download_id]['message'] = 'Processing...'
                elif '%' in line:
                    try:
                        percent = float(line.split('%')[0].strip().split()[-1])
                        download_status[download_id]['progress'] = percent
                        download_status[download_id]['message'] = f"Downloading... {percent:.1f}%"
                    except Exception as e:
                        logger.warning(f"Failed to parse progress: {e}")

        return_code = process.wait()
        if return_code != 0:
            error = process.stderr.read()
            logger.error(f"yt-dlp failed with return code {return_code}")
            logger.error(f"yt-dlp stderr: {error}")
            download_status[download_id] = {
                'status': 'error',
                'message': f"Download failed: {error}"
            }
            return None

        output_file = None
        for file in os.listdir(TEMP_DIR):
            if file.startswith(file_id):
                output_file = os.path.join(TEMP_DIR, file)
                break

        if not output_file:
            download_status[download_id] = {
                'status': 'error',
                'message': "Could not find downloaded file"
            }
            return None

        # Fetch video title with same cookies
        title_command = [YT_DLP_CMD, '--get-title']
        if cookies_path and os.path.exists(cookies_path):
            title_command.extend(['--cookies', cookies_path])
        elif os.path.exists(static_cookies):
            title_command.extend(['--cookies', static_cookies])
        title_command.append(youtube_url)
        title_result = subprocess.run(title_command,
                                     capture_output=True,
                                     text=True)
        if title_result.returncode == 0:
            video_title = sanitize_filename(title_result.stdout.strip())
            mp3_file = os.path.join(TEMP_DIR, f"{video_title}.mp3")
            shutil.move(output_file, mp3_file)
            os.chmod(mp3_file, 0o600)  # Restrict file access
            download_status[download_id] = {
                'status': 'completed',
                'progress': 100,
                'message': 'Download complete!',
                'filename': f"{video_title}.mp3"
            }
            return video_title
        else:
            filename = os.path.basename(output_file).split('.')[0] + '.mp3'
            mp3_file = os.path.join(TEMP_DIR, filename)
            shutil.move(output_file, mp3_file)
            os.chmod(mp3_file, 0o600)
            download_status[download_id] = {
                'status': 'completed',
                'progress': 100,
                'message': 'Download complete!',
                'filename': filename
            }
            return filename

    except Exception as e:
        logger.error(f"Error in download_with_yt_dlp: {str(e)}")
        download_status[download_id] = {
            'status': 'error',
            'message': f"Error: {str(e)}"
        }
        return None
    finally:
        if cookies_path and os.path.exists(cookies_path):
            try:
                os.remove(cookies_path)
                logger.info(f"Cleaned up user-uploaded cookies: {cookies_path}")
            except Exception as e:
                logger.error(f"Error cleaning up cookies file: {e}")

@app.route('/', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def index():
    if request.method == 'POST':
        youtube_url = request.form.get('youtube_url')
        cookies_file = request.files.get('cookies_file')

        if not youtube_url:
            return render_template('index.html', error="Please enter a YouTube URL")
        if not is_valid_youtube_url(youtube_url):
            return render_template('index.html', error="Please enter a valid YouTube URL")

        try:
            subprocess.run([YT_DLP_CMD, '--version'],
                          check=True,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
            logger.info("Using system yt-dlp for download")
            download_id = str(uuid.uuid4())

            cookies_path = None
            if cookies_file and cookies_file.filename:
                cookies_filename = f"{download_id}_cookies.txt"
                cookies_path = os.path.join(TEMP_DIR, cookies_filename)
                cookies_file.save(cookies_path)
                os.chmod(cookies_path, 0o600)  # Restrict access
                logger.info(f"Saved user-uploaded cookies to {cookies_path}")

            thread = threading.Thread(
                target=download_with_yt_dlp,
                args=(youtube_url, download_id, cookies_path)
            )
            thread.start()
            return redirect(url_for('download_progress', download_id=download_id))
        except subprocess.CalledProcessError as e:
            logger.error(f"yt-dlp not available: {str(e)}")
            return render_template('index.html',
                                  error="yt-dlp is not installed. Please install it with: sudo apt install yt-dlp")
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return render_template('index.html', error=f"An error occurred: {str(e)}")

    return render_template('index.html')

@app.route('/progress/<download_id>')
def download_progress(download_id):
    if download_id not in download_status:
        return render_template('index.html', error="Invalid download ID")
    status = download_status[download_id]
    return render_template('progress.html',
                         download_id=download_id,
                         status=status)

@app.route('/api/progress/<download_id>')
def api_progress(download_id):
    if download_id not in download_status:
        return jsonify({'error': 'Invalid download ID'}), 404
    return jsonify(download_status[download_id])

@app.route('/download/<filename>')
def download(filename):
    mp3_path = os.path.join(TEMP_DIR, filename)
    if os.path.exists(mp3_path):
        try:
            response = send_file(mp3_path, as_attachment=True)
            @response.call_on_close
            def cleanup():
                try:
                    os.remove(mp3_path)
                    logger.info(f"Cleaned up file: {mp3_path}")
                except Exception as e:
                    logger.error(f"Error cleaning up file: {e}")
            return response
        except Exception as e:
            logger.error(f"Error sending file: {e}")
            return render_template('index.html', error="Error downloading file")
    else:
        return render_template('index.html', error="File not found. Please try again.")

@app.route('/about')
def about():
    return render_template('about.html')

@app.errorhandler(Exception)
def handle_error(error):
    logger.error(f"Unhandled error: {str(error)}")
    return render_template('index.html', error="An unexpected error occurred. Please try again."), 500

def cleanup_temp_files():
    """Clean up old files in temp directory"""
    try:
        for file in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, file)
            try:
                if os.path.isfile(file_path) and (file.endswith('.mp3') or file.endswith('_cookies.txt')):
                    os.remove(file_path)
                    logger.info(f"Cleaned up temp file: {file_path}")
            except Exception as e:
                logger.error(f"Error cleaning up file {file_path}: {e}")
    except Exception as e:
        logger.error(f"Error cleaning up temp directory: {e}")

# Write cookies.txt from environment variable if provided (for Coolify)
static_cookies = os.path.join(CONFIG_DIR, "cookies.txt")
cookies_content = os.environ.get('COOKIES_CONTENT')
if cookies_content and not os.path.exists(static_cookies):
    with open(static_cookies, 'w') as f:
        f.write(cookies_content)
    os.chmod(static_cookies, 0o600)
    logger.info("Created cookies.txt from COOKIES_CONTENT")

if __name__ == '__main__':
    # Check for yt-dlp at startup
    try:
        version = subprocess.run([YT_DLP_CMD, '--version'],
                               check=True,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               text=True)
        logger.info(f"Using yt-dlp version: {version.stdout.strip()}")
    except Exception as e:
        logger.error("yt-dlp not found. Please install it with: sudo apt install yt-dlp")

    # Ensure cookies.txt has correct permissions if it exists
    if os.path.exists(static_cookies):
        os.chmod(static_cookies, 0o600)
        logger.info("Set permissions for cookies.txt to 600")

    # Register cleanup function
    import atexit
    atexit.register(cleanup_temp_files)

    app.run(host='0.0.0.0', port=5001, debug=True)

# SECURITY NOTES:
# 1. config/cookies.txt is in .gitignore to avoid committing sensitive data:
#    echo "config/cookies.txt" >> .gitignore
# 2. For GitHub repo, use git-secret to encrypt cookies.txt if needed:
#    git secret init
#    git secret tell your.email@example.com
#    git secret add config/cookies.txt
#    git secret hide
# 3. For Coolify, provide cookies.txt via volume mount or COOKIES_CONTENT env var:
#    Volume: /path/to/cookies.txt -> /app/config/cookies.txt
#    Env: COOKIES_CONTENT with contents of cookies.txt
# 4. Configure web server to block access to config/ and temp_downloads/:
#    Nginx: location /config/ { deny all; return 403; }
#    Apache: <Directory "/path/to/config"> Deny from all </Directory>
# 5. Ensure directories (chmod 700) and files (chmod 600) have restrictive permissions:
#    # setup.sh
#    chmod 700 temp_downloads config
#    chmod 600 config/cookies.txt
