from urllib import request
from unittest.mock import patch, MagicMock, mock_open

import json
import pytest

import comfyui


class TestModifyWorkflow:
    """Tests for the modify_workflow function."""

    def test_minimax_h3_replaces_prompt_here(self):
        """Verify that 'PROMPT HERE' placeholder in LlamaCppRouterClient gets replaced."""
        import os
        original_workflow = comfyui.BASE_WORKFLOW
        try:
            wf_path = os.path.join(os.path.dirname(comfyui.__file__), "workflows", "minimax_h3.json")
            with open(wf_path, "r") as f:
                minimax_wf = json.load(f)
            result = comfyui.modify_workflow(minimax_wf, "a dancing cat")
            # Node 634 (LlamaCppRouterClient) has 'prompt': 'PROMPT HERE' which gets replaced
            assert result["634"]["inputs"]["prompt"] == "a dancing cat"
        finally:
            comfyui.BASE_WORKFLOW = original_workflow

    def test_replaces_prompt_in_node_76(self):
        wf = comfyui.BASE_WORKFLOW
        result = comfyui.modify_workflow(wf, "a sunset")
        assert result["76"]["inputs"]["value"] == "a sunset"

    def test_preserves_other_fields_in_node_76(self):
        wf = comfyui.BASE_WORKFLOW
        result = comfyui.modify_workflow(wf, "a sunset")
        assert result["76"]["inputs"]["value"] == "a sunset"
        assert result["75:74"]["inputs"]["text"] == ["76", 0]

    def test_steps_overrides_flux2_scheduler(self):
        wf = comfyui.BASE_WORKFLOW
        result = comfyui.modify_workflow(wf, "a sunset", steps=5)
        assert result["75:62"]["inputs"]["steps"] == 5

    def test_steps_none_preserves_default(self):
        wf = comfyui.BASE_WORKFLOW
        default_steps = wf["75:62"]["inputs"]["steps"]
        result = comfyui.modify_workflow(wf, "a sunset", steps=None)
        assert result["75:62"]["inputs"]["steps"] == default_steps


class TestQueuePrompt:
    """Tests for the queue_prompt function."""

    @patch("comfyui.request.urlopen")
    def test_posts_to_correct_url(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"prompt_id": "test-123"}'
        mock_urlopen.return_value = mock_response

        comfyui.queue_prompt({}, "client-1")

        args = mock_urlopen.call_args
        req = args[0][0]
        assert f"http://{comfyui.COMFYUI_HOST}/prompt" in req.full_url
        body = json.loads(req.data)
        assert body["prompt"] == {}
        assert body["client_id"] == "client-1"

    @patch("comfyui.request.urlopen")
    def test_returns_parsed_response(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"prompt_id": "abc-456"}'
        mock_urlopen.return_value = mock_response

        result = comfyui.queue_prompt({}, "client-1")
        assert result["prompt_id"] == "abc-456"

    @patch("comfyui.request.urlopen")
    def test_raises_on_http_error(self, mock_urlopen):
        error = request.HTTPError(
            "http://localhost:7861/prompt", 500, "error",
            {}, MagicMock()
        )
        error.read = lambda: b'{"error": "bad workflow"}'
        mock_urlopen.side_effect = error

        with pytest.raises(RuntimeError) as exc_info:
            comfyui.queue_prompt({}, "client-1")
        assert "500" in str(exc_info.value)


class TestGenerate:
    """Tests for the generate function."""

    @patch("comfyui.get_images")
    def test_returns_images_list(self, mock_get_images):
        mock_get_images.return_value = {
            "94": [b"\x89PNG\x0d\x0a"]
        }
        result = comfyui.generate("a sunset")
        assert isinstance(result, list)
        assert len(result) == 1

    @patch("comfyui.get_images")
    def test_returns_empty_list_when_no_images(self, mock_get_images):
        mock_get_images.return_value = {}
        result = comfyui.generate("a sunset")
        assert result == []

    @patch("comfyui.get_images")
    def test_raises_on_error_response(self, mock_get_images):
        mock_get_images.return_value = {"__error__": ["KSampler"]}
        with pytest.raises(RuntimeError) as exc_info:
            comfyui.generate("a sunset")
        assert "KSampler" in str(exc_info.value)

    @patch("comfyui.get_images")
    def test_passes_steps_to_get_images(self, mock_get_images):
        mock_get_images.return_value = {"save_image_websocket_node": [b"img"]}
        comfyui.generate("a sunset", steps=6)
        mock_get_images.assert_called_once_with("a sunset", 6)


class TestGetImages:
    """Tests for the get_images function."""

    @patch("comfyui.queue_prompt")
    @patch("comfyui.WebSocket")
    def test_closes_ws_on_completion(self, mock_ws_class, mock_queue):
        mock_queue.return_value = {"prompt_id": "pid"}
        ws = MagicMock()
        ws_class_iter = iter([
            json.dumps({"type": "executing", "data": {"node": "2", "prompt_id": "pid"}}),
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": "pid"}}),
        ])
        ws.recv.side_effect = lambda: next(ws_class_iter)
        mock_ws_class.return_value = ws

        comfyui.get_images("a sunset")
        ws.close.assert_called_once()

    @patch("comfyui.queue_prompt")
    @patch("comfyui.WebSocket")
    def test_captures_binary_image_data(self, mock_ws_class, mock_queue):
        mock_queue.return_value = {"prompt_id": "pid"}
        ws = MagicMock()
        ws_class_iter = iter([
            json.dumps({"type": "executing", "data": {"node": "75:62", "prompt_id": "pid"}}),
            json.dumps({"type": "executing", "data": {"node": "94", "prompt_id": "pid"}}),
            b"\x00\x00\x00\x00\x00\x00\x00\x00PNGDATA123",
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": "pid"}}),
        ])
        ws.recv.side_effect = lambda: next(ws_class_iter)
        mock_ws_class.return_value = ws

        result = comfyui.get_images("a sunset")
        images = result.get("94", [])
        assert len(images) == 1
        # First 8 bytes (type/meta) stripped
        assert images[0] == b"PNGDATA123"

    @patch("comfyui.queue_prompt")
    @patch("comfyui.WebSocket")
    def test_detects_execution_error(self, mock_ws_class, mock_queue):
        mock_queue.return_value = {"prompt_id": "pid"}
        ws = MagicMock()
        ws_class_iter = iter([
            json.dumps({"type": "executing", "data": {"node": "2", "prompt_id": "pid"}}),
            json.dumps({
                "type": "execution_error",
                "data": {"node_type": "KSampler", "prompt_id": "pid"},
            }),
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": "pid"}}),
        ])
        ws.recv.side_effect = lambda: next(ws_class_iter)
        mock_ws_class.return_value = ws

        result = comfyui.get_images("a sunset")
        assert "__error__" in result
        assert "KSampler" in result["__error__"]

    @patch("comfyui.queue_prompt")
    @patch("comfyui.WebSocket")
    def test_ignores_binary_data_from_other_nodes(self, mock_ws_class, mock_queue):
        mock_queue.return_value = {"prompt_id": "pid"}
        ws = MagicMock()
        ws_class_iter = iter([
            json.dumps({"type": "executing", "data": {"node": "2", "prompt_id": "pid"}}),
            b"\x00\x00\x00\x00\x00\x00\x00\x00OTHERNODE",
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": "pid"}}),
        ])
        ws.recv.side_effect = lambda: next(ws_class_iter)
        mock_ws_class.return_value = ws

        result = comfyui.get_images("a sunset")
        assert "OTHERNODE" not in str(result)

    @patch("comfyui.queue_prompt")
    @patch("comfyui.WebSocket")
    def test_returns_empty_on_ws_timeout(self, mock_ws_class, mock_queue):
        mock_queue.return_value = {"prompt_id": "pid"}
        ws = MagicMock()
        ws.recv.side_effect = Exception("timeout")
        mock_ws_class.return_value = ws

        result = comfyui.get_images("a sunset")
        assert result == {}
        ws.close.assert_called_once()

    @patch("comfyui.queue_prompt")
    @patch("comfyui.WebSocket")
    def test_passes_steps_to_modify_workflow(self, mock_ws_class, mock_queue):
        mock_queue.return_value = {"prompt_id": "pid"}
        ws = MagicMock()
        ws_class_iter = iter([
            json.dumps({"type": "executing", "data": {"node": "2", "prompt_id": "pid"}}),
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": "pid"}}),
        ])
        ws.recv.side_effect = lambda: next(ws_class_iter)
        mock_ws_class.return_value = ws

        with patch("comfyui.modify_workflow", wraps=comfyui.modify_workflow) as mock_modify:
            comfyui.get_images("a sunset", steps=7)
            args, _ = mock_modify.call_args
            assert args[2] == 7


class TestWorkflowIntegrity:
    """Tests to ensure the base workflow is loadable and well-formed."""

    def test_base_workflow_loaded(self):
        assert "76" in comfyui.BASE_WORKFLOW
        assert "94" in comfyui.BASE_WORKFLOW

    def test_base_workflow_has_save_image_websocket_node(self):
        save_node = comfyui.BASE_WORKFLOW["94"]
        assert save_node["class_type"] == "SaveImageWebsocket"

    def test_base_workflow_has_clip_text_encode(self):
        clip_node = comfyui.BASE_WORKFLOW["75:74"]
        assert clip_node["class_type"] == "CLIPTextEncode"

    def test_comfyui_host_config(self):
        assert comfyui.COMFYUI_HOST == "localhost:7861"

    def test_comfyui_host_from_env(self):
        import os
        original = os.environ.get("COMFYUI_HOST")
        try:
            os.environ["COMFYUI_HOST"] = "remote:8188"
            # Need to reimport to pick up env var
            import importlib
            importlib.reload(comfyui)
            assert comfyui.COMFYUI_HOST == "remote:8188"
        finally:
            if original:
                os.environ["COMFYUI_HOST"] = original
            else:
                os.environ.pop("COMFYUI_HOST", None)


class TestGenerateVideo:
    """Tests for the generate_video function."""

    @patch("comfyui._generate_video")
    def test_returns_video_bytes(self, mock_generate):
        mock_generate.return_value = {"629": [b"\x00MP4DATA"]}
        result = comfyui.generate_video("a video of a cat")
        assert isinstance(result, bytes)
        assert result == b"\x00MP4DATA"

    @patch("comfyui._generate_video")
    def test_returns_none_when_no_video(self, mock_generate):
        mock_generate.return_value = {}
        result = comfyui.generate_video("a video of a cat")
        assert result is None

    @patch("comfyui._generate_video")
    def test_raises_on_error_response(self, mock_generate):
        mock_generate.return_value = {"__error__": ["VAELoader"]}
        with pytest.raises(RuntimeError) as exc_info:
            comfyui.generate_video("a video of a cat")
        assert "VAELoader" in str(exc_info.value)

    @patch("comfyui._generate_video")
    def test_passes_workflow_and_prompt(self, mock_generate):
        mock_generate.return_value = {"629": [b"video"]}
        comfyui.generate_video("test prompt")
        mock_generate.assert_called_once()
        args = mock_generate.call_args
        assert args[0][1] == "test prompt"  # second positional arg is user_prompt


class TestParseVideoBinary:
    """Tests for the _parse_video_binary helper."""

    def test_parses_mp4_frame(self):
        import struct
        fmt = b"mp4"
        header = b'VIDF' + struct.pack("<I", len(fmt)) + fmt
        video_payload = b"\x00\x01\x02MP4CONTENT"
        # ComfyUI wraps with 4-byte big-endian event type (100)
        frame = struct.pack(">I", 100) + header + video_payload

        video_bytes, format_str = comfyui._parse_video_binary(frame)
        assert video_bytes == b"\x00\x01\x02MP4CONTENT"
        assert format_str == "mp4"

    def test_parses_webm_frame(self):
        import struct
        fmt = b"webm"
        header = b'VIDF' + struct.pack("<I", len(fmt)) + fmt
        video_payload = b"WEBM_CONTENT_HERE"
        # ComfyUI wraps with 4-byte big-endian event type (100)
        frame = struct.pack(">I", 100) + header + video_payload

        video_bytes, format_str = comfyui._parse_video_binary(frame)
        assert video_bytes == b"WEBM_CONTENT_HERE"
        assert format_str == "webm"

    def test_raises_on_too_short_data(self):
        with pytest.raises(ValueError):
            comfyui._parse_video_binary(b"short")

    def test_raises_on_bad_magic(self):
        import struct
        header = b"XXXX" + struct.pack("<I", 3) + b"mp4"
        frame = struct.pack(">I", 100) + header + b"data"
        with pytest.raises(ValueError) as exc_info:
            comfyui._parse_video_binary(frame)
        assert "VIDF" in str(exc_info.value)


class TestGetVideo:
    """Tests for the get_video function."""

    @patch("comfyui.queue_prompt")
    @patch("comfyui.WebSocket")
    def test_closes_ws_on_completion(self, mock_ws_class, mock_queue):
        mock_queue.return_value = {"prompt_id": "pid"}
        ws = MagicMock()
        ws_class_iter = iter([
            json.dumps({"type": "executing", "data": {"node": "2", "prompt_id": "pid"}}),
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": "pid"}}),
        ])
        ws.recv.side_effect = lambda: next(ws_class_iter)
        mock_ws_class.return_value = ws

        # Need a workflow with SaveVideoWebsocket node
        import os
        original_workflow = comfyui.BASE_WORKFLOW
        try:
            wf_path = os.path.join(os.path.dirname(comfyui.__file__), "workflows", "minimax_h3.json")
            with open(wf_path, "r") as f:
                workflow = json.load(f)
            result = comfyui.get_video(workflow, "a video")
        finally:
            comfyui.BASE_WORKFLOW = original_workflow
        ws.close.assert_called_once()

    @patch("comfyui.queue_prompt")
    @patch("comfyui.WebSocket")
    def test_captures_binary_video_data(self, mock_ws_class, mock_queue):
        import struct
        # Build VIDF protocol frame: [event_type_BE=100][VIDF][fmt_len_LE='mp4'][video]
        fmt = b"mp4"
        header = b"VIDF" + struct.pack("<I", len(fmt)) + fmt
        video_payload = b"MP4DATA123"
        ws_frame = struct.pack(">I", 100) + header + video_payload  # 4-byte BE event type + VIDF frame

        mock_queue.return_value = {"prompt_id": "pid"}
        ws = MagicMock()
        ws_class_iter = iter([
            json.dumps({"type": "executing", "data": {"node": "2", "prompt_id": "pid"}}),
            json.dumps({"type": "executing", "data": {"node": "631", "prompt_id": "pid"}}),
            ws_frame,
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": "pid"}}),
        ])
        ws.recv.side_effect = lambda: next(ws_class_iter)
        mock_ws_class.return_value = ws

        import os
        original_workflow = comfyui.BASE_WORKFLOW
        try:
            wf_path = os.path.join(os.path.dirname(comfyui.__file__), "workflows", "minimax_h3.json")
            with open(wf_path, "r") as f:
                workflow = json.load(f)
            result = comfyui.get_video(workflow, "a video")
        finally:
            comfyui.BASE_WORKFLOW = original_workflow

        video_data = result.get("629", [])
        assert len(video_data) == 1
        assert video_data[0] == b"MP4DATA123"

    @patch("comfyui.queue_prompt")
    @patch("comfyui.WebSocket")
    def test_detects_execution_error(self, mock_ws_class, mock_queue):
        mock_queue.return_value = {"prompt_id": "pid"}
        ws = MagicMock()
        ws_class_iter = iter([
            json.dumps({"type": "executing", "data": {"node": "2", "prompt_id": "pid"}}),
            json.dumps({
                "type": "execution_error",
                "data": {"node_type": "KSampler", "prompt_id": "pid"},
            }),
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": "pid"}}),
        ])
        ws.recv.side_effect = lambda: next(ws_class_iter)
        mock_ws_class.return_value = ws

        import os
        original_workflow = comfyui.BASE_WORKFLOW
        try:
            wf_path = os.path.join(os.path.dirname(comfyui.__file__), "workflows", "minimax_h3.json")
            with open(wf_path, "r") as f:
                workflow = json.load(f)
            result = comfyui.get_video(workflow, "a video")
        finally:
            comfyui.BASE_WORKFLOW = original_workflow

        assert "__error__" in result
        assert "KSampler" in result["__error__"]
