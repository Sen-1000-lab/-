import discord
from discord import app_commands
from discord.ext import tasks
from datetime import datetime
import json
import os

# --- 設定 ---
TOKEN = os.getenv('DISCORD_TOKEN')
class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        self.vc_check.start()

    @tasks.loop(minutes=1)
    async def vc_check(self):
        data = load_data()
        for guild in self.guilds:
            gid = str(guild.id)
            rate = data["config"].get(gid, {}).get("vc_rate", 10)
            for vc in guild.voice_channels:
                for m in vc.members:
                    if not m.bot and not m.voice.self_deaf:
                        await process_xp(str(m.id), guild, rate, data, None)
                        record_activity(gid, "vc", data)
                        u = data["users"].get(str(m.id), {})
                        u["total_vc"] = u.get("total_vc", 0) + 1
                        data["users"][str(m.id)] = u
        save_data(data)

client = MyClient()
DATA_FILE = 'server_data.json'

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            try: return json.load(f)
            except: pass
    return {"users": {}, "config": {}, "activity": {"msg": {}, "vc": {}, "react": {}}}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def record_activity(gid, type_key, data):
    if "activity" not in data: data["activity"] = {"msg": {}, "vc": {}, "react": {}}
    if gid not in data["activity"][type_key]: data["activity"][type_key][gid] = []
    data["activity"][type_key][gid].append(datetime.now().timestamp())

async def process_xp(user_id, guild, amount, data, current_channel):
    gid = str(guild.id)
    if user_id not in data["users"]:
        data["users"][user_id] = {"xp": 0, "level": 1, "msg_count": 0, "total_vc": 0, "react_count": 0}
    u = data["users"][user_id]
    u["xp"] += amount
    threshold = data["config"].get(gid, {}).get("xp_threshold", 100)
    if u["xp"] >= threshold:
        u["level"] += 1
        u["xp"] -= threshold
        cid = data["config"].get(gid, {}).get("notify_channel")
        target = guild.get_channel(int(cid)) if cid else current_channel
        if target: await target.send(f"🆙 {guild.get_member(int(user_id)).mention} Level {u['level']}!")
        role_id = data["config"].get(gid, {}).get("roles", {}).get(str(u["level"]))
        if role_id:
            member = guild.get_member(int(user_id))
            role = guild.get_role(int(role_id))
            if member and role: await member.add_roles(role)

@client.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    data = load_data()
    uid, gid = str(message.author.id), str(message.guild.id)
    rate = data["config"].get(gid, {}).get("msg_rate", 5)
    await process_xp(uid, message.guild, rate, data, message.channel)
    data["users"][uid]["msg_count"] = data["users"][uid].get("msg_count", 0) + 1
    record_activity(gid, "msg", data)
    save_data(data)

@client.event
async def on_reaction_add(reaction, user):
    if user.bot: return
    data = load_data()
    gid = str(reaction.message.guild.id)
    record_activity(gid, "react", data)
    uid = str(user.id)
    if uid in data["users"]:
        data["users"][uid]["react_count"] = data["users"][uid].get("react_count", 0) + 1
        await process_xp(uid, reaction.message.guild, 2, data, None)
    save_data(data)

# --- スラッシュコマンド群 ---

@client.tree.command(name="rank", description="ランキング表示")
async def rank(interaction: discord.Interaction):
    data = load_data()
    sorted_u = sorted(data["users"].items(), key=lambda x: (x[1]['level'], x[1]['xp']), reverse=True)[:10]
    desc = "\n".join([f"**{i+1}位**: <@{uid}> - Lv.{u['level']}" for i, (uid, u) in enumerate(sorted_u)])
    await interaction.response.send_message(embed=discord.Embed(title="🏆 ランキング", description=desc, color=0xffd700))

@client.tree.command(name="stats_user", description="個人統計を表示")
async def stats_user(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    u = load_data()["users"].get(str(member.id), {"level":1, "xp":0, "msg_count":0, "total_vc":0, "react_count":0})
    embed = discord.Embed(title=f"👤 {member.display_name}", color=0x3498db)
    embed.add_field(name="Lv/XP", value=f"Lv.{u['level']} ({u['xp']}xp)")
    embed.add_field(name="統計", value=f"💬{u.get('msg_count',0)} 🎙️{u.get('total_vc',0)}分 ❤️{u.get('react_count',0)}")
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="stats_server", description="過疎具合を表示")
async def stats_server(interaction: discord.Interaction):
    data = load_data()
    gid = str(interaction.guild.id)
    days = data["config"].get(gid, {}).get("kaso_days", 1)
    limit = datetime.now().timestamp() - (days * 86400)
    def cnt(k): return len([t for t in data["activity"].get(k, {}).get(gid, []) if t > limit])
    m, v, r = cnt("msg"), cnt("vc"), cnt("react")
    score = m + (v * 2) + r
    status = "活発🔥" if score > days * 50 else "普通🌿" if score > days * 10 else "過疎👻"
    await interaction.response.send_message(f"🏰 判定: **{status}** ({days}日間計: メッセ{m}/VC{v}分/リアク{r})")

@client.tree.command(name="config_all", description="【管理】XP取得量と過疎日数を一括設定")
@app_commands.checks.has_permissions(administrator=True)
async def config_all(interaction: discord.Interaction, msg: int, vc: int, react: int, kaso_days: int):
    data = load_data()
    data["config"].setdefault(str(interaction.guild.id), {}).update({"msg_rate":msg, "vc_rate":vc, "react_rate":react, "kaso_days":kaso_days})
    save_data(data)
    await interaction.response.send_message("✅ 設定を更新しました。")

@client.tree.command(name="config_level", description="【管理】必要XPと通知先、ロール報酬を設定")
@app_commands.checks.has_permissions(administrator=True)
async def config_level(interaction: discord.Interaction, required_xp: int = None, channel: discord.TextChannel = None, level: int = None, role: discord.Role = None):
    data = load_data()
    conf = data["config"].setdefault(str(interaction.guild.id), {})
    if required_xp: conf["xp_threshold"] = required_xp
    if channel: conf["notify_channel"] = str(channel.id)
    if level and role: conf.setdefault("roles", {})[str(level)] = str(role.id)
    save_data(data)
    await interaction.response.send_message("✅ レベル設定を更新しました。")

@client.tree.command(name="give_xp", description="【管理】XP付与")
@app_commands.checks.has_permissions(administrator=True)
async def give_xp(interaction: discord.Interaction, member: discord.Member, amount: int):
    data = load_data()
    await process_xp(str(member.id), interaction.guild, amount, data, interaction.channel)
    save_data(data)
    await interaction.response.send_message(f"✅ {member.mention} に {amount}XP 付与しました。")

client.run(TOKEN)
