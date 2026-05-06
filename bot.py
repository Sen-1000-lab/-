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

# --- 3. フォント取得 (標準サイズ) ---
def get_font(size):
    # フォントパスはそのまま、呼び出し時のサイズで調整
    font_paths = ["font.ttf", "font.otf", "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", "C:\\Windows\\Fonts\\msgothic.ttc"]
    for path in font_paths:
        if os.path.exists(path): return ImageFont.truetype(path, size)
    return ImageFont.load_default()

# --- 4. 画像生成 (普通サイズ・モダンレイアウト) ---
async def create_level_card(member, level, xp, threshold):
    # 高さを少し抑えてシュッとさせました
    img = Image.new('RGB', (600, 180), color=(26, 27, 30)) 
    draw = ImageDraw.Draw(img)
    
    # フォントサイズを標準的な大きさに変更
    f_name = get_font(32)   # 名前用
    f_lv = get_font(28)     # Lv数値用
    f_label = get_font(20)  # "LEVEL" や "XP" という文字用
    f_xp = get_font(22)     # XP数値用

    # アイコン描画 (少し小さくして左に配置)
    try:
        asset = member.display_avatar.with_format("png").with_size(128)
        pfp = Image.open(io.BytesIO(await asset.read())).convert("RGBA").resize((120, 120))
        mask = Image.new("L", (120, 120), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 120, 120), fill=255)
        img.paste(pfp, (30, 30), mask)
    except: pass

    # 名前
    draw.text((170, 35), f"{member.display_name}", fill=(255, 255, 255), font=f_name)
    
    # レベル表示 (LEVEL 12 みたいな並び)
    draw.text((170, 85), "LEVEL", fill=(114, 137, 218), font=f_label)
    draw.text((245, 78), f"{level}", fill=(255, 255, 255), font=f_lv)

    # XP表示 (右寄せで 100 / 1000 XP みたいな感じ)
    xp_text = f"{xp} / {threshold} XP"
    bbox = draw.textbbox((0, 0), xp_text, font=f_xp)
    draw.text((570 - (bbox[2] - bbox[0]), 85), xp_text, fill=(180, 180, 180), font=f_xp)

    # プログレスバー (細めにしてスッキリ)
    bar_w, bar_h, bar_x, bar_y = 400, 16, 170, 120
    prog = min((xp / threshold) * bar_w, bar_w) if threshold > 0 else bar_w
    
    # バーの背景
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=8, fill=(60, 63, 65))
    # バーの進捗 (Discordカラー)
    if prog > 0:
        draw.rounded_rectangle([bar_x, bar_y, bar_x + prog, bar_y + bar_h], radius=8, fill=(114, 137, 218))

    out = io.BytesIO(); img.save(out, format="PNG"); out.seek(0)
    return discord.File(out, filename="rank.png")

# レベルアップ画像も少しだけ落ち着いたデザインに
async def create_levelup_image(member, old_lv, new_lv):
    img = Image.new('RGB', (500, 150), color=(35, 39, 42))
    draw = ImageDraw.Draw(img)
    f_main = get_font(45)
    f_sub = get_font(30)

    draw.text((250, 50), "LEVEL UP!", fill=(255, 215, 0), font=f_main, anchor="mm")
    draw.text((250, 100), f"Lv.{old_lv} → Lv.{new_lv}", fill=(255, 255, 255), font=f_sub, anchor="mm")
    
    # 飾り付けの線を上下に入れる
    draw.line([(50, 130), (450, 130)], fill=(255, 215, 0), width=2)
    
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
    await client.tree.sync()
    print(f"✅ {client.user} 起動完了（1人VC除外設定済）")
    
@client.event
async def on_message(message):
    # BotのメッセージやDMは無視
    if message.author.bot or not message.guild:
        return
    
    data = load_data()
    gid = str(message.guild.id)
    cid = str(message.channel.id)
    conf = data["config"].get(gid, {})
    final_xp = 0
    is_kuji = False

    # --- 1. おみくじ判定 ---
    if cid == conf.get("omikuji_channel") and message.content == "おみくじ":
        is_kuji = True
        res = random.choice(["大吉","中吉","小吉","吉","末吉","凶","大凶"])
        final_xp = conf.get("omikuji_base_xp", 0)
        if res == "大吉":
            final_xp += conf.get("bonus_daikichi", 0)
        await message.reply(f"⛩️ おみくじ結果：**{res}** (獲得XP: {final_xp})")

    # --- 2. ランくじ！判定 ---
    elif cid == conf.get("rankuji_channel") and message.content == "ランくじ！":
        is_kuji = True
        out = ["💎ランク当","✨大当","✴️中当","✳️小当","💀ハズレ"]
        w = conf.get("rankuji_weights", [1, 2, 5, 10, 82])
        res_list = random.choices(out, weights=w, k=1)
        res = res_list[0]
        final_xp = conf.get("rankuji_base_xp", 0)
        if res == "💎ランク当":
            final_xp += conf.get("bonus_rank_win", 0)
        await message.reply(f"🎲 抽選結果：**{res}** (獲得XP: {final_xp})")

    # --- 3. くじ引きのXP付与（くじを引いた場合） ---
    if is_kuji:
        if final_xp > 0:
            await process_xp(message.author, final_xp, data, current_channel=message.channel, skip_mult=True)
            save_data(data)
        return # くじの時はここで終了

    # --- 4. 通常の会話XP処理 (合言葉ボーナスなし) ---
    amount = conf.get("msg_rate", 20)
    data.setdefault("activity_log", {}).setdefault(gid, []).append(get_now_jst().timestamp())
    
    await process_xp(message.author, amount, data, current_channel=message.channel)
    save_data(data)
 
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

@client.tree.command(name="rank", description="現在のランクカードを表示します")
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    # 相手が指定されなければ実行した本人を対象にする
    target = member or interaction.user
    
    data = load_data()
    uid = str(target.id)
    gid = str(interaction.guild.id)
    
    # ユーザーデータとサーバー設定（しきい値）を取得
    u = data["users"].get(uid, {"xp": 0, "level": 1})
    conf = data["config"].get(gid, {})
    thres = conf.get("xp_threshold", 100)

    # 1. 応答を待機状態にする（画像生成中のタイムアウト防止）
    await interaction.response.defer()
    
    # 2. 画像を作成
    file = await create_level_card(target, u["level"], u["xp"], thres)
    
    # 3. 待機状態の応答を上書きして画像を送信
    await interaction.followup.send(file=file)


@client.tree.command(name="config_show", description="【管理者】現在の全設定を確認")
@app_commands.checks.has_permissions(administrator=True)
async def config_show(interaction: discord.Interaction):
    data = load_data(); conf = data["config"].get(str(interaction.guild.id), {})
    embed = discord.Embed(title="⚙️ 設定一覧", color=0x3498db)
    for k, v in conf.items():
        if "claimed" not in k: embed.add_field(name=k, value=f"`{v}`", inline=True)
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="config_threshold", description="【管理者】レベルアップに必要なXPを設定します")
@app_commands.checks.has_permissions(administrator=True)
async def config_threshold(interaction: discord.Interaction, threshold: int):
    data = load_data()
    conf = data["config"].setdefault(str(interaction.guild.id), {})
    conf["xp_threshold"] = threshold
    save_data(data)
    await interaction.response.send_message(f"✅ 次のレベルに必要なXPを **{threshold}** に設定しました。")

@client.tree.command(name="config_rates", description="【管理者】メッセージ、VC、リアクションの獲得XPを設定します")
@app_commands.checks.has_permissions(administrator=True)
async def config_rates(interaction: discord.Interaction, msg: int, vc: int, react: int):
    data = load_data()
    conf = data["config"].setdefault(str(interaction.guild.id), {})
    conf.update({"msg_rate": msg, "vc_rate": vc, "react_rate": react})
    save_data(data)
    await interaction.response.send_message(f"✅ 獲得XPを更新：MSG **{msg}** / VC **{vc}** / React **{react}**")

@client.tree.command(name="config_channel", description="【管理者】お祝い画像を送るチャンネルを設定します")
@app_commands.checks.has_permissions(administrator=True)
async def config_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    data = load_data()
    conf = data["config"].setdefault(str(interaction.guild.id), {})
    conf["notify_channel"] = str(channel.id)
    save_data(data)
    await interaction.response.send_message(f"✅ レベルアップ通知を {channel.mention} に設定しました。")

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

# --- くじ引き設定コマンド群 ---

@client.tree.command(name="config_omikuji", description="【管理者】おみくじを有効にするチャンネルを設定します")
@app_commands.checks.has_permissions(administrator=True)
async def config_omikuji(interaction: discord.Interaction, channel: discord.TextChannel):
    data = load_data()
    conf = data["config"].setdefault(str(interaction.guild.id), {})
    conf["omikuji_channel"] = str(channel.id)
    save_data(data)
    await interaction.response.send_message(f"⛩️ {channel.mention} で「おみくじ」を有効にしました。")

@client.tree.command(name="config_rankuji", description="【管理者】ランくじ！を有効にするチャンネルを設定します")
@app_commands.checks.has_permissions(administrator=True)
async def config_rankuji(interaction: discord.Interaction, channel: discord.TextChannel):
    data = load_data()
    conf = data["config"].setdefault(str(interaction.guild.id), {})
    conf["rankuji_channel"] = str(channel.id)
    save_data(data)
    await interaction.response.send_message(f"🎲 {channel.mention} で「ランくじ！」を有効にしました。")

@client.tree.command(name="config_kuji_xp", description="【管理者】くじ引き時に一律で付与するXPを設定します")
@app_commands.checks.has_permissions(administrator=True)
async def config_kuji_xp(interaction: discord.Interaction, omikuji_xp: int, rankuji_xp: int):
    data = load_data()
    conf = data["config"].setdefault(str(interaction.guild.id), {})
    conf["omikuji_base_xp"] = omikuji_xp
    conf["rankuji_base_xp"] = rankuji_xp
    save_data(data)
    await interaction.response.send_message(f"✅ 基本XP設定：おみくじ {omikuji_xp} / ランくじ {rankuji_xp}")

@client.tree.command(name="config_kuji_bonus", description="【管理者】特定の当たりが出た時のボーナスXPを設定します")
@app_commands.checks.has_permissions(administrator=True)
async def config_kuji_bonus(interaction: discord.Interaction, daikichi_bonus: int, rank_win_bonus: int):
    data = load_data()
    conf = data["config"].setdefault(str(interaction.guild.id), {})
    conf["bonus_daikichi"] = daikichi_bonus
    conf["bonus_rank_win"] = rank_win_bonus
    save_data(data)
    await interaction.response.send_message(f"✅ ボーナス設定：大吉 +{daikichi_bonus} / ランク当 +{rank_win_bonus}")

@client.tree.command(name="config_rankuji", description="【管理者】ランくじ！を有効にするチャンネルを設定します")
@app_commands.checks.has_permissions(administrator=True)
async def config_rankuji(interaction: discord.Interaction, channel: discord.TextChannel):
    data = load_data()
    conf = data["config"].setdefault(str(interaction.guild.id), {})
    conf["rankuji_channel"] = str(channel.id)
    save_data(data)
    await interaction.response.send_message(f"🎲 {channel.mention} で「ランくじ！」が引けるようになりました。")

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

# --- 管理者用：XP付与コマンド ---
@client.tree.command(name="give_xp", description="【管理者】指定したメンバーにXPを付与します")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(member="XPを付与するメンバー", amount="付与するXPの量")
async def give_xp(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message("1以上の数値を入力してください。", ephemeral=True)
        return

    data = load_data()
    # process_xpを呼び出してXPを付与（倍率無視、通知あり）
    await process_xp(member, amount, data, current_channel=interaction.channel, skip_mult=True)
    save_data(data)

    await interaction.response.send_message(f"✅ {member.display_name} に **{amount} XP** を付与しました！")

# エラーハンドリング（権限がない場合）
@give_xp.error
async def give_xp_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ このコマンドを実行する権限（管理者権限）がありません。", ephemeral=True)

@client.tree.command(name="top", description="レベルが高い上位10名を表示します")
async def top(interaction: discord.Interaction):
    data = load_data()
    users = data.get("users", {})
    
    if not users:
        await interaction.response.send_message("まだデータがありません。", ephemeral=True)
        return

    # レベル、次にXPの順でソートして上位10人を取得
    sorted_users = sorted(
        users.items(), 
        key=lambda x: (x[1].get("level", 1), x[1].get("xp", 0)), 
        reverse=True
    )[:10]

    embed = discord.Embed(
        title=f"🏆 {interaction.guild.name} レベルランキング",
        color=discord.Color.gold(),
        timestamp=get_now_jst()
    )

    leaderboard_text = ""
    for i, (uid, udata) in enumerate(sorted_users, 1):
        member = interaction.guild.get_member(int(uid))
        name = member.display_name if member else f"User({uid})"
        
        level = udata.get("level", 1)
        xp = udata.get("xp", 0)
        
        # 上位3名には絵文字をつける
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"`{i}.` ")
        leaderboard_text += f"{medal} **{name}** - Lv.{level} (XP: {xp})\n"

    embed.description = leaderboard_text
    await interaction.response.send_message(embed=embed)


# --- 8. 起動 ---
if __name__ == "__main__":
    keep_alive()
    client.run(TOKEN)
