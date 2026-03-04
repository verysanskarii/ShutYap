import os
import re
import tempfile
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import assemblyai as aai

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")


class ProcessRequest(BaseModel):
    youtube_url: str
    api_key: str


@app.post("/process")
async def process_video(req: ProcessRequest):
    aai.settings.api_key = req.api_key

    video_id = extract_video_id(req.youtube_url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "audio.%(ext)s")

        try:
            result = subprocess.run(
                [
                    "yt-dlp",
                    "-x",
                    "--audio-format", "mp3",
                    "--audio-quality", "0",
                    "-o", audio_path,
                    req.youtube_url,
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode != 0:
                raise HTTPException(status_code=500, detail=f"yt-dlp error: {result.stderr}")
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=500, detail="Download timed out")
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="yt-dlp not found. Run: brew install yt-dlp")

        files = os.listdir(tmpdir)
        if not files:
            raise HTTPException(status_code=500, detail="Audio download failed — no file found")
        actual_path = os.path.join(tmpdir, files[0])

        try:
            config = aai.TranscriptionConfig(
                speaker_labels=True,
                speech_models=["universal"]
            )
            transcriber = aai.Transcriber()
            transcript = transcriber.transcribe(actual_path, config=config)

            if transcript.status == aai.TranscriptStatus.error:
                raise HTTPException(status_code=500, detail=f"Transcription error: {transcript.error}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        segments = []
        for utt in transcript.utterances:
            segments.append({
                "speaker": utt.speaker,
                "start": utt.start / 1000.0,
                "end": utt.end / 1000.0,
                "text": utt.text,
            })

        speakers = sorted(list(set(s["speaker"] for s in segments)))

        return {
            "video_id": video_id,
            "segments": segments,
            "speakers": speakers,
        }


def extract_video_id(url):
    patterns = [
        r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:embed/)([A-Za-z0-9_-]{11})",
        r"(?:shorts/)([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None
