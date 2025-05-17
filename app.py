from flask import Flask, render_template, request, send_file, url_for, redirect, jsonify, send_from_directory
import os
import uuid
import re
import subprocess
import shutil
import logging
import threading
import time

# Set up logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("app.log"),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', template_folder='templates')

@app.route('/sw.js')
def serve_sw():
    return app.send_static_file('sw.js')

# Create a temporary directory for downloads if it doesn't exist
TEMP_DIR = "temp_downloads"
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# Use system-installed yt-dlp (Linux version)
YT_DLP_CMD = "yt-dlp"

# Proxy configuration (set to None if not using a proxy)
PROXY = os.environ.get('YT_DLP_PROXY', None)  # Load from environment variable, or set to None

# Cookies file path
COOKIES_FILE = "cookies.txt"

# Store download progress and status
download_status = {}

def sanitize_filename(title):
    """Remove invalid characters from filename"""
    return re.sub(r'[\\/*?:"<>|]', "", title)

def validate_cookies_file():
    """Check if cookies file exists and is valid"""
    if not os.path.exists(COOKIES_FILE):
        logger.warning(f"Cookies file {COOKIES_FILE} not found")
        return False
    with open(COOKIES_FILE, 'r') as f:
        content = f.read()
        if 'youtube.com' not in content and 'google.com' not in content:
            logger.warning(f"Cookies file {COOKIES_FILE} does not contain YouTube/Google cookies")
            return False
    logger.info(f"Valid cookies file found: {COOKIES_FILE}")
    return True

def download_with_yt_dlp(youtube_url, download_id):
    """Download audio using system yt-dlp"""
    try:
        # Generate a unique filename base (without extension)
        file_id = str(uuid.uuid4())
        output_template = os.path.join(TEMP_DIR, f"{file_id}.%(ext)s")

        # Initialize progress tracking
        download_status[download_id] = {
            'status': 'downloading',
            'progress': 0,
            'message': 'Starting download...',
            'filename': None
        }

        # Check cookies file
        use_cookies = validate_cookies_file()
        if not use_cookies:
            logger.warning("Proceeding without cookies due to invalid or missing cookies file")

        # Use yt-dlp to download the audio
        command = [
            YT_DLP_CMD,
            '-x',  # Extract audio
            '--audio-format', 'mp3',
            '--audio-quality', '0',  # Best quality
            '--newline',  # Get progress updates per line
            '--progress',  # Show progress
            '-o', output_template,
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',  # Modern user agent
        ]

        # Add cookies if valid
        if use_cookies:
            command.extend(['--cookies', COOKIES_FILE])
            logger.info(f"Using cookies file: {COOKIES_FILE}")

        # Add proxy if configured
        if PROXY:
            command.extend(['--proxy', PROXY])
            logger.info(f"Using proxy: {PROXY}")

        command.append(youtube_url)
        logger.info(f"Running yt-dlp command: {' '.join(command)}")

        # Run the command
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            universal_newlines=True,
            bufsize=1
        )

        # Process output in real-time
        stderr_output = []
        for line in process.stdout:
            line = line.strip()
            logger.debug(f"yt-dlp stdout: {line}")
            # Parse progress updates
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
            # Collect stderr in real-time
            if process.stderr:
                stderr_line = process.stderr.readline().strip()
                if stderr_line:
                    stderr_output.append(stderr_line)

        # Wait for process to complete
        return_code = process.wait()
        if return_code != 0:
            error = '\n'.join(stderr_output) if stderr_output else "Unknown error"
            logger.error(f"yt-dlp failed with return code {return_code}")
            logger.error(f"yt-dlp stderr: {error}")
            if "Sign in to confirm" in error:
                download_status[download_id] = {
                    'status': 'error',
                    'message': "This video requires authentication. Please ensure a valid cookies file is provided or try a different video."
                }
            elif "Proxy" in error or "Connection" in error:
                download_status[download_id] = {
                    'status': 'error',
                    'message': f"Proxy error: {error}. Please check proxy settings or disable the proxy."
                }
            else:
                download_status[download_id] = {
                    'status': 'error',
                    'message': f"Download failed: {error}"
                }
            return None

        # Find the output file (should be the only file starting with file_id)
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

        # Get the video title from yt-dlp
        title_command = [YT_DLP_CMD, '--get-title']
        if use_cookies:
            title_command.extend(['--cookies', COOKIES_FILE])
        if PROXY:
            title_command.extend(['--proxy', PROXY])
        title_command.append(youtube_url)
        title_result = subprocess.run(title_command,
                                     capture_output=True,
                                     text=True)
        if title_result.returncode == 0:
            video_title = sanitize_filename(title_result.stdout.strip())
            # Rename the file to include the video title
            mp3_file = os.path.join(TEMP_DIR, f"{video_title}.mp3")
            shutil.move(output_file, mp3_file)
            download_status[download_id] = {
                'status': 'completed',
                'progress': 100,
                'message': 'Download complete!',
                'filename': f"{video_title}.mp3"
            }
            return video_title
        else:
            # If we can't get the title, just use the file_id
            filename = os.path.basename(output_file).split('.')[0] + '.mp3'
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

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        youtube_url = request.form.get('youtube_url')
        if not youtube_url:
            return render_template('index.html', error="Please enter a YouTube URL")

        try:
            subprocess.run([YT_DLP_CMD, '--version'],
                          check=True,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
            logger.info("Using system yt-dlp for download")
            download_id = str(uuid.uuid4())
            thread = threading.Thread(
                target=download_with_yt_dlp,
                args=(youtube_url, download_id)
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

def cleanup_temp_files():
    """Clean up old files in temp directory"""
    try:
        for file in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, file)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    logger.info(f"Cleaned up temp file: {file_path}")
            except Exception as e:
                logger.error(f"Error cleaning up file {file_path}: {e}")
    except Exception as e:
        logger.error(f"Error cleaning up temp directory: {e}")

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

    # Check cookies file at startup
    if not validate_cookies_file():
        logger.error(f"Invalid or missing cookies file: {COOKIES_FILE}. Downloads may fail for restricted videos.")

    # Register cleanup function
    import atexit
    atexit.register(cleanup_temp_files)

    app.run(host='0.0.0.0', port=5001, debug=True)
