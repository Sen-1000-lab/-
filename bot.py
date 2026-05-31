import discord
from discord import app_commands
from discord.ext import tasks

import datetime
import json
import os
import io
import random
import aiohttp

from flask import Flask
from threading import Thread

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont


# ==================================================
# Keep Alive
# ==================================================

app = Flask("")


@app.route("/")
def home():
    return "Bot is Alive"


def run_web():
    app.run(
        host="0.0.0.0",
        port=8080
    )


def keep_alive():
    Thread(
        target=run_web,
        daemon=True
    ).start()


# ==================================================
# Environment
# ==================================================

TOKEN = os.getenv("DISCORD_TOKEN")

DATA_FILE = "server_data.json"
BACKUP_FILE = "server_data_backup.json"


# ==================================================
# Utility
# ==================================================

def get_now_jst():
    return datetime.datetime.now(
        datetime.timezone(
            datetime.timedelta(hours=9)
        )
    )


def load_data():

    default_data = {
        "users": {},
        "config": {},
        "activity_log": {}
    }

    if not os.path.exists(DATA_FILE):
        return default_data

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        data.setdefault("users", {})
        data.setdefault("config", {})
        data.setdefault("activity_log", {})

        return data

    except Exception:

        if os.path.exists(BACKUP_FILE):

            try:

                with open(
                    BACKUP_FILE,
                    "r",
                    encoding="utf-8"
                ) as f:

                    return json.load(f)

            except Exception:
                pass

        return default_data


def save_data(data):

    try:

        if os.path.exists(DATA_FILE):

            try:
                os.replace(
                    DATA_FILE,
                    BACKUP_FILE
                )
            except Exception:
                pass

        with open(
            DATA_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=4
            )

    except Exception as e:
        print("保存失敗:", e)


# ==================================================
# Font
# ==================================================

def get_font(size):

    paths = [
        "font.ttf",
        "font.otf",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        "C:\\Windows\\Fonts\\msgothic.ttc"
    ]

    for path in paths:

        try:

            if os.path.exists(path):

                return ImageFont.truetype(
                    path,
                    size
                )

        except Exception:
            pass

    return ImageFont.load_default()


# ==================================================
# User Data
# ==================================================

def get_user_data(data, uid):

    uid = str(uid)

    user = data["users"].setdefault(
        uid,
        {
            "xp": 0,
            "level": 1,
            "total_msg": 0,
            "total_vc": 0,
            "total_react": 0,
            "last_daily": 0
        }
    )

    user.setdefault("xp", 0)
    user.setdefault("level", 1)
    user.setdefault("total_msg", 0)
    user.setdefault("total_vc", 0)
    user.setdefault("total_react", 0)
    user.setdefault("last_daily", 0)

    return user


# ==================================================
# Image Generator
# ==================================================

async def create_level_card(
    member,
    level,
    xp,
    threshold
):

    img = Image.new(
        "RGB",
        (700, 220),
        (32, 34, 37)
    )

    draw = ImageDraw.Draw(img)

    name_font = get_font(34)
    level_font = get_font(28)
    xp_font = get_font(22)

    try:

        avatar = (
            member.display_avatar
            .with_format("png")
            .with_size(256)
        )

        avatar_bytes = await avatar.read()

        pfp = Image.open(
            io.BytesIO(avatar_bytes)
        ).convert("RGBA")

        pfp = pfp.resize(
            (140, 140)
        )

        mask = Image.new(
            "L",
            (140, 140),
            0
        )

        ImageDraw.Draw(mask).ellipse(
            (0, 0, 140, 140),
            fill=255
        )

        img.paste(
            pfp,
            (30, 40),
            mask
        )

    except Exception:
        pass

    draw.text(
        (200, 35),
        member.display_name,
        fill=(255, 255, 255),
        font=name_font
    )

    draw.text(
        (200, 95),
        f"LEVEL {level}",
        fill=(114, 137, 218),
        font=level_font
    )

    draw.text(
        (200, 140),
        f"{xp} / {threshold} XP",
        fill=(200, 200, 200),
        font=xp_font
    )

    bar_x = 200
    bar_y = 180
    bar_w = 450
    bar_h = 18

    draw.rounded_rectangle(
        (
            bar_x,
            bar_y,
            bar_x + bar_w,
            bar_y + bar_h
        ),
        radius=10,
        fill=(70, 70, 70)
    )

    progress = 0

    if threshold > 0:
        progress = min(
            bar_w,
            int(
                (xp / threshold)
                * bar_w
            )
        )

    if progress > 0:

        draw.rounded_rectangle(
            (
                bar_x,
                bar_y,
                bar_x + progress,
                bar_y + bar_h
            ),
            radius=10,
            fill=(114, 137, 218)
        )

    buffer = io.BytesIO()

    img.save(
        buffer,
        format="PNG"
    )

    buffer.seek(0)

    return discord.File(
        buffer,
        filename="rank.png"
    )


async def create_levelup_image(
    member,
    old_level,
    new_level
):

    img = Image.new(
        "RGB",
        (650, 220),
        (35, 39, 42)
    )

    draw = ImageDraw.Draw(img)

    title_font = get_font(50)
    sub_font = get_font(32)

    draw.text(
        (325, 80),
        "LEVEL UP!",
        fill=(255, 215, 0),
        font=title_font,
        anchor="mm"
    )

    draw.text(
        (325, 145),
        f"Lv.{old_level} → Lv.{new_level}",
        fill=(255, 255, 255),
        font=sub_font,
        anchor="mm"
    )

    buffer = io.BytesIO()

    img.save(
        buffer,
        format="PNG"
    )

    buffer.seek(0)

    return discord.File(
        buffer,
        filename="levelup.png"
    )
    # ==================================================
# XP System
# ==================================================

def get_guild_config(data, guild_id):

    gid = str(guild_id)

    return data["config"].setdefault(
        gid,
        {
            "xp_threshold": 100,
            "msg_rate": 10,
            "vc_rate": 5,
            "react_rate": 2,

            "notify_channel": None,
            "history_channel": None,

            "hh_enabled": False,
            "hh_start": 20,
            "hh_end": 22,
            "hh_mult": 2.0,

            "role_bonuses": {},
            "level_roles": {},

            "bonus_word": "",
            "bonus_xp": 50,
            "bonus_once": True,
            "bonus_claimed": [],

            "omikuji_channel": None,
            "rankuji_channel": None,

            "omikuji_base_xp": 30,
            "rankuji_base_xp": 30,

            "bonus_daikichi": 100,
            "bonus_rank_win": 200,

            "rankuji_weights": [
                1,
                2,
                5,
                10,
                82
            ]
        }
    )


# ==================================================
# XP Multiplier
# ==================================================

def get_total_multiplier(member, data):

    conf = get_guild_config(
        data,
        member.guild.id
    )

    multiplier = 1.0

    # -------------------------
    # Happy Hour
    # -------------------------

    if conf.get("hh_enabled"):

        now_hour = get_now_jst().hour

        start = conf.get(
            "hh_start",
            20
        )

        end = conf.get(
            "hh_end",
            22
        )

        active = False

        if start < end:
            active = (
                start <= now_hour < end
            )
        else:
            active = (
                now_hour >= start
                or now_hour < end
            )

        if active:
            multiplier *= float(
                conf.get(
                    "hh_mult",
                    2.0
                )
            )

    # -------------------------
    # Role Bonus
    # -------------------------

    role_bonus = conf.get(
        "role_bonuses",
        {}
    )

    best_bonus = 1.0

    for role_id, value in role_bonus.items():

        try:

            if any(
                r.id == int(role_id)
                for r in member.roles
            ):

                best_bonus = max(
                    best_bonus,
                    float(value)
                )

        except Exception:
            pass

    multiplier *= best_bonus

    return multiplier


# ==================================================
# Level Up
# ==================================================

async def process_xp(
    member,
    amount,
    data,
    current_channel=None,
    skip_mult=False,
    xp_type="msg"
):

    uid = str(member.id)

    user = get_user_data(
        data,
        uid
    )

    # -------------------------
    # Statistics
    # -------------------------

    if xp_type == "msg":
        user["total_msg"] += 1

    elif xp_type == "vc":
        user["total_vc"] += 1

    elif xp_type == "react":
        user["total_react"] += 1

    old_level = user["level"]

    multiplier = (
        1.0
        if skip_mult
        else get_total_multiplier(
            member,
            data
        )
    )

    user["xp"] += int(
        amount * multiplier
    )

    conf = get_guild_config(
        data,
        member.guild.id
    )

    threshold = conf.get(
        "xp_threshold",
        100
    )

    while user["xp"] >= threshold:

        user["xp"] -= threshold
        user["level"] += 1

    # -------------------------
    # Level Up
    # -------------------------

    if user["level"] > old_level:

        # ---------------------
        # Role Reward
        # ---------------------

        level_roles = conf.get(
            "level_roles",
            {}
        )

        for lv, role_id in level_roles.items():

            try:

                if user["level"] >= int(lv):

                    role = member.guild.get_role(
                        int(role_id)
                    )

                    if (
                        role
                        and role
                        not in member.roles
                    ):
                        await member.add_roles(
                            role
                        )

            except Exception:
                pass

        # ---------------------
        # Notify
        # ---------------------

        notify_channel = None

        cid = conf.get(
            "notify_channel"
        )

        if cid:

            try:
                notify_channel = (
                    member.guild.get_channel(
                        int(cid)
                    )
                )
            except Exception:
                pass

        if (
            notify_channel is None
            and current_channel
        ):
            notify_channel = current_channel

        if notify_channel:

            try:

                image = (
                    await create_levelup_image(
                        member,
                        old_level,
                        user["level"]
                    )
                )

                await notify_channel.send(
                    content=(
                        f"🎉 {member.mention} "
                        f"レベルアップ！"
                    ),
                    file=image
                )

            except Exception:
                pass

        # ---------------------
        # History Log
        # ---------------------

        history_id = conf.get(
            "history_channel"
        )

        if history_id:

            try:

                history_channel = (
                    member.guild.get_channel(
                        int(history_id)
                    )
                )

                if history_channel:

                    now = get_now_jst().strftime(
                        "%Y/%m/%d %H:%M"
                    )

                    await history_channel.send(
                        f"📋 {now} | "
                        f"{member.display_name} "
                        f"Lv.{old_level}"
                        f" → "
                        f"Lv.{user['level']}"
                    )

            except Exception:
                pass


# ==================================================
# Activity
# ==================================================

async def get_server_activity(
    guild,
    data,
    days=7
):

    gid = str(guild.id)

    logs = (
        data
        .get("activity_log", {})
        .get(gid, [])
    )

    now = datetime.datetime.now().timestamp()

    limit = (
        now -
        (days * 86400)
    )

    recent = [
        x
        for x in logs
        if x >= limit
    ]

    count = len(recent)

    average = count / days

    if average < 5:
        status = "極めて静か"

    elif average < 30:
        status = "少し過疎気味"

    elif average < 100:
        status = "安定"

    else:
        status = "活発"

    return (
        status,
        count
    )


# ==================================================
# Discord Client
# ==================================================

class MyClient(
    discord.Client
):

    def __init__(self):

        super().__init__(
            intents=discord.Intents.all()
        )

        self.tree = (
            app_commands.CommandTree(
                self
            )
        )

    async def setup_hook(self):

        self.vc_xp_loop.start()
        self.render_ping.start()

    # ----------------------------------
    # VC XP
    # ----------------------------------

    @tasks.loop(minutes=1)
    async def vc_xp_loop(self):

        data = load_data()

        for guild in self.guilds:

            conf = get_guild_config(
                data,
                guild.id
            )

            vc_rate = conf.get(
                "vc_rate",
                5
            )

            for vc in guild.voice_channels:

                members = [
                    m
                    for m in vc.members
                    if not m.bot
                ]

                # 2人以上
                if len(members) < 2:
                    continue

                for member in members:

                    await process_xp(
                        member,
                        vc_rate,
                        data,
                        xp_type="vc"
                    )

        save_data(data)

    # ----------------------------------
    # Render Ping
    # ----------------------------------

    @tasks.loop(minutes=10)
    async def render_ping(self):

        try:

            url = os.getenv(
                "RENDER_EXTERNAL_URL"
            )

            if not url:
                return

            async with aiohttp.ClientSession() as session:

                async with session.get(url):
                    pass

        except Exception:
            pass


client = MyClient()
# ==================================================
# Events
# ==================================================

@client.event
async def on_ready():

    try:
        synced = await client.tree.sync()

        print(
            f"✅ 起動完了 "
            f"({len(synced)} commands)"
        )

    except Exception as e:

        print(
            "同期エラー:",
            e
        )


# ==================================================
# Message XP
# ==================================================

@client.event
async def on_message(message):

    if message.author.bot:
        return

    if not message.guild:
        return

    data = load_data()

    gid = str(
        message.guild.id
    )

    uid = str(
        message.author.id
    )

    conf = get_guild_config(
        data,
        gid
    )

    # ---------------------------------
    # Activity Log
    # ---------------------------------

    data.setdefault(
        "activity_log",
        {}
    ).setdefault(
        gid,
        []
    ).append(
        get_now_jst().timestamp()
    )

    # ---------------------------------
    # おみくじ
    # ---------------------------------

    omikuji_channel = conf.get(
        "omikuji_channel"
    )

    if (
        omikuji_channel
        and str(message.channel.id)
        == str(omikuji_channel)
        and message.content == "おみくじ"
    ):

        result = random.choice(
            [
                "大吉",
                "中吉",
                "小吉",
                "吉",
                "末吉",
                "凶",
                "大凶"
            ]
        )

        xp = conf.get(
            "omikuji_base_xp",
            30
        )

        if result == "大吉":

            xp += conf.get(
                "bonus_daikichi",
                100
            )

        await process_xp(
            message.author,
            xp,
            data,
            current_channel=message.channel,
            skip_mult=True
        )

        save_data(data)

        await message.reply(
            f"⛩️ おみくじ結果："
            f"**{result}**\n"
            f"獲得XP：{xp}"
        )

        return

    # ---------------------------------
    # ランくじ
    # ---------------------------------

    rankuji_channel = conf.get(
        "rankuji_channel"
    )

    if (
        rankuji_channel
        and str(message.channel.id)
        == str(rankuji_channel)
        and message.content == "ランくじ！"
    ):

        rewards = [
            "💎ランク当",
            "✨大当",
            "✴️中当",
            "✳️小当",
            "💀ハズレ"
        ]

        weights = conf.get(
            "rankuji_weights",
            [1, 2, 5, 10, 82]
        )

        result = random.choices(
            rewards,
            weights=weights,
            k=1
        )[0]

        xp = conf.get(
            "rankuji_base_xp",
            30
        )

        if result == "💎ランク当":

            xp += conf.get(
                "bonus_rank_win",
                200
            )

        await process_xp(
            message.author,
            xp,
            data,
            current_channel=message.channel,
            skip_mult=True
        )

        save_data(data)

        await message.reply(
            f"🎲 抽選結果："
            f"**{result}**\n"
            f"獲得XP：{xp}"
        )

        return

    # ---------------------------------
    # 通常XP
    # ---------------------------------

    msg_rate = conf.get(
        "msg_rate",
        10
    )

    await process_xp(
        message.author,
        msg_rate,
        data,
        current_channel=message.channel,
        xp_type="msg"
    )

    # ---------------------------------
    # 合言葉ボーナス
    # ---------------------------------

    bonus_word = conf.get(
        "bonus_word",
        ""
    )

    if (
        bonus_word
        and bonus_word in message.content
    ):

        claimed = conf.setdefault(
            "bonus_claimed",
            []
        )

        once = conf.get(
            "bonus_once",
            True
        )

        can_claim = (
            uid not in claimed
            or not once
        )

        if can_claim:

            bonus_xp = conf.get(
                "bonus_xp",
                50
            )

            await process_xp(
                message.author,
                bonus_xp,
                data,
                current_channel=message.channel,
                skip_mult=True
            )

            try:
                await message.add_reaction(
                    "🎁"
                )
            except Exception:
                pass

            if uid not in claimed:
                claimed.append(uid)

    save_data(data)


# ==================================================
# Reaction XP
# ==================================================

@client.event
async def on_raw_reaction_add(
    payload
):

    if payload.guild_id is None:
        return

    guild = client.get_guild(
        payload.guild_id
    )

    if not guild:
        return

    member = payload.member

    if not member:
        return

    if member.bot:
        return

    data = load_data()

    conf = get_guild_config(
        data,
        guild.id
    )

    react_rate = conf.get(
        "react_rate",
        2
    )

    await process_xp(
        member,
        react_rate,
        data,
        xp_type="react"
    )

    save_data(data)


# ==================================================
# Message Delete
# ==================================================

@client.event
async def on_message_delete(
    message
):

    if not message.guild:
        return

    if message.author.bot:
        return

    data = load_data()

    uid = str(
        message.author.id
    )

    if uid not in data["users"]:
        return

    conf = get_guild_config(
        data,
        message.guild.id
    )

    penalty = conf.get(
        "msg_rate",
        10
    )

    user = data["users"][uid]

    user["xp"] = max(
        0,
        user["xp"] - penalty
    )

    user["total_msg"] = max(
        0,
        user.get(
            "total_msg",
            0
        ) - 1
    )

    save_data(data)


# ==================================================
# Reaction Remove
# ==================================================

@client.event
async def on_raw_reaction_remove(
    payload
):

    if payload.guild_id is None:
        return

    guild = client.get_guild(
        payload.guild_id
    )

    if not guild:
        return

    member = guild.get_member(
        payload.user_id
    )

    if not member:
        return

    if member.bot:
        return

    data = load_data()

    uid = str(member.id)

    if uid not in data["users"]:
        return

    conf = get_guild_config(
        data,
        guild.id
    )

    penalty = conf.get(
        "react_rate",
        2
    )

    user = data["users"][uid]

    user["xp"] = max(
        0,
        user["xp"] - penalty
    )

    user["total_react"] = max(
        0,
        user.get(
            "total_react",
            0
        ) - 1
    )

    save_data(data)
    # ==================================================
# User Commands
# ==================================================

@client.tree.command(
    name="rank",
    description="ランクカードを表示します"
)
async def rank(
    interaction: discord.Interaction,
    member: discord.Member = None
):

    target = (
        member
        if member
        else interaction.user
    )

    data = load_data()

    user = get_user_data(
        data,
        target.id
    )

    conf = get_guild_config(
        data,
        interaction.guild.id
    )

    threshold = conf.get(
        "xp_threshold",
        100
    )

    await interaction.response.defer()

    file = await create_level_card(
        target,
        user["level"],
        user["xp"],
        threshold
    )

    await interaction.followup.send(
        file=file
    )


# ==================================================
# Stats
# ==================================================

@client.tree.command(
    name="stats",
    description="統計情報を表示します"
)
async def stats(
    interaction: discord.Interaction,
    member: discord.Member = None
):

    target = (
        member
        if member
        else interaction.user
    )

    data = load_data()

    user = get_user_data(
        data,
        target.id
    )

    embed = discord.Embed(
        title=f"📊 {target.display_name} の統計",
        color=0x3498DB,
        timestamp=get_now_jst()
    )

    embed.add_field(
        name="レベル",
        value=user["level"],
        inline=True
    )

    embed.add_field(
        name="現在XP",
        value=user["xp"],
        inline=True
    )

    embed.add_field(
        name="通算メッセージ",
        value=user["total_msg"],
        inline=False
    )

    embed.add_field(
        name="通算リアクション",
        value=user["total_react"],
        inline=False
    )

    embed.add_field(
        name="VC獲得回数",
        value=user["total_vc"],
        inline=False
    )

    await interaction.response.send_message(
        embed=embed
    )


# ==================================================
# Daily Bonus
# ==================================================

@client.tree.command(
    name="daily",
    description="1日1回のXPボーナス"
)
async def daily(
    interaction: discord.Interaction
):

    data = load_data()

    user = get_user_data(
        data,
        interaction.user.id
    )

    now = datetime.datetime.now().timestamp()

    remain = (
        86400 -
        (
            now -
            user["last_daily"]
        )
    )

    if remain > 0:

        hours = int(
            remain // 3600
        )

        minutes = int(
            (remain % 3600)
            // 60
        )

        await interaction.response.send_message(
            f"❌ まだ受け取れません\n"
            f"あと {hours}時間 {minutes}分",
            ephemeral=True
        )

        return

    reward = random.randint(
        50,
        150
    )

    user["last_daily"] = now

    await process_xp(
        interaction.user,
        reward,
        data,
        current_channel=interaction.channel,
        skip_mult=True
    )

    save_data(data)

    await interaction.response.send_message(
        f"🎁 デイリーボーナス！\n"
        f"`{reward} XP` 獲得しました！"
    )


# ==================================================
# Top Ranking
# ==================================================

@client.tree.command(
    name="top",
    description="ランキング表示"
)
async def top(
    interaction: discord.Interaction
):

    data = load_data()

    if not data["users"]:

        await interaction.response.send_message(
            "データがありません。"
        )

        return

    sorted_users = sorted(
        data["users"].items(),
        key=lambda x: (
            x[1].get(
                "level",
                1
            ),
            x[1].get(
                "xp",
                0
            )
        ),
        reverse=True
    )

    embed = discord.Embed(
        title=f"🏆 {interaction.guild.name} ランキング",
        color=discord.Color.gold(),
        timestamp=get_now_jst()
    )

    lines = []

    for index, (
        uid,
        user
    ) in enumerate(
        sorted_users[:10],
        start=1
    ):

        member = (
            interaction.guild.get_member(
                int(uid)
            )
        )

        if not member:
            continue

        medal = {
            1: "🥇",
            2: "🥈",
            3: "🥉"
        }.get(
            index,
            f"`{index}`"
        )

        lines.append(
            f"{medal} "
            f"**{member.display_name}** "
            f"- Lv.{user['level']} "
            f"({user['xp']}XP)"
        )

    embed.description = (
        "\n".join(lines)
        if lines
        else "データなし"
    )

    await interaction.response.send_message(
        embed=embed
    )


# ==================================================
# Server Activity
# ==================================================

@client.tree.command(
    name="activity",
    description="サーバー活動状況"
)
async def activity(
    interaction: discord.Interaction
):

    data = load_data()

    status, count = (
        await get_server_activity(
            interaction.guild,
            data,
            7
        )
    )

    embed = discord.Embed(
        title="📈 サーバー活動状況",
        color=0x2ECC71
    )

    embed.add_field(
        name="状態",
        value=status,
        inline=False
    )

    embed.add_field(
        name="7日間の発言数",
        value=f"{count}件",
        inline=False
    )

    await interaction.response.send_message(
        embed=embed
    )
    # ==================================================
# Admin Check
# ==================================================

async def admin_only(
    interaction: discord.Interaction
):
    return (
        interaction.user
        .guild_permissions
        .administrator
    )


# ==================================================
# Config Show
# ==================================================

@client.tree.command(
    name="config_show",
    description="現在の設定を表示"
)
@app_commands.check(
    admin_only
)
async def config_show(
    interaction: discord.Interaction
):

    data = load_data()

    conf = get_guild_config(
        data,
        interaction.guild.id
    )

    embed = discord.Embed(
        title="⚙️ 現在の設定",
        color=0x3498DB
    )

    for key, value in conf.items():

        if key == "bonus_claimed":
            continue

        embed.add_field(
            name=key,
            value=f"`{value}`",
            inline=False
        )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


@client.tree.command(
    name="reset_all_xp",
    description="全員のXPとレベルをリセット"
)
@app_commands.check(admin_only)
async def reset_all_xp(
    interaction: discord.Interaction
):

    data = load_data()

    guild_id = str(interaction.guild.id)

    users = data.get("users", {})

    # 全ユーザー初期化
    for uid, user in users.items():

        user["xp"] = 0
        user["level"] = 1

    save_data(data)

    await interaction.response.send_message(
        "✅ 全ユーザーのXPとレベルをリセットしました。",
        ephemeral=True
    )
# ==================================================
# XP Threshold
# ==================================================

@client.tree.command(
    name="config_threshold",
    description="必要XP設定"
)
@app_commands.check(
    admin_only
)
async def config_threshold(
    interaction: discord.Interaction,
    threshold: int
):

    data = load_data()

    conf = get_guild_config(
        data,
        interaction.guild.id
    )

    conf["xp_threshold"] = threshold

    save_data(data)

    await interaction.response.send_message(
        f"✅ 必要XPを "
        f"{threshold} に設定しました。"
    )


# ==================================================
# XP Rates
# ==================================================

@client.tree.command(
    name="config_rates",
    description="XP量設定"
)
@app_commands.check(
    admin_only
)
async def config_rates(
    interaction: discord.Interaction,
    msg: int,
    vc: int,
    react: int
):

    data = load_data()

    conf = get_guild_config(
        data,
        interaction.guild.id
    )

    conf["msg_rate"] = msg
    conf["vc_rate"] = vc
    conf["react_rate"] = react

    save_data(data)

    await interaction.response.send_message(
        "✅ XP量を更新しました。"
    )


# ==================================================
# Notify Channel
# ==================================================

@client.tree.command(
    name="config_channel",
    description="通知チャンネル設定"
)
@app_commands.check(
    admin_only
)
async def config_channel(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):

    data = load_data()

    conf = get_guild_config(
        data,
        interaction.guild.id
    )

    conf["notify_channel"] = str(
        channel.id
    )

    save_data(data)

    await interaction.response.send_message(
        f"✅ 通知先を "
        f"{channel.mention}"
        f" に設定しました。"
    )


# ==================================================
# History Channel
# ==================================================

@client.tree.command(
    name="config_history",
    description="ログチャンネル設定"
)
@app_commands.check(
    admin_only
)
async def config_history(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):

    data = load_data()

    conf = get_guild_config(
        data,
        interaction.guild.id
    )

    conf["history_channel"] = str(
        channel.id
    )

    save_data(data)

    await interaction.response.send_message(
        f"✅ ログチャンネルを "
        f"{channel.mention}"
        f" に設定しました。"
    )


# ==================================================
# Happy Hour
# ==================================================

@client.tree.command(
    name="config_hh",
    description="ハッピーアワー設定"
)
@app_commands.check(
    admin_only
)
async def config_hh(
    interaction: discord.Interaction,
    enabled: bool,
    start: int,
    end: int,
    multiplier: float
):

    data = load_data()

    conf = get_guild_config(
        data,
        interaction.guild.id
    )

    conf["hh_enabled"] = enabled
    conf["hh_start"] = start
    conf["hh_end"] = end
    conf["hh_mult"] = multiplier

    save_data(data)

    await interaction.response.send_message(
        "✅ ハッピーアワーを更新しました。"
    )


# ==================================================
# Level Reward
# ==================================================

@client.tree.command(
    name="config_reward",
    description="レベル報酬設定"
)
@app_commands.check(
    admin_only
)
async def config_reward(
    interaction: discord.Interaction,
    level: int,
    role: discord.Role
):

    data = load_data()

    conf = get_guild_config(
        data,
        interaction.guild.id
    )

    conf.setdefault(
        "level_roles",
        {}
    )[str(level)] = str(role.id)

    save_data(data)

    await interaction.response.send_message(
        f"✅ Lv.{level} → "
        f"{role.mention}"
        f" を設定しました。"
    )


# ==================================================
# Role Bonus
# ==================================================

@client.tree.command(
    name="config_role_bonus",
    description="役職XP倍率"
)
@app_commands.check(
    admin_only
)
async def config_role_bonus(
    interaction: discord.Interaction,
    role: discord.Role,
    multiplier: float
):

    data = load_data()

    conf = get_guild_config(
        data,
        interaction.guild.id
    )

    conf.setdefault(
        "role_bonuses",
        {}
    )[str(role.id)] = multiplier

    save_data(data)

    await interaction.response.send_message(
        f"✅ {role.mention}"
        f" の倍率を "
        f"{multiplier}倍 "
        f"に設定しました。"
    )


# ==================================================
# Admin Set
# ==================================================

@client.tree.command(
    name="admin_set",
    description="レベル変更"
)
@app_commands.check(
    admin_only
)
async def admin_set(
    interaction: discord.Interaction,
    member: discord.Member,
    level: int,
    xp: int
):

    data = load_data()

    user = get_user_data(
        data,
        member.id
    )

    user["level"] = level
    user["xp"] = xp

    save_data(data)

    await interaction.response.send_message(
        f"✅ {member.display_name}"
        f" を Lv.{level}"
        f" / {xp}XP に変更しました。"
    )


# ==================================================
# Give XP
# ==================================================

@client.tree.command(
    name="give_xp",
    description="XP付与"
)
@app_commands.check(
    admin_only
)
async def give_xp(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: int
):

    if amount <= 0:

        await interaction.response.send_message(
            "1以上を指定してください。",
            ephemeral=True
        )

        return

    data = load_data()

    await process_xp(
        member,
        amount,
        data,
        current_channel=interaction.channel,
        skip_mult=True
    )

    save_data(data)

    await interaction.response.send_message(
        f"✅ {member.mention}"
        f" に {amount}XP 付与しました。"
    )
    # ==================================================
# Omikuji Config
# ==================================================

@client.tree.command(
    name="config_omikuji",
    description="おみくじチャンネル設定"
)
@app_commands.check(admin_only)
async def config_omikuji(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):

    data = load_data()

    conf = get_guild_config(
        data,
        interaction.guild.id
    )

    conf["omikuji_channel"] = str(
        channel.id
    )

    save_data(data)

    await interaction.response.send_message(
        f"✅ {channel.mention} を"
        f" おみくじチャンネルに設定しました。"
    )


# ==================================================
# Rankuji Config
# ==================================================

@client.tree.command(
    name="config_rankuji",
    description="ランくじチャンネル設定"
)
@app_commands.check(admin_only)
async def config_rankuji(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):

    data = load_data()

    conf = get_guild_config(
        data,
        interaction.guild.id
    )

    conf["rankuji_channel"] = str(
        channel.id
    )

    save_data(data)

    await interaction.response.send_message(
        f"✅ {channel.mention} を"
        f" ランくじチャンネルに設定しました。"
    )


# ==================================================
# Kuji XP
# ==================================================

@client.tree.command(
    name="config_kuji_xp",
    description="くじXP設定"
)
@app_commands.check(admin_only)
async def config_kuji_xp(
    interaction: discord.Interaction,
    omikuji_xp: int,
    rankuji_xp: int
):

    data = load_data()

    conf = get_guild_config(
        data,
        interaction.guild.id
    )

    conf["omikuji_base_xp"] = omikuji_xp
    conf["rankuji_base_xp"] = rankuji_xp

    save_data(data)

    await interaction.response.send_message(
        "✅ XP設定を更新しました。"
    )


# ==================================================
# Kuji Bonus
# ==================================================

@client.tree.command(
    name="config_kuji_bonus",
    description="くじボーナス設定"
)
@app_commands.check(admin_only)
async def config_kuji_bonus(
    interaction: discord.Interaction,
    daikichi_bonus: int,
    rank_bonus: int
):

    data = load_data()

    conf = get_guild_config(
        data,
        interaction.guild.id
    )

    conf["bonus_daikichi"] = daikichi_bonus
    conf["bonus_rank_win"] = rank_bonus

    save_data(data)

    await interaction.response.send_message(
        "✅ ボーナス設定を更新しました。"
    )


# ==================================================
# Tree Error Handler
# ==================================================

@client.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):

    if isinstance(
        error,
        app_commands.CheckFailure
    ):

        msg = (
            "❌ このコマンドは"
            "管理者専用です。"
        )

        try:

            if interaction.response.is_done():

                await interaction.followup.send(
                    msg,
                    ephemeral=True
                )

            else:

                await interaction.response.send_message(
                    msg,
                    ephemeral=True
                )

        except Exception:
            pass

        return

    if isinstance(
        error,
        app_commands.CommandOnCooldown
    ):

        try:

            await interaction.response.send_message(
                "⏳ 少し待ってから"
                "実行してください。",
                ephemeral=True
            )

        except Exception:
            pass

        return

    print(
        "Command Error:",
        error
    )


# ==================================================
# Global Error
# ==================================================

@client.event
async def on_error(
    event,
    *args,
    **kwargs
):

    import traceback

    print(
        "\n===== ERROR ====="
    )

    traceback.print_exc()

    print(
        "=================\n"
    )


# ==================================================
# Startup
# ==================================================

if __name__ == "__main__":

    if not TOKEN:

        raise ValueError(
            "DISCORD_TOKEN が"
            "設定されていません"
        )

    keep_alive()

    client.run(
        TOKEN,
        log_handler=None
    )
