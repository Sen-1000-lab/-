import discord
from discord import app_commands
from discord.ext import tasks
import datetime
import json
import os
import io
import random
from flask import Flask
from threading import Thread
from PIL import Image, ImageDraw, ImageFont

# --- 1. 常時起動設定 ---
app = Flask('')
@app.route('/')
def home(): return "Bot is alive!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- 2. データ管理 ---
TOKEN = os.getenv('DISCORD_TOKEN')
DATA_FILE = 'server_data.json'

def get_now_jst():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except: pass
    return {"users": {}, "config": {}}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- 3. フォント取得ロジック ---
def get_font(size):
    font_paths = [
        "font.ttf", "font.otf",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        "C:\\Windows\\Fonts\\msgothic.ttc"
    ]
    for path in font_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

# --- 4. 画像生成 (テキスト巨大化版) ---
async def create_level_card(member, level, xp, threshold):
    img = Image.new('RGB', (600, 240), color=(35, 39, 42))
    draw = ImageDraw.Draw(img)
    f_name = get_font(50); f_info = get_font(40); f_xp = get_font(24)
    try:
        asset = member.display_avatar.with_format("png").with_size(128)
        pfp = Image.open(io.BytesIO(await asset.read())).convert("RGBA").resize((140, 140))
        mask = Image.new("L", (140, 140), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 140, 140), fill=255)
        img.paste(pfp, (25, 45), mask)
    except: pass
    draw.text((190, 40), f"{member.display_name}", fill=(255, 255, 255), font=f_name)
    draw.text((190, 105), f"Level: {level}", fill=(255, 215, 0), font=f_info)
    bar_w, bar_h, bar_x, bar_y = 380, 30, 190, 160
    prog = min((xp / threshold) * bar_w, bar_w) if threshold > 0 else bar_w
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=15, fill=(60, 63, 65))
    if prog > 0:
        draw.rounded_rectangle([bar_x, bar_y, bar_x + prog, bar_y + bar_h], radius=15, fill=(114, 137, 218))
    draw.text((190, 195), f"{xp} / {threshold} XP", fill=(180, 180, 180), font=f_xp)
    out = io.BytesIO(); img.save(out, format="PNG"); out.seek(0)
    return discord.File(out, filename="rank.png")

async def create_levelup_image(member, old_lv, new_lv):
    img = Image.new('RGB', (600, 200), color=(44, 47, 51))
    draw = ImageDraw.Draw(img)
    f_title = get_font(55); f_sub = get_font(45)
    for _ in range(30):
        x, y = random.randint(0, 600), random.randint(0, 200)
        draw.ellipse((x, y, x+4, y+4), fill=(255, 215, 0))
    draw.text((300, 60), "LEVEL UP !!", fill=(255, 215, 0), font=f_title, anchor="mm")
    draw.text((300, 135), f"Lv.{old_lv} ➔ Lv.{new_lv}", fill=(255, 255, 255), font=f_sub, anchor="mm")
    out = io.BytesIO(); img.save(out, format="PNG"); out.seek(0)
    return discord.File(out, filename="levelup.png")

# --- 5. XPシステム ---
async def process_xp(user_id, guild, amount, data, current_channel=None):
    gid = str(guild.id)
    u = data["users"].setdefault(user_id, {"xp":0, "level":1})
    old_lv = u["level"]
    u["xp"] += int(amount)
    thres = data["config"].get(gid, {}).get("xp_threshold", 100)
    while u["xp"] >= thres:
        u["level"] += 1; u["xp"] -= thres
    if u["level"] > old_lv:
        cid = data["config"].get(gid, {}).get("notify_channel")
        target = guild.get_channel(int(cid)) if cid else current_channel
        if target:
            member = guild.get_member(int(user_id))
            if member:
                file = await create_levelup_image(member, old_lv, u["level"])
                await target.send(content=f"🎉 {member.mention} レベルアップ！", file=file)

# --- 6. クライアント ---
class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        self.main_loop.start()

    @tasks.loop(minutes=1)
    async def main_loop(self):
        data = load_data()
        for guild in self.guilds:
            gid = str(guild.id); conf = data["config"].setdefault(gid, {})
            rate = conf.get("vc_rate", 10)
            for vc in guild.voice_channels:
                for m in vc.members:
                    if not m.bot and not m.voice.self_deaf:
                        await process_xp(str(m.id), guild, rate, data)
        save_data(data)

client = MyClient()

@client.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    data = load_data(); uid, gid = str(message.author.id), str(message.guild.id)
    rate = data["config"].get(gid, {}).get("msg_rate", 5)
    await process_xp(uid, message.guild, rate, data, message.channel)
    save_data(data)

@client.event
async def on_raw_reaction_add(payload):
    guild = client.get_guild(payload.guild_id)
    if not guild: return
    member = guild.get_member(payload.user_id)
    if not member or member.bot: return
    data = load_data(); gid = str(guild.id); uid = str(member.id)
    rate = data["config"].get(gid, {}).get("react_rate", 2)
    await process_xp(uid, guild, rate, data)
    save_data(data)

# --- 7. スラッシュコマンド ---

@client.tree.command(name="rank", description="現在のレベルを表示します。")
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    data = load_data(); target = member or interaction.user; gid = str(interaction.guild.id)
    u = data["users"].get(str(target.id), {"level":1, "xp":0})
    thres = data["config"].get(gid, {}).get("xp_threshold", 100)
    await interaction.response.defer()
    file = await create_level_card(target, u["level"], u["xp"], thres)
    await interaction.followup.send(file=file)

@client.tree.command(name="set_rates", description="XP獲得レートをまとめて設定します。")
@app_commands.checks.has_permissions(administrator=True)
async def set_rates(interaction: discord.Interaction, msg: int = 5, vc: int = 10, react: int = 2):
    data = load_data(); gid = str(interaction.guild.id)
    conf = data["config"].setdefault(gid, {})
    conf["msg_rate"] = msg
    conf["vc_rate"] = vc
    conf["react_rate"] = react
    save_data(data)
    await interaction.response.send_message(f"✅ レートを更新しました：メッセージ={msg}, VC={vc}, リアクション={react}")

@client.tree.command(name="set_threshold", description="レベルアップに必要なXPを設定します。")
@app_commands.checks.has_permissions(administrator=True)
async def set_threshold(interaction: discord.Interaction, amount: int):
    data = load_data(); gid = str(interaction.guild.id)
    data["config"].setdefault(gid, {})["xp_threshold"] = amount
    save_data(data)
    await interaction.response.send_message(f"✅ 必要XPを **{amount}** に設定しました。")

@client.tree.command(name="set_notify_channel", description="レベルアップ通知チャンネルを設定します。")
@app_commands.checks.has_permissions(administrator=True)
async def set_notify_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    data = load_data(); gid = str(interaction.guild.id)
    data["config"].setdefault(gid, {})["notify_channel"] = str(channel.id)
    save_data(data)
    await interaction.response.send_message(f"✅ 通知チャンネルを {channel.mention} に設定しました。")

@client.tree.command(name="reset_user_xp", description="特定の人のXPをリセットします。")
@app_commands.checks.has_permissions(administrator=True)
async def reset_user_xp(interaction: discord.Interaction, member: discord.Member):
    data = load_data(); uid = str(member.id)
    if uid in data["users"]:
        data["users"][uid] = {"xp": 0, "level": 1}
        save_data(data)
        await interaction.response.send_message(f"✅ {member.mention} のデータをリセットしました。")
    else: await interaction.response.send_message("❌ データがありません。", ephemeral=True)

@client.tree.command(name="reset_all_xp", description="全員のXPをリセットします。")
@app_commands.checks.has_permissions(administrator=True)
async def reset_all_xp(interaction: discord.Interaction, confirm: str):
    if confirm != "実行":
        await interaction.response.send_message("❌ 『実行』と入力してください。", ephemeral=True); return
    data = load_data(); data["users"] = {}
    save_data(data)
    await interaction.response.send_message("⚠️ 全員のXPデータをリセットしました。")

keep_alive()
client.run(TOKEN)
