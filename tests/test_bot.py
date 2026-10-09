import pytest
import discord.ext.commands
from discord.utils import MISSING


def test_bot_app_exists():
    import bot
    assert hasattr(bot, "app")


def test_bot_is_bot_instance():
    import bot
    assert isinstance(bot.app, discord.ext.commands.Bot)


def test_genimg_command_registered():
    import bot
    cmd = bot.app.tree.get_command("genimg")
    assert cmd is not None


def test_genimg_command_has_prompt_parameter():
    import bot
    cmd = bot.app.tree.get_command("genimg")
    params = cmd.parameters
    assert len(params) == 2
    assert params[0].name == "prompt"
    assert params[0].required is True
    assert params[1].name == "steps"
    assert params[1].required is False


def test_genvid_command_registered():
    import bot
    cmd = bot.app.tree.get_command("genvid")
    assert cmd is not None


def test_genvid_has_prompt_parameter():
    import bot
    cmd =(bot.app.tree.get_command("genvid"))
    params = cmd.parameters
    assert len(params) == 2
    assert params[0].name == "prompt"
    assert params[0].required is True
    assert params[1].name == "duration"
    assert params[1].required is False


def test_genspeech_command_registered():
    import bot
    cmd = bot.app.tree.get_command("genspeech")
    assert cmd is not None


def test_genspeech_command_has_input_and_voice_parameters():
    import bot
    cmd = bot.app.tree.get_command("genspeech")
    params = cmd.parameters
    assert len(params) == 2
    assert params[0].name == "input"
    assert params[0].required is True
    assert params[1].name == "voice"
    assert params[1].required is False


def test_genspeech_voice_parameter_has_no_static_choices():
    import bot
    cmd = bot.app.tree.get_command("genspeech")
    params = cmd.parameters
    voice_param = params[1]
    # No static choices (Discord would reject any typed value outside the
    # list); the dropdown is driven by an autocomplete handler instead.
    assert voice_param.choices == []


def test_voice_autocomplete_empty_query_shows_first_25():
    import asyncio
    import bot
    original = bot._VOICE_IDS
    try:
        bot._VOICE_IDS = [f"v{i:02d}" for i in range(40)]
        choices = asyncio.run(bot.voice_autocomplete(None, ""))
        assert len(choices) == bot.VOICE_SUGGESTION_LIMIT == 25
        assert [c.value for c in choices] == bot._VOICE_IDS[:25]
    finally:
        bot._VOICE_IDS = original


def test_voice_autocomplete_finds_voice_beyond_first_25():
    import asyncio
    import bot
    original = bot._VOICE_IDS
    try:
        bot._VOICE_IDS = [f"v{i:02d}" for i in range(70)] + [
            "pm_santa", "pm_versatile", "af_heart", "af_nicole",
        ]
        choices = asyncio.run(bot.voice_autocomplete(None, "pm_santa"))
        assert [c.value for c in choices] == ["pm_santa"]
    finally:
        bot._VOICE_IDS = original


def test_voice_autocomplete_prefix_matches_first():
    import asyncio
    import bot
    original = bot._VOICE_IDS
    try:
        bot._VOICE_IDS = [f"v{i:02d}" for i in range(70)] + [
            "pm_santa", "pm_versatile", "af_heart", "af_nicole",
        ]
        choices = asyncio.run(bot.voice_autocomplete(None, "pm"))
        assert [c.value for c in choices] == ["pm_santa", "pm_versatile"]
    finally:
        bot._VOICE_IDS = original


def test_voice_autocomplete_no_match_returns_empty():
    import asyncio
    import bot
    original = bot._VOICE_IDS
    try:
        bot._VOICE_IDS = ["af_heart", "af_nicole"]
        assert asyncio.run(bot.voice_autocomplete(None, "zzz")) == []
    finally:
        bot._VOICE_IDS = original


def test_voice_parameter_default_and_optional():
    import bot
    cmd = bot.app.tree.get_command("genspeech")
    voice_param = cmd.parameters[1]
    assert voice_param.required is False
    assert voice_param.default == bot.kokoro.DEFAULT_VOICE


def test_voice_parameter_sync_payload_has_no_choices():
    import bot
    cmd = bot.app.tree.get_command("genspeech")
    payload = cmd.to_dict(bot.app.tree)
    options = {o["name"]: o for o in payload["options"]}
    # No "choices" key: the Discord client accepts any typed voice and
    # asks the bot for autocomplete suggestions instead.
    assert "choices" not in options["voice"]
