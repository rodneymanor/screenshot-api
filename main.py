from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import subprocess
import os
from datetime import timedelta
import shutil
import uuid
from typing import Optional
from pydantic import BaseModel
import logging
import uvicorn

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Video Screenshot API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)

class ScreenshotRequest(BaseModel):
    num_screenshots: Optional[int] = 10
    quality: Optional[int] = 2  # 2-31, lower is better

def process_video(
    video_path: str,
    output_dir: str,
    num_screenshots: int = 10,
    quality: int = 2
) -> None:
    """Process video and generate screenshots."""
    try:
        # Get video duration using FFprobe
        duration_cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        
        duration = float(subprocess.check_output(duration_cmd).decode('utf-8').strip())
        interval = duration / (num_screenshots + 1)
        
        # Extract screenshots
        for i in range(num_screenshots):
            time_point = interval * (i + 1)
            timestamp = str(timedelta(seconds=int(time_point)))
            output_file = os.path.join(output_dir, f'screenshot_{i+1:03d}.jpg')
            
            ffmpeg_cmd = [
                'ffmpeg',
                '-ss', timestamp,
                '-i', video_path,
                '-vframes', '1',
                '-q:v', str(quality),
                output_file
            ]
            
            subprocess.run(ffmpeg_cmd, stderr=subprocess.PIPE)
            logger.info(f'Generated screenshot {i+1}/{num_screenshots}')
    
    except Exception as e:
        logger.error(f"Error processing video: {str(e)}")
        raise

@app.post("/screenshots/")
async def create_screenshots(
    video: UploadFile = File(...),
    num_screenshots: Optional[int] = 10,
    quality: Optional[int] = 2
):
    """
    Upload a video and receive screenshots as a ZIP file.
    """
    if not video.filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
        raise HTTPException(400, "Unsupported file format")
    
    # Create temporary directories
    job_id = str(uuid.uuid4())
    job_dir = os.path.join(TEMP_DIR, job_id)
    screenshots_dir = os.path.join(job_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    
    try:
        # Save uploaded video
        video_path = os.path.join(job_dir, video.filename)
        with open(video_path, "wb") as buffer:
            shutil.copyfileobj(video.file, buffer)
        
        # Process video
        process_video(video_path, screenshots_dir, num_screenshots, quality)
        
        # Create ZIP file
        zip_path = os.path.join(job_dir, "screenshots.zip")
        with shutil.ZipFile(zip_path, 'w') as zipf:
            for file in os.listdir(screenshots_dir):
                file_path = os.path.join(screenshots_dir, file)
                zipf.write(file_path, file)
        
        # Return ZIP file
        return FileResponse(
            zip_path,
            media_type='application/zip',
            filename=f'screenshots_{job_id}.zip',
            background=shutil.rmtree(job_dir, ignore_errors=True)  # Cleanup after sending
        )
        
    except Exception as e:
        # Cleanup on error
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(500, f"Error processing video: {str(e)}")

@app.on_event("startup")
async def startup_event():
    """Clean up temp directory on startup."""
    shutil.rmtree(TEMP_DIR, ignore_errors=True)
    os.makedirs(TEMP_DIR, exist_ok=True)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)