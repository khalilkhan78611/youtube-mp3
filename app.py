import os
import random
import re
import shutil
import subprocess
import time
import uuid
from pathvalidate import sanitize_filename
from typing import Dict, Optional, List

# Configure logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global settings
YT_DLP_CMD = "yt-dlp"
TEMP_DIR = "temp_downloads"
COOKIES_FILE = "cookies.txt"
os.makedirs(TEMP_DIR, exist_ok=True)

# Configuration
class Config:
    DELAY_RANGE = (5, 15)  # Random delay between downloads (seconds)
    MAX_RETRIES = 3        # Max retries for failed downloads
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    PROXY = os.environ.get('YT_DLP_PROXY')  # Optional proxy

# Global download tracking
download_status: Dict[str, dict] = {}

def sanitize_filename(filename: str) -> str:
    """Sanitize filename by removing invalid characters."""
    return re.sub(r'[\\/*?:"<>|]', "", filename).strip()

class YouTubeDownloader:
    def __init__(self):
        self.cookies_available = os.path.exists(COOKIES_FILE)
        if self.cookies_available:
            logger.info("Cookies file found - will use for authentication")
        else:
            logger.warning("No cookies.txt file - age-restricted videos may fail")

    def _build_command(self, url: str, output_template: str) -> List[str]:
        """Build the yt-dlp command with all options."""
        command = [
            YT_DLP_CMD,
            '--newline',
            '--progress',
            '--no-warnings',
            '--audio-format', 'mp3',
            '--audio-quality', '0',
            '--extract-audio',
            '--user-agent', Config.USER_AGENT,
            '-o', output_template,
        ]

        if self.cookies_available:
            command.extend(['--cookies', COOKIES_FILE])

        if Config.PROXY:
            command.extend(['--proxy', Config.PROXY])

        command.extend([
            '--force-ipv4',  # Avoid IPv6 if problematic
            '--socket-timeout', '30',  # 30 second timeout
            '--retries', '10',  # Retry on failures
            url
        ])

        return command

    def _handle_error(self, download_id: str, error_msg: str) -> None:
        """Handle different types of download errors."""
        error_lower = error_msg.lower()
        
        if any(msg in error_lower for msg in ["sign in", "robot", "captcha"]):
            message = "YouTube requires CAPTCHA verification (add cookies.txt)"
        elif "429" in error_msg or "too many requests" in error_lower:
            message = "Rate limited - try again later with different IP"
        elif "unavailable" in error_lower:
            message = "Video is unavailable/private"
        elif "age restricted" in error_lower:
            message = "Age-restricted video (requires cookies)"
        else:
            message = "Download failed"

        download_status[download_id] = {
            'status': 'error',
            'message': message,
            'error': error_msg,
            'progress': 0
        }

    def _get_video_title(self, url: str) -> Optional[str]:
        """Get video title without downloading."""
        try:
            cmd = [YT_DLP_CMD, '--get-title', '--no-warnings', url]
            if self.cookies_available:
                cmd.extend(['--cookies', COOKIES_FILE])
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15
            )
            return sanitize_filename(result.stdout.strip()) if result.returncode == 0 else None
        except Exception as e:
            logger.warning(f"Couldn't get video title: {str(e)}")
            return None

    def _process_output_line(self, line: str, download_id: str) -> None:
        """Parse yt-dlp output for progress updates."""
        try:
            if '[download]' in line:
                if 'Destination:' in line:
                    download_status[download_id]['message'] = 'Processing...'
                elif '%' in line:
                    percent = float(line.split('%')[0].strip().split()[-1])
                    download_status[download_id].update({
                        'progress': percent,
                        'message': f"Downloading... {percent:.1f}%"
                    })
        except Exception as e:
            logger.debug(f"Progress parsing error: {str(e)}")

    def download(self, youtube_url: str, download_id: str) -> Optional[str]:
        """Main download method with retry logic."""
        for attempt in range(Config.MAX_RETRIES):
            try:
                # Random delay between attempts
                if attempt > 0:
                    delay = random.uniform(*Config.DELAY_RANGE)
                    logger.info(f"Retry #{attempt + 1} in {delay:.1f} seconds...")
                    time.sleep(delay)

                # Initialize tracking
                file_id = str(uuid.uuid4())
                output_template = os.path.join(TEMP_DIR, f"{file_id}.%(ext)s")
                
                download_status[download_id] = {
                    'status': 'downloading',
                    'progress': 0,
                    'message': 'Starting download...',
                    'filename': None,
                    'attempt': attempt + 1
                }

                # Build and run command
                command = self._build_command(youtube_url, output_template)
                logger.debug(f"Running command: {' '.join(command)}")

                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )

                # Process output in real-time
                stderr_lines = []
                while True:
                    output_line = process.stdout.readline()
                    if output_line == '' and process.poll() is not None:
                        break
                    if output_line:
                        self._process_output_line(output_line.strip(), download_id)

                    # Capture stderr
                    stderr_line = process.stderr.readline()
                    if stderr_line:
                        stderr_lines.append(stderr_line.strip())

                # Check result
                if process.returncode != 0:
                    error_msg = '\n'.join(stderr_lines) or f"Exit code {process.returncode}"
                    self._handle_error(download_id, error_msg)
                    continue  # Will retry if attempts remain

                # Find and rename downloaded file
                downloaded_files = [
                    f for f in os.listdir(TEMP_DIR) 
                    if f.startswith(file_id) and f.endswith('.mp3')
                ]

                if not downloaded_files:
                    self._handle_error(download_id, "Downloaded file not found")
                    continue

                temp_file = os.path.join(TEMP_DIR, downloaded_files[0])
                video_title = self._get_video_title(youtube_url) or f"audio_{file_id[:8]}"
                final_filename = f"{sanitize_filename(video_title)}.mp3"
                final_path = os.path.join(TEMP_DIR, final_filename)

                try:
                    shutil.move(temp_file, final_path)
                    download_status[download_id] = {
                        'status': 'completed',
                        'progress': 100,
                        'message': 'Download complete!',
                        'filename': final_filename,
                        'filepath': final_path
                    }
                    return final_filename
                except OSError as e:
                    self._handle_error(download_id, f"File move failed: {str(e)}")
                    continue

            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {str(e)}", exc_info=True)
                self._handle_error(download_id, f"Unexpected error: {str(e)}")

        # All attempts failed
        logger.error(f"All {Config.MAX_RETRIES} attempts failed for {youtube_url}")
        return None

# Example usage
if __name__ == "__main__":
    downloader = YouTubeDownloader()
    
    # Test download
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    download_id = "test_download_1"
    
    result = downloader.download(test_url, download_id)
    if result:
        print(f"Successfully downloaded: {result}")
        print(f"Final status: {download_status[download_id]}")
    else:
        print("Download failed")
        print(f"Error details: {download_status[download_id].get('error')}")
