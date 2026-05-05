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
from PIL import Image, ImageDraw

# --- Flask（常時起動用） ---
app = Flask('')
@app.route('/')
def home(): return "Bot is alive!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- 設定・データ管理 ---
TOKEN = os.getenv('DISCORD_TOKEN')
DATA_FILE = 'server_data.json'

def get_now_jst():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            try: return json.load(f)
            except: pass
    return {"users": {}, "config": {}, "activity": {"msg": {}, "vc": {}, "react": {}}}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- 🖼 画像生成 (レベルカード) ---
async def create_level_card(member, level, xp, threshold):
    img = Image.new('RGB', (600, 200), color=(44, 47, 51))
    draw = ImageDraw.Draw(img)
    try:
        asset = member.display_avatar.with_format("png").with_size(128)
        pfp = Image.open(io.BytesIO(await asset.read())).convert("RGBA").resize((128, 128))
        mask = Image.new("L", (128, 128), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 128, 128), fill=255)
        img.paste(pfp, (20, 36), mask)
    except: pass
    draw.text((170, 50), f"{member.display_name}", fill=(255, 255, 255))
    draw.text((170, 90), f"Level: {level}", fill=(255, 215, 0))
    bar_w = 350
    prog = min((xp / threshold) * bar_w, bar_w)
    draw.rectangle([170, 130, 170 + bar_w, 145], fill=(100, 100, 100))
    draw.rectangle([170, 130, 170 + prog, 145], fill=(114, 137, 218))
    draw.text((170, 155), f"{xp} / {threshold} XP", fill=(200, 200, 200))
    out = io.BytesIO(); img.save(out, format="PNG"); out.seek(0)
    return discord.File(out, filename="rank.png")

# --- 🖼 画像生成 (レベルアップ通知) ---
async def create_levelup_image(member, old_lv, new_lv):
    img = Image.new('RGB', (500, 150), color=(44, 47, 51))
    draw = ImageDraw.Draw(img)
    for _ in range(25): # キラキラ
        x, y = random.randint(0, 500), random.randint(0, 150)
        draw.ellipse((x, y, x+4, y+4), fill=(255, 215, 0))
    draw.text((150, 40), f"{member.display_name}", fill=(255, 255, 255))
    draw.text((150, 70), "✨ LEVEL UP !! ✨", fill=(255, 215, 0))
    draw.text((150, 100), f"Lv.{old_lv}  ➔  Lv.{new_lv}", fill=(255, 255, 255))
    out = io.BytesIO(); img.save(out, format="PNG"); out.seek(0)
    return discord.File(out, filename="levelup.png")

# --- XP計算ロジック ---
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
    # 倍率適用
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
                # 報酬ロール
                rid = data["config"].get(gid, {}).get("roles", {}).get(str(u["level"]))
                if rid:
                    role = guild.get_role(int(rid))
                    if role: await member.add_roles(role)

# --- クライアントクラス ---
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
        data = load_data()
        now_h = get_now_jst().hour
        for guild in self.guilds:
            gid = str(guild.id)
            conf = data["config"].setdefault(gid, {})
            # VCチェック
            rate = conf.get("vc_rate", 10)
            for vc in guild.voice_channels:
                for m in vc.members:
                    if not m.bot and not m.voice.self_deaf:
                        await process_xp(str(m.id), guild, rate, data)
                        data["users"][str(m.id)]["total_vc"] += 1
            # ハッピーアワー告知
            if conf.get("hh_enabled"):
                s, e = conf.get("hh_start", 0), conf.get("hh_end", 0)
                is_now = (s <= now_h < e) if s < e else (now_h >= s or now_h < e)
                if is_now != self.last_hh_state.get(gid, False):
                    self.last_hh_state[gid] = is_now
                    target = guild.get_channel(int(conf.get("hh_ann_cid", 0)))
                    if target:
                        m_key = "hh_msg_start" if is_now else "hh_msg_end"
                        msg = conf.get(m_key, "状態変化").replace("{multiplier}", str(conf.get("hh_mult", 2.0)))
                        await target.send(msg)
        save_data(data)

client = MyClient()

@client.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    data = load_data()
    uid, gid = str(message.author.id), str(message.guild.id)
    conf = data["config"].get(gid, {})
    
    # メッセージXP
    await process_xp(uid, message.guild, conf.get("msg_rate", 5), data, message.channel)
    data["users"][uid]["msg_count"] += 1

    # ボーナスワード
    bw = conf.get("bonus_word")
    if bw and bw in message.content:
        claimed = uid in conf.get("bonus_claimed", [])
        if not conf.get("bonus_once") or not claimed:
            await process_xp(uid, message.guild, conf.get("bonus_xp", 0), data, message.channel)
            await message.add_reaction("🎁")
            if conf.get("bonus_once"):
                conf.setdefault("bonus_claimed", []).append(uid)
    save_data(data)

# --- スラッシュコマンド ---
@client.tree.command(name="rank")
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    data = load_data(); target = member or interaction.user; gid = str(interaction.guild.id)
    u = data["users"].get(str(target.id), {"level":1, "xp":0})
    thres = data["config"].get(gid, {}).get("xp_threshold", 100)
    await interaction.response.send_message(file=await create_level_card(target, u["level"], u["xp"], thres))

@client.tree.command(name="top")
async def top(interaction: discord.Interaction):
    data = load_data()
    sorted_u = sorted(data["users"].items(), key=lambda x: (x[1]['level'], x[1]['xp']), reverse=True)[:10]
    res = [f"**{i+1}位**: <@{uid}> Lv.{u['level']}" for i, (uid, u) in enumerate(sorted_u)]
    await interaction.response.send_message(embed=discord.Embed(title="🏆 ランキング", description="\n".join(res)))

@client.tree.command(name="config_all_xp")
@app_commands.checks.has_permissions(administrator=True)
async def config_all_xp(interaction: discord.Interaction, msg: int, vc: int, threshold: int):
    data = load_data()
    data["config"].setdefault(str(interaction.guild.id), {}).update({"msg_rate":msg, "vc_rate":vc, "xp_threshold":threshold})
    save_data(data)
    await interaction.response.send_message("✅ XP基本設定を更新しました。")

@client.tree.command(name="config_happy_hour")
@app_commands.checks.has_permissions(administrator=True)
async def config_hh(interaction: discord.Interaction, start: int, end: int, multiplier: float, enable: bool):
    data = load_data()
    data["config"].setdefault(str(interaction.guild.id), {}).update({"hh_start":start, "hh_end":end, "hh_mult":multiplier, "hh_enabled":enable})
    save_data(data)
    await interaction.response.send_message("✅ ハッピーアワー設定完了。")

@client.tree.command(name="config_hh_announce")
@app_commands.checks.has_permissions(administrator=True)
async def config_hh_ann(interaction: discord.Interaction, channel: discord.TextChannel, start_msg: str, end_msg: str):
    data = load_data()
    data["config"].setdefault(str(interaction.guild.id), {}).update({"hh_ann_cid":str(channel.id), "hh_msg_start":start_msg, "hh_msg_end":end_msg})
    save_data(data)
    await interaction.response.send_message("✅ 告知設定完了。")

@client.tree.command(name="config_bonus_word")
@app_commands.checks.has_permissions(administrator=True)
async def config_bonus(interaction: discord.Interaction, word: str, amount: int, once: bool):
    data = load_data()
    data["config"].setdefault(str(interaction.guild.id), {}).update({"bonus_word":word, "bonus_xp":amount, "bonus_once":once, "bonus_claimed":[]})
    save_data(data)
    await interaction.response.send_message(f"✅ ボーナスワード『{word}』を設定しました。")

# 起動
keep_alive()
client.run(TOKEN)
