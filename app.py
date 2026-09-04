import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Audio Split AI")

BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "work"
WORK_DIR.mkdir(exist_ok=True)


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.post("/api/separate")
async def separate(
    audio: UploadFile = File(...),
    mode: str = Form("simple"),
):
    job_id = uuid.uuid4().hex
    job_dir = WORK_DIR / job_id
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"

    input_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    filename = Path(audio.filename or "audio").name
    input_file = input_dir / filename

    try:
        with open(input_file, "wb") as f:
            shutil.copyfileobj(audio.file, f)

        model = "htdemucs_6s" if mode == "detailed" else "htdemucs"

        command = [
            "python",
            "-m",
            "demucs",
            "-n",
            model,
            "-o",
            str(output_dir),
            str(input_file),
        ]

        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if process.returncode != 0:
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": process.stderr[-3000:]
                    or "Erro ao processar o áudio."
                },
            )

        model_dir = output_dir / model
        track_dir = model_dir / input_file.stem

        if not track_dir.exists():
            possible = list(model_dir.glob("*"))
            if possible:
                track_dir = possible[0]

        if not track_dir.exists():
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": "Os arquivos separados não foram encontrados."
                },
            )

        stems = []

        if mode == "simple":
            vocals = track_dir / "vocals.wav"
            drums = track_dir / "drums.wav"
            bass = track_dir / "bass.wav"
            other = track_dir / "other.wav"

            if vocals.exists():
                stems.append(
                    {
                        "name": "vocals",
                        "url": f"/api/download/{job_id}/vocals.wav",
                    }
                )

            instrument_files = [
                file
                for file in [drums, bass, other]
                if file.exists()
            ]

            if instrument_files:
                instruments = track_dir / "instruments.wav"

                inputs = []
                for file in instrument_files:
                    inputs.extend(["-i", str(file)])

                mix_command = [
                    "ffmpeg",
                    "-y",
                    *inputs,
                    "-filter_complex",
                    (
                        f"amix=inputs={len(instrument_files)}:"
                        "duration=longest:normalize=0"
                    ),
                    "-c:a",
                    "pcm_s16le",
                    str(instruments),
                ]

                mix_process = subprocess.run(
                    mix_command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                if mix_process.returncode == 0:
                    stems.append(
                        {
                            "name": "instruments",
                            "url": f"/api/download/{job_id}/instruments.wav",
                        }
                    )

        else:
            for stem_name in [
                "vocals",
                "drums",
                "bass",
                "guitar",
                "piano",
                "other",
            ]:
                stem_file = track_dir / f"{stem_name}.wav"

                if stem_file.exists():
                    stems.append(
                        {
                            "name": stem_name,
                            "url": f"/api/download/{job_id}/{stem_name}.wav",
                        }
                    )

        if not stems:
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": "Nenhuma faixa foi gerada."
                },
            )

        return {
            "success": True,
            "job_id": job_id,
            "stems": stems,
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e),
            },
        )

    finally:
        await audio.close()


@app.get("/api/download/{job_id}/{filename}")
def download(job_id: str, filename: str):
    safe_job_id = Path(job_id).name
    safe_filename = Path(filename).name

    job_dir = WORK_DIR / safe_job_id

    if not job_dir.exists():
        return JSONResponse(
            status_code=404,
            content={"error": "Trabalho não encontrado."},
        )

    matches = list(job_dir.rglob(safe_filename))

    if not matches:
        return JSONResponse(
            status_code=404,
            content={"error": "Arquivo não encontrado."},
        )

    return FileResponse(
        matches[0],
        media_type="audio/wav",
        filename=safe_filename,
    )


app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)
