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
        if (node_data.get("class_type") == "CLIPTextEncode"
                and isinstance(node_data.get("inputs", {}).get("text"), str)
                and node_data.get("inputs", {}).get("text")):
            return node_id, "text"
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
