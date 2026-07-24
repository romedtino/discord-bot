from urllib import request
from unittest.mock import patch, MagicMock, mock_open

import json
import pytest

import comfyui


class TestModifyWorkflow:
    """Tests for the modify_workflow function."""

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
