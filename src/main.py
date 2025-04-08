import discord
import os
import asyncio
from discord.ext import commands
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from functools import partial
from dotenv import load_dotenv

load_dotenv()

# Constants
TIMEOUT_DELAY = 240
QUEUE_LOAD_LIMIT = 20
QUEUE_EMBEDDING_SONG_LIMIT = 10

# FFmpeg options
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

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
        }
    
    async def search_youtube(self, query: str) -> dict:
        """Asynchronously search YouTube for a single song and return its info."""
        loop = asyncio.get_running_loop()
        with YoutubeDL(self.ydl_opts) as ydl:
            try:
                info = await loop.run_in_executor(None, partial(ydl.extract_info, f"ytsearch:{query}", download=False))
                if not info or not info.get('entries'):
                    return None
                return info['entries'][0]
            except Exception as e:
                print(f"Search error: {e}")
                return None
    
    async def extract_info(self, url: str, playlist: bool = False) -> dict:
        """Asynchronously extract info from a URL."""
        loop = asyncio.get_running_loop()
        opts = self.ydl_opts.copy()
        opts['noplaylist'] = not playlist
        with YoutubeDL(opts) as ydl:
            try:
                return await loop.run_in_executor(None, partial(ydl.extract_info, url, download=False))
            except Exception as e:
                print(f"Extraction error: {e}")
                return None
    
    def format_track_data(self, info):
        """Format track data from YouTube info."""
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
        self.queue = []
        self.waiting_urls = []
        self.currently_playing = None
        self.is_playing_audio = False
        self.audio_lock = False
    
    def reset(self):
        """Reset all state for this guild."""
        self.queue = []
        self.waiting_urls = []
        self.currently_playing = None
        self.is_playing_audio = False
        self.audio_lock = False

class MusicPlayer:
    def __init__(self, bot):
        self.bot = bot
        self.youtube_service = YouTubeService()
        self.guild_states = {}
    
    def get_guild_state(self, guild_id: int) -> GuildState:
        """Get or create a guild state object."""
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = GuildState(guild_id)
        return self.guild_states[guild_id]
    
    def sync_playback_error(self, error, ctx):
        """Handle playback errors."""
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
                next_song = guild_state.queue.pop(0)
                source = discord.FFmpegOpusAudio(next_song['url'], **FFMPEG_OPTIONS)
                
                # Create a partial function to capture the context for error handling
                error_callback = partial(self.sync_playback_error, ctx=ctx)
                ctx.voice_client.play(source, after=error_callback)
                
                guild_state.is_playing_audio = True
                guild_state.audio_lock = True
                guild_state.currently_playing = next_song
                
                # Send now playing message
                await self.send_now_playing_message(ctx, next_song)
            
            # Wait for the audio to finish playing
            while guild_state.is_playing_audio and ctx.voice_client:
                if ctx.voice_client.is_playing():
                    guild_state.audio_lock = False
                
                if not guild_state.audio_lock and not ctx.voice_client.is_playing():
                    guild_state.is_playing_audio = False
                
                await asyncio.sleep(1)
        
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
        """Process waiting URLs and add them to the queue."""
        guild_state = self.get_guild_state(ctx.guild.id)
        
        while guild_state.waiting_urls and ctx.voice_client:
            if len(guild_state.queue) > QUEUE_LOAD_LIMIT:
                await asyncio.sleep(1)
                continue
            
            next_song = guild_state.waiting_urls.pop(0)
            info = await self.youtube_service.extract_info(next_song['url'])
            
            if ctx.voice_client and info:
                print(f"Adding {next_song['url']} to the queue in {ctx.guild.id} guild.")
                
                track = self.youtube_service.format_track_data(info)
                guild_state.queue.append(track)
                
                if not ctx.voice_client.is_playing():
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

# Initialize the bot with appropriate intents
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Create our music player instance
music_player = MusicPlayer(bot)

@bot.command()
async def play(ctx: commands.Context, *, search: str = None):
    """Play a song or an entire playlist from YouTube."""
    if search is None:
        return await ctx.send("Please provide a search term or URL.")
    await music_player.play(ctx, search)

@bot.command()
async def stop(ctx: commands.Context):
    """Stop playback and disconnect."""
    await music_player.stop(ctx)

@bot.command()
async def skip(ctx: commands.Context):
    """Skip the currently playing song."""
    await music_player.skip(ctx)

@bot.command()
async def queue(ctx: commands.Context):
    """Display the current queue."""
    await music_player.queue(ctx)

@bot.command()
async def clear(ctx: commands.Context):
    """Clear the current queue without stopping playback."""
    await music_player.clear(ctx)

@bot.command()
async def okul(ctx: commands.Context):
    """Play the Okul song."""
    await play(ctx, search="https://www.youtube.com/shorts/CevwOKeDFDQ")

@bot.event
async def on_voice_state_update(member, before, after):
    # Reset the guild state if the bot leaves the voice channel
    if member == bot.user and before.channel and not after.channel:
        if member.guild.id in music_player.guild_states:
            music_player.guild_states[member.guild.id].reset()

@bot.event
async def on_ready():
    print(f"Application Started: {bot.user}")

if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_BOT_TOKEN"))
