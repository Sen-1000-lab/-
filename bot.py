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
    font_paths = ["font.ttf", "font.otf", "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", "C:\\Windows\\Fonts\\msgothic.ttc"]
    for path in font_paths:
        if os.path.exists(path): return ImageFont.truetype(path, size)
    return ImageFont.load_default()

# --- 4. 画像生成 (テキスト巨大化版) ---
async def create_level_card(member, level, xp, threshold):
    img = Image.new('RGB', (600, 240), color=(35, 39, 42))
    draw = ImageDraw.Draw(img)
    f_name, f_info, f_xp = get_font(50), get_font(40), get_font(24)
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
    if prog > 0: draw.rounded_rectangle([bar_x, bar_y, bar_x + prog, bar_y + bar_h], radius=15, fill=(114, 137, 218))
    draw.text((190, 195), f"{xp} / {threshold} XP", fill=(180, 180, 180), font=f_xp)
    out = io.BytesIO(); img.save(out, format="PNG"); out.seek(0)
    return discord.File(out, filename="rank.png")

async def create_levelup_image(member, old_lv, new_lv):
    img = Image.new('RGB', (600, 200), color=(44, 47, 51))
    draw = ImageDraw.Draw(img)
    f_title, f_sub = get_font(55), get_font(45)
    for _ in range(30):
        x, y = random.randint(0, 600), random.randint(0, 200)
        draw.ellipse((x, y, x+4, y+4), fill=(255, 215, 0))
    draw.text((300, 60), "LEVEL UP !!", fill=(255, 215, 0), font=f_title, anchor="mm")
    draw.text((300, 135), f"Lv.{old_lv} ➔ Lv.{new_lv}", fill=(255, 255, 255), font=f_sub, anchor="mm")
    out = io.BytesIO(); img.save(out, format="PNG"); out.seek(0)
    return discord.File(out, filename="levelup.png")

# --- 5. XPシステム ---
def get_total_multiplier(member, data):
    gid = str(member.guild.id); conf = data["config"].get(gid, {})
    mult = 1.0
    if conf.get("hh_enabled"):
        now_h = get_now_jst().hour
        s, e = conf.get("hh_start", 0), conf.get("hh_end", 0)
        active = (s <= now_h < e) if s < e else (now_h >= s or now_h < e)
        if active: mult *= conf.get("hh_mult", 2.0)
    role_bonuses = conf.get("role_bonuses", {})
    if role_bonuses:
        best_m = 1.0
        for rid, m in role_bonuses.items():
            if any(r.id == int(rid) for r in member.roles): best_m = max(best_m, float(m))
        mult *= best_m
    return mult

async def process_xp(member, amount, data, current_channel=None, skip_mult=False):
    gid, uid = str(member.guild.id), str(member.id)
    u = data["users"].setdefault(uid, {"xp":0, "level":1})
    old_lv = u["level"]
    mult = 1.0 if skip_mult else get_total_multiplier(member, data)
    u["xp"] += int(amount * mult)
    thres = data["config"].get(gid, {}).get("xp_threshold", 100)
    while u["xp"] >= thres: u["level"] += 1; u["xp"] -= thres
    if u["level"] > old_lv:
        # ロール報酬付与
        level_roles = data["config"].get(gid, {}).get("level_roles", {})
        for lv, rid in level_roles.items():
            if u["level"] >= int(lv):
                role = member.guild.get_role(int(rid))
                if role and role not in member.roles: await member.add_roles(role)
        # 通知
        cid = data["config"].get(gid, {}).get("notify_channel")
        target = member.guild.get_channel(int(cid)) if cid else current_channel
        if target:
            file = await create_levelup_image(member, old_lv, u["level"])
            await target.send(content=f"🎉 {member.mention} レベルアップ！", file=file)
# 100行目あたりに追加
def get_omikuji_result():
    return random.choice(["大吉", "中吉", "小吉", "吉", "末吉", "凶", "大凶"])

def get_rankuji_result():
    outcomes = ["💎 ランク当たり", "✨ 大当たり", "✴️ 中当たり", "✳️ 小当たり", "💀 ハズレ"]
    weights = [1, 2, 5, 10, 82]
    return random.choices(outcomes, weights=weights, k=1)[0]


# --- 6. クライアント ---
class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self); self.last_hh_state = {}
    async def setup_hook(self):
        await self.tree.sync(); self.main_loop.start()
    @tasks.loop(minutes=1)
    async def main_loop(self):
        data = load_data(); now_h = get_now_jst().hour
        for guild in self.guilds:
            gid = str(guild.id); conf = data["config"].setdefault(gid, {})
            rate = conf.get("vc_rate", 10)
            for vc in guild.voice_channels:
                for m in vc.members:
                    if not m.bot and not m.voice.self_deaf: await process_xp(m, rate, data)
            if conf.get("hh_enabled"):
                s, e = conf.get("hh_start", 0), conf.get("hh_end", 0)
                is_now = (s <= now_h < e) if s < e else (now_h >= s or now_h < e)
                if is_now != self.last_hh_state.get(gid, False):
                    self.last_hh_state[gid] = is_now
                    ann_id = conf.get("hh_ann_cid")
                    if ann_id:
                        target = guild.get_channel(int(ann_id))
                        if target: await target.send(f"⚡ ハッピーアワー {'開始' if is_now else '終了'}！ ({conf.get('hh_mult', 2.0)}倍)")
        save_data(data)

client = MyClient()

@client.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    data = load_data(); gid, uid = str(message.guild.id), str(message.author.id)
    conf = data["config"].get(gid, {})
    allowed_channels = conf.get("kuji_channels", [])
    if message.channel.id in allowed_channels:
        if message.content == "おみくじ":
            res = random.choice(["大吉", "中吉", "小吉", "吉", "末吉", "凶", "大凶"])
            await message.reply(f"⛩️ おみくじの結果：**{res}** です！")
        elif message.content == "ランくじ！":
            outcomes = ["💎 ランク当たり", "✨ 大当たり", "✴️ 中当たり", "✳️ 小当たり", "💀 ハズレ"]
            res = random.choices(outcomes, weights=[1, 2, 5, 10, 82], k=1)[0]
            await message.reply(f"🎲 抽選結果：**{res}**")
    conf = data["config"].get(gid, {})
    await process_xp(message.author, conf.get("msg_rate", 5), data, message.channel)
    bw = conf.get("bonus_word")
    if bw and bw in message.content:
        claimed = conf.setdefault("bonus_claimed", [])
        if not conf.get("bonus_once") or uid not in claimed:
            await process_xp(message.author, conf.get("bonus_xp", 0), data, message.channel)
            await message.add_reaction("🎁")
            if conf.get("bonus_once"): claimed.append(uid)
    save_data(data)

@client.event
async def on_raw_reaction_add(payload):
    guild = client.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)
    if member and not member.bot:
        data = load_data(); await process_xp(member, data["config"].get(str(guild.id))
