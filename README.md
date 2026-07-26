# Discord ComfyUI Image Generation Bot

A Discord bot that generates images using ComfyUI via a `/generate` slash command.

## Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure ComfyUI

Ensure ComfyUI is running on `localhost:7861`. To use a different host:

```bash
export COMFYUI_HOST="your-host:8188"
```

### 3. Configure Discord

1. Create a [Discord application](https://discord.com/developers/applications)
2. Enable **Message Content Intent** under Bot settings
3. Invite the bot to your server with the `applications.commands` scope
4. Set the bot token:

```bash
export DISCORD_BOT_TOKEN="your-bot-token"
```

## Usage

### Discord command

Use `/genimg` in any channel the bot has access to:

```
/genimg prompt: a cat sitting on a windowsill
```

The bot will respond with the generated image(s).

### ComfyUI standalone

Generate images from the command line without the Discord bot:

```bash
uv run python -m comfyui "a sunset over mountains"
```

Or import the module:

```python
import comfyui

images = comfyui.generate("a sunset over mountains")
```

## Testing

```bash
uv run pytest tests/ -v
```

## Structure

```
comfyui.py        - ComfyUI API logic (modify workflow, queue prompt, get images)
bot.py            - Discord bot with /genimg command
main.py           - Entry point (runs the bot)
workflows/t2i.json - ComfyUI workflow (text-to-image with SaveImageWebsocket)
tests/            - Unit tests
```

## Workflow

The bot uses `workflows/t2i.json` — an exported ComfyUI workflow that:
- Takes a text prompt
- Generates an image via the KSampler node
- Streams the result through `SaveImageWebsocket`
- Returns image bytes via WebSocket binary frames

The prompt is injected directly into the `CLIPTextEncode` node (node 6), bypassing the LLM client node (node 28).
