# main.py
from fastapi import FastAPI, Request, BackgroundTasks, Form, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import yt_dlp
import os
import uvicorn
import re
import asyncio
import uuid # For unique filenames

# Initialize FastAPI app
app = FastAPI(title="Secure YouTube Video Downloader")

# --- Configuration ---
DOWNLOAD_DIR = "downloads"
MAX_CONCURRENT_DOWNLOADS = 3 # Limit concurrent downloads to prevent resource exhaustion
MAX_VIDEO_DURATION_SECONDS = 3600 # 1 hour (e.g., to prevent excessively large files)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# --- Concurrency Control ---
# Use a semaphore to limit the number of concurrent downloads
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# --- Video Download Logic ---
async def download_video_task(youtube_url: str, download_path: str, request_id: str):
    """
    Performs the video download using yt-dlp with enhanced error handling and limits.
    This function runs in a background task.
    """
    try:
        async with download_semaphore: # Acquire a semaphore slot
            print(f"[{request_id}] Starting download for URL: {youtube_url}")

            # Get video info first to check duration before downloading
            ydl_opts_info = {
                'quiet': True,
                'skip_download': True, # Only get info, don't download yet
                'cachedir': False,
            }
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info_dict = ydl.extract_info(youtube_url, download=False)
                duration = info_dict.get('duration')

                if duration and duration > MAX_VIDEO_DURATION_SECONDS:
                    print(f"[{request_id}] Video duration ({duration}s) exceeds limit ({MAX_VIDEO_DURATION_SECONDS}s). Aborting download for {youtube_url}.")
                    # In a real application, you might want to log this or update a status.
                    return {"status": "error", "message": "Video duration exceeds the allowed limit."}

            # Sanitize title for filename to prevent path traversal or invalid characters
            video_title = info_dict.get('title', 'video')
            sanitized_title = re.sub(r'[<>:"/\\|?*]', '_', video_title)
            # Add a unique ID to the filename to prevent overwrites and provide uniqueness
            unique_filename = f"{sanitized_title}_{uuid.uuid4().hex}.%(ext)s"

            ydl_opts = {
                'outtmpl': os.path.join(download_path, unique_filename),
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'noplaylist': True,
                'cachedir': False,
                'progress_hooks': [lambda d: print(f"[{request_id}] Download status: {d.get('status')}, filename: {d.get('filename')}")],
                'verbose': True,
                'logtostderr': True,
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }],
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(youtube_url, download=True)
                print(f"[{request_id}] Finished download for: {info_dict.get('title')}")
                return {"status": "success", "message": f"Successfully downloaded {info_dict.get('title')}"}

    except yt_dlp.utils.DownloadError as e:
        error_message = f"Download error for {youtube_url}: {e}"
        print(f"[{request_id}] {error_message}")
        return {"status": "error", "message": f"Failed to download video: {str(e)}"}
    except Exception as e:
        error_message = f"An unexpected error occurred during download for {youtube_url}: {e}"
        print(f"[{request_id}] {error_message}")
        return {"status": "error", "message": "An unexpected error occurred during download. Please try again later."}
    finally:
        # The semaphore is automatically released when exiting the 'async with' block.
        pass

# --- Frontend HTML ---
# Using f-string for HTML to easily inject dynamic content if needed, though not used here.
HTML_FORM = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Secure YouTube Downloader</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {
            font-family: 'Inter', sans-serif;
            background-color: #f3f4f6;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
        }
        .container {
            background-color: #ffffff;
            padding: 2.5rem;
            border-radius: 1rem;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
            max-width: 500px;
            width: 90%;
            text-align: center;
        }
        input[type="url"], button {
            padding: 0.75rem 1rem;
            border-radius: 0.5rem;
            border: 1px solid #d1d5db;
            width: calc(100% - 2rem);
            margin-top: 1rem;
            font-size: 1rem;
        }
        button {
            background-image: linear-gradient(to right, #6366f1, #8b5cf6);
            color: white;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease-in-out;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            width: 100%;
            margin-bottom: 0.5rem;
        }
        button:hover {
            opacity: 0.9;
            transform: translateY(-2px);
            box-shadow: 0 6px 8px -1px rgba(0, 0, 0, 0.15), 0 3px 5px -1px rgba(0, 0, 0, 0.08);
        }
        button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }
        .message-box {
            background-color: #e0f2f7;
            border: 1px solid #a7d9ed;
            color: #0c4a6e;
            padding: 1rem;
            border-radius: 0.5rem;
            margin-top: 1rem;
            text-align: left;
            word-wrap: break-word;
            font-size: 0.9rem;
            line-height: 1.4;
            display: none;
        }
        .message-box.show {
            display: block;
        }
        h1 {
            color: #374151;
            font-size: 1.875rem;
            font-weight: 700;
            margin-bottom: 1.5rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Download YouTube Videos</h1>
        <form id="downloadForm" action="/download" method="post">
            <input
                type="url"
                name="youtube_url"
                id="youtubeUrl"
                placeholder="Paste YouTube video URL here..."
                required
                pattern="^(https?://)?(www\\.)?(youtube\\.com|youtu\\.be)/.+$"
                title="Please enter a valid YouTube URL."
            >
            <button type="submit">Download Video</button>
        </form>
        <div id="messageBox" class="message-box"></div>
    </div>

    <script>
        const downloadForm = document.getElementById('downloadForm');
        const youtubeUrlInput = document.getElementById('youtubeUrl');
        const messageBox = document.getElementById('messageBox');
        let downloadInitiated = false; // Flag to prevent multiple submissions

        downloadForm.addEventListener('submit', async function(event) {
            event.preventDefault();

            if (downloadInitiated) {
                showMessage("A download is already in progress. Please wait.", "info");
                return;
            }

            const youtubeUrl = youtubeUrlInput.value.trim();

            if (!youtubeUrl) {
                showMessage("Please enter a YouTube video URL.", "error");
                return;
            }

            const youtubeRegex = /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\/.+$/;
            if (!youtubeRegex.test(youtubeUrl)) {
                showMessage("Please enter a valid YouTube URL (e.g., https://www.youtube.com/watch?v=dQw4w9WgXcQ or https://youtu.be/dQw4w9WgXcQ).", "error");
                return;
            }

            downloadInitiated = true; // Set flag
            showMessage("Starting download... This may take a moment. Please do not close this page.", "info");
            youtubeUrlInput.disabled = true;
            downloadForm.querySelector('button[type="submit"]').disabled = true;

            try {
                const formData = new FormData();
                formData.append('youtube_url', youtubeUrl);

                const response = await fetch('/download', {
                    method: 'POST',
                    body: formData,
                });

                const data = await response.json();

                if (response.ok) {
                    showMessage(data.message, "success");
                } else {
                    showMessage(`Error: ${data.message || "Something went wrong."}`, "error");
                }
            } catch (error) {
                console.error('Fetch error:', error);
                showMessage("Network error. Please try again later.", "error");
            } finally {
                youtubeUrlInput.disabled = false;
                downloadForm.querySelector('button[type="submit"]').disabled = false;
                downloadInitiated = false; // Reset flag
            }
        });

        function showMessage(message, type) {
            messageBox.textContent = message;
            messageBox.className = 'message-box show';
            if (type === "error") {
                messageBox.style.backgroundColor = '#fde0df';
                messageBox.style.borderColor = '#ef4444';
                messageBox.style.color = '#b91c1c';
            } else if (type === "success") {
                messageBox.style.backgroundColor = '#d1fae5';
                messageBox.style.borderColor = '#34d399';
                messageBox.style.color = '#065f46';
            } else { // info
                messageBox.style.backgroundColor = '#e0f2f7';
                messageBox.style.borderColor = '#a7d9ed';
                messageBox.style.color = '#0c4a6e';
            }
        }
    </script>
</body>
</html>
"""

# --- FastAPI Routes ---

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """
    Serves the main HTML page with the YouTube URL input form.
    """
    return HTMLResponse(content=HTML_FORM)

@app.post("/download")
async def download_video(
    youtube_url: str = Form(...),
    background_tasks: BackgroundTasks,
    request: Request # Inject Request object to get client host
):
    """
    Initiates a video download as a background task.
    Validates the YouTube URL and handles rate limiting.
    """
    client_host = request.client.host if request.client else "unknown"
    request_id = str(uuid.uuid4())[:8] # Short unique ID for logging

    print(f"[{request_id}] Received download request from {client_host} for URL: {youtube_url}")

    # Server-side validation of the URL using a robust regex.
    # This regex is more comprehensive for YouTube URLs.
    # It covers standard YouTube URLs, short-form youtu.be links, and various query parameters.
    youtube_regex = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be)/"
        r"(watch\?v=|embed/|v/|.+\?v=)?([a-zA-Z0-9_-]{11})(.*)?$"
    )
    if not youtube_regex.match(youtube_url):
        print(f"[{request_id}] Invalid YouTube URL provided by {client_host}: {youtube_url}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Invalid YouTube URL provided. Please enter a valid YouTube link (e.g., https://www.youtube.com/watch?v=example or https://youtu.be/example).", "status": "error"}
        )

    # Check if we are at the maximum concurrent download limit
    if download_semaphore.locked():
        print(f"[{request_id}] Download capacity reached. Rejecting request from {client_host}.")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"message": "Server is currently busy with other downloads. Please try again shortly.", "status": "error"}
        )

    # Add the download_video_task to the background tasks.
    background_tasks.add_task(download_video_task, youtube_url, DOWNLOAD_DIR, request_id)

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"message": f"Download initiated for {youtube_url}. This process runs in the background.", "status": "processing"}
    )

# --- How to Run ---
# To run this application:
# 1. Save the code as 'main.py'.
# 2. Open your terminal in the same directory as 'main.py'.
# 3. Run: uvicorn main:app --reload
# 4. Open your web browser and go to http://127.0.0.1:8000