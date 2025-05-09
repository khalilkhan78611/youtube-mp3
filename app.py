from flask import Flask, render_template, request, send_file, url_for, redirect, jsonify
from pytube import YouTube
from pytube.exceptions import RegexMatchError, VideoUnavailable
import os
import uuid
import re
import subprocess
import shutil
import logging
import yt_dlp
import threading

# Set up logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("app.log"),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', template_folder='templates')

# Create a temporary directory for downloads if it doesn't exist
TEMP_DIR = "temp_downloads"
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# Dictionary to store download status
download_status = {}

def sanitize_filename(title):
    """Remove invalid characters from filename"""
    return re.sub(r'[\\/*?:"<>|]', "", title)

def download_with_yt_dlp(youtube_url, download_id):
    """Download audio using yt-dlp Python package"""
    try:
        download_status[download_id] = {"status": "downloading", "message": "Download in progress..."}
        
        # Generate a unique filename base (without extension)
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
        
        logger.info(f"Attempting download with yt-dlp: {youtube_url}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(youtube_url, download=True)
            video_title = sanitize_filename(info_dict.get('title', file_id))
            
            # Find the downloaded file
            output_file = None
            for file in os.listdir(TEMP_DIR):
                if file.startswith(file_id):
                    output_file = os.path.join(TEMP_DIR, file)
                    break
            
            if not output_file:
                raise Exception("Could not find downloaded file")
            
            # Rename to include the video title
            mp3_file = os.path.join(TEMP_DIR, f"{video_title}.mp3")
            shutil.move(output_file, mp3_file)
            
            download_status[download_id] = {
                "status": "completed", 
                "filename": f"{video_title}.mp3",
                "title": video_title
            }
            
    except Exception as e:
        logger.error(f"Error in download_with_yt_dlp: {str(e)}")
        download_status[download_id] = {"status": "error", "message": str(e)}
        raise

def download_with_pytube(youtube_url, download_id):
    """Download audio using pytube as fallback"""
    try:
        download_status[download_id] = {"status": "downloading", "message": "Download in progress..."}
        
        # Create YouTube object
        yt = YouTube(youtube_url)
        
        # Get video title and sanitize for filename
        video_title = sanitize_filename(yt.title)
        logger.info(f"Processing video with pytube: {video_title}")
        
        # Get the audio stream (highest quality)
        audio_stream = yt.streams.filter(only_audio=True).order_by('abr').desc().first()
        
        if not audio_stream:
            raise Exception("No audio stream found for this video")
        
        # Download the audio file with temporary name
        temp_file = audio_stream.download(output_path=TEMP_DIR, filename=str(uuid.uuid4()))
        
        # Rename to MP3 file
        mp3_file = os.path.join(TEMP_DIR, f"{video_title}.mp3")
        shutil.move(temp_file, mp3_file)
        
        download_status[download_id] = {
            "status": "completed", 
            "filename": f"{video_title}.mp3",
            "title": video_title
        }
        
    except Exception as e:
        logger.error(f"Error in download_with_pytube: {str(e)}")
        download_status[download_id] = {"status": "error", "message": str(e)}
        raise

def update_progress(d, download_id):
    """Update progress for yt-dlp downloads"""
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', '0%')
        speed = d.get('_speed_str', 'N/A')
        eta = d.get('_eta_str', 'N/A')
        message = f"Downloading: {percent} | Speed: {speed} | ETA: {eta}"
        download_status[download_id] = {"status": "downloading", "message": message}
    elif d['status'] == 'error':
        download_status[download_id] = {"status": "error", "message": "Download failed"}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_download', methods=['POST'])
def start_download():
    youtube_url = request.form.get('youtube_url')
    if not youtube_url:
        return jsonify({"error": "Please enter a YouTube URL"}), 400
    
    download_id = str(uuid.uuid4())
    download_status[download_id] = {"status": "starting", "message": "Preparing download..."}
    
    # Start download in a separate thread
    threading.Thread(target=process_download, args=(youtube_url, download_id)).start()
    
    return jsonify({"download_id": download_id})

def process_download(youtube_url, download_id):
    try:
        # Try yt-dlp first (Python package)
        logger.info("Attempting download with yt-dlp Python package")
        download_with_yt_dlp(youtube_url, download_id)
    except Exception as e:
        logger.warning(f"yt-dlp failed, falling back to pytube: {str(e)}")
        try:
            # Fall back to pytube if yt-dlp fails
            download_with_pytube(youtube_url, download_id)
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            if isinstance(e, RegexMatchError):
                download_status[download_id] = {"status": "error", "message": "Invalid YouTube URL"}
            elif isinstance(e, VideoUnavailable):
                download_status[download_id] = {"status": "error", "message": "Video unavailable"}
            else:
                download_status[download_id] = {"status": "error", "message": str(e)}

@app.route('/check_status/<download_id>')
def check_status(download_id):
    status = download_status.get(download_id, {"status": "unknown", "message": "Download ID not found"})
    return jsonify(status)

@app.route('/download/<filename>')
def download(filename):
    mp3_path = os.path.join(TEMP_DIR, filename)
    if os.path.exists(mp3_path):
        return send_file(mp3_path, as_attachment=True)
    else:
        return render_template('index.html', error="File not found. Please try again.")

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/health')
def health():
    return {"status": "healthy"}, 200

if __name__ == '__main__':
    # Log system information
    logger.info(f"Current directory: {os.getcwd()}")
    logger.info("Starting application with yt-dlp Python package")
    
    # Check for ffmpeg (required for audio conversion)
    try:
        subprocess.run(['ffmpeg', '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("ffmpeg is available")
    except Exception as e:
        logger.error("ffmpeg is not available. Audio conversion may fail.")
        logger.error("Install ffmpeg with: sudo apt install ffmpeg")
    
    app.run(host='0.0.0.0', port=5001, debug=True)
