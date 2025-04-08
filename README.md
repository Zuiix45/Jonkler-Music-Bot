<div align="center">

# 🎵 Jonkler - Discord Music Bot

<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python Version">
<img src="https://img.shields.io/badge/discord.py-2.3.1+-blue?style=for-the-badge&logo=discord&logoColor=white" alt="Discord.py">
<img src="https://img.shields.io/badge/License-GNU-yellow?style=for-the-badge" alt="License">

**A powerful, high-quality music bot for Discord with YouTube integration**

[Installation](#installation) • 
[Features](#features) • 
[Commands](#commands) • 
[Configuration](#configuration) • 
[Troubleshooting](#troubleshooting)

</div>

---

## 📋 Overview

Jonkler is a feature-rich Discord music bot that brings high-quality audio streaming to your server. With support for YouTube videos, playlists, and search functionality, your Discord server will transform into the perfect place for sharing and enjoying music with friends.

## ✨ Features

### 🎧 Audio Experience
- **High-Quality Playback**: Crystal clear audio streaming from YouTube
- **Smart Queue System**: Add unlimited songs to the queue
- **Playlist Support**: Load entire YouTube playlists with a single command

### 🔍 Discovery and Control
- **YouTube Search**: Find songs by name without needing exact URLs
- **Rich Information**: View song details, thumbnails, and duration
- **Playback Controls**: Skip, stop, and clear queue with simple commands

### 🤖 Bot Behavior
- **Smart Auto-Disconnect**: Bot leaves voice channel after inactivity
- **Dual Command System**: Use both slash commands and traditional prefix commands
- **Server Isolation**: Queue and playback state isolated by server

## 🛠️ Installation

### Prerequisites
- **Python 3.10+**
- **FFmpeg** installed on your system
- **Discord Bot Token** ([Create one here](https://discord.com/developers/applications))

### Quick Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/penny-wise-bot.git
   cd penny-wise-bot
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**
   - Rename `.env.example` to `.env`
   - Add your Discord bot token to the `.env` file
   ```
   DISCORD_BOT_TOKEN=your_token_here
   ```

4. **Launch the bot**
   ```bash
   python src/main.py
   ```

5. **Invite the bot** to your server using the OAuth2 URL generator in the Discord Developer Portal

## 💬 Commands

### Prefix Commands
| Command | Description | Example |
|---------|-------------|---------|
| `!play` | Play a song from YouTube | `!play never gonna give you up` |
| `!stop` | Stop playback and disconnect | `!stop` |
| `!skip` | Skip the current song | `!skip` |
| `!queue` | Display the current queue | `!queue` |
| `!clear` | Clear the current queue | `!clear` |
| `!okul` | Play the Okul song | `!okul` |

### Slash Commands
All commands are also available as slash commands:
- `/play search:query` - Play a song from YouTube
- `/stop` - Stop playback and disconnect
- `/skip` - Skip the current song
- `/queue` - Display the current queue
- `/clear` - Clear the current queue
- `/okul` - Play the Okul song

## ⚙️ Configuration

The bot uses the following environment variables which can be set in the `.env` file:
