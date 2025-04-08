import discord
import os
import asyncio
import functools
import time
from collections import deque
from discord.ext import commands
from yt_dlp import YoutubeDL
from functools import partial, lru_cache
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

# Constants
TIMEOUT_DELAY = 240
QUEUE_LOAD_LIMIT = 20
QUEUE_EMBEDDING_SONG_LIMIT = 10
MAX_CONCURRENT_EXTRACTIONS = 5  # Limit to avoid rate limiting
CACHE_TTL = 3600  # 1 hour cache for YouTube data

# FFmpeg options - optimized for better performance
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -af dynaudnorm=f=200:g=3:n=0:p=0.95'  # Added dynamic audio normalization
}

# Thread pool for CPU-bound tasks
thread_pool = ThreadPoolExecutor(max_workers=4)

class LoggerOutputs:
    @staticmethod
    def error(msg):
        pass
    
    @staticmethod
    def warning(msg):
        pass
    
    @staticmethod
    def debug(msg):
        pass

class YouTubeCache:
    """Cache for YouTube data with TTL"""
    def __init__(self, ttl=CACHE_TTL):
        self.cache = {}
        self.ttl = ttl
    
    def get(self, key):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return data
            else:
                del self.cache[key]
        return None
    
    def set(self, key, value):
        self.cache[key] = (value, time.time())
    
    def clear_expired(self):
        """Clear expired cache entries"""
        current_time = time.time()
        expired_keys = [k for k, (_, t) in self.cache.items() if current_time - t >= self.ttl]
        for key in expired_keys:
            del self.cache[key]

class YouTubeService:
    def __init__(self):
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'extract_flat': 'in_playlist',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'logger': LoggerOutputs,
            'socket_timeout': 10,  # Reduce timeout for faster failure response
            'retries': 2,          # Limit retries for faster response
        }
        self.cache = YouTubeCache()
        self.extraction_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)
    
    async def search_youtube(self, query: str) -> dict:
        """Asynchronously search YouTube for a single song and return its info."""
        cache_key = f"search:{query}"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            return cached_result
            
        async with self.extraction_semaphore:
            loop = asyncio.get_running_loop()
            with YoutubeDL(self.ydl_opts) as ydl:
                try:
                    info = await loop.run_in_executor(thread_pool, 
                                                     partial(ydl.extract_info, f"ytsearch:{query}", download=False))
                    if not info or not info.get('entries'):
                        return None
                    result = info['entries'][0]
                    self.cache.set(cache_key, result)
                    return result
                except Exception as e:
                    print(f"Search error: {e}")
                    return None
    
    async def extract_info(self, url: str, playlist: bool = False) -> dict:
        """Asynchronously extract info from a URL with caching."""
        cache_key = f"info:{url}:{playlist}"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            return cached_result
            
        async with self.extraction_semaphore:
            loop = asyncio.get_running_loop()
            opts = self.ydl_opts.copy()
            opts['noplaylist'] = not playlist
            with YoutubeDL(opts) as ydl:
                try:
                    result = await loop.run_in_executor(thread_pool, 
                                                      partial(ydl.extract_info, url, download=False))
                    if result:
                        self.cache.set(cache_key, result)
                    return result
                except Exception as e:
                    print(f"Extraction error: {e}")
                    return None
    
    async def extract_multiple_urls(self, urls, playlist=False):
        """Extract info from multiple URLs concurrently."""
        tasks = []
        for url in urls:
            tasks.append(self.extract_info(url, playlist))
        
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    def format_track_data(self, info):
        """Format track data from YouTube info."""
        if not info:
            return None
            
        return {
            'url': info['url'],
            'title': info.get('title', 'Unknown Title'),
            'duration': info.get('duration', 0),
            'thumbnail': info.get('thumbnail', None),
            'uploader': info.get('uploader', 'Unknown Uploader')
        }

class GuildState:
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.queue = deque()  # Using deque for more efficient queue operations
        self.waiting_urls = deque()
        self.currently_playing = None
        self.is_playing_audio = False
        self.audio_lock = False
        self.last_activity = time.time()
    
    def reset(self):
        """Reset all state for this guild."""
        self.queue.clear()
        self.waiting_urls.clear()
        self.currently_playing = None
        self.is_playing_audio = False
        self.audio_lock = False
    
    def update_activity(self):
        """Update the last activity timestamp."""
        self.last_activity = time.time()

class MusicPlayer:
    def __init__(self, bot):
        self.bot = bot
        self.youtube_service = YouTubeService()
        self.guild_states = {}
        self.cleanup_task = None
    
    def get_guild_state(self, guild_id: int) -> GuildState:
        """Get or create a guild state object."""
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = GuildState(guild_id)
        return self.guild_states[guild_id]
    
    def sync_playback_error(self, error, ctx):
        """Handle playback errors synchronously."""
        if error:
            print(f'Error in playback for guild {ctx.guild.id}: {error}')
            # Run the error handler asynchronously
            asyncio.run_coroutine_threadsafe(self.playback_error(error, ctx), self.bot.loop)
    
    async def playback_error(self, error, ctx):
        """Async error handler for playback issues."""
        print(f'Handling error: {error}')
        # You can add more sophisticated error handling here
    
    async def player_loop(self, ctx: commands.Context):
        """Main player loop that processes the queue."""
        guild_state = self.get_guild_state(ctx.guild.id)
        
        while guild_state.queue and ctx.voice_client:
            if not ctx.voice_client.is_playing():
                next_song = guild_state.queue.popleft()  # Using deque.popleft() for O(1) performance
                
                try:
                    source = discord.FFmpegOpusAudio(next_song['url'], **FFMPEG_OPTIONS)
                    
                    # Create a partial function to capture the context for error handling
                    error_callback = partial(self.sync_playback_error, ctx=ctx)
                    ctx.voice_client.play(source, after=error_callback)
                    
                    guild_state.is_playing_audio = True
                    guild_state.audio_lock = True
                    guild_state.currently_playing = next_song
                    guild_state.update_activity()
                    
                    # Send now playing message
                    await self.send_now_playing_message(ctx, next_song)
                    
                    # Update the timestamp for the currently playing song
                    guild_state.currently_playing['timestamp'] = discord.utils.utcnow().timestamp()
                except Exception as e:
                    print(f"Error playing track: {e}")
                    continue  # Skip this track and try the next one
            
            # Wait for the audio to finish playing
            while guild_state.is_playing_audio and ctx.voice_client:
                if ctx.voice_client.is_playing():
                    guild_state.audio_lock = False
                
                if not guild_state.audio_lock and not ctx.voice_client.is_playing():
                    guild_state.is_playing_audio = False
                
                await asyncio.sleep(0.5)  # Reduced sleep time for more responsive queue processing
        
        # Disconnect after a timeout if nothing else is playing
        await asyncio.sleep(TIMEOUT_DELAY)
        # Refresh guild state before checking
        guild_state = self.get_guild_state(ctx.guild.id)
        if ctx.voice_client and not ctx.voice_client.is_playing() and not guild_state.queue and not guild_state.waiting_urls:
            await ctx.voice_client.disconnect()
            guild_state.reset()
    
    async def send_now_playing_message(self, ctx, song):
        """Send a message showing what's currently playing."""
        embed = discord.Embed(
            title="Now Playing",
            description=f"[{song['title']}]({song['url']})",
            color=discord.Color.blue()
        )
        
        embed.set_thumbnail(url=song.get('thumbnail', ''))
        embed.add_field(name="Duration", value=f"{song.get('duration', 0)} seconds", inline=True)
        embed.add_field(name="Uploader", value=song.get('uploader', 'Unknown Uploader'), inline=True)
        
        await ctx.send(embed=embed)
    
    async def extract_playlist_urls(self, ctx: commands.Context):
        """Process waiting URLs and add them to the queue - optimized version."""
        guild_state = self.get_guild_state(ctx.guild.id)
        
        # Process URLs in batches for better efficiency
        while guild_state.waiting_urls and ctx.voice_client:
            if len(guild_state.queue) > QUEUE_LOAD_LIMIT:
                await asyncio.sleep(1)
                continue
            
            # Process multiple URLs concurrently (up to 5 at a time)
            batch_size = min(MAX_CONCURRENT_EXTRACTIONS, len(guild_state.waiting_urls))
            batch_urls = []
            
            for _ in range(batch_size):
                if guild_state.waiting_urls:
                    batch_urls.append(guild_state.waiting_urls.popleft()['url'])
            
            # Extract info concurrently
            results = await self.youtube_service.extract_multiple_urls(batch_urls)
            
            for i, info in enumerate(results):
                if isinstance(info, Exception):
                    print(f"Error extracting info: {info}")
                    continue
                    
                if ctx.voice_client and info:
                    track = self.youtube_service.format_track_data(info)
                    if track:
                        guild_state.queue.append(track)
            
            # Start playing if not already playing
            if not ctx.voice_client.is_playing() and guild_state.queue:
                self.bot.loop.create_task(self.player_loop(ctx))
        
        await asyncio.sleep(0.5)
    
    async def play(self, ctx: commands.Context, search: str):
        """Play a song or playlist."""
        if not ctx.author.voice:
            return await ctx.send("You need to be in a voice channel!")
        
        # Connect if not already connected
        if not ctx.voice_client:
            await ctx.author.voice.channel.connect()
        
        guild_state = self.get_guild_state(ctx.guild.id)
        guild_state.update_activity()
        
        # Check if the search query is a playlist URL
        if "list=" in search:
            await self.handle_playlist(ctx, search, guild_state)
        else:
            await self.handle_single_song(ctx, search, guild_state)
        
        await self.extract_playlist_urls(ctx)
    
    async def handle_playlist(self, ctx, url, guild_state):
        """Handle playlist processing."""
        info = await self.youtube_service.extract_info(url, playlist=True)
        if not info or 'entries' not in info:
            return await ctx.send("Couldn't retrieve playlist info.")
        
        # Queue all playlist entries
        for entry in info['entries']:
            if entry is None or 'url' not in entry:
                continue
            
            if "youtube.com/watch" in entry['url']:
                guild_state.waiting_urls.append({'url': entry['url']})
        
        embed = discord.Embed(
            title="Playlist Added to Queue",
            description=f"{len(info['entries'])} songs found in the playlist.",
            color=discord.Color.green()
        )
        
        embed.add_field(name="Playlist URL", value=f"[Click Here]({url})", inline=False)
        embed.add_field(name="Requested by", value=ctx.author.mention, inline=True)
        await ctx.send(embed=embed)
    
    async def handle_single_song(self, ctx, search, guild_state):
        """Handle single song processing."""
        if "youtube.com/watch" in search:
            guild_state.waiting_urls.append({'url': search})
            info = await self.youtube_service.extract_info(search)
        else:
            info = await self.youtube_service.search_youtube(search)
            if not info:
                return await ctx.send("No results found!")
            
            guild_state.waiting_urls.append({'url': info['url']})
        
        if info:
            print(f"Adding {info['url']} to the queue in {ctx.guild.id} guild.")
            
            # Create an embed for the song being added to the waiting list
            embed = discord.Embed(
                title="Song Added to Queue",
                description=f"[{info['title']}]({info['url']})",
                color=discord.Color.green()
            )
            
            embed.set_thumbnail(url=info.get('thumbnail', ''))
            embed.add_field(name="Duration", value=f"{info.get('duration', 0)} seconds", inline=True)
            embed.add_field(name="Uploader", value=info.get('uploader', 'Unknown Uploader'), inline=True)
            embed.add_field(name="Position in Queue", value=len(guild_state.waiting_urls), inline=True)
            embed.add_field(name="Requested by", value=ctx.author.mention, inline=True)
            
            await ctx.send(embed=embed)
    
    async def stop(self, ctx: commands.Context):
        """Stop playback and disconnect."""
        if ctx.voice_client:
            if ctx.voice_client.is_playing():
                ctx.voice_client.stop()
            
            await ctx.voice_client.disconnect()
            self.get_guild_state(ctx.guild.id).reset()
            await ctx.send("Playback stopped and disconnected.")
        else:
            await ctx.send("Not in a voice channel!")
    
    async def skip(self, ctx: commands.Context):
        """Skip the currently playing song."""
        guild_state = self.get_guild_state(ctx.guild.id)
        
        if ctx.voice_client:
            if ctx.voice_client.is_playing():
                current_song = guild_state.currently_playing
                ctx.voice_client.stop()
                if current_song and 'title' in current_song:
                    await ctx.send(f"Skipping {current_song['title']}...")
                else:
                    await ctx.send("Skipping current song...")
            else:
                await ctx.send("Nothing is playing to skip!")
        else:
            await ctx.send("Not in a voice channel!")
    
    async def queue(self, ctx: commands.Context):
        """Display the current queue."""
        guild_state = self.get_guild_state(ctx.guild.id)
        
        if guild_state.queue:
            queue_string = "\n".join([f"{i}. {song['title']}" for i, song in enumerate(guild_state.queue[:QUEUE_EMBEDDING_SONG_LIMIT], start=1)])
            
            if len(guild_state.queue) > QUEUE_EMBEDDING_SONG_LIMIT:
                queue_string += f"\n...and {len(guild_state.queue) - QUEUE_EMBEDDING_SONG_LIMIT} more!"
            
            embed = discord.Embed(title="Current Queue", description=queue_string, color=discord.Color.blue())
            
            # Add currently playing
            if guild_state.currently_playing:
                embed.add_field(
                    name="Currently Playing", 
                    value=f"[{guild_state.currently_playing['title']}]",
                    inline=False
                )
            
            embed.set_footer(text="Use !skip to skip the current song.")
            embed.add_field(name="Total Songs", value=len(guild_state.queue), inline=True)
            
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="Queue is empty", 
                description="Add some songs to get started!", 
                color=discord.Color.red()
            )
            
            # Still show currently playing if available
            if guild_state.currently_playing:
                embed.add_field(
                    name="Currently Playing", 
                    value=f"[{guild_state.currently_playing['title']}]",
                    inline=False
                )
            
            await ctx.send(embed=embed)
    
    async def clear(self, ctx: commands.Context):
        """Clear the current queue."""
        guild_state = self.get_guild_state(ctx.guild.id)
        
        if guild_state.queue or guild_state.waiting_urls:
            guild_state.queue = []
            guild_state.waiting_urls = []
            await ctx.send("Queue has been cleared!")
        else:
            await ctx.send("Queue is already empty!")
    
    async def start_cleanup_task(self):
        """Start a background task to clean up inactive guilds and expired cache."""
        self.cleanup_task = self.bot.loop.create_task(self._cleanup_loop())
    
    async def _cleanup_loop(self):
        """Periodically clean up inactive guilds and expired cache."""
        try:
            while True:
                # Clean up expired cache entries
                self.youtube_service.cache.clear_expired()
                
                # Clean up inactive guild states
                current_time = time.time()
                inactive_guilds = []
                
                for guild_id, state in self.guild_states.items():
                    # If inactive for more than 15 minutes and not playing
                    if (current_time - state.last_activity > 900 and 
                        not state.is_playing_audio and 
                        not state.queue and 
                        not state.waiting_urls):
                        inactive_guilds.append(guild_id)
                
                for guild_id in inactive_guilds:
                    self.guild_states.pop(guild_id, None)
                
                await asyncio.sleep(300)  # Run cleanup every 5 minutes
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error in cleanup loop: {e}")
            # Restart the task
            self.cleanup_task = self.bot.loop.create_task(self._cleanup_loop())

# Initialize the bot with appropriate intents
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Create our music player instance
music_player = MusicPlayer(bot)

# Handling command registration based on available library features
try:
    @bot.tree.command(name="play")
    async def play_slash(interaction: discord.Interaction, search: str):
        """Play a song or an entire playlist from YouTube."""
        ctx = await bot.get_context(interaction)
        await interaction.response.defer()
        await music_player.play(ctx, search)

    @bot.tree.command(name="stop")
    async def stop_slash(interaction: discord.Interaction):
        """Stop playback and disconnect."""
        ctx = await bot.get_context(interaction)
        await interaction.response.defer()
        await music_player.stop(ctx)

    @bot.tree.command(name="skip")
    async def skip_slash(interaction: discord.Interaction):
        """Skip the currently playing song."""
        ctx = await bot.get_context(interaction)
        await interaction.response.defer()
        await music_player.skip(ctx)

    @bot.tree.command(name="queue")
    async def queue_slash(interaction: discord.Interaction):
        """Display the current queue."""
        ctx = await bot.get_context(interaction)
        await interaction.response.defer()
        await music_player.queue(ctx)
        
    @bot.tree.command(name="pause")
    async def pause_slash(interaction: discord.Interaction):
        """Pause the current playback."""
        ctx = await bot.get_context(interaction)
        await interaction.response.defer()
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await interaction.followup.send("Playback paused.")
        else:
            await interaction.followup.send("Nothing is playing to pause!")
    
    @bot.tree.command(name="resume")
    async def resume_slash(interaction: discord.Interaction):
        """Resume the current playback."""
        ctx = await bot.get_context(interaction)
        await interaction.response.defer()
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await interaction.followup.send("Playback resumed.")
        else:
            await interaction.followup.send("Nothing is paused to resume!")

    @bot.tree.command(name="clear")
    async def clear_slash(interaction: discord.Interaction):
        """Clear the current queue without stopping playback."""
        ctx = await bot.get_context(interaction)
        await interaction.response.defer()
        await music_player.clear(ctx)

    # Set flag for slash commands availability
    has_slash_commands = True
except (ImportError, AttributeError) as e:
    print(f"Slash commands not available: {e}")
    print("Consider updating discord.py to version 2.0+ for slash command support")
    print("pip install -U discord.py")
    has_slash_commands = False
    
@bot.command()
async def okul(ctx: commands.Context):
    """Pause the current music, play the Okul meme, and resume."""
    if not ctx.author.voice:
        return await ctx.send("You need to be in a voice channel!")
    
    if ctx.voice_client is None:
        await ctx.author.voice.channel.connect()
    
    time_point = discord.utils.utcnow().timestamp()
    playing = ctx.voice_client.is_playing()
    if playing:
        ctx.voice_client.pause()
    
    okul_path = os.path.join(os.path.dirname(__file__), "..\\", os.getenv("OKUL_MEME_PATH"))
    if os.path.exists(okul_path):
        ctx.voice_client.play(discord.FFmpegOpusAudio(okul_path, options="-vn -af dynaudnorm=f=200:g=3:n=0:p=0.95"))
    else:
        await ctx.send("Okul meme file not found!")

    # Wait for the Okul meme to finish
    while ctx.voice_client.is_playing():
        await asyncio.sleep(1)

    # Replay the previous music from where it left off
    guild_state = music_player.get_guild_state(ctx.guild.id)
    
    if playing and guild_state.currently_playing:
        guild_state.currently_playing['timestamp'] += discord.utils.utcnow().timestamp() - time_point
        previous_track = guild_state.currently_playing
        ctx.voice_client.play(discord.FFmpegOpusAudio(previous_track['url'], options=f"-ss {discord.utils.utcnow().timestamp() - int(guild_state.currently_playing['timestamp'])} {FFMPEG_OPTIONS['options']}"))

@bot.event
async def on_voice_state_update(member, before, after):
    # Reset the guild state if the bot leaves the voice channel
    if member == bot.user and before.channel and not after.channel:
        if member.guild.id in music_player.guild_states:
            music_player.guild_states[member.guild.id].reset()

@bot.event
async def on_ready():
    print(f"Application Started: {bot.user}")
    # Sync commands with Discord only if slash commands are available
    if has_slash_commands:
        try:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(f"Failed to sync commands: {e}")
    else:
        print("Using prefix commands only. Prefix: '!'")

if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_BOT_TOKEN"))
