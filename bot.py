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

# --- 3. フォント取得ロジック (見た目を良くする心臓部) ---
def get_font(size):
    # 日本語対応フォントのパス候補
    font_paths = [
        "font.ttf", "font.otf", # 自分でフォントを入れる場合
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", # Linux/Replit
        "C:\\Windows\\Fonts\\msgothic.ttc" # Windows
    ]
    for path in font_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

# --- 4. 画像生成 (デザインをアップグレード) ---
async def create_level_card(member, level, xp, threshold):
    img = Image.new('RGB', (600, 200), color=(35, 39, 42)) # Discord風の暗い色
    draw = ImageDraw.Draw(img)
    
    f_name = get_font(32); f_info = get_font(24); f_xp = get_font(18)

    try:
        asset = member.display_avatar.with_format("png").with_size(128)
        pfp = Image.open(io.BytesIO(await asset.read())).convert("RGBA").resize((128, 128))
        mask = Image.new("L", (128, 128), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 128, 128), fill=255)
        img.paste(pfp, (30, 36), mask)
    except: pass

    draw.text((180, 45), f"{member.display_name}", fill=(255, 255, 255), font=f_name)
    draw.text((180, 90), f"Level: {level}", fill=(255, 215, 0), font=f_info)

    # 角丸の経験値バー
    bar_w, bar_h, bar_x, bar_y = 380, 22, 180, 130
    prog = min((xp / threshold) * bar_w, bar_w) if threshold > 0 else bar_w
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=11, fill=(60, 63, 65))
    if prog > 0:
        draw.rounded_rectangle([bar_x, bar_y, bar_x + prog, bar_y + bar_h], radius=11, fill=(114, 137, 218))
    
    draw.text((180, 158), f"{xp} / {threshold} XP", fill=(180, 180, 180), font=f_xp)
    
    out = io.BytesIO(); img.save(out, format="PNG"); out.seek(0)
    return discord.File(out, filename="rank.png")

async def create_levelup_image(member, old_lv, new_lv):
    img = Image.new('RGB', (500, 150), color=(44, 47, 51))
    draw = ImageDraw.Draw(img)
    f_title = get_font(30); f_sub = get_font(24)

    for _ in range(30): # キラキラの演出
        x, y = random.randint(0, 500), random.randint(0, 150)
        draw.ellipse((x, y, x+3, y+3), fill=(255, 215, 0))

    draw.text((150, 35), "✨ LEVEL UP !! ✨", fill=(255, 215, 0), font=f_title)
    draw.text((150, 85), f"Lv.{old_lv}  ➔  Lv.{new_lv}", fill=(255, 255, 255), font=f_sub)
    
    out = io.BytesIO(); img.save(out, format="PNG"); out.seek(0)
    return discord.File(out, filename="levelup.png")

# --- 5. XPシステム ---
def get_xp_multiplier(gid, data):
    conf = data["config"].get(gid, {})
    if not conf.get("hh_enabled"): return 1
    now_h = get_now_jst().hour
    s, e = conf.get("hh_start", 0), conf.get("hh_end", 0)
    active = (s <= now_h < e) if s < e else (now_h >= s or now_h < e)
    return conf.get("hh_mult", 2.0) if active else 1

async def process_xp(user_id, guild, amount, data, current_channel=None):
    gid = str(guild.id)
    u = data["users"].setdefault(user_id, {"xp":0, "level":1, "msg_count":0, "total_vc":0, "react_count":0})
    old_lv = u["level"]
    u["xp"] += int(amount * get_xp_multiplier(gid, data))
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
                rid = data["config"].get(gid, {}).get("roles", {}).get(str(u["level"]))
                if rid:
                    role = guild.get_role(int(rid))
                    if role: await member.add_roles(role)

# --- 6. クライアント & イベント ---
class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)
        self.last_hh_state = {}

    async def setup_hook(self):
        await self.tree.sync()
        self.main_loop.start()

    @tasks.loop(minutes=1)
    async def main_loop(self):
        data = load_data(); now_h = get_now_jst().hour
        for guild in self.guilds:
            gid = str(guild.id); conf = data["config"].setdefault(gid, {})
            rate = conf.get("vc_rate", 10)
            for vc in guild.voice_channels:
                for m in vc.members:
                    if not m.bot and not m.voice.self_deaf:
                        await process_xp(str(m.id), guild, rate, data)
                        data["users"][str(m.id)]["total_vc"] = data["users"][str(m.id)].get("total_vc", 0) + 1
            if conf.get("hh_enabled"):
                s, e = conf.get("hh_start", 0), conf.get("hh_end", 0)
                is_now = (s <= now_h < e) if s < e else (now_h >= s or now_h < e)
                if is_now != self.last_hh_state.get(gid, False):
                    self.last_hh_state[gid] = is_now
                    target = guild.get_channel(int(conf.get("hh_ann_cid", 0)))
                    if target:
                        msg = conf.get("hh_msg_start" if is_now else "hh_msg_end", "変化").replace("{multiplier}", str(conf.get("hh_mult", 2.0)))
                        await target.send(msg)
        save_data(data)

client = MyClient()

@client.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    data = load_data(); uid, gid = str(message.author.id), str(message.guild.id)
    conf = data["config"].get(gid, {})
    await process_xp(uid, message.guild, conf.get("msg_rate", 5), data, message.channel)
    data["users"][uid]["msg_count"] = data["users"][uid].get("msg_count", 0) + 1
    bw = conf.get("bonus_word")
    if bw and bw in message.content:
        claimed = uid in conf.get("bonus_claimed", [])
        if not conf.get("bonus_once") or not claimed:
            await process_xp(uid, message.guild, conf.get("bonus_xp", 0), data, message.channel)
            await message.add_reaction("🎁")
            if conf.get("bonus_once"): conf.setdefault("bonus_claimed", []).append(uid)
    save_data(data)

@client.event
async def on_raw_reaction_add(payload):
    if payload.member.bot: return
    data = load_data(); gid = str(payload.guild_id); uid = str(payload.user_id)
    guild = client.get_guild(payload.guild_id)
    rate = data["config"].get(gid, {}).get("react_rate", 2)
    await process_xp(uid, guild, rate, data)
    data["users"].setdefault(uid, {})["react_count"] = data["users"][uid].get("react_count", 0) + 1
    save_data(data)

# --- 7. スラッシュコマンド (指定通りの構成) ---

@client.tree.command(name="rank", description="【一般】現在のレベルと進捗を表示します。")
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    data = load_data(); target = member or interaction.user; gid = str(interaction.guild.id)
    u = data["users"].get(str(target.id), {"level":1, "xp":0})
    thres = data["config"].get(gid, {}).get("xp_threshold", 100)
    await interaction.response.defer() # 画像生成待ち対策
    file = await create_level_card(target, u["level"], u["xp"], thres)
    await interaction.followup.send(file=file)

@client.tree.command(name="top", description="【一般】レベルランキング上位10名を表示します。")
async def top(interaction: discord.Interaction):
    data = load_data()
    sorted_u = sorted(data["users"].items(), key=lambda x: (x[1]['level'], x[1]['xp']), reverse=True)[:10]
    res = [f"**{i+1}位**: <@{uid}> Lv.{u['level']}" for i, (uid, u) in enumerate(sorted_u)]
    await interaction.response.send_message(embed=discord.Embed(title="🏆 ランキング", description="\n".join(res) or "データなし", color=0xffd700))

@client.tree.command(name="give", description="【管理】指定したユーザーにXPを付与します。")
@app_commands.checks.has_permissions(administrator=True)
async def give(interaction: discord.Interaction, member: discord.Member, amount: int):
    data = load_data()
    await process_xp(str(member.id), interaction.guild, amount, data, interaction.channel)
    save_data(data)
    await interaction.response.send_message(f"✅ {member.mention} に {amount} XPを付与しました。")

@client.tree.command(name="config_xp_rate", description="【管理】メッセージ/VC/リアクションでもらえるXP量を設定します。")
@app_commands.checks.has_permissions(administrator=True)
async def config_xp_rate(interaction: discord.Interaction, msg: int, vc: int, react: int):
    data = load_data(); gid = str(interaction.guild.id)
    data["config"].setdefault(gid, {}).update({"msg_rate":msg, "vc_rate":vc, "react_rate":react})
    save_data(data); await interaction.response.send_message(f"✅ 設定完了: メッセ{msg} / VC{vc} / リアク{react}")

@client.tree.command(name="config_notify", description="【管理】通知チャンネルとレベルアップ閾値を設定します。")
@app_commands.checks.has_permissions(administrator=True)
async def config_notify(interaction: discord.Interaction, channel: discord.TextChannel, threshold: int = 100):
    data = load_data(); gid = str(interaction.guild.id)
    data["config"].setdefault(gid, {}).update({"notify_channel": str(channel.id), "xp_threshold": threshold})
    save_data(data); await interaction.response.send_message(f"✅ 通知先: {channel.mention} / 閾値: {threshold}")

@client.tree.command(name="config_happy_hour", description="【管理】ハッピータイムを設定します。")
@app_commands.checks.has_permissions(administrator=True)
async def config_happy_hour(interaction: discord.Interaction, start_h: int, end_h: int, multiplier: float, announce_channel: discord.TextChannel):
    data = load_data(); gid = str(interaction.guild.id)
    data["config"].setdefault(gid, {}).update({
        "hh_enabled": True, "hh_start": start_h, "hh_end": end_h, 
        "hh_mult": multiplier, "hh_ann_cid": str(announce_channel.id),
        "hh_msg_start": f"🔥 ハッピータイム開始！XPが {multiplier} 倍です！",
        "hh_msg_end": "❄️ ハッピータイムが終了しました。"
    })
    save_data(data); await interaction.response.send_message(f"✅ {start_h}時-{end_h}時（{multiplier}倍）に設定しました。")

@client.tree.command(name="set_role", description="【管理】レベル報酬役職を設定します。")
@app_commands.checks.has_permissions(administrator=True)
async def set_role(interaction: discord.Interaction, level: int, role: discord.Role):
    data = load_data(); gid = str(interaction.guild.id)
    data["config"].setdefault(gid, {}).setdefault("roles", {})[str(level)] = str(role.id)
    save_data(data); await interaction.response.send_message(f"✅ Lv.{level} 到達時に {role.name} を付与します。")

@client.tree.command(name="bonus_word", description="【管理】特定の単語を発言した時のボーナスXPを設定します。")
@app_commands.checks.has_permissions(administrator=True)
async def bonus_word(interaction: discord.Interaction, word: str, xp: int, once: bool = True):
    data = load_data(); gid = str(interaction.guild.id)
    data["config"].setdefault(gid, {}).update({"bonus_word": word, "bonus_xp": xp, "bonus_once": once, "bonus_claimed": []})
    save_data(data); await interaction.response.send_message(f"✅ ボーナス単語「{word}」を設定しました。")

# --- 8. 実行 ---
keep_alive()
try:
    client.run(TOKEN)
except Exception as e:
    print(f"Error: {e}")
    os.system("kill 1")
