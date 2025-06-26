import re
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

app = FastAPI(
    title="Douyin Downloader API",
    description="API for downloading Douyin videos/audios without watermark",
    version="1.0.0"
)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

def extract_douyin_id(url: str) -> str:
    """Extract Douyin video ID from URL"""
    patterns = [
        r"https?://v\.douyin\.com/(\w+)",
        r"https?://www\.douyin\.com/video/(\d+)",
        r"https?://vm\.tiktok\.com/(\w+)"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    raise HTTPException(
        status_code=400,
        detail="Invalid Douyin URL. Supported formats: "
               "1. https://v.douyin.com/ABC123/ "
               "2. https://www.douyin.com/video/1234567890123456789 "
               "3. https://vm.tiktok.com/ABC123/"
    )

def get_download_urls(video_id: str) -> dict:
    """Fetch download URLs using third-party API"""
    api_url = f"https://api.douyin.wtf/api?url=https://www.douyin.com/video/{video_id}"
    
    try:
        response = requests.get(
            api_url,
            headers={"User-Agent": USER_AGENT},
            timeout=15
        )
        response.raise_for_status()
        
        data = response.json()
        
        if "video_data" not in data or "music_data" not in data:
            raise ValueError("Invalid API response structure")
        
        return {
            "video": data["video_data"]["nwm_video_url"],
            "audio": data["music_data"]["play_url"]["uri"]
        }
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"API request failed: {str(e)}"
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(
            status_code=502,
            detail=f"API response error: {str(e)}"
        )

@app.get("/")
async def read_root():
    return RedirectResponse("https://github.com/your-repo")

@app.get("/info")
@limiter.limit("10/minute")
async def get_video_info(request: Request, url: str):
    """Get video information without downloading"""
    try:
        video_id = extract_douyin_id(url)
        download_urls = get_download_urls(video_id)
        return {
            "status": "success",
            "video_id": video_id,
            "video_url": download_urls["video"],
            "audio_url": download_urls["audio"]
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )

@app.get("/download")
@limiter.limit("5/minute")
async def download_douyin(request: Request, url: str, media_type: str = "video"):
    """Download endpoint with rate limiting"""
    try:
        video_id = extract_douyin_id(url)
        download_urls = get_download_urls(video_id)
        
        if media_type not in download_urls:
            raise HTTPException(
                status_code=400,
                detail="Invalid media type. Choose 'video' or 'audio'"
            )
        
        media_url = download_urls[media_type]
        
        # Stream the content directly to the user
        response = requests.get(
            media_url,
            headers={"User-Agent": USER_AGENT},
            stream=True,
            timeout=30
        )
        response.raise_for_status()
        
        return StreamingResponse(
            response.iter_content(chunk_size=1024 * 1024),
            media_type="video/mp4" if media_type == "video" else "audio/mpeg",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=douyin_{media_type}_{video_id}"
                    f"{'.mp4' if media_type == 'video' else '.mp3'}"
                )
            }
        )
    except HTTPException as he:
        raise he
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=504,
            detail=f"Download failed: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )

# Error handler for rate limiting
@app.exception_handler(RateLimitExceeded)
async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
    return HTTPException(
        status_code=429,
        detail="Too many requests. Limit: 5 downloads/min, 10 info requests/min"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)