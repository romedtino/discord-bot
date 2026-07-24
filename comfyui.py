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

_WORKFLOW_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "workflows", "t2i.json"
)

with open(_WORKFLOW_PATH, "r") as _f:
    BASE_WORKFLOW = json.load(_f)

logger.info("ComfyUI target: http://%s", COMFYUI_HOST)


def modify_workflow(workflow, user_prompt, steps=None):
    modified = json.loads(json.dumps(workflow))
    # Feed the prompt directly to the PrimitiveStringMultiline node (node 76),
    # which is referenced by the positive CLIPTextEncode node (75:74).
    modified["76"]["inputs"]["value"] = user_prompt
    modified["75:73"]["inputs"]["noise_seed"] = random.randint(0, 2**64 - 1)
    if steps is not None:
        modified["75:62"]["inputs"]["steps"] = steps
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
            if last_node == "94":
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
    return images.get("94", [])


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
