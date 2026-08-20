import pytest
import discord.ext.commands


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
    assert len(params) == 1
    assert params[0].name == "prompt"
    assert params[0].required is True
