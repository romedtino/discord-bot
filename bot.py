import io
import asyncio
import json
import logging
import os
from pathlib import Path

import discord
from discord.ext import commands
from discord import app_commands
from PIL import Image

import comfyui

INTENTS = discord.Intents.default()
INTENTS.message_content = True

app = commands.Bot(intents=INTENTS, command_prefix=None)

logger = logging.getLogger(__name__)


@app_commands.command(name="genimg", description="Generate an image given a prompt.")
@app_commands.describe(prompt="Text description of the image to generate.", steps="Number of diffusion steps.")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def genimg(
    interaction: discord.Interaction,
    prompt: str,
    steps: int = comfyui.STEPS_DEFAULT,
):
    await interaction.response.defer(thinking=True)
    if steps < comfyui.STEPS_MIN or steps > comfyui.STEPS_MAX:
        await interaction.followup.send(
            f"Steps must be between {comfyui.STEPS_MIN} and {comfyui.STEPS_MAX} for this workflow."
        )
        return
    try:
        loop = asyncio.get_running_loop()
        image_data_list = await loop.run_in_executor(None, comfyui.generate, prompt, steps)
    except Exception as e:
        await interaction.followup.send(f"Error communicating with ComfyUI: {e}")
        return
    if not image_data_list:
        await interaction.followup.send(
            "No images were generated. The generation may have failed."
        )
        return
    for i, image_data in enumerate(image_data_list):
        img = Image.open(io.BytesIO(image_data))
        output = io.BytesIO()
        img.save(output, format="PNG")
        output.seek(0)
        file = discord.File(output, filename=f"image_{i + 1}.png")
        await interaction.followup.send(
            content=f"{interaction.user.mention} requested({steps}): {prompt}",
            file=file
        )

app.tree.add_command(genimg)


_WORKFLOWS_DIR = os.path.join(os.path.dirname(comfyui.__file__), "workflows")


def _load_workflow(workflow_name):
    """Load a workflow JSON file from the workflows directory."""
    wf_path = os.path.join(_WORKFLOWS_DIR, f"{workflow_name}.json")
    with open(wf_path, "r") as f:
        return json.load(f)


@app_commands.command(name="genvid", description="Generate a video given a prompt.")
@app_commands.describe(prompt="Text description of the video to generate.")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def genvid(
    interaction: discord.Interaction,
    prompt: str,
):
    await interaction.response.defer(thinking=True)
    try:
        video_workflow = _load_workflow("minimax_h3")

        loop = asyncio.get_running_loop()
        video_data = await loop.run_in_executor(None, comfyui._generate_video, video_workflow, prompt)
    except Exception as e:
        await interaction.followup.send(f"Error communicating with ComfyUI: {e}")
        return

    if not video_data:
        await interaction.followup.send(
            "No video was generated. The generation may have failed."
        )
        return
    file = discord.File(io.BytesIO(video_data), filename="video.mp4")
    await interaction.followup.send(
        content=f"{interaction.user.mention} requested: {prompt}",
        file=file,
    )

app.tree.add_command(genvid)


@app.event
async def on_ready():
    logger.info("===== on_ready called! =====")
    logger.info("Logged in as %s", app.user)
    logger.info("In %d guilds", len(app.guilds))
    await _set_presence()
    try:
        synced = await app.tree.sync()
        logger.info("Global sync result: %s commands", len(synced))
    except Exception:
        logger.exception("Global sync failed")
    for guild in app.guilds:
        try:
            synced = await app.tree.sync(guild=guild)
            logger.info("Synced %d commands for guild '%s' (%s)", len(synced), guild.name, guild.id)
        except Exception:
            logger.exception("Failed to sync for guild '%s'", guild.name)
    logger.info("===== on_ready complete =====")


@app.event
async def on_guild_join(guild):
    await _set_presence()


@app.event
async def on_guild_remove(guild):
    await _set_presence()


async def _set_presence():
    await app.change_presence(
        activity=discord.Game(name=f"Chatting with {len(app.guilds)} dragons")
    )


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(level=logging.INFO)

    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN not found. "
            "Create a .env file with DISCORD_BOT_TOKEN=your-token"
        )
    app.run(token=token)
