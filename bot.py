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

# --- 1. 常時起動設定 (Render/Replit等用) ---
app = Flask('')
@app.route('/')
def home(): return "Bot is alive!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- 2. データ管理 (バックアップ機能付き) ---
TOKEN = os.getenv('DISCORD_TOKEN')
DATA_FILE = 'server_data.json'
BACKUP_FILE = 'server_data_bak.json'

def get_now_jst():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except: pass
    return {"users": {}, "config": {}}

def save_data(data):
    if os.path.exists(DATA_FILE):
        os.replace(DATA_FILE, BACKUP_FILE)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- 3. フォント取得 (巨大文字用) ---
def get_font(size):
    font_paths = ["font.ttf", "font.otf", "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", "C:\\Windows\\Fonts\\msgothic.ttc"]
    for path in font_paths:
        if os.path.exists(path): return ImageFont.truetype(path, size)
    return ImageFont.load_default()

# --- 4. 画像生成 (デカ文字・高解像度レイアウト) ---
async def create_level_card(member, level, xp, threshold):
    img = Image.new('RGB', (600, 300), color=(35, 39, 42))
    draw = ImageDraw.Draw(img)
    f_name, f_info, f_xp = get_font(70), get_font(60), get_font(35)
    try:
        asset = member.display_avatar.with_format("png").with_size(256)
        pfp = Image.open(io.BytesIO(await asset.read())).convert("RGBA").resize((170, 170))
        mask = Image.new("L", (170, 170), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 170, 170), fill=255)
        img.paste(pfp, (25, 45), mask)
    except: pass
    draw.text((215, 35), f"{member.display_name}", fill=(255, 255, 255), font=f_name)
    draw.text((215, 120), f"Lv. {level}", fill=(255, 215, 0), font=f_info)
    bar_w, bar_h, bar_x, bar_y = 360, 40, 215, 205
    prog = min((xp / threshold) * bar_w, bar_w) if threshold > 0 else bar_w
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=20, fill=(60, 63, 65))
    if prog > 0: draw.rounded_rectangle([bar_x, bar_y, bar_x + prog, bar_y + bar_h], radius=20, fill=(114, 137, 218))
    draw.text((215, 250), f"XP: {xp} / {threshold}", fill=(180, 180, 180), font=f_xp)
    out = io.BytesIO(); img.save(out, format="PNG"); out.seek(0)
    return discord.File(out, filename="rank.png")

async def create_levelup_image(member, old_lv, new_lv):
    img = Image.new('RGB', (600, 250), color=(44, 47, 51))
    draw = ImageDraw.Draw(img)
    f_title, f_sub = get_font(90), get_font(70)
    for _ in range(50):
        x, y = random.randint(0, 600), random.randint(0, 250)
        draw.ellipse((x, y, x+6, y+6), fill=(random.randint(200, 255), 215, 0))
    draw.text((300, 80), "LEVEL UP!", fill=(255, 215, 0), font=f_title, anchor="mm")
    draw.text((300, 180), f"Lv.{old_lv} > {new_lv}", fill=(255, 255, 255), font=f_sub, anchor="mm")
    out = io.BytesIO(); img.save(out, format="PNG"); out.seek(0)
    return discord.File(out, filename="levelup.png")

# --- 5. XPシステム ---
def get_total_multiplier(member, data):
    gid = str(member.guild.id); conf = data["config"].get(gid, {})
    mult = 1.0
    if conf.get("hh_enabled"):
        now_h = get_now_jst().hour
        s, e = conf.get("hh_start", 0), conf.get("hh_end", 0)
        if (s <= now_h < e) if s < e else (now_h >= s or now_h < e):
            mult *= conf.get("hh_mult", 2.0)
    rb = conf.get("role_bonuses", {})
    if rb:
        best = 1.0
        for rid, m in rb.items():
            if any(r.id == int(rid) for r in member.roles): best = max(best, float(m))
        mult *= best
    return mult

async def process_xp(member, amount, data, current_channel=None, skip_mult=False, type="msg"):
    gid, uid = str(member.guild.id), str(member.id)
    # 通算データの枠がなければ作成（ここが追加）
    u = data["users"].setdefault(uid, {"xp":0, "level":1, "total_msg":0, "total_vc":0, "total_react":0})
    
    # 通算カウントアップ（ここが追加）
    if type == "msg": u["total_msg"] = u.get("total_msg", 0) + 1
    elif type == "vc": u["total_vc"] = u.get("total_vc", 0) + 1
    elif type == "react": u["total_react"] = u.get("total_react", 0) + 1

    old_lv = u["level"]
    mult = 1.0 if skip_mult else get_total_multiplier(member, data)
    u["xp"] += int(amount * mult)
    
    conf = data["config"].get(gid, {})
    thres = conf.get("xp_threshold", 100)
    while u["xp"] >= thres: u["level"] += 1; u["xp"] -= thres
    
    if u["level"] > old_lv:
        # ロール付与（既存の機能）
        level_roles = conf.get("level_roles", {})
        for lv, rid in level_roles.items():
            if u["level"] >= int(lv):
                role = member.guild.get_role(int(rid))
                if role and role not in member.roles: await member.add_roles(role)

        # ① ランクアップ通知（画像・全員用：既存の機能）
        cid = conf.get("notify_channel")
        target = member.guild.get_channel(int(cid)) if cid else current_channel
        if target:
            file = await create_levelup_image(member, old_lv, u["level"])
            await target.send(content=f"🎉 {member.mention} レベルアップ！", file=file)

        # ② レベルアップ履歴（管理者ログ用：ここが追加）
        history_cid = conf.get("history_channel")
        h_target = member.guild.get_channel(int(history_cid))
        if h_target:
            now = get_now_jst().strftime('%Y/%m/%d %H:%M')
            await h_target.send(f"📋 【ログ】`{now}`: **{member.display_name}** が Lv.{u['level']} に昇格しました。")

async def process_xp(member, amount, data, current_channel=None, skip_mult=False):
    gid, uid = str(member.guild.id), str(member.id)
    u = data["users"].setdefault(uid, {"xp":0, "level":1})
    old_lv = u["level"]
    mult = 1.0 if skip_mult else get_total_multiplier(member, data)
    u["xp"] += int(amount * mult)
    
    conf = data["config"].get(gid, {})
    thres = conf.get("xp_threshold", 100)
    while u["xp"] >= thres:
        u["level"] += 1
        u["xp"] -= thres
    
    if u["level"] > old_lv:
        level_roles = conf.get("level_roles", {})
        for lv, rid in level_roles.items():
            if u["level"] >= int(lv):
                role = member.guild.get_role(int(rid))
                if role and role not in member.roles: await member.add_roles(role)
        cid = conf.get("notify_channel")
        target = member.guild.get_channel(int(cid)) if cid else current_channel
        if target:
            file = await create_levelup_image(member, old_lv, u["level"])
            await target.send(content=f"🎊 {member.mention} **LEVEL UP!!**", file=file)

async def get_server_activity_custom(guild, data, days):
    gid = str(guild.id)
    activity_data = data.get("activity_log", {}).get(gid, [])
    threshold_seconds = days * 86400
    now = datetime.datetime.now().timestamp()
    limit_time = now - threshold_seconds
    recent_messages = [ts for ts in activity_data if ts > limit_time]
    
    # 掃除
    oldest_allowed = now - (30 * 86400) 
    data.setdefault("activity_log", {})[gid] = [ts for ts in recent_messages if ts > oldest_allowed]
    
    count = len(recent_messages)
    avg = count / days
    if avg < 5: status = "極めて静か"
    elif avg < 30: status = "少し過疎気味"
    elif avg < 100: status = "安定"
    else: status = "活発"
    return status, count

# --- 6. クライアント ---
class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)
        self.last_hh_state = {}

    async def setup_hook(self):
        self.main_loop.start()

    @tasks.loop(minutes=1)
    async def main_loop(self):
        data = load_data()
        for guild in self.guilds:
            gid = str(guild.id); conf = data["config"].setdefault(gid, {})
            rate = conf.get("vc_rate", 10)
            for vc in guild.voice_channels:
                # メンバーが2人以上（自分以外に誰かいる）時のみXP付与
                members_in_vc = [m for m in vc.members if not m.bot]
                if len(members_in_vc) >= 2:
                    for m in members_in_vc:
                        await process_xp(m, rate, data, type="vc")
        save_data(data)

client = MyClient()

@client.event
async def on_ready():
    for guild in client.guilds:
        await client.tree.sync(guild=guild)
    print(f"✅ {client.user} 起動完了（1人VC除外設定済）")

@client.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    data = load_data(); gid, uid = str(message.guild.id), str(message.author.id)
    conf = data["config"].setdefault(gid, {})
    
    # おみくじ/ランくじ
    if message.channel.id in conf.get("kuji_channels", []):
        if message.content == "おみくじ":
            res = random.choice(["大吉","中吉","小吉","吉","末吉","凶","大凶"])
            await message.reply(f"⛩️ おみくじ結果：**{res}**")
        elif message.content == "ランくじ！":
            out = ["💎ランク当","✨大当","✴️中当","✳️小当","💀ハズレ"]
            w = conf.get("rankuji_weights", [1, 2, 5, 10, 82])
            res = random.choices(out, weights=w, k=1)
            await message.reply(f"🎲 抽選結果：**{res[0]}**")

    # XP処理 (メッセージ)
    await process_xp(message.author, conf.get("msg_rate", 5), data, message.channel)
    
    # 合言葉ボーナス
    bw = conf.get("bonus_word")
    if bw and bw in message.content:
        claimed = conf.setdefault("bonus_claimed", [])
        if uid not in claimed or not conf.get("bonus_once", True):
            await process_xp(message.author, conf.get("bonus_xp", 50), data, message.channel, skip_mult=True)
            await message.add_reaction("🎁")
            if uid not in claimed: claimed.append(uid)
    save_data(data)

@client.event
async def on_raw_reaction_add(payload):
    guild = client.get_guild(payload.guild_id)
    if not guild or not payload.member or payload.member.bot: return
    data = load_data()
    await process_xp(payload.member, data["config"].get(str(guild.id), {}).get("react_rate", 2), data, type="react")
    save_data(data)

@client.event
async def on_message_delete(message):
    if message.author.bot or not message.guild: return
    data = load_data(); uid = str(message.author.id)
    penalty = data["config"].get(str(message.guild.id), {}).get("msg_rate", 5)
    if uid in data["users"]:
        u = data["users"][uid]
        u["xp"] = max(0, u["xp"] - penalty)
        u["total_msg"] = max(0, u.get("total_msg", 0) - 1)
        save_data(data)

@client.event
async def on_raw_reaction_remove(payload):
    guild = client.get_guild(payload.guild_id)
    if not guild: return
    member = guild.get_member(payload.user_id)
    if not member or member.bot: return
    data = load_data(); uid = str(member.id)
    penalty = data["config"].get(str(guild.id), {}).get("react_rate", 2)
    if uid in data["users"]:
        u = data["users"][uid]
        u["xp"] = max(0, u["xp"] - penalty)
        u["total_react"] = max(0, u.get("total_react", 0) - 1)
        save_data(data)


# --- 7. スラッシュコマンド (全機能網羅) ---

@client.tree.command(name="rank", description="デカ文字ランクカードを表示")
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    data = load_data()
    u = data["users"].get(str(member.id), {"xp": 0, "level": 1})
    thres = data["config"].get(str(interaction.guild.id), {}).get("xp_threshold", 100)
    await interaction.response.defer()
    file = await create_level_card(member, u["level"], u["xp"], thres)
    await interaction.followup.send(file=file)

@client.tree.command(name="config_show", description="【管理者】現在の全設定を確認")
@app_commands.checks.has_permissions(administrator=True)
async def config_show(interaction: discord.Interaction):
    data = load_data(); conf = data["config"].get(str(interaction.guild.id), {})
    embed = discord.Embed(title="⚙️ 設定一覧", color=0x3498db)
    for k, v in conf.items():
        if "claimed" not in k: embed.add_field(name=k, value=f"`{v}`", inline=True)
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="config_base", description="【管理者】基本XP設定 (次LvへのXP, メッセージXP, VC XP)")
@app_commands.checks.has_permissions(administrator=True)
async def config_base(interaction: discord.Interaction, threshold: int, msg: int, vc: int, notify_ch: discord.TextChannel):
    data = load_data(); conf = data["config"].setdefault(str(interaction.guild.id), {})
    conf.update({"xp_threshold": threshold, "msg_rate": msg, "vc_rate": vc, "notify_channel": str(notify_ch.id)})
    save_data(data); await interaction.response.send_message("✅ 基本設定を更新しました。")

@client.tree.command(name="config_hh", description="【管理者】ハッピーアワー (開始/終了時, 倍率)")
@app_commands.checks.has_permissions(administrator=True)
async def config_hh(interaction: discord.Interaction, enabled: bool, start: int, end: int, mult: float):
    data = load_data(); conf = data["config"].setdefault(str(interaction.guild.id), {})
    conf.update({"hh_enabled": enabled, "hh_start": start, "hh_end": end, "hh_mult": mult, "hh_ann_cid": str(interaction.channel.id)})
    save_data(data); await interaction.response.send_message(f"✅ ハッピーアワーを {'有効' if enabled else '無効'} にしました。")

@client.tree.command(name="config_reward", description="【管理者】レベル報酬/役職倍率")
@app_commands.checks.has_permissions(administrator=True)
async def config_reward(interaction: discord.Interaction, level: int = None, role: discord.Role = None, mult: float = None):
    data = load_data(); conf = data["config"].setdefault(str(interaction.guild.id), {})
    if level and role: conf.setdefault("level_roles", {})[str(level)] = str(role.id)
    if role and mult: conf.setdefault("role_bonuses", {})[str(role.id)] = mult
    save_data(data); await interaction.response.send_message("✅ 報酬/倍率設定を更新。")

@client.tree.command(name="kuji_set", description="【管理者】おみくじch設定")
@app_commands.checks.has_permissions(administrator=True)
async def kuji_set(interaction: discord.Interaction, channel: discord.TextChannel):
    data = load_data(); conf = data["config"].setdefault(str(interaction.guild.id), {})
    chs = conf.setdefault("kuji_channels", [])
    if channel.id in chs: chs.remove(channel.id); m = "解除"
    else: chs.append(channel.id); m = "登録"
    save_data(data); await interaction.response.send_message(f"✅ {channel.mention} をおみくじ対象に{m}しました。")

@client.tree.command(name="admin_set", description="【管理者】特定ユーザーのXP/Lvを直接変更")
@app_commands.checks.has_permissions(administrator=True)
async def admin_set(interaction: discord.Interaction, member: discord.Member, level: int, xp: int):
    data = load_data(); data["users"][str(member.id)] = {"xp": xp, "level": level}
    save_data(data); await interaction.response.send_message(f"✅ {member.display_name} を Lv.{level} / {xp}XP に設定。")
    
@client.tree.command(name="daily", description="1日1回のボーナスXPを受け取ります")
async def daily(interaction: discord.Interaction):
    data = load_data()
    uid = str(interaction.user.id)
    u = data["users"].setdefault(uid, {"xp": 0, "level": 1, "last_daily": 0})
    
    now = datetime.datetime.now().timestamp()
    # 24時間（86400秒）経過しているかチェック
    if now - u.get("last_daily", 0) < 86400:
        rem = int(86400 - (now - u["last_daily"]))
        hours = rem // 3600
        await interaction.response.send_message(f"❌ まだ受け取れません！ あと約 {hours} 時間後です。", ephemeral=True)
        return
        
    bonus = random.randint(50, 150) # 50〜150の間でランダム
    u["last_daily"] = now
    await process_xp(interaction.user, bonus, data, interaction.channel, skip_mult=True)
    save_data(data)
    
    await interaction.response.send_message(f"🎁 **デイリーボーナス！** \n`{bonus} XP` を獲得しました！")

@client.tree.command(name="stats", description="自分の通算統計データを表示します")
async def stats(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    data = load_data()
    u = data["users"].get(str(member.id), {})
    embed = discord.Embed(title=f"📊 {member.display_name} の統計", color=0x3498db)
    embed.add_field(name="通算メッセージ", value=f"{u.get('total_msg', 0)} 通", inline=True)
    embed.add_field(name="通算リアクション", value=f"{u.get('total_react', 0)} 回", inline=True)
    embed.add_field(name="通算VC獲得数", value=f"{u.get('total_vc', 0)} 回", inline=True)
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="config_history", description="【管理者】管理者用ログチャンネルを設定")
@app_commands.checks.has_permissions(administrator=True)
async def config_history(interaction: discord.Interaction, channel: discord.TextChannel):
    data = load_data()
    data["config"].setdefault(str(interaction.guild.id), {})["history_channel"] = str(channel.id)
    save_data(data)
    await interaction.response.send_message(f"✅ 管理者ログを {channel.mention} に設定しました。")

# --- 8. 起動 ---
if __name__ == "__main__":
    keep_alive()
    client.run(TOKEN)
