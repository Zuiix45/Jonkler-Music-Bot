import discord
import os
import asyncio
from discord.ext import commands
from yt_dlp import YoutubeDL
from functools import partial
from dotenv import load_dotenv

load_dotenv()

# Initialize the bot with appropriate intents
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# YouTube-DL and FFmpeg options
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'extract_flat': 'in_playlist',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

TIMEOUT_DELAY = 60

# Dictionary to maintain queues for each guild
queues = {}
waiting_urls = {}
is_playing_audio = {}
audio_lock = {}

async def search_youtube(query: str) -> dict:
    """Asynchronously search YouTube for a single song and return its info."""
    loop = asyncio.get_running_loop()
    with YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            info = await loop.run_in_executor(None, partial(ydl.extract_info, f"ytsearch:{query}", download=False))
            if not info or not info.get('entries'):
                return None
            return info['entries'][0]
        except Exception as e:
            print(f"Search error: {e}")
            return None

async def extract_info(url: str, playlist: bool = False) -> dict:
    """Asynchronously extract info from a URL."""
    loop = asyncio.get_running_loop()
    opts = YDL_OPTIONS.copy()
    opts['noplaylist'] = not playlist
    with YoutubeDL(opts) as ydl:
        try:
            return await loop.run_in_executor(None, partial(ydl.extract_info, url, download=False))
        except Exception as e:
            print(f"Extraction error: {e}")
            return None

# Define the async error handling function
async def playback_error(error: Exception):
    if error:
        print(f'Error in playback: {error}')

# Wrapper to run the async function
def sync_playback_error(error: Exception):
    asyncio.run_coroutine_threadsafe(playback_error(error), bot.loop)

async def player_loop(ctx: commands.Context):
    while queues[ctx.guild.id]:
        if not ctx.voice_client.is_playing():
            next_song = queues[ctx.guild.id].pop(0)
            source = discord.FFmpegOpusAudio(next_song['url'], **FFMPEG_OPTIONS)
            ctx.voice_client.play(source, after=sync_playback_error)
            await ctx.send(f"Now playing: {next_song['title']}")
            
            is_playing_audio[ctx.guild.id] = True
            audio_lock[ctx.guild.id] = True
        
        # Wait for the audio to finish playing
        while is_playing_audio[ctx.guild.id]:
            if ctx.voice_client.is_playing():
                audio_lock[ctx.guild.id] = False
            
            if not audio_lock[ctx.guild.id] and not ctx.voice_client.is_playing():
                is_playing_audio[ctx.guild.id] = False
            
            await asyncio.sleep(1)
    
    await ctx.send("Queue finished.")
    
    # Disconnect after a timeout
    await asyncio.sleep(TIMEOUT_DELAY)
    if not ctx.voice_client.is_playing():
        await ctx.voice_client.disconnect()

async def extract_playlist_urls(ctx: commands.Context):
    while waiting_urls[ctx.guild.id]:
        next_song = waiting_urls[ctx.guild.id].pop(0)
        info = await extract_info(next_song['url'])
        
        if not info:
            continue
        
        track = {
            'url': info['url'],
            'title': info.get('title', 'Unknown Title')
        }
        
        queues[ctx.guild.id].append(track)
        
        if not ctx.voice_client.is_playing():
            ctx.bot.loop.create_task(player_loop(ctx))

@bot.command()
async def play(ctx: commands.Context, *, search: str):
    """Play a song or an entire playlist from YouTube."""
    if not ctx.author.voice:
        return await ctx.send("You need to be in a voice channel!")

    # Connect if not already connected
    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()

    # Initialize queue for the guild if not present
    if ctx.guild.id not in queues:
        queues[ctx.guild.id] = []
    
    if ctx.guild.id not in waiting_urls:
        waiting_urls[ctx.guild.id] = []

    # Check if the search query is a playlist URL (using 'list=' as a hint)
    if "list=" in search:
        info = await extract_info(search, playlist=True)
        if not info or 'entries' not in info:
            return await ctx.send("Couldn't retrieve playlist info.")
        
        # Queue all playlist entries
        for entry in info['entries']:
            if entry is None or 'url' not in entry:
                continue
            
            if "youtube.com/watch" in entry['url']:
                waiting_urls[ctx.guild.id].append({'url': entry['url']})
            
        await ctx.send(f"Playlist added to queue with {len(info['entries'])} songs.")
        
        await extract_playlist_urls(ctx)
    else:
        # If it's a URL or a search term for a single song
        if "youtube.com/watch" in search:
            info = await extract_info(search)
        else:
            info = await search_youtube(search)
        if not info:
            return await ctx.send("No results found!")
        
        track = {
            'url': info['url'],
            'title': info.get('title', 'Unknown Title')
        }
        
        queues[ctx.guild.id].append(track)
        await ctx.send(f"Added to queue: {track['title']}")
        
        # Start playing if not already playing
        if not ctx.voice_client.is_playing():
            ctx.bot.loop.create_task(player_loop(ctx))

@bot.command()
async def stop(ctx: commands.Context):
    """Stop playback and disconnect."""
    if ctx.voice_client:
        if ctx.guild.id in queues:
            queues[ctx.guild.id].clear()
        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()
    else:
        await ctx.send("Not in a voice channel!")

@bot.command()
async def skip(ctx: commands.Context):
    """Skip the currently playing song."""
    if ctx.voice_client:
        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        await ctx.send("Skipped the current song.")
    else:
        await ctx.send("Not in a voice channel!")

if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_BOT_TOKEN"))
