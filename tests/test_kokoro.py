import json
from unittest.mock import patch, MagicMock

import pytest
from urllib import request

import kokoro


class TestGenerateSpeech:
    """Tests for the generate_speech function."""

    @patch("kokoro.request.urlopen")
    def test_posts_to_correct_url(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b"mp3-bytes"
        mock_urlopen.return_value = mock_response

        kokoro.generate_speech("hello", "af_heart")

        args = mock_urlopen.call_args
        req = args[0][0]
        assert f"http://{kokoro.KOKORO_HOST}/v1/audio/speech" == req.full_url
        assert req.get_header("Content-type") == "application/json"

    @patch("kokoro.request.urlopen")
    def test_payload_contains_input_and_voice(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b"mp3-bytes"
        mock_urlopen.return_value = mock_response

        kokoro.generate_speech("hello world", "af_nicole")

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        assert body["input"] == "hello world"
        assert body["voice"] == "af_nicole"
        assert body["response_format"] == "mp3"
        assert body["stream"] is False

    @patch("kokoro.request.urlopen")
    def test_returns_audio_bytes(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b"mp3-bytes"
        mock_urlopen.return_value = mock_response

        result = kokoro.generate_speech("hello", "af_heart")
        assert result == b"mp3-bytes"

    @patch("kokoro.request.urlopen")
    def test_default_voice_is_af_heart(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b"mp3-bytes"
        mock_urlopen.return_value = mock_response

        kokoro.generate_speech("hello")

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        assert body["voice"] == "af_heart"

    @patch("kokoro.request.urlopen")
    def test_raises_on_http_error(self, mock_urlopen):
        error = request.HTTPError(
            "http://localhost:8880/v1/audio/speech", 500, "error",
            {}, MagicMock()
        )
        error.read = lambda: b'{"error": "model failed"}'
        mock_urlopen.side_effect = error

        with pytest.raises(RuntimeError) as exc_info:
            kokoro.generate_speech("hello", "af_heart")
        assert "500" in str(exc_info.value)


class TestKokoroConfig:
    """Tests for module-level configuration."""

    def test_voices(self):
        assert kokoro.VOICES == ("af_heart", "af_nicole")

    def test_default_voice(self):
        assert kokoro.DEFAULT_VOICE == "af_heart"

    def test_kokoro_host_config(self):
        assert kokoro.KOKORO_HOST == "192.168.1.59:8880"

    def test_kokoro_host_from_env(self):
        import os
        import importlib
        original = os.environ.get("KOKORO_HOST")
        try:
            os.environ["KOKORO_HOST"] = "remote:8880"
            # Need to reimport to pick up env var
            importlib.reload(kokoro)
            assert kokoro.KOKORO_HOST == "remote:8880"
        finally:
            if original:
                os.environ["KOKORO_HOST"] = original
            else:
                os.environ.pop("KOKORO_HOST", None)
            importlib.reload(kokoro)
