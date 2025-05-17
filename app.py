import random
import time

# Settings
YT_DLP_CMD = "yt-dlp"
TEMP_DIR = "temp_downloads"
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# Optional: Set proxy via environment variable
PROXY = os.environ.get('YT_DLP_PROXY', None)

# Delay settings (in seconds)
DELAY_MIN = 2
DELAY_MAX = 5

def download_with_yt_dlp(youtube_url, download_id):
    try:
        # Add random delay to prevent rate limiting
        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        logger.info(f"Sleeping for {delay:.2f} seconds to avoid rate limits")
        time.sleep(delay)

        file_id = str(uuid.uuid4())
        output_template = os.path.join(TEMP_DIR, f"{file_id}.%(ext)s")

        # Initialize progress tracking
        download_status[download_id] = {
            'status': 'downloading',
            'progress': 0,
            'message': 'Starting download...',
            'filename': None
        }

        # Build yt-dlp command with modern user-agent
        command = [
            YT_DLP_CMD,
            '-x', '--audio-format', 'mp3', '--audio-quality', '0',
            '--newline', '--progress',
            '-o', output_template,
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
        ]

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

        stderr_output = []

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

            # Read stderr in real-time
            stderr_line = process.stderr.readline().strip()
            if stderr_line:
                stderr_output.append(stderr_line)

        return_code = process.wait()

        if return_code != 0:
            error = '\n'.join(stderr_output) if stderr_output else "Unknown error"
            logger.error(f"yt-dlp failed with return code {return_code}")
            logger.error(f"yt-dlp stderr: {error}")

            if "Sign in to confirm" in error:
                download_status[download_id] = {
                    'status': 'error',
                    'message': "This video requires authentication and cannot be downloaded without cookies."
                }
            elif "429" in error or "Too Many Requests" in error:
                download_status[download_id] = {
                    'status': 'error',
                    'message': "Too many requests. Please try again later."
                }
            else:
                download_status[download_id] = {
                    'status': 'error',
                    'message': f"Download failed: {error}"
                }
            return None

        # Find output file
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

        # Get title (no cookies)
        title_command = [YT_DLP_CMD, '--get-title', youtube_url]
        if PROXY:
            title_command.extend(['--proxy', PROXY])

        title_result = subprocess.run(title_command, capture_output=True, text=True)

        if title_result.returncode == 0:
            video_title = sanitize_filename(title_result.stdout.strip())
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
