import io
import asyncio
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
@app_commands.describe(prompt="Text description of the image to generate.", steps="Number of diffusion steps (2-4). Higher values produce more detailed images but take longer.")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def genimg(
    interaction: discord.Interaction,
    prompt: str,
    steps: discord.app_commands.Range[int, 2, 4] = 2,
):
    await interaction.response.defer(thinking=True)
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
