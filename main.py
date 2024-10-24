from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import subprocess
import os
from datetime import timedelta
import shutil
import uuid
from typing import Optional, List
import logging
import uvicorn
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Video Screenshot API")

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

# Mount the temp directory for static file access
app.mount("/temp", StaticFiles(directory=TEMP_DIR), name="temp")

def get_video_duration(video_path: str) -> float:
    """Get video duration using FFprobe."""
    duration_cmd = [
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        video_path
    ]
    return float(subprocess.check_output(duration_cmd).decode('utf-8').strip())

def process_video(
    video_path: str,
    output_dir: str,
    num_screenshots: int = 10,
    quality: int = 2
) -> List[str]:
    """Process video and return list of screenshot paths."""
    screenshot_paths = []
    try:
        duration = get_video_duration(video_path)
        interval = duration / (num_screenshots + 1)
        
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
            screenshot_paths.append(output_file)
            logger.info(f'Generated screenshot {i+1}/{num_screenshots}')
        
        return screenshot_paths
    
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
    Upload a video and receive URLs for all screenshots.
    Screenshots are saved in a job-specific directory.
    """
    if not video.filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
        raise HTTPException(400, "Unsupported file format")
    
    # Create job directory with UUID
    job_id = str(uuid.uuid4())
    job_dir = os.path.join(TEMP_DIR, job_id)
    os.makedirs(job_dir)
    
    try:
        # Save uploaded video
        video_path = os.path.join(job_dir, video.filename)
        with open(video_path, "wb") as buffer:
            shutil.copyfileobj(video.file, buffer)
        
        # Process video and get screenshot paths
        screenshot_paths = process_video(video_path, job_dir, num_screenshots, quality)
        
        # Remove the video file to save space
        os.remove(video_path)
        
        # Generate URLs for each screenshot
        base_url = f"/temp/{job_id}"
        screenshots = []
        for i, path in enumerate(screenshot_paths, 1):
            filename = os.path.basename(path)
            screenshots.append({
                "id": i,
                "filename": filename,
                "url": f"{base_url}/{filename}"
            })
        
        return JSONResponse({
            "job_id": job_id,
            "screenshot_dir": f"/temp/{job_id}",
            "screenshots": screenshots
        })
        
    except Exception as e:
        # Cleanup on error
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(500, f"Error processing video: {str(e)}")

# Optional: Add a cleanup endpoint to manually remove old jobs
@app.delete("/screenshots/{job_id}")
async def cleanup_screenshots(job_id: str):
    """Delete a job's screenshots directory."""
    job_dir = os.path.join(TEMP_DIR, job_id)
    if os.path.exists(job_dir):
        shutil.rmtree(job_dir)
        return {"message": f"Cleaned up job {job_id}"}
    raise HTTPException(404, "Job not found")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)