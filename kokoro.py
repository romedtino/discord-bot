import json
import logging
import os
from urllib import request

logger = logging.getLogger(__name__)

KOKORO_HOST = os.getenv("KOKORO_HOST", "192.168.1.59:8880")

VOICES = ("af_heart", "af_nicole")
DEFAULT_VOICE = "af_heart"

logger.info("Kokoro TTS target: http://%s", KOKORO_HOST)


def list_voices():
    """Query the Kokoro TTS endpoint for available voices.

    Returns a tuple of (voice_ids, default_voice).
    """
    req = request.Request(f"http://{KOKORO_HOST}/v1/audio/voices")
    try:
        data = json.loads(request.urlopen(req).read().decode("utf-8"))
    except request.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(
            f"Kokoro TTS returned {e.code}: {body}"
        ) from e
    if isinstance(data, dict):
        entries = data.get("voices", [])
        default_voice = data.get("default_voice", DEFAULT_VOICE)
    else:
        # Legacy plain-string list shape (?legacy=true)
        entries = data
        default_voice = DEFAULT_VOICE
    voice_ids = [
        entry["id"] if isinstance(entry, dict) else entry for entry in entries
    ]
    return voice_ids, default_voice


def generate_speech(text, voice=DEFAULT_VOICE):
    """Call the Kokoro TTS OpenAI-compatible endpoint and return raw mp3 bytes."""
    payload = {
        "input": text,
        "voice": voice,
        "response_format": "mp3",
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"http://{KOKORO_HOST}/v1/audio/speech",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        return request.urlopen(req).read()
    except request.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(
            f"Kokoro TTS returned {e.code}: {body}"
        ) from e
