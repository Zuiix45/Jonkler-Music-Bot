import unittest
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Add the src directory to the path so we can import main
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

# Import the bot and music_player from main
from main import bot, music_player

class MockVoiceClient:
    """Mock for discord.VoiceClient"""
    def __init__(self):
        self.is_playing_status = False
        self.is_paused_status = False
        
    def is_playing(self):
        return self.is_playing_status
        
    def is_paused(self):
        return self.is_paused_status
        
    def play(self, *args, **kwargs):
        self.is_playing_status = True
        self.is_paused_status = False
        
    def pause(self):
        self.is_paused_status = True
        self.is_playing_status = False
        
    def resume(self):
        self.is_paused_status = False
        self.is_playing_status = True
        
    def stop(self):
        self.is_playing_status = False
        self.is_paused_status = False
        
    async def disconnect(self):
        self.is_playing_status = False
        self.is_paused_status = False

class MockInteraction:
    """Mock for discord.Interaction"""
    def __init__(self):
        self.response = AsyncMock()
        self.followup = AsyncMock()
        self.guild = MagicMock()
        self.guild.id = 1234
        self.channel = MagicMock()
        self.author = MagicMock()
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, *args):
        pass

class MockContext:
    """Mock for commands.Context"""
    def __init__(self, voice_client=None):
        self.voice_client = voice_client
        self.guild = MagicMock()
        self.guild.id = 1234
        self.channel = MagicMock()
        self.author = MagicMock()
        self.send = AsyncMock()

class TestSlashCommands(unittest.TestCase):
    """Test cases for Discord slash commands"""
    
    def setUp(self):
        """Set up test environment"""
        self.voice_client = MockVoiceClient()
        self.interaction = MockInteraction()
        self.ctx = MockContext(self.voice_client)
        
        # Prepare MusicPlayer for tests
        music_player.get_guild_state = MagicMock()
        music_player.get_guild_state.return_value = MagicMock()
        
        # Mock bot.get_context to return our mock context
        bot.get_context = AsyncMock(return_value=self.ctx)
        
    async def _run_test(self, coro):
        """Helper to run async test functions"""
        return await coro
        
    def test_play_slash(self):
        """Test play slash command"""
        # Mock music_player.play
        music_player.play = AsyncMock()
        
        # Run the test
        asyncio.run(self._run_test(
            bot.tree.get_command("play").callback(self.interaction, "test song")
        ))
        
        # Assertions
        self.interaction.response.defer.assert_called_once()
        music_player.play.assert_called_once_with(self.ctx, "test song")
        
    def test_stop_slash(self):
        """Test stop slash command"""
        # Mock music_player.stop
        music_player.stop = AsyncMock()
        
        # Run the test
        asyncio.run(self._run_test(
            bot.tree.get_command("stop").callback(self.interaction)
        ))
        
        # Assertions
        self.interaction.response.defer.assert_called_once()
        music_player.stop.assert_called_once_with(self.ctx)
        
    def test_skip_slash(self):
        """Test skip slash command"""
        # Mock music_player.skip
        music_player.skip = AsyncMock()
        
        # Run the test
        asyncio.run(self._run_test(
            bot.tree.get_command("skip").callback(self.interaction)
        ))
        
        # Assertions
        self.interaction.response.defer.assert_called_once()
        music_player.skip.assert_called_once_with(self.ctx)
        
    def test_queue_slash(self):
        """Test queue slash command"""
        # Mock music_player.queue
        music_player.queue = AsyncMock()
        
        # Run the test
        asyncio.run(self._run_test(
            bot.tree.get_command("queue").callback(self.interaction)
        ))
        
        # Assertions
        self.interaction.response.defer.assert_called_once()
        music_player.queue.assert_called_once_with(self.ctx)
        
    def test_pause_slash_when_playing(self):
        """Test pause slash command when music is playing"""
        # Set up voice client mock
        self.voice_client.is_playing_status = True
        
        # Run the test
        asyncio.run(self._run_test(
            bot.tree.get_command("pause").callback(self.interaction)
        ))
        
        # Assertions
        self.interaction.response.defer.assert_called_once()
        self.assertTrue(self.voice_client.is_paused_status)
        self.interaction.followup.send.assert_called_once_with("Playback paused.")
        
    def test_pause_slash_when_not_playing(self):
        """Test pause slash command when no music is playing"""
        # Set up voice client mock
        self.voice_client.is_playing_status = False
        
        # Run the test
        asyncio.run(self._run_test(
            bot.tree.get_command("pause").callback(self.interaction)
        ))
        
        # Assertions
        self.interaction.response.defer.assert_called_once()
        self.interaction.followup.send.assert_called_once_with("Nothing is playing to pause!")
        
    def test_resume_slash_when_paused(self):
        """Test resume slash command when music is paused"""
        # Set up voice client mock
        self.voice_client.is_paused_status = True
        
        # Run the test
        asyncio.run(self._run_test(
            bot.tree.get_command("resume").callback(self.interaction)
        ))
        
        # Assertions
        self.interaction.response.defer.assert_called_once()
        self.assertTrue(self.voice_client.is_playing_status)
        self.interaction.followup.send.assert_called_once_with("Playback resumed.")
        
    def test_resume_slash_when_not_paused(self):
        """Test resume slash command when no music is paused"""
        # Set up voice client mock
        self.voice_client.is_paused_status = False
        
        # Run the test
        asyncio.run(self._run_test(
            bot.tree.get_command("resume").callback(self.interaction)
        ))
        
        # Assertions
        self.interaction.response.defer.assert_called_once()
        self.interaction.followup.send.assert_called_once_with("Nothing is paused to resume!")
        
    def test_clear_slash(self):
        """Test clear slash command"""
        # Mock music_player.clear
        music_player.clear = AsyncMock()
        
        # Run the test
        asyncio.run(self._run_test(
            bot.tree.get_command("clear").callback(self.interaction)
        ))
        
        # Assertions
        self.interaction.response.defer.assert_called_once()
        music_player.clear.assert_called_once_with(self.ctx)

if __name__ == "__main__":
    unittest.main()
