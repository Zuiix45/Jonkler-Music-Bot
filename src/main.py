import discord
import os
from discord.ext import commands
from yt_dlp import YoutubeDL
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
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
    'options': '-vn',
}

def search_youtube(query: str) -> str:
    """Search YouTube using yt-dlp's search function"""
    with YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch:{query}", download=False)
            # New structure for search results
            if not info or not info.get('entries'):
                return None
            # Get the first video's URL from the results
            return info['entries'][0]['url']
        except Exception as e:
            print(f"Search error: {e}")
            return None

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.command()
async def play(ctx: commands.Context, *, search: str):
    """Play a song from YouTube"""
    if not ctx.author.voice:
        return await ctx.send("You need to be in a voice channel!")

    # Get or create voice client
    voice_client = ctx.voice_client
    if not voice_client:
        voice_client = await ctx.author.voice.channel.connect()

    # Search YouTube
    video_url = search_youtube(search)
    if not video_url:
        return await ctx.send("No results found!")

    # Extract audio information
    with YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            info = ydl.extract_info(video_url, download=False)
        except Exception as e:
            return await ctx.send(f"Error extracting audio: {e}")

    if 'entries' in info:  # Playlist handling (though we disabled playlists)
        info = info['entries'][0]

    title = info.get('title', 'Unknown Title')
    url = info['url']

    # Create audio source
    source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
    
    # Play audio
    voice_client.play(source)
    await ctx.send(f"Now playing: {title}")

@bot.command()
async def stop(ctx: commands.Context):
    """Stop and disconnect"""
    voice_client = ctx.voice_client
    if voice_client:
        await voice_client.disconnect()
        await ctx.send("Disconnected!")
    else:
        await ctx.send("Not in a voice channel!")

if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_BOT_TOKEN"))