import os
import re
import subprocess
import tempfile
import uuid
import requests
from flask import Flask, request, send_file, jsonify

app = Flask(__name__)


@app.route("/", methods=["GET"])
def health():
    return "OK - servizio di montaggio video attivo", 200


@app.route("/render", methods=["POST"])
def render():
    data = request.get_json(force=True, silent=True) or {}
    audio_url = data.get("audio_url")
    image_url = data.get("image_url")

    if not audio_url or not image_url:
        return jsonify({"error": "Servono audio_url e image_url nel body JSON"}), 400

    audio_url = _normalize_drive_url(audio_url)
    image_url = _normalize_drive_url(image_url)

    work_dir = tempfile.mkdtemp()
    audio_path = os.path.join(work_dir, "audio.mp3")
    image_path = os.path.join(work_dir, "image.jpg")
    output_path = os.path.join(work_dir, f"{uuid.uuid4()}.mp4")

    try:
        _download(audio_url, audio_path)
        _download(image_url, image_path)

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", image_path,
            "-i", audio_path,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "stillimage",
            "-c:a", "aac",
            "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=270)

        if result.returncode != 0 or not os.path.exists(output_path):
            return jsonify({
                "error": "FFmpeg ha fallito",
                "details": result.stderr[-2000:]
            }), 500

        return send_file(
            output_path,
            mimetype="video/mp4",
            as_attachment=True,
            download_name="short.mp4",
        )
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Download fallito: {str(e)}"}), 502
    except subprocess.TimeoutExpired:
        return jsonify({"error": "FFmpeg ha impiegato troppo tempo (timeout)"}), 504


def _download(url, dest_path):
    resp = requests.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)


def _normalize_drive_url(url):
    """Converte un link di condivisione Google Drive in link di download diretto."""
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if match:
        file_id = match.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
