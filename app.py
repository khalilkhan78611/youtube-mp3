from flask import Flask, render_template, request, send_file, jsonify
from pytube.exceptions import RegexMatchError, VideoUnavailable
import os
import uuid
import re
import subprocess
import shutil
import logging
import yt_dlp
import threading
import time
import atexit

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', template_folder='templates')

# Create temporary directory for downloads
TEMP_DIR = "temp_downloads"
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# Dictionary to store download status
download_status = {}

def sanitize_filename(title):
    """Sanitize filename by removing invalid characters."""
    return re.sub(r'[\\/*?:"<>|]', "", title)

def cleanup_old_files():
    """Delete temporary files older than 1 hour."""
    try:
        for file in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, file)
            if os.path.getmtime(file_path) < time.time() - 3600:  # 1 hour
                os.remove(file_path)
                logger.info(f"Deleted old file: {file}")
    except Exception as e:
        logger.error(f"Error cleaning up old files: {str(e)}")

def download_with_yt_dlp(youtube_url, download_id):
    """Download YouTube audio as MP3 using yt_dlp."""
    try:
        download_status[download_id] = {"status": "downloading", "message": "Download in progress..."}
        
        file_id = str(uuid.uuid4())
        output_template = os.path.join(TEMP_DIR, f"{file_id}.%(ext)s")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': False,
            'no_warnings': False,
            'logger': logger,
            'progress_hooks': [lambda d: update_progress(d, download_id)],
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(youtube_url, download=True)
            video_title = sanitize_filename(info_dict.get('title', file_id))
            
            output_file = None
            for file in os.listdir(TEMP_DIR):
                if file.startswith(file_id):
                    output_file = os.path.join(TEMP_DIR, file)
                    break
            
            if not output_file:
                raise Exception("Could not find downloaded file")
            
            # Append download_id to avoid filename conflicts
            mp3_file = os.path.join(TEMP_DIR, f"{video_title}_{download_id}.mp3")
            shutil.move(output_file, mp3_file)
            
            download_status[download_id] = {
                "status": "completed",
                "filename": f"{video_title}_{download_id}.mp3",
                "title": video_title
            }
            
    except Exception as e:
        logger.error(f"Error in download_with_yt_dlp: {str(e)}")
        download_status[download_id] = {"status": "error", "message": str(e)}
        raise

def update_progress(d, download_id):
    """Update download progress in download_status."""
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', '0%').strip()
        speed = d.get('_speed_str', 'N/A').strip()
        eta = d.get('_eta_str', 'N/A').strip()
        message = f"Downloading: {percent} | Speed: {speed} | ETA: {eta}"
        download_status[download_id] = {"status": "downloading", "message": message}

@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')

@app.route('/start_download', methods=['POST'])
def start_download():
    """Start a YouTube audio download."""
    youtube_url = request.form.get('youtube_url')
    if not youtube_url:
        return jsonify({"error": "Please enter a YouTube URL"}), 400
    
    download_id = str(uuid.uuid4())
    download_status[download_id] = {"status": "starting", "message": "Preparing download..."}
    
    threading.Thread(target=download_with_yt_dlp, args=(youtube_url, download_id)).start()
    
    return jsonify({"download_id": download_id})

@app.route('/check_status/<download_id>')
def check_status(download_id):
    """Check the status of a download."""
    status = download_status.get(download_id, {"status": "unknown", "message": "Download ID not found"})
    return jsonify(status)

@app.route('/download/<filename>')
def download(filename):
    """Serve the downloaded MP3 file to the browser."""
    mp3_path = os.path.join(TEMP_DIR, filename)
    if not os.path.exists(mp3_path):
        return jsonify({"error": "File not found"}), 404
    
    try:
        response = send_file(
            mp3_path,
            as_attachment=True,
            download_name=filename,
            mimetype='audio/mpeg'
        )
        
        @response.call_on_close
        def cleanup():
            try:
                os.remove(mp3_path)
                logger.info(f"Cleaned up file: {filename}")
            except Exception as e:
                logger.error(f"Error cleaning up file {filename}: {str(e)}")
        
        return response
    except Exception as e:
        logger.error(f"Error sending file {filename}: {str(e)}")
        return jsonify({"error": "Error downloading file"}), 500

@app.route('/about')
def about():
    """Render the about page."""
    return render_template('about.html')

@app.route('/health')
def health():
    """Health check endpoint."""
    return {"status": "healthy"}, 200

# Schedule cleanup of old files on exit
atexit.register(cleanup_old_files)

if __name__ == '__main__':
    logger.info(f"Current directory: {os.getcwd()}")
    try:
        subprocess.run(['ffmpeg', '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("ffmpeg is available")
    except Exception as e:
        logger.error("ffmpeg is not available. Install with: sudo apt install ffmpeg")
    
    # Run cleanup periodically in a background thread
    def periodic_cleanup():
        while True:
            cleanup_old_files()
            time.sleep(600)  # Run every 10 minutes
    
    threading.Thread(target=periodic_cleanup, daemon=True).start()
    
    app.run(host='0.0.0.0', port=5000, debug=True)
