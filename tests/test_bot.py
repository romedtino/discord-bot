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
    # Choices are fetched live from the TTS server in on_ready, so
    # nothing is baked in at definition time.
    assert voice_param.choices == []


def test_set_voice_choices():
    import bot
    cmd = bot.app.tree.get_command("genspeech")
    original = cmd._params["voice"].choices
    try:
        bot._set_voice_choices(["af_heart", "af_nicole"])
        choices = cmd.parameters[1].choices
        assert [c.value for c in choices] == ["af_heart", "af_nicole"]
        assert [c.name for c in choices] == ["af_heart", "af_nicole"]
    finally:
        cmd._params["voice"].choices = original


def test_voice_parameter_default_and_optional():
    import bot
    cmd = bot.app.tree.get_command("genspeech")
    voice_param = cmd.parameters[1]
    assert voice_param.required is False
    assert voice_param.default == bot.kokoro.DEFAULT_VOICE


def test_set_voice_choices_caps_at_discord_limit():
    import bot
    cmd = bot.app.tree.get_command("genspeech")
    original = cmd._params["voice"].choices
    try:
        ids = [f"v{i:02d}" for i in range(40)]
        bot._set_voice_choices(ids)
        choices = cmd.parameters[1].choices
        assert len(choices) == bot.DISCORD_CHOICE_LIMIT == 25
        assert [c.value for c in choices] == ids[:25]
    finally:
        cmd._params["voice"].choices = original


def test_set_voice_choices_in_sync_payload():
    import bot
    cmd = bot.app.tree.get_command("genspeech")
    original = cmd._params["voice"].choices
    try:
        bot._set_voice_choices(["af_heart", "af_nicole"])
        payload = cmd.to_dict(bot.app.tree)
        options = {o["name"]: o for o in payload["options"]}
        assert [c["value"] for c in options["voice"]["choices"]] == [
            "af_heart",
            "af_nicole",
        ]
    finally:
        cmd._params["voice"].choices = original
