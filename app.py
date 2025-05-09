from flask import Flask, render_template, request, send_file, url_for, redirect
from pytube import YouTube
from pytube.exceptions import RegexMatchError, VideoUnavailable
import os
import uuid
import re
import subprocess
import shutil
import logging

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

# Use the local yt-dlp.exe in the same directory
YT_DLP_PATH = os.path.join(os.getcwd(), "yt-dlp.exe")

def sanitize_filename(title):
    """Remove invalid characters from filename"""
    return re.sub(r'[\\/*?:"<>|]', "", title)

def download_with_yt_dlp(youtube_url):
    """Download audio using local yt-dlp.exe"""
    try:
        # Check if yt-dlp.exe exists
        if not os.path.exists(YT_DLP_PATH):
            raise Exception(f"yt-dlp.exe not found at {YT_DLP_PATH}")
        
        # Generate a unique filename base (without extension)
        file_id = str(uuid.uuid4())
        output_template = os.path.join(TEMP_DIR, f"{file_id}.%(ext)s")
        
        # Use yt-dlp to download the audio
        command = f'"{YT_DLP_PATH}" -v -x --audio-format mp3 --audio-quality 0 -o "{output_template}" "{youtube_url}"'
        
        logger.info(f"Running yt-dlp command: {command}")
        
        # Run the command with shell=True for Windows
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            universal_newlines=True
        )
        
        # Log output in real-time
        stdout, stderr = "", ""
        for line in process.stdout:
            logger.debug(f"yt-dlp stdout: {line.strip()}")
            stdout += line
        
        for line in process.stderr:
            logger.error(f"yt-dlp stderr: {line.strip()}")
            stderr += line
        
        # Wait for process to complete
        return_code = process.wait()
        
        if return_code != 0:
            logger.error(f"yt-dlp failed with return code {return_code}")
            logger.error(f"yt-dlp stderr: {stderr}")
            raise Exception(f"yt-dlp failed: {stderr}")
        
        # Find the output file (should be the only file starting with file_id)
        output_file = None
        for file in os.listdir(TEMP_DIR):
            if file.startswith(file_id):
                output_file = os.path.join(TEMP_DIR, file)
                break
        
        if not output_file:
            raise Exception("Could not find downloaded file")
        
        # Get the video title from yt-dlp
        title_command = f'"{YT_DLP_PATH}" --get-title "{youtube_url}"'
        title_result = subprocess.run(title_command, 
                                     shell=True,
                                     capture_output=True, 
                                     text=True)
        
        if title_result.returncode == 0:
            video_title = sanitize_filename(title_result.stdout.strip())
            # Rename the file to include the video title
            mp3_file = os.path.join(TEMP_DIR, f"{video_title}.mp3")
            shutil.move(output_file, mp3_file)
            return video_title
        else:
            # If we can't get the title, just use the file_id
            return os.path.basename(output_file).split('.')[0]
            
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
            # Check if local yt-dlp.exe exists
            if os.path.exists(YT_DLP_PATH):
                try:
                    # Try yt-dlp first
                    logger.info(f"Attempting download with local yt-dlp: {YT_DLP_PATH}")
                    video_title = download_with_yt_dlp(youtube_url)
                except Exception as e:
                    logger.warning(f"yt-dlp failed, falling back to pytube: {str(e)}")
                    # Fall back to pytube if yt-dlp fails
                    video_title = download_with_pytube(youtube_url)
            else:
                # Use pytube if yt-dlp is not found
                logger.info("Local yt-dlp.exe not found, using pytube")
                video_title = download_with_pytube(youtube_url)
            
            # Redirect to the download page
            return redirect(url_for('download', filename=f"{video_title}.mp3"))
            
        except RegexMatchError:
            return render_template('index.html', error="Invalid YouTube URL. Please check the URL and try again.")
        except VideoUnavailable:
            return render_template('index.html', error="This video is unavailable. It might be private or age-restricted.")
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return render_template('index.html', error=f"An error occurred: {str(e)}")
    
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

if __name__ == '__main__':
    # Log system information
    logger.info(f"Current directory: {os.getcwd()}")
    logger.info(f"Looking for yt-dlp.exe at: {YT_DLP_PATH}")
    
    # Check for local yt-dlp.exe at startup
    if os.path.exists(YT_DLP_PATH):
        logger.info(f"Local yt-dlp.exe found at: {YT_DLP_PATH}")
    else:
        logger.warning("Local yt-dlp.exe not found. Will use pytube as fallback.")
        logger.info("To use yt-dlp, download yt-dlp.exe from GitHub and place it in the same directory as this script.")
    
    app.run(debug=True)