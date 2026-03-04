import os
import re
import json
import tempfile
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
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

    async def stream():
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "audio.%(ext)s")

            yield f"data: {json.dumps({'status': 'step', 'step': 1, 'msg': 'breaking into youtube and stealing the audio 🕵️'})}\n\n"

            try:
                proc = await asyncio.create_subprocess_exec(
                    "python3", "-m", "yt_dlp",
                    "-f", "bestaudio",
                    "--no-playlist",
                    "--no-post-overwrites",
                    "-o", audio_path,
                    req.youtube_url,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )

                async for line in proc.stdout:
                    text = line.decode().strip()
                    if text and '[download]' in text:
                        yield f"data: {json.dumps({'status': 'step', 'step': 1, 'msg': '↳ ' + text})}\n\n"

                await proc.wait()
                if proc.returncode != 0:
                    # collect remaining output for real error
                    remaining = await proc.stdout.read()
                    err_text = remaining.decode()[-500:]
                    yield f"data: {json.dumps({'status': 'error', 'msg': f'yt-dlp failed: {err_text}'})}\n\n"
                    return

            except FileNotFoundError:
                yield f"data: {json.dumps({'status': 'error', 'msg': 'python3 not found on server. contact support'})}\n\n"
                return

            files = os.listdir(tmpdir)
            if not files:
                yield f"data: {json.dumps({'status': 'error', 'msg': 'download failed — no file found'})}\n\n"
                return

            actual_path = os.path.join(tmpdir, files[0])
            size_mb = os.path.getsize(actual_path) / 1024 / 1024

            yield f"data: {json.dumps({'status': 'step', 'step': 2, 'msg': f'got {size_mb:.1f}mb of unfiltered yap. packaging it up 📦'})}\n\n"

            try:
                config = aai.TranscriptionConfig(
                    speaker_labels=True,
                    speech_models=["universal-2"]
                )
                transcriber = aai.Transcriber()

                yield f"data: {json.dumps({'status': 'step', 'step': 3, 'msg': 'AI is being forced to listen to every word. it did not consent 🤖'})}\n\n"

                # Run transcription in background, stream funny messages while waiting
                loop = asyncio.get_event_loop()
                transcribe_task = loop.run_in_executor(
                    None, lambda: transcriber.transcribe(actual_path, config=config)
                )

                waiting_msgs = [
                    "AI is suffering through this so you don't have to 😔",
                    "still listening... it's taking notes 📝",
                    "your podcast is 73% filler apparently 💀",
                    "the AI has developed opinions. we're scared 😰",
                    "identifying who talks the most (we already know) 🙄",
                    "processing... please do not tap the glass 🐟",
                    "counting every 'um', 'like', and 'you know' 🫠",
                    "almost there... probably... maybe... 🤞",
                    "the AI is judging everyone's vocal fry rn 😶",
                    "still going. this podcast could've been an email 📧",
                ]
                msg_index = 0
                while not transcribe_task.done():
                    await asyncio.sleep(4)
                    if not transcribe_task.done():
                        msg = waiting_msgs[msg_index % len(waiting_msgs)]
                        msg_index += 1
                        yield f"data: {json.dumps({'status': 'step', 'step': 3, 'msg': msg})}\n\n"

                transcript = await transcribe_task

                if transcript.status == aai.TranscriptStatus.error:
                    yield f"data: {json.dumps({'status': 'error', 'msg': transcript.error})}\n\n"
                    return

            except Exception as e:
                yield f"data: {json.dumps({'status': 'error', 'msg': str(e)})}\n\n"
                return

            yield f"data: {json.dumps({'status': 'step', 'step': 4, 'msg': 'building criminal profiles for each yapper 🔍'})}\n\n"

            segments = []
            for utt in transcript.utterances:
                segments.append({
                    "speaker": utt.speaker,
                    "start": utt.start / 1000.0,
                    "end": utt.end / 1000.0,
                    "text": utt.text,
                })

            speakers = sorted(list(set(s["speaker"] for s in segments)))

            yield f"data: {json.dumps({'status': 'done', 'video_id': video_id, 'segments': segments, 'speakers': speakers})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


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
