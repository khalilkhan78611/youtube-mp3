from flask import Flask, render_template, request, send_file, url_for, redirect
from pytube import YouTube
from pytube.exceptions import RegexMatchError, VideoUnavailable
import os
import uuid
import re
import subprocess
import shutil
import logging
import yt_dlp  # Using the Python package instead of the executable

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

def sanitize_filename(title):
    """Remove invalid characters from filename"""
    return re.sub(r'[\\/*?:"<>|]', "", title)

def download_with_yt_dlp(youtube_url):
    """Download audio using yt-dlp Python package"""
    try:
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
            
            return video_title
            
    except Exception as e:
        logger.error(f"Error in download_with_yt_dlp: {str(e)}")
        raise

def download_with_pytube(youtube_url):
    """Download audio using pytube as fallback"""
    try:
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
        
        return video_title
        
    except Exception as e:
        logger.error(f"Error in download_with_pytube: {str(e)}")
        raise

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Get the YouTube URL from the form
        youtube_url = request.form.get('youtube_url')
        
        if not youtube_url:
            return render_template('index.html', error="Please enter a YouTube URL")
        
        try:
            # Try yt-dlp first (Python package)
            logger.info("Attempting download with yt-dlp Python package")
            video_title = download_with_yt_dlp(youtube_url)
            
        except Exception as e:
            logger.warning(f"yt-dlp failed, falling back to pytube: {str(e)}")
            try:
                # Fall back to pytube if yt-dlp fails
                video_title = download_with_pytube(youtube_url)
            except Exception as e:
                logger.error(f"Error: {str(e)}")
                if isinstance(e, RegexMatchError):
                    return render_template('index.html', error="Invalid YouTube URL. Please check the URL and try again.")
                elif isinstance(e, VideoUnavailable):
                    return render_template('index.html', error="This video is unavailable. It might be private or age-restricted.")
                else:
                    return render_template('index.html', error=f"An error occurred: {str(e)}")
        
        # Redirect to the download page
        return redirect(url_for('download', filename=f"{video_title}.mp3"))
    
    return render_template('index.html')

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
    
    app.run(host='0.0.0.0', port=5000, debug=True)
