import asyncio
import os
import sys
import io
import math
import aiohttp
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageChops
import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import re
import time
import json
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
START_TIME = time.time()

try:
    with open("token.txt", "r", encoding="utf-8") as f:
        TOKEN = f.read().strip()
except FileNotFoundError:
    raise RuntimeError("token.txt was not found.")

if not TOKEN:
    raise RuntimeError("token.txt is empty.")

def discord_timestamp(dt: datetime) -> str:
    return f"<t:{int(dt.timestamp())}:R>"

def parse_duration(text: str):
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)\s*", text.lower())
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit.startswith(("second", "sec", "s")):
        seconds = value
    elif unit.startswith(("minute", "min", "m")):
        seconds = value * 60
    elif unit.startswith(("hour", "hr", "h")):
        seconds = value * 3600
    else:
        seconds = value * 86400
    return int(seconds)

def split_options(text: str):
    return [x.strip() for x in re.split(r"[|,]", text) if x.strip()]

NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

class PollButton(discord.ui.Button):
    def __init__(self, poll_view, index: int):
        super().__init__(style=discord.ButtonStyle.secondary, label=NUMBER_EMOJIS[index], row=index // 5)
        self.poll_view = poll_view
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        if self.poll_view.ended:
            await interaction.response.send_message("❌ This poll has ended.", ephemeral=True)
            return
        previous = self.poll_view.votes.get(interaction.user.id)
        if previous == self.index:
            del self.poll_view.votes[interaction.user.id]
            await interaction.response.send_message("✅ Your vote was removed.", ephemeral=True)
            return
        self.poll_view.votes[interaction.user.id] = self.index
        await interaction.response.send_message(
            f"✅ Your vote was recorded for **{self.poll_view.options[self.index]}**.", ephemeral=True
        )

class ViewVotesButton(discord.ui.Button):
    def __init__(self, poll_view):
        super().__init__(style=discord.ButtonStyle.primary, label="View Votes", row=2)
        self.poll_view = poll_view

    async def callback(self, interaction: discord.Interaction):
        lines = []
        total_votes = len(self.poll_view.votes)
        for i, option in enumerate(self.poll_view.options):
            voters = [f"<@{user_id}>" for user_id, choice in self.poll_view.votes.items() if choice == i]
            count = len(voters)
            percentage = round((count / total_votes) * 100) if total_votes > 0 else 0
            voter_text = ", ".join(voters) if voters else "No votes"
            lines.append(f"**{NUMBER_EMOJIS[i]} {option}** — {percentage}%\n{voter_text}")
        embed = discord.Embed(title="📊 Poll Votes", description="\n\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

class LeaderboardButton(discord.ui.Button):
    def __init__(self, poll_view):
        super().__init__(style=discord.ButtonStyle.success, label="View Leaderboard", row=2)
        self.poll_view = poll_view

    async def callback(self, interaction: discord.Interaction):
        counts = [sum(1 for choice in self.poll_view.votes.values() if choice == i) for i in range(len(self.poll_view.options))]
        ranked = sorted(enumerate(counts), key=lambda x: x[1], reverse=True)
        lines = []
        for i, count in ranked:
            lines.append(f"{NUMBER_EMOJIS[i]} **{self.poll_view.options[i]}** — {count} vote" + ("" if count == 1 else "s"))
        embed = discord.Embed(title="🏆 Poll Leaderboard", description="\n".join(lines), color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, ephemeral=True)

class PollView(discord.ui.View):
    def __init__(self, question: str, options: list[str], duration: int):
        super().__init__(timeout=None)
        self.question = question
        self.options = options
        self.duration = duration
        self.votes = {}
        self.ended = False
        for i in range(len(options)):
            self.add_item(PollButton(self, i))
        self.add_item(ViewVotesButton(self))
        self.add_item(LeaderboardButton(self))

async def finish_poll(message: discord.Message, view: PollView):
    await asyncio.sleep(view.duration)
    view.ended = True
    for item in view.children:
        item.disabled = True
    total_votes = len(view.votes)
    counts = [sum(1 for choice in view.votes.values() if choice == i) for i in range(len(view.options))]
    lines = []
    for i, option in enumerate(view.options):
        count = counts[i]
        percentage = max(1, round((count / total_votes) * 100)) if total_votes > 0 and count > 0 else 0
        lines.append(f"{NUMBER_EMOJIS[i]} **{option}** — {count} vote" + ("" if count == 1 else "s") + f" ({percentage}%)")
    if total_votes > 0:
        highest = max(counts)
        winners = [view.options[i] for i, count in enumerate(counts) if count == highest]
        winner_text = f"🏆 Winner: **{winners[0]}**" if len(winners) == 1 else "🏆 Winners: " + ", ".join(f"**{winner}**" for winner in winners)
    else:
        winner_text = "🏆 Winner: No votes"
    embed = discord.Embed(title="📊 Poll Results", description="\n".join(lines), color=discord.Color.green())
    embed.add_field(name="Result", value=winner_text, inline=False)
    embed.set_footer(text=f"Total votes: {total_votes}")
    try:
        await message.edit(view=view)
        await message.reply(embed=embed)
    except discord.HTTPException:
        pass

@bot.tree.command(name="ping", description="Check the bot latency.")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 **pong** ms:{latency} fps:N/A")

@bot.tree.command(name="poll", description="Create a poll.")
@app_commands.describe(question="The poll question.", options="Options separated by | or ,", timer="How long the poll should last.")
async def poll(interaction: discord.Interaction, question: str, options: str, timer: str):
    if interaction.guild is None:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.create_polls:
        await interaction.response.send_message("❌ You do not have permission to create polls.", ephemeral=True)
        return
    parsed_options = split_options(options)
    if len(parsed_options) < 2:
        await interaction.response.send_message("❌ You need at least 2 options.", ephemeral=True)
        return
    if len(parsed_options) > 10:
        await interaction.response.send_message("❌ You can have a maximum of 10 options.", ephemeral=True)
        return
    duration = parse_duration(timer)
    if duration is None or duration <= 0:
        await interaction.response.send_message("❌ Invalid timer. Use formats like `30 seconds`, `5 minutes`, `6 hours`, or `3 days`.", ephemeral=True)
        return
    if duration > 10 * 86400:
        await interaction.response.send_message("❌ The maximum poll duration is 10 days.", ephemeral=True)
        return
    end_time = datetime.now(timezone.utc).timestamp() + duration
    poll_text = f"📊 {interaction.user.display_name} asks:\n\n**{question}**\n\n"
    for i, option in enumerate(parsed_options):
        poll_text += f"{NUMBER_EMOJIS[i]}: {option}\n"
    poll_text += f"\nEnds <t:{int(end_time)}:R>"
    view = PollView(question=question, options=parsed_options, duration=duration)
    await interaction.response.send_message(poll_text, view=view)
    message = await interaction.original_response()
    asyncio.create_task(finish_poll(message, view))

@bot.tree.command(name="userinfo", description="Show information about a user.")
@app_commands.describe(user="The user to inspect.")
async def userinfo(interaction: discord.Interaction, user: discord.Member | None = None):
    target = user or interaction.user
    embed = discord.Embed(title="👤 User Info", color=discord.Color.blurple())
    embed.add_field(name="Username", value=str(target), inline=True)
    embed.add_field(name="Display Name", value=target.display_name, inline=True)
    embed.add_field(name="User ID", value=str(target.id), inline=True)
    embed.add_field(name="Account Created", value=discord_timestamp(target.created_at), inline=False)
    embed.add_field(name="Joined Server", value=discord_timestamp(target.joined_at) if target.joined_at else "Unknown", inline=False)
    embed.set_thumbnail(url=target.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="serverinfo", description="Show information about the server.")
async def serverinfo(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
    guild = interaction.guild
    embed = discord.Embed(title="🏠 Server Info", color=discord.Color.blurple())
    embed.add_field(name="Server Name", value=guild.name, inline=False)
    embed.add_field(name="Created", value=discord_timestamp(guild.created_at), inline=False)
    embed.add_field(name="Members", value=str(guild.member_count), inline=True)
    embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="Emojis", value=str(len(guild.emojis)), inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="avatar", description="Show a user's avatar.")
@app_commands.describe(user="The user whose avatar you want to see.")
async def avatar(interaction: discord.Interaction, user: discord.User | None = None):
    target = user or interaction.user
    embed = discord.Embed(title=f"🖼️ {target.display_name}'s Avatar", color=discord.Color.blurple())
    embed.set_image(url=target.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="help", description="Show all utility commands.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🛠️ Utility Bot Commands", description=(
        "**/ping** — Check bot latency\n**/poll** — Create a poll\n**/userinfo** — Show user information\n"
        "**/serverinfo** — Show server information\n**/avatar** — Show a user's avatar\n**/help** — Show this help menu\n"
        "**/membercount** — Show member count\n**/botinfo** — Show bot information\n"
        "**/remind** — Set a reminder\n**/choose** — Choose randomly from options\n"
        "**/random** — Generate a random number\n**/coinflip** — Flip a coin\n**/8ball** — Ask the Magic 8-Ball\n**/ai** — Ask Gemini a question\n**/youtubeuser** — Views the youtube profile"
    ), color=discord.Color.blurple())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="membercount", description="Show the server member count.")
async def membercount(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
    await interaction.response.send_message(f"👥 **Member Count:** {interaction.guild.member_count}")

@bot.tree.command(name="botinfo", description="Show information about the bot.")
async def botinfo(interaction: discord.Interaction):
    uptime_seconds = int(time.time() - START_TIME)
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime = f"{days}d {hours}h {minutes}m {seconds}s"
    embed = discord.Embed(title="🤖 Bot Info", color=discord.Color.blurple())
    embed.add_field(name="Servers", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)} ms", inline=True)
    embed.add_field(name="Uptime", value=uptime, inline=False)
    embed.add_field(name="discord.py", value=discord.__version__, inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="remind", description="Set a reminder.")
@app_commands.describe(duration="Examples: 30 seconds, 5 minutes, 2 hours", message="What should I remind you about?")
async def remind(interaction: discord.Interaction, duration: str, message: str):
    seconds = parse_duration(duration)
    if seconds is None or seconds <= 0:
        await interaction.response.send_message("❌ Invalid duration. Use formats like `30 seconds`, `5 minutes`, or `2 hours`.", ephemeral=True)
        return
    if seconds > 30 * 86400:
        await interaction.response.send_message("❌ The maximum reminder duration is 30 days.", ephemeral=True)
        return
    end_time = datetime.now(timezone.utc).timestamp() + seconds
    await interaction.response.send_message(f"⏰ Reminder set! I'll remind you <t:{int(end_time)}:R>.")
    await asyncio.sleep(seconds)
    try:
        await interaction.followup.send(f"⏰ {interaction.user.mention}, reminder: **{message}**")
    except discord.HTTPException:
        pass

@bot.tree.command(name="choose", description="Randomly choose one option.")
@app_commands.describe(options="Options separated by | or ,")
async def choose(interaction: discord.Interaction, options: str):
    choices = split_options(options)
    if len(choices) < 2:
        await interaction.response.send_message("❌ Please provide at least 2 options separated by `|` or `,`.", ephemeral=True)
        return
    selected = random.choice(choices)
    await interaction.response.send_message(f"🎯 I choose: **{selected}**")

@bot.tree.command(name="random", description="Generate a random number.")
@app_commands.describe(minimum="Minimum number.", maximum="Maximum number.")
async def random_command(interaction: discord.Interaction, minimum: int, maximum: int):
    if minimum > maximum:
        await interaction.response.send_message("❌ Minimum cannot be greater than maximum.", ephemeral=True)
        return
    number = random.randint(minimum, maximum)
    await interaction.response.send_message(f"🎲 Random number: **{number}**")

@bot.tree.command(name="coinflip", description="Flip a coin.")
async def coinflip(interaction: discord.Interaction):
    result = random.choice(["Heads", "Tails"])
    await interaction.response.send_message(f"🪙 **{result}!**")

EIGHT_BALL_RESPONSES = ["Yes.", "No.", "Definitely!", "Absolutely not.", "It is likely.", "It is unlikely.", "Ask again later.", "Maybe.", "Without a doubt.", "I don't think so."]

@bot.tree.command(name="8ball", description="Ask the Magic 8-Ball a question.")
@app_commands.describe(question="Your question.")
async def eight_ball(interaction: discord.Interaction, question: str):
    answer = random.choice(EIGHT_BALL_RESPONSES)
    embed = discord.Embed(title="🎱 Magic 8-Ball", color=discord.Color.purple())
    embed.add_field(name="Question", value=question, inline=False)
    embed.add_field(name="Answer", value=answer, inline=False)
    await interaction.response.send_message(embed=embed)

def load_key(filename: str):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None

async def gemini_generate(prompt: str):
    api_key = load_key("gemini_key.txt")
    if not api_key:
        return None, "❌ `gemini_key.txt` was not found or is empty."

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
    except Exception as e:
        return None, f"❌ Gemini error: `{str(e)[:180]}`"

    # Retry temporary 503/high-demand errors automatically.
    max_attempts = 3
    delays = [2, 5, 10]

    for attempt in range(max_attempts):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-3.8-flash",
                contents=prompt
            )
            answer = response.text
            if not answer:
                return None, "❌ Gemini returned an empty response."
            return answer, None
        except Exception as e:
            error_text = str(e)
            is_503 = "503" in error_text or "UNAVAILABLE" in error_text or "high demand" in error_text.lower()

            if is_503 and attempt < max_attempts - 1:
                await asyncio.sleep(delays[attempt])
                continue

            return None, f"❌ Gemini error: `{error_text[:180]}`"

    return None, "❌ Gemini is temporarily unavailable. Please try again later."

# =========================
# /ai — AI Command
# =========================

@bot.tree.command(name="ai", description="Ask the AI a question")
@app_commands.describe(prompt="What do you want to ask the AI?")
async def ai(interaction: discord.Interaction, prompt: str):

    await interaction.response.defer()

    try:
        with open("gemini_key.txt", "r") as f:
            gemini_key = f.read().strip()

        import google.generativeai as genai

        genai.configure(api_key=gemini_key)

        model = genai.GenerativeModel("gemini-3.8-flash")

        response = model.generate_content(prompt)

        ai_response = response.text

        embed = discord.Embed(
            title="🤖 AI Response",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="📝 Your Prompt",
            value=f"**{prompt}**",
            inline=False
        )

        embed.add_field(
            name="💬 AI Respond",
            value=ai_response[:1024],
            inline=False
        )

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(
            f"❌ AI error: `{e}`",
            ephemeral=True
        )

YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/channels"
YT_NOTIFY_FILE = Path("youtube_notifications.json")

def load_yt_notifications():
    try:
        with open(YT_NOTIFY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"channels": {}, "notify_channels": {}}
        data.setdefault("channels", {})
        data.setdefault("notify_channels", {})
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {"channels": {}, "notify_channels": {}}

def save_yt_notifications(data):
    with open(YT_NOTIFY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def extract_youtube_identifier(value: str):
    value = value.strip()
    if "youtube.com" in value or "youtu.be" in value:
        parsed = urllib.parse.urlparse(value)
        parts = [p for p in parsed.path.split("/") if p]
        if parts:
            if parts[0].startswith("@"):
                return "handle", parts[0]
            if parts[0] == "channel" and len(parts) >= 2:
                return "id", parts[1]
            if parts[0] == "user" and len(parts) >= 2:
                return "username", parts[1]
        return "url", value
    if value.startswith("@"):
        return "handle", value
    return "username", value

async def youtube_channel_lookup(value: str):
    api_key = load_key("youtube_api_key.txt")
    if not api_key:
        return None, "❌ `youtube_api_key.txt` was not found or is empty."
    kind, identifier = extract_youtube_identifier(value)
    params = {"part": "snippet,statistics", "key": api_key}
    if kind == "id":
        params["id"] = identifier
    elif kind == "handle":
        params["forHandle"] = identifier
    elif kind == "username":
        params["forUsername"] = identifier
    else:
        return None, "❌ Please provide a YouTube channel URL, @handle, username, or channel ID."
    url = YOUTUBE_API_URL + "?" + urllib.parse.urlencode(params)
    def request():
        with urllib.request.urlopen(url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    try:
        result = await asyncio.to_thread(request)
    except Exception as e:
        return None, f"❌ YouTube API error: `{str(e)[:180]}`"
    items = result.get("items", [])
    if not items:
        return None, "❌ YouTube channel not found."
    return items[0], None

def youtube_profile_embed(channel):
    snippet = channel["snippet"]
    stats = channel.get("statistics", {})
    title = snippet.get("title", "Unknown Channel")
    description = snippet.get("description", "")
    if len(description) > 500:
        description = description[:497] + "..."
    embed = discord.Embed(title=f"▶️ {title}", url=f"https://www.youtube.com/channel/{channel['id']}", description=description or "No channel description.", color=discord.Color.red())
    thumbnails = snippet.get("thumbnails", {})
    if thumbnails.get("high"):
        embed.set_thumbnail(url=thumbnails["high"]["url"])
    embed.add_field(name="👥 Subscribers", value=stats.get("subscriberCount", "Hidden"), inline=True)
    embed.add_field(name="👀 Views", value=stats.get("viewCount", "0"), inline=True)
    embed.add_field(name="🎬 Videos", value=stats.get("videoCount", "0"), inline=True)
    embed.add_field(name="📅 Created", value=snippet.get("publishedAt", "Unknown")[:10], inline=True)
    return embed

@bot.tree.command(name="youtubeuser", description="View the profile of a YouTube channel.")
@app_commands.describe(channel="YouTube channel URL, @handle, username, or channel ID.")
async def youtubeuser(interaction: discord.Interaction, channel: str):
    await interaction.response.defer()
    result, error = await youtube_channel_lookup(channel)
    if error:
        await interaction.followup.send(error)
        return
    await interaction.followup.send(embed=youtube_profile_embed(result))

@bot.tree.command(name="channelnotifyaddset", description="Set this channel as the YouTube notification channel.")
async def channelnotifyaddset(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can use this command.", ephemeral=True)
        return
    data = load_yt_notifications()
    data["notify_channels"][str(interaction.guild.id)] = interaction.channel.id
    save_yt_notifications(data)
    await interaction.response.send_message(f"✅ YouTube notification channel set to {interaction.channel.mention}.", ephemeral=True)

@bot.tree.command(name="addnotifyyt", description="Add a YouTube channel for upload notifications.")
@app_commands.describe(channel="YouTube channel URL, @handle, username, or channel ID.")
async def addnotifyyt(interaction: discord.Interaction, channel: str):
    if interaction.guild is None:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can use this command.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    result, error = await youtube_channel_lookup(channel)
    if error:
        await interaction.followup.send(error, ephemeral=True)
        return
    data = load_yt_notifications()
    guild_id = str(interaction.guild.id)
    channel_id = result["id"]
    title = result["snippet"]["title"]
    data["channels"].setdefault(guild_id, {})
    if channel_id in data["channels"][guild_id]:
        await interaction.followup.send(f"⚠️ **{title}** is already being monitored.", ephemeral=True)
        return
    data["channels"][guild_id][channel_id] = {"title": title, "last_video_id": None}
    save_yt_notifications(data)
    await interaction.followup.send(
        f"✅ **{title}** has been added for YouTube notifications.\n"
        f"🔔 The bot will monitor the channel and post new uploads in the configured notification channel.",
        ephemeral=True
    )

@bot.tree.command(name="ows", description="Set the channel for the One Word Story game")
@app_commands.describe(channel="The channel where the One Word Story will happen")
async def ows(interaction: discord.Interaction, channel: discord.TextChannel):
    if not hasattr(bot, "ows_games"):
        bot.ows_games = {}

    bot.ows_games[channel.id] = {
        "words": [],
        "last_user": None
    }

    await interaction.response.send_message(
        f"📖 One Word Story is now active in {channel.mention}!\n"
        f"Send **one word per message** to build the story."
    )


@bot.tree.command(name="ows_stop", description="Stop an active One Word Story game")
@app_commands.describe(channel="The channel where the One Word Story is running")
async def ows_stop(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You must be an administrator to stop an OWS game.",
            ephemeral=True
        )
        return

    if not hasattr(bot, "ows_games") or channel.id not in bot.ows_games:
        await interaction.response.send_message(
            "❌ There is no active OWS game in that channel.",
            ephemeral=True
        )
        return

    game = bot.ows_games[channel.id]
    words = game["words"]

    story = " ".join(words)

    embed = discord.Embed(
        title="📖 One Word Story",
        description=story if story else "*No words were sent.*",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🛑 Game Ended By",
        value=interaction.user.mention,
        inline=False
    )

    await channel.send(
        f"🛑 **The game has ended by {interaction.user.mention}.**",
        embed=embed
    )

    del bot.ows_games[channel.id]

    await interaction.response.send_message(
        f"✅ The OWS game in {channel.mention} has been stopped.",
        ephemeral=True
    )


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if hasattr(bot, "ows_games") and message.channel.id in bot.ows_games:
        word = message.content.strip()

        if not word:
            return

        if len(word.split()) != 1:
            await message.delete()
            await message.channel.send(
                f"❌ {message.author.mention}, you can only send **one word** at a time!",
                delete_after=3
            )
            return

        game = bot.ows_games[message.channel.id]

        if game["last_user"] == message.author.id:
            await message.delete()
            await message.channel.send(
                f"❌ {message.author.mention}, you can't send another word yet!",
                delete_after=3
            )
            return

        game["words"].append(word)
        game["last_user"] = message.author.id

    await bot.process_commands(message)

async def youtube_notification_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        data = load_yt_notifications()
        api_key = load_key("youtube_api_key.txt")
        if api_key:
            for guild_id, channels in data.get("channels", {}).items():
                notify_channel_id = data.get("notify_channels", {}).get(guild_id)
                if not notify_channel_id:
                    continue
                discord_channel = bot.get_channel(int(notify_channel_id))
                if discord_channel is None:
                    continue
                for channel_id, info in channels.items():
                    try:
                        url = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode({
                            "part": "snippet", "channelId": channel_id, "order": "date", "maxResults": 1,
                            "type": "video", "key": api_key
                        })
                        def request_latest():
                            with urllib.request.urlopen(url, timeout=20) as response:
                                return json.loads(response.read().decode("utf-8"))
                        result = await asyncio.to_thread(request_latest)
                        items = result.get("items", [])
                        if not items:
                            continue
                        latest = items[0]
                        video_id = latest.get("id", {}).get("videoId")
                        if not video_id:
                            continue
                        if info.get("last_video_id") is None:
                            info["last_video_id"] = video_id
                            continue
                        if info["last_video_id"] == video_id:
                            continue
                        info["last_video_id"] = video_id
                        title = latest["snippet"].get("title", info.get("title", "YouTube"))
                        await discord_channel.send(
                            f"@here **{info.get('title', 'YouTube channel')}** has posted a "
                            f"[video](https://www.youtube.com/watch?v={video_id})\n**{title}**",
                            allowed_mentions=discord.AllowedMentions(everyone=True)
                        )
                    except Exception as e:
                        print(f"YouTube notification error for {channel_id}: {e}")
        save_yt_notifications(data)
        await asyncio.sleep(300)

youtube_notification_task = None

@bot.event
async def setup_hook():
    global youtube_notification_task
    youtube_notification_task = asyncio.create_task(youtube_notification_loop())

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Slash command sync error: {e}")

@bot.tree.command(
    name="restart",
    description="Restart the bot to update the commands"
)
async def restart(interaction: discord.Interaction):
    if interaction.user.id != 1426253266181685298:
        await interaction.response.send_message(
            "❌ You do not have permission to use this command.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        "🔄 Restarting the bot to update the commands..."
    )

    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)
    
# ============================================================
# /gfx-roblox
# ============================================================
# DM ONLY
# Color → Roblox ID → Shape → Generate GFX
#
# NO POSE SYSTEM
# NO IMPORTS IN THIS SECTION
# ============================================================
# ============================================================
# COLORS
# ============================================================
GFX_COLORS = {
    "red": (255, 55, 55),
    "blue": (55, 125, 255),
    "green": (55, 210, 100),
    "yellow": (255, 220, 55),
    "orange": (255, 145, 45),
    "purple": (165, 85, 255),
    "pink": (255, 85, 175),
    "cyan": (45, 220, 255),
    "white": (245, 245, 255),
    "black": (25, 25, 35),
    "gold": (255, 190, 45),
    "lime": (150, 255, 55),
    "teal": (40, 205, 175),
}
# ============================================================
# SHAPES
# ============================================================
SHAPES = [
    "Circle",
    "Square",
    "Diamond",
    "Triangle",
    "Hexagon",
    "Star",
    "Heart",
    "Lightning",
]
# ============================================================
# SHAPE HELPERS
# ============================================================
def gfx_star_points(
    cx,
    cy,
    outer,
    inner,
    points=5,
):
    result = []
    for i in range(points * 2):
        angle = (
            -math.pi / 2
            + i * math.pi / points
        )
        radius = (
            outer
            if i % 2 == 0
            else inner
        )
        result.append(
            (
                cx + math.cos(angle) * radius,
                cy + math.sin(angle) * radius,
            )
        )
    return result
def gfx_heart_points(
    cx,
    cy,
    scale,
):
    result = []
    for i in range(101):
        t = (
            2
            * math.pi
            * i
            / 100
        )
        x = (
            16
            * math.sin(t) ** 3
        )
        y = (
            13 * math.cos(t)
            - 5 * math.cos(2 * t)
            - 2 * math.cos(3 * t)
            - math.cos(4 * t)
        )
        result.append(
            (
                cx + x * scale,
                cy - y * scale,
            )
        )
    return result
def gfx_lightning_points(
    cx,
    cy,
    size,
):
    return [
        (
            cx + size * 0.10,
            cy - size,
        ),
        (
            cx - size * 0.50,
            cy + size * 0.05,
        ),
        (
            cx - size * 0.08,
            cy + size * 0.02,
        ),
        (
            cx - size * 0.35,
            cy + size,
        ),
        (
            cx + size * 0.55,
            cy - size * 0.18,
        ),
        (
            cx + size * 0.12,
            cy - size * 0.12,
        ),
    ]
# ============================================================
# SHAPE MASK
# ============================================================
def gfx_shape_mask(
    size,
    shape,
):
    width, height = size
    mask = Image.new(
        "L",
        size,
        0,
    )
    draw = ImageDraw.Draw(
        mask
    )
    cx = width // 2
    cy = height // 2
    radius = (
        min(width, height)
        // 2
        - 90
    )
    if shape == "Circle":
        draw.ellipse(
            (
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
            ),
            fill=255,
        )
    elif shape == "Square":
        draw.rounded_rectangle(
            (
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
            ),
            radius=45,
            fill=255,
        )
    elif shape == "Diamond":
        draw.polygon(
            [
                (
                    cx,
                    cy - radius,
                ),
                (
                    cx + radius,
                    cy,
                ),
                (
                    cx,
                    cy + radius,
                ),
                (
                    cx - radius,
                    cy,
                ),
            ],
            fill=255,
        )
    elif shape == "Triangle":
        draw.polygon(
            [
                (
                    cx,
                    cy - radius,
                ),
                (
                    cx + radius,
                    cy + radius,
                ),
                (
                    cx - radius,
                    cy + radius,
                ),
            ],
            fill=255,
        )
    elif shape == "Hexagon":
        points = []
        for i in range(6):
            angle = (
                -math.pi / 2
                + i * math.pi / 3
            )
            points.append(
                (
                    cx
                    + math.cos(angle)
                    * radius,
                    cy
                    + math.sin(angle)
                    * radius,
                )
            )
        draw.polygon(
            points,
            fill=255,
        )
    elif shape == "Star":
        draw.polygon(
            gfx_star_points(
                cx,
                cy,
                radius,
                radius * 0.45,
            ),
            fill=255,
        )
    elif shape == "Heart":
        draw.polygon(
            gfx_heart_points(
                cx,
                cy + 25,
                radius / 18,
            ),
            fill=255,
        )
    elif shape == "Lightning":
        draw.polygon(
            gfx_lightning_points(
                cx,
                cy,
                radius,
            ),
            fill=255,
        )
    return mask
# ============================================================
# GRADIENT
# ============================================================
def gfx_gradient(
    size,
    base_color,
):
    width, height = size
    image = Image.new(
        "RGBA",
        size,
    )
    pixels = image.load()
    r, g, b = base_color
    for y in range(height):
        progress = (
            y
            / max(
                1,
                height - 1,
            )
        )
        brightness = (
            1.0
            - 0.30 * progress
        )
        rr = int(
            r * brightness
        )
        gg = int(
            g * brightness
        )
        bb = int(
            b * brightness
        )
        for x in range(width):
            side_light = (
                1.0
                - (
                    abs(
                        x
                        - width / 2
                    )
                    / (width / 2)
                )
                * 0.18
            )
            pixels[x, y] = (
                min(
                    255,
                    int(
                        rr
                        * side_light
                    ),
                ),
                min(
                    255,
                    int(
                        gg
                        * side_light
                    ),
                ),
                min(
                    255,
                    int(
                        bb
                        * side_light
                    ),
                ),
                255,
            )
    return image
# ============================================================
# GLOW
# ============================================================
def gfx_add_glow(
    image,
    mask,
    color,
):
    glow = Image.new(
        "RGBA",
        image.size,
        (*color, 0),
    )
    blurred = mask.filter(
        ImageFilter.GaussianBlur(40)
    )
    blurred = blurred.point(
        lambda value: int(
            value * 0.55
        )
    )
    glow.putalpha(
        blurred
    )
    image.alpha_composite(
        glow
    )
# ============================================================
# GLOSS
# ============================================================
def gfx_add_gloss(
    image,
    mask,
):
    width, height = image.size
    gloss = Image.new(
        "RGBA",
        image.size,
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(
        gloss
    )
    draw.ellipse(
        (
            int(width * 0.15),
            int(height * 0.04),
            int(width * 0.78),
            int(height * 0.48),
        ),
        fill=(
            255,
            255,
            255,
            90,
        ),
    )
    gloss = gloss.filter(
        ImageFilter.GaussianBlur(45)
    )
    gloss.putalpha(
        ImageChops.multiply(
            gloss.getchannel("A"),
            mask,
        )
    )
    image.alpha_composite(
        gloss
    )
    streak = Image.new(
        "RGBA",
        image.size,
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(
        streak
    )
    draw.rounded_rectangle(
        (
            int(width * 0.18),
            int(height * 0.18),
            int(width * 0.72),
            int(height * 0.27),
        ),
        radius=30,
        fill=(
            255,
            255,
            255,
            75,
        ),
    )
    streak = streak.filter(
        ImageFilter.GaussianBlur(12)
    )
    streak.putalpha(
        ImageChops.multiply(
            streak.getchannel("A"),
            mask,
        )
    )
    image.alpha_composite(
        streak
    )
# ============================================================
# MAKE GFX
# ============================================================
def gfx_make(
    avatar,
    color_name,
    shape,
):
    size = 760
    color = GFX_COLORS[
        color_name
    ]
    # Background
    image = gfx_gradient(
        (size, size),
        color,
    )
    # Background light
    light = Image.new(
        "RGBA",
        (size, size),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(
        light
    )
    draw.ellipse(
        (
            70,
            25,
            size - 70,
            size - 90,
        ),
        fill=(
            255,
            255,
            255,
            50,
        ),
    )
    light = light.filter(
        ImageFilter.GaussianBlur(90)
    )
    image.alpha_composite(
        light
    )
    # Shape
    mask = gfx_shape_mask(
        (size, size),
        shape,
    )
    gfx_add_glow(
        image,
        mask,
        color,
    )
    shape_layer = Image.new(
        "RGBA",
        (size, size),
        (
            color[0],
            color[1],
            color[2],
            230,
        ),
    )
    shape_layer.putalpha(
        mask.point(
            lambda value: int(
                value * 0.88
            )
        )
    )
    image.alpha_composite(
        shape_layer
    )
    # Border
    expanded = mask.filter(
        ImageFilter.MaxFilter(19)
    )
    border_alpha = ImageChops.subtract(
        expanded,
        mask,
    )
    border = Image.new(
        "RGBA",
        (size, size),
        (0, 0, 0, 0),
    )
    border.paste(
        (
            255,
            255,
            255,
            230,
        ),
        (
            0,
            0,
            size,
            size,
        ),
        border_alpha,
    )
    image.alpha_composite(
        border
    )
    # Avatar
    avatar = avatar.convert(
        "RGBA"
    )
    bbox = avatar.getbbox()
    if bbox:
        avatar = avatar.crop(
            bbox
        )
    avatar.thumbnail(
        (530, 530),
        Image.Resampling.LANCZOS,
    )
    avatar_x = (
        size - avatar.width
    ) // 2
    avatar_y = (
        size - avatar.height
    ) // 2 + 15
    # Shadow
    avatar_alpha = avatar.getchannel(
        "A"
    )
    shadow_alpha = avatar_alpha.filter(
        ImageFilter.GaussianBlur(24)
    )
    shadow = Image.new(
        "RGBA",
        (size, size),
        (0, 0, 0, 0),
    )
    shadow_piece = Image.new(
        "RGBA",
        avatar.size,
        (
            0,
            0,
            0,
            150,
        ),
    )
    shadow.paste(
        shadow_piece,
        (
            avatar_x + 18,
            avatar_y + 25,
        ),
        shadow_alpha,
    )
    image.alpha_composite(
        shadow
    )
    # Avatar enhancement
    avatar = ImageEnhance.Contrast(
        avatar
    ).enhance(1.08)
    avatar = ImageEnhance.Color(
        avatar
    ).enhance(1.10)
    avatar = ImageEnhance.Sharpness(
        avatar
    ).enhance(1.18)
    image.alpha_composite(
        avatar,
        (
            avatar_x,
            avatar_y,
        ),
    )
    # Avatar gloss
    avatar_mask = Image.new(
        "L",
        (size, size),
        0,
    )
    avatar_mask.paste(
        avatar.getchannel("A"),
        (
            avatar_x,
            avatar_y,
        ),
    )
    gfx_add_gloss(
        image,
        avatar_mask,
    )
    # Final shine
    shine = Image.new(
        "RGBA",
        (size, size),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(
        shine
    )
    draw.ellipse(
        (
            100,
            35,
            660,
            310,
        ),
        fill=(
            255,
            255,
            255,
            28,
        ),
    )
    shine = shine.filter(
        ImageFilter.GaussianBlur(80)
    )
    image.alpha_composite(
        shine
    )
    return image
# ============================================================
# ROBLOX AVATAR
# ============================================================
async def gfx_get_avatar(
    session,
    user_id,
):
    thumbnail_url = (
        "https://thumbnails.roblox.com/v1/users/avatar"
        f"?userIds={user_id}"
        "&size=720x720"
        "&format=Png"
        "&isCircular=false"
    )
    async with session.get(
        thumbnail_url,
        timeout=aiohttp.ClientTimeout(
            total=20
        ),
    ) as response:
        if response.status != 200:
            return None
        data = await response.json()
    if not data.get("data"):
        return None
    image_url = data["data"][0].get(
        "imageUrl"
    )
    if not image_url:
        return None
    async with session.get(
        image_url,
        timeout=aiohttp.ClientTimeout(
            total=20
        ),
    ) as response:
        if response.status != 200:
            return None
        raw = await response.read()
    return Image.open(
        io.BytesIO(raw)
    ).convert("RGBA")
# ============================================================
# SHAPE SELECT
# ============================================================
class GFXShapeSelect(
    discord.ui.Select
):
    def __init__(
        self,
        author_id,
    ):
        self.author_id = author_id
        options = [
            discord.SelectOption(
                label=shape,
                value=shape,
            )
            for shape in SHAPES
        ]
        super().__init__(
            placeholder="Choose a shape...",
            min_values=1,
            max_values=1,
            options=options,
        )
    async def callback(
        self,
        interaction,
    ):
        if (
            interaction.user.id
            != self.author_id
        ):
            await interaction.response.send_message(
                "❌ This menu isn't for you.",
                ephemeral=True,
            )
            return
        self.view.selected_shape = (
            self.values[0]
        )
        self.view.stop()
        await interaction.response.defer()
class GFXShapeView(
    discord.ui.View
):
    def __init__(
        self,
        author_id,
    ):
        super().__init__(
            timeout=120
        )
        self.selected_shape = None
        self.add_item(
            GFXShapeSelect(
                author_id
            )
        )
# ============================================================
# /gfx-roblox
# ============================================================
@bot.tree.command(
    name="gfx-roblox",
    description="Create a glossy Roblox GFX"
)
async def gfx_roblox(
    interaction: discord.Interaction
):
    # --------------------------------------------------------
    # DM ONLY
    # --------------------------------------------------------
    if interaction.guild is not None:
        await interaction.response.send_message(
            "❌ This command can only be used in DMs."
        )
        return
    # --------------------------------------------------------
    # COLOR
    # --------------------------------------------------------
    await interaction.response.send_message(
        "🎨 **GFX Roblox**\n\n"
        "Send a color:\n"
        "`red`, `blue`, `green`, `yellow`, `orange`, "
        "`purple`, `pink`, `cyan`, `white`, `black`, "
        "`gold`, `lime`, `teal`"
    )
    def color_check(
        message
    ):
        return (
            message.author.id
            == interaction.user.id
            and message.channel.id
            == interaction.channel.id
        )
    try:
        color_message = await bot.wait_for(
            "message",
            timeout=120,
            check=color_check,
        )
    except asyncio.TimeoutError:
        await interaction.channel.send(
            "⌛ Timed out."
        )
        return
    color = (
        color_message.content
        .strip()
        .lower()
    )
    if color not in GFX_COLORS:
        await interaction.channel.send(
            "❌ Invalid color.\n\n"
            "Available colors:\n"
            + ", ".join(
                GFX_COLORS.keys()
            )
        )
        return
    # --------------------------------------------------------
    # ROBLOX ID
    # --------------------------------------------------------
    await interaction.channel.send(
        "👤 **Send the Roblox User ID.**\n"
        "Example: `123456789`"
    )
    def id_check(
        message
    ):
        return (
            message.author.id
            == interaction.user.id
            and message.channel.id
            == interaction.channel.id
        )
    try:
        id_message = await bot.wait_for(
            "message",
            timeout=120,
            check=id_check,
        )
    except asyncio.TimeoutError:
        await interaction.channel.send(
            "⌛ Timed out."
        )
        return
    try:
        roblox_id = int(
            id_message.content.strip()
        )
    except ValueError:
        await interaction.channel.send(
            "❌ That isn't a valid Roblox User ID."
        )
        return
    if roblox_id <= 0:
        await interaction.channel.send(
            "❌ That isn't a valid Roblox User ID."
        )
        return
    # --------------------------------------------------------
    # SHAPE
    # --------------------------------------------------------
    await interaction.channel.send(
        "🔷 **Choose your GFX shape:**"
    )
    view = GFXShapeView(
        interaction.user.id
    )
    await interaction.channel.send(
        view=view
    )
    timed_out = await view.wait()
    if (
        timed_out
        or not view.selected_shape
    ):
        await interaction.channel.send(
            "⌛ Shape selection timed out."
        )
        return
    shape = view.selected_shape
    # --------------------------------------------------------
    # GENERATE
    # --------------------------------------------------------
    generating = await interaction.channel.send(
        "⏳ **Generating your glossy GFX...**"
    )
    try:
        async with aiohttp.ClientSession() as session:
            avatar = await gfx_get_avatar(
                session,
                roblox_id,
            )
        if avatar is None:
            await generating.edit(
                content=(
                    "❌ I couldn't get that Roblox avatar.\n"
                    "Check the Roblox User ID and try again."
                )
            )
            return
        gfx = await asyncio.to_thread(
            gfx_make,
            avatar,
            color,
            shape,
        )
        output = io.BytesIO()
        gfx.save(
            output,
            format="PNG",
            optimize=True,
        )
        output.seek(0)
        file = discord.File(
            output,
            filename="roblox_gfx.png",
        )
        await generating.edit(
            content="✨ **Your GFX is ready!**"
        )
        await interaction.channel.send(
            file=file
        )
    except Exception as error:
        print(
            "GFX ERROR:",
            repr(error)
        )
        await generating.edit(
            content=(
                "❌ Something went wrong while "
                "generating the GFX."
            )
        )

bot.run(TOKEN)
