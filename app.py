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

# Create temporary directory for downloads
TEMP_DIR = "temp_downloads"
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# Dictionary to store download status
download_status = {}

def sanitize_filename(title):
    return re.sub(r'[\\/*?:"<>|]', "", title)

def download_with_yt_dlp(youtube_url, download_id):
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

def update_progress(d, download_id):
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', '0%')
        speed = d.get('_speed_str', 'N/A')
        eta = d.get('_eta_str', 'N/A')
        message = f"Downloading: {percent} | Speed: {speed} | ETA: {eta}"
        download_status[download_id] = {"status": "downloading", "message": message}

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
    
    threading.Thread(target=download_with_yt_dlp, args=(youtube_url, download_id)).start()
    
    return jsonify({"download_id": download_id})

@app.route('/check_status/<download_id>')
def check_status(download_id):
    status = download_status.get(download_id, {"status": "unknown", "message": "Download ID not found"})
    return jsonify(status)

@app.route('/download/<filename>')
def download(filename):
    mp3_path = os.path.join(TEMP_DIR, filename)
    if os.path.exists(mp3_path):
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
            return render_template('index.html', error="Error downloading file")
    return render_template('index.html', error="File not found")

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/health')
def health():
    return {"status": "healthy"}, 200

if __name__ == '__main__':
    logger.info(f"Current directory: {os.getcwd()}")
    try:
        subprocess.run(['ffmpeg', '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("ffmpeg is available")
    except Exception as e:
        logger.error("ffmpeg is not available. Install with: sudo apt install ffmpeg")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
