import io
import json
import logging
import random
import sys
import uuid
import os
from urllib import request
from websocket import WebSocket
from PIL import Image

logger = logging.getLogger(__name__)

COMFYUI_HOST = os.getenv("COMFYUI_HOST", "localhost:7861")
WORKFLOW_FILE = os.getenv("WORKFLOW_FILE", "t2i")

_STEPS_CONFIG = {
    "t2i": (2, 4, 2),
    "t2i-zimage": (4, 9, 4),
    "krea": (4, 8, 4),
}
STEPS_MIN, STEPS_MAX, STEPS_DEFAULT = _STEPS_CONFIG.get(WORKFLOW_FILE, (2, 4, 2))

_WORKFLOW_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "workflows", f"{WORKFLOW_FILE}.json"
)

with open(_WORKFLOW_PATH, "r") as _f:
    BASE_WORKFLOW = json.load(_f)

logger.info("ComfyUI target: http://%s", COMFYUI_HOST)
logger.info("Workflow file: %s", _WORKFLOW_PATH)


def _find_node_by_class(workflow, class_type):
    for node_id, node_data in workflow.items():
        if node_data.get("class_type") == class_type:
            return node_id
    return None


def _find_positive_prompt_node(workflow):
    prompt_node = _find_node_by_class(workflow, "PrimitiveStringMultiline")
    if prompt_node is not None:
        return prompt_node, "value"
    for node_id, node_data in workflow.items():
        inputs = node_data.get("inputs", {})
        # Check for "text" key (CLIPTextEncode and similar)
        if isinstance(inputs.get("text"), str) and inputs["text"]:
            return node_id, "text"
        # Check for "prompt" key (MiniMaxH3ImageToVideo and similar)
        if isinstance(inputs.get("prompt"), str) and inputs["prompt"]:
            return node_id, "prompt"
    return None, None


def _find_sampler_seed_node(workflow):
    random_noise = _find_node_by_class(workflow, "RandomNoise")
    if random_noise is not None:
        return random_noise, "noise_seed"
    kSampler = _find_node_by_class(workflow, "KSampler")
    if kSampler is not None and "seed" in workflow[kSampler].get("inputs", {}):
        return kSampler, "seed"
    kSamplerAdvanced = _find_node_by_class(workflow, "KSamplerAdvanced")
    if kSamplerAdvanced is not None and "noise" in workflow[kSamplerAdvanced].get("inputs", {}):
        noise_key = None
        for key in ("noise_seed", "seed"):
            if key in workflow[kSamplerAdvanced].get("inputs", {}).get("noise", {}):
                noise_key = key
                break
        return kSamplerAdvanced, noise_key
    return None, None


def _find_steps_node(workflow):
    for key in ("Flux2Scheduler", "KSampler", "KSamplerAdvanced", "Scheduler"):
        node_id = _find_node_by_class(workflow, key)
        if node_id is not None and "steps" in workflow[node_id].get("inputs", {}):
            return node_id, "steps"
    return None, None


def modify_workflow(workflow, user_prompt, steps=None):
    modified = json.loads(json.dumps(workflow))
    prompt_node, prompt_key = _find_positive_prompt_node(modified)
    if prompt_node is not None:
        modified[prompt_node]["inputs"][prompt_key] = user_prompt
    seed_node, seed_key = _find_sampler_seed_node(modified)
    if seed_node is not None and seed_key is not None:
        modified[seed_node]["inputs"][seed_key] = random.randint(0, 2**64 - 1)
    steps_node, steps_key = _find_steps_node(modified)
    if steps_node is not None and steps is not None and steps_key is not None:
        modified[steps_node]["inputs"][steps_key] = steps
    return modified


def queue_prompt(prompt, client_id):
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode("utf-8")
    req = request.Request(
        f"http://{COMFYUI_HOST}/prompt", data=data
    )
    try:
        return json.loads(request.urlopen(req).read())
    except request.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(
            f"ComfyUI returned {e.code}: {body}"
        ) from e


def get_images(user_prompt, steps=None):
    client_id = str(uuid.uuid4())
    workflow = modify_workflow(BASE_WORKFLOW, user_prompt, steps)
    output_node = _find_node_by_class(workflow, "SaveImageWebsocket")
    result = queue_prompt(workflow, client_id)
    prompt_id = result["prompt_id"]

    ws = WebSocket()
    ws.connect(f"ws://{COMFYUI_HOST}/ws?clientId={client_id}")
    ws.settimeout(120)

    output_images = {}
    current_node = ""
    last_node = ""
    error_nodes = []

    while True:
        try:
            out = ws.recv()
        except Exception:
            ws.close()
            return output_images
        if isinstance(out, str):
            message = json.loads(out)
            msg_type = message.get("type")
            if msg_type == "executing":
                data = message["data"]
                if data.get("node") is None:
                    break
                if data.get("prompt_id") == prompt_id:
                    current_node = data["node"]
                    last_node = current_node
            elif msg_type == "execution_error":
                data = message["data"]
                if data.get("prompt_id") == prompt_id:
                    error_nodes.append(data.get("node_type"))
        else:
            if output_node and last_node == output_node:
                images_output = output_images.get(last_node, [])
                images_output.append(out[8:])
                output_images[last_node] = images_output

    ws.close()
    if error_nodes:
        return {"__error__": error_nodes}
    return output_images


def generate(user_prompt, steps=None):
    """Run a full generation and return a list of raw image bytes."""
    images = get_images(user_prompt, steps)
    if "__error__" in images:
        raise RuntimeError(f"ComfyUI generation failed: {images['__error__']}")
    if not images:
        return []
    return next(iter(images.values()))


def _get_output(workflow, class_type):
    """Find a node by class type and return its node id."""
    for node_id, node_data in workflow.items():
        if node_data.get("class_type") == class_type:
            return node_id
    return None


def _parse_video_binary(data):
    """Parse the SaveVideoWebsocket binary protocol.

    ComfyUI wraps all binary messages with a 4-byte big-endian event type.
    The SaveVideoWebsocket node sends VIDF frames as event type 100.
    Wire format: [event_type_BE uint32][VIDF magic][format_len_LE][format_str][video_data]

    Returns (video_bytes, format_string) or raises ValueError on bad format.
    """
    import struct as _struct

    if len(data) < 13:
        raise ValueError(f"Video data too short ({len(data)} bytes), expected at least 13")

    # Bytes 0-3: ComfyUI event type (big-endian uint32, 100 for video)
    event_type = _struct.unpack(">I", data[0:4])[0]

    # Bytes 4-7: Magic 'VIDF'
    magic = data[4:8]
    if magic != b'VIDF':
        raise ValueError(
            f"Expected VIDF magic bytes at offset 4, got {magic!r} "
            f"(event_type={event_type}, first_16_bytes={data[:16].hex()})"
        )

    # Bytes 8-11: Format length (little-endian uint32)
    fmt_len = _struct.unpack('<I', data[8:12])[0]

    # Bytes 12..12+fmt_len: Format string (e.g. 'mp4')
    format_str = data[12:12 + fmt_len].decode('utf-8')

    # Rest: raw video data
    video_bytes = data[12 + fmt_len:]
    if not video_bytes:
        raise ValueError("Video payload is empty")

    return video_bytes, format_str


def get_video(workflow_template, user_prompt):
    """Run a video generation workflow (minimax_h3) and return raw mp4 bytes."""
    client_id = str(uuid.uuid4())
    workflow = modify_workflow(workflow_template, user_prompt)
    output_node = _get_output(workflow, "SaveVideoWebsocket")
    logger.info("Video generation: output_node=%s", output_node)

    result = queue_prompt(workflow, client_id)
    prompt_id = result["prompt_id"]
    logger.info("Video generation: queued prompt_id=%s", prompt_id)

    ws = WebSocket()
    ws.connect(f"ws://{COMFYUI_HOST}/ws?clientId={client_id}")
    ws.settimeout(120)

    video_data = None
    current_node = ""
    last_node = ""
    error_nodes = []
    message_count = 0
    all_executing_nodes = set()
    all_executed_nodes = set()
    executed_nodes = set()  # Track nodes that completed execution

    while True:
        try:
            out = ws.recv()
        except Exception as e:
            logger.warning("Video generation: websocket exception: %s", e)
            logger.info("Video generation: collected nodes - executing=%s, executed=%s",
                       all_executing_nodes, all_executed_nodes)
            ws.close()
            return {"__error__": ["websocket_timeout"]}
        if isinstance(out, str):
            message = json.loads(out)
            msg_type = message.get("type")
            data = message.get("data", {})
            msg_prompt_id = data.get("prompt_id")

            if msg_type == "executing":
                node = data.get("node")
                all_executing_nodes.add(str(node) if node else "<completion>")
                logger.info("Video generation: executing message node=%s prompt_id=%s (our=%s)",
                           node, msg_prompt_id, prompt_id)
                if node is None:
                    logger.info("Video generation: execution complete (node=None), messages=%d, video_data=%s",
                               message_count, bool(video_data))
                    break
                if msg_prompt_id == prompt_id:
                    current_node = data["node"]
                    last_node = current_node
                    logger.info("Video generation: MATCHED executing node %s", current_node)
            elif msg_type == "execution_error":
                all_executing_nodes.add("<error>")
                if msg_prompt_id == prompt_id:
                    error_nodes.append(data.get("node_type"))
                    logger.error("Video generation: execution_error from node_type=%s", data.get("node_type"))
            elif msg_type == "executed":
                executed_node = data.get("node")
                all_executed_nodes.add(str(executed_node) if executed_node else "<unknown>")
                output_keys = list(data.get("output", {}).keys()) if isinstance(data.get("output"), dict) else "N/A"
                logger.info("Video generation: executed node=%s prompt_id=%s (our=%s) output=%s",
                           executed_node, msg_prompt_id, prompt_id, output_keys)
                # Track completed nodes for binary data matching
                if msg_prompt_id == prompt_id and executed_node:
                    executed_nodes.add(executed_node)
            elif msg_type == "status":
                logger.debug("Video generation: status message %s", data.get("status", {}))
        else:
            message_count += 1
            first_bytes = out[:20].hex() if len(out) >= 20 else out.hex()
            logger.info("Video generation: binary #%d last_node=%s output_node=%s len=%d first=%s",
                       message_count, last_node, output_node, len(out), first_bytes)
            if output_node:
                # Try strict match with last_node first
                if last_node == output_node:
                    try:
                        video_data, fmt = _parse_video_binary(out)
                        logger.info("Video generation: parsed video from last_node match (%d bytes, format=%s)",
                                   len(video_data), fmt)
                    except ValueError as e:
                        logger.warning("Failed to parse SaveVideoWebsocket data (last_node match): %s", e)
                # Fallback: check if output_node completed execution
                # SaveVideoWebsocket may not send an "executing" message, so last_node might be stale
                elif output_node in executed_nodes:
                    try:
                        video_data, fmt = _parse_video_binary(out)
                        logger.info("Video generation: parsed video from executed_nodes match (%d bytes, format=%s)",
                                   len(video_data), fmt)
                    except ValueError as e:
                        logger.warning("Failed to parse SaveVideoWebsocket data (executed_nodes match): %s", e)
                else:
                    # Last resort: try parsing any binary from our prompt
                    # This handles cases where SaveVideoWebsocket doesn't send "executing"/"executed" messages
                    logger.info("Video generation: binary from unknown node, attempting parse as fallback")
                    try:
                        video_data, fmt = _parse_video_binary(out)
                        logger.info("Video generation: parsed video from fallback (%d bytes, format=%s)",
                                   len(video_data), fmt)
                    except ValueError:
                        logger.debug("Not a SaveVideoWebsocket message (skipped)")

    ws.close()
    logger.info("Video generation: final state - error_nodes=%s, video_data=%d bytes, all_executing=%s, all_executed=%s",
               error_nodes, len(video_data) if video_data else 0,
               sorted(all_executing_nodes), sorted(all_executed_nodes))
    if error_nodes:
        return {"__error__": error_nodes}
    if not video_data:
        return {"__error__": ["no_video_output"]}
    return {output_node: [video_data]}


def _generate_video(workflow_template, user_prompt):
    """Run a full video generation and return raw mp4 bytes."""
    result = get_video(workflow_template, user_prompt)
    if "__error__" in result:
        raise RuntimeError(f"ComfyUI video generation failed: {result['__error__']}")
    if not result:
        return None
    video_list = next(iter(result.values()))
    if not video_list:
        return None
    return video_list[0]


def generate_video(user_prompt):
    """Run a full video generation using BASE_WORKFLOW and return raw mp4 bytes."""
    result = _generate_video(BASE_WORKFLOW, user_prompt)
    if "__error__" in result:
        raise RuntimeError(f"ComfyUI video generation failed: {result['__error__']}")
    if not result:
        return None
    video_list = next(iter(result.values()))
    if not video_list:
        return None
    return video_list[0]


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(level=logging.INFO)
    prompt = sys.argv[1] if len(sys.argv) > 1 else "a cat"
    logger.info("Generating: %s", prompt)
    image_data_list = generate(prompt)
    if not image_data_list:
        logger.warning("No images generated.")
        sys.exit(1)
    for i, image_data in enumerate(image_data_list):
        img = Image.open(io.BytesIO(image_data))
        img.show()
