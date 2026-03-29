import os
import random
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

DB_PATH = "minigame_bot.db"
TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")
UTC7 = timezone(timedelta(hours=7))
BASE_DIR = Path(__file__).resolve().parent
BAU_CUA_IMAGE_FILE = BASE_DIR / "bau_cua_board.jpg"

BAU_CUA_ITEMS = ["bầu", "cua", "tôm", "cá", "gà", "nai"]
BAU_CUA_EMOJIS = {
    "bầu": "🍐",
    "cua": "🦀",
    "tôm": "🦐",
    "cá": "🐟",
    "gà": "🐓",
    "nai": "🦌",
}
CHECK_EMOJI = "✅"
CROSS_EMOJI = "❌"


# ================== DATABASE ==================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def setup_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            coins INTEGER NOT NULL DEFAULT 0,
            daily_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def ensure_user(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (user_id,))
    conn.commit()
    conn.close()


def get_balance(user_id: int) -> int:
    ensure_user(user_id)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return int(row["coins"]) if row else 0


def add_coins(user_id: int, amount: int):
    ensure_user(user_id)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()


def set_daily(user_id: int, when_iso: str):
    ensure_user(user_id)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET daily_at = ? WHERE user_id = ?", (when_iso, user_id))
    conn.commit()
    conn.close()


def get_daily(user_id: int):
    ensure_user(user_id)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT daily_at FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["daily_at"] if row else None


def can_claim_daily(user_id: int):
    last = get_daily(user_id)
    if not last:
        return True, None
    last_dt = datetime.fromisoformat(last)
    now = datetime.now(UTC7)
    if now - last_dt >= timedelta(hours=24):
        return True, None
    return False, timedelta(hours=24) - (now - last_dt)


# ================== HELPERS ==================
def fmt_coin(amount: int) -> str:
    return f"{amount:,} xu".replace(",", ".")


def make_embed(title: str, description: str = "", color: int = 0xF1C40F) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(UTC7),
    )
    embed.set_footer(text="Kim Long MiniGame")
    return embed


def normalize_phrase(text: str) -> str:
    return " ".join(text.lower().strip().split())


def is_valid_noitu(previous_word: Optional[str], new_word: str) -> bool:
    if not previous_word or not new_word.strip():
        return False
    last = previous_word.strip().lower().split()[-1]
    first = new_word.strip().lower().split()[0]
    return last == first


def scramble_word(word: str) -> str:
    if len(word) <= 1:
        return word
    scrambled = word
    for _ in range(10):
        scrambled = "".join(random.sample(word, len(word)))
        if scrambled != word:
            return scrambled
    return scrambled


def format_scrambled_letters(word: str) -> str:
    cleaned = word.replace(" ", "")
    scrambled = scramble_word(cleaned)
    return "/".join(scrambled)


def make_gheptu_embed(scrambled_display: str, length: int) -> discord.Embed:
    embed = discord.Embed(
        title="🎲 Vua Tiếng Việt",
        description=(
            f"**Từ cần đoán:** `{scrambled_display}` (gồm **{length}** ký tự)\n"
            "**Thời gian:** 60 giây\n"
            "**Cách trả lời:** gõ trực tiếp đáp án vào khung chat."
        ),
        color=0x8E44AD,
        timestamp=datetime.now(UTC7),
    )
    embed.set_footer(text="Kim Long MiniGame")
    return embed


async def finalize_gheptu_after_timeout(channel: discord.abc.Messageable, channel_id: int, round_id: int):
    await asyncio.sleep(60)
    game = bot.gheptu_games.get(channel_id)
    if not game or game["round_id"] != round_id:
        return

    answer = game["answer"]
    bot.gheptu_games.pop(channel_id, None)
    bot.correct_word = None
    bot.gheptu_channel_id = None

    await channel.send(f"Không ai đoán đúng từ **{answer}**.")


def draw_card() -> int:
    cards = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11]
    return random.choice(cards)


def calculate_score(hand: list[int]) -> int:
    hand_copy = hand.copy()
    total = sum(hand_copy)
    while total > 21 and 11 in hand_copy:
        hand_copy[hand_copy.index(11)] = 1
        total = sum(hand_copy)
    return total


def display_hand(hand: list[int]) -> str:
    converted = []
    for value in hand:
        if value == 11:
            converted.append("A")
        elif value == 10:
            converted.append(random.choice(["10", "J", "Q", "K"]))
        else:
            converted.append(str(value))
    return " ".join(f"[`{card}`]" for card in converted)


def build_bau_cua_file() -> Optional[discord.File]:
    if BAU_CUA_IMAGE_FILE.exists():
        return discord.File(str(BAU_CUA_IMAGE_FILE), filename="bau_cua_board.jpg")
    return None


def format_bau_cua_results(results: list[str]) -> str:
    return " | ".join(f"{BAU_CUA_EMOJIS[item]} {item.title()}" for item in results)


def format_dice_faces(results: list[str]) -> str:
    return "\n".join(f"┌─────┐\n│  {BAU_CUA_EMOJIS[item]}  │\n└─────┘" for item in results)


# ================== BOT SETUP ==================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

bot.correct_word = None
bot.gheptu_channel_id = None
bot.gheptu_games = {}
bot.noitu_games = {}
active_bau_cua_rooms: dict[int, "BauCuaVsBotView"] = {}
active_taixiu_rooms: dict[int, "TaiXiuView"] = {}


@bot.event
async def on_ready():
    setup_db()
    try:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            synced = await bot.tree.sync(guild=guild)
            print(f"Synced {len(synced)} guild commands to {GUILD_ID}")
        else:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} global commands")
    except Exception as e:
        print(f"Sync error: {e}")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


# ================== LỆNH CƠ BẢN ==================
@bot.tree.command(name="kiemtra", description="Kiểm tra bot còn hoạt động không")
async def kiemtra(interaction: discord.Interaction):
    embed = make_embed("🏓 Bot đang hoạt động", f"Độ trễ hiện tại: **{round(bot.latency * 1000)}ms**", 0x2ECC71)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="sodu", description="Xem số xu của bạn")
async def sodu(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    coins = get_balance(target.id)
    embed = make_embed("💰 Số dư tài khoản", color=0xF1C40F)
    embed.add_field(name="Người chơi", value=target.mention, inline=False)
    embed.add_field(name="Số dư", value=f"**{fmt_coin(coins)}**", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="diemdanh", description="Nhận thưởng hằng ngày")
async def diemdanh(interaction: discord.Interaction):
    ok, wait_time = can_claim_daily(interaction.user.id)
    if not ok and wait_time is not None:
        hours, remainder = divmod(int(wait_time.total_seconds()), 3600)
        minutes = remainder // 60
        embed = make_embed("⏳ Chưa đến giờ điểm danh", f"Bạn quay lại sau **{hours}h {minutes}m** nữa nhé.", 0xE67E22)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    reward = random.randint(50, 120)
    add_coins(interaction.user.id, reward)
    set_daily(interaction.user.id, datetime.now(UTC7).isoformat())

    embed = make_embed("📅 Điểm danh thành công", color=0x2ECC71)
    embed.add_field(name="Thưởng nhận được", value=f"+{fmt_coin(reward)}", inline=False)
    embed.add_field(name="Số dư hiện tại", value=f"**{fmt_coin(get_balance(interaction.user.id))}**", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="xucxac", description="Tung xúc xắc và nhận thưởng")
async def xucxac(interaction: discord.Interaction):
    number = random.randint(1, 6)
    reward_map = {1: 0, 2: 5, 3: 10, 4: 15, 5: 25, 6: 50}
    reward = reward_map[number]
    add_coins(interaction.user.id, reward)

    embed = make_embed("🎲 Kết quả xúc xắc", color=0x3498DB)
    embed.add_field(name="Bạn tung ra", value=f"**{number}**", inline=True)
    embed.add_field(name="Phần thưởng", value=f"+{fmt_coin(reward)}", inline=True)
    embed.add_field(name="Số dư hiện tại", value=f"**{fmt_coin(get_balance(interaction.user.id))}**", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="bxh", description="Xem bảng xếp hạng xu")
async def bxh(interaction: discord.Interaction):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message("Chưa có dữ liệu bảng xếp hạng.")
        return

    lines = []
    for index, row in enumerate(rows, start=1):
        user = interaction.guild.get_member(row["user_id"]) if interaction.guild else None
        name = user.display_name if user else f"User {row['user_id']}"
        medal = "🥇" if index == 1 else "🥈" if index == 2 else "🥉" if index == 3 else f"#{index}"
        lines.append(f"{medal} **{name}** — {fmt_coin(row['coins'])}")

    embed = make_embed("🏆 Bảng xếp hạng tài phú", "\n".join(lines), 0x9B59B6)
    await interaction.response.send_message(embed=embed)


# ================== GAME BẦU CUA VS BOT ==================
class BauCuaBetModal(discord.ui.Modal, title="Nhập số xu cược"):
    amount = discord.ui.TextInput(
        label="Số xu muốn cược",
        placeholder="Ví dụ: 1000",
        required=True,
        max_length=10,
    )

    def __init__(self, room: "BauCuaVsBotView"):
        super().__init__()
        self.room = room

    async def on_submit(self, interaction: discord.Interaction):
        if self.room.is_closed or self.room.remaining_seconds() <= 0:
            await interaction.response.send_message("⌛ Ván này đã đóng cược.", ephemeral=True)
            return

        if not self.room.choice:
            await interaction.response.send_message("❌ Hãy chọn cửa trước khi nhập tiền cược.", ephemeral=True)
            return

        raw_amount = str(self.amount).strip().replace(".", "").replace(",", "")
        if not raw_amount.isdigit():
            await interaction.response.send_message("❌ Số xu phải là số nguyên dương.", ephemeral=True)
            return

        amount = int(raw_amount)
        if amount <= 0:
            await interaction.response.send_message("❌ Số xu phải lớn hơn 0.", ephemeral=True)
            return
        if amount > get_balance(interaction.user.id):
            await interaction.response.send_message("❌ Bạn không đủ xu.", ephemeral=True)
            return

        self.room.player_id = interaction.user.id
        self.room.bet = amount
        await interaction.response.send_message(
            f"✅ Bạn đã đặt **{fmt_coin(amount)}** vào cửa **{BAU_CUA_EMOJIS[self.room.choice]} {self.room.choice}**. Chờ bot mở bát nhé.",
            ephemeral=True,
        )
        await self.room.refresh_message()


class BauCuaVsBotView(discord.ui.View):
    def __init__(self, host_id: int):
        super().__init__(timeout=60)
        self.host_id = host_id
        self.player_id: Optional[int] = None
        self.choice: Optional[str] = None
        self.bet: Optional[int] = None
        self.round_id = random.randint(1000, 99999)
        self.end_time = datetime.now(UTC7) + timedelta(seconds=60)
        self.message: Optional[discord.Message] = None
        self.is_closed = False
        self.results: list[str] = []

    def remaining_seconds(self) -> int:
        return max(0, int((self.end_time - datetime.now(UTC7)).total_seconds()))

    def room_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎲 BẦU CUA ĐẤU BOT",
            description="Người chơi đánh với BOT. Có **60 giây** để chọn cửa và nhập tiền cược.",
            color=0x3498DB,
            timestamp=datetime.now(UTC7),
        )
        embed.add_field(name="⏳ Còn lại", value=f"**{self.remaining_seconds()}s**", inline=True)
        embed.add_field(name="🎯 Cửa đã chọn", value=(f"{BAU_CUA_EMOJIS[self.choice]} {self.choice.title()}" if self.choice else "Chưa chọn"), inline=True)
        embed.add_field(name="💰 Tiền cược", value=(fmt_coin(self.bet) if self.bet else "Chưa nhập"), inline=True)
        embed.add_field(name="🤖 Đối thủ", value="BOT", inline=True)
        embed.add_field(name="👤 Người chơi", value=(f"<@{self.player_id}>" if self.player_id else "Chưa có"), inline=True)
        embed.add_field(
            name="📌 Cách chơi",
            value=(
                "1. Chọn cửa ở menu\n"
                "2. Bấm **Nhập tiền cược**\n"
                "3. Chờ bot mở bát khi hết 60 giây"
            ),
            inline=False,
        )
        embed.set_footer(text=f"Round #{self.round_id} • Hôm nay lúc {datetime.now(UTC7).strftime('%H:%M')}")
        return embed

    def result_embed(self) -> discord.Embed:
        win_count = self.results.count(self.choice) if self.choice else 0
        gross = (self.bet or 0) * win_count
        net = gross - (self.bet or 0)
        player_win = net > 0
        player_draw = net == 0
        color = 0x2ECC71 if player_win else 0xF1C40F if player_draw else 0xE74C3C

        embed = discord.Embed(
            title=f"🎯 KẾT QUẢ BẦU CUA • ROUND #{self.round_id}",
            color=color,
            timestamp=datetime.now(UTC7),
        )
        embed.add_field(name="🎲 Kết quả", value=format_bau_cua_results(self.results), inline=False)
        embed.add_field(name="🎲 Xí ngầu", value=f"```\n{format_dice_faces(self.results)}\n```", inline=False)
        embed.add_field(name="👤 Người chơi", value=f"<@{self.player_id}>" if self.player_id else "Không có", inline=True)
        embed.add_field(name="🤖 BOT", value="Đã mở bát", inline=True)
        embed.add_field(name="🎯 Cửa chọn", value=f"{BAU_CUA_EMOJIS[self.choice]} {self.choice.title()}" if self.choice else "Không có", inline=True)
        embed.add_field(name="💰 Tiền cược", value=fmt_coin(self.bet or 0), inline=True)

        if player_win:
            embed.add_field(name="🏆 Người thắng", value=f"<@{self.player_id}> thắng **{fmt_coin(net)}**", inline=False)
            embed.add_field(name="💥 Người thua", value=f"BOT thua **{fmt_coin(net)}**", inline=False)
        elif player_draw:
            embed.add_field(name="🏆 Kết quả", value="Hòa vốn, không ai thắng thua.", inline=False)
        else:
            embed.add_field(name="🏆 Người thắng", value=f"BOT thắng **{fmt_coin(-net)}**", inline=False)
            embed.add_field(name="💥 Người thua", value=f"<@{self.player_id}> thua **{fmt_coin(-net)}**", inline=False)

        if self.player_id is not None:
            embed.add_field(name="💳 Số dư hiện tại", value=fmt_coin(get_balance(self.player_id)), inline=False)

        embed.set_footer(text=f"Hôm nay lúc {datetime.now(UTC7).strftime('%H:%M')}")
        return embed

    async def refresh_message(self):
        if self.message is None or self.is_closed:
            return
        embed = self.room_embed()
        file = build_bau_cua_file()
        try:
            if file is not None:
                embed.set_image(url="attachment://bau_cua_board.jpg")
                await self.message.edit(embed=embed, view=self, attachments=[file])
            else:
                await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            return

    async def countdown_loop(self):
        while not self.is_closed:
            await asyncio.sleep(5)
            if self.remaining_seconds() <= 0:
                break
            await self.refresh_message()
        await self.close_room()

    async def close_room(self):
        if self.is_closed:
            return
        self.is_closed = True
        for item in self.children:
            item.disabled = True

        if not self.player_id or not self.choice or not self.bet:
            embed = discord.Embed(
                title=f"⌛ HỦY VÁN BẦU CUA #{self.round_id}",
                description="Hết 60 giây nhưng chưa nhập đủ cửa và tiền cược.",
                color=0xE67E22,
                timestamp=datetime.now(UTC7),
            )
            if self.message is not None:
                file = build_bau_cua_file()
                if file is not None:
                    embed.set_image(url="attachment://bau_cua_board.jpg")
                    await self.message.edit(embed=embed, view=self, attachments=[file])
                else:
                    await self.message.edit(embed=embed, view=self)
            self.stop()
            return

        self.results = [random.choice(BAU_CUA_ITEMS) for _ in range(3)]
        win_count = self.results.count(self.choice)
        gross = self.bet * win_count
        net = gross - self.bet
        add_coins(self.player_id, net)

        if self.message is not None:
            embed = self.result_embed()
            file = build_bau_cua_file()
            if file is not None:
                embed.set_image(url="attachment://bau_cua_board.jpg")
                await self.message.edit(embed=embed, view=self, attachments=[file])
            else:
                await self.message.edit(embed=embed, view=self)
        self.stop()

    @discord.ui.select(
        placeholder="Chọn cửa...",
        options=[
            discord.SelectOption(label=item.title(), value=item, emoji=BAU_CUA_EMOJIS[item])
            for item in BAU_CUA_ITEMS
        ],
    )
    async def select_choice(self, interaction: discord.Interaction, select: discord.ui.Select):
        if self.is_closed or self.remaining_seconds() <= 0:
            await interaction.response.send_message("⌛ Ván này đã đóng cược.", ephemeral=True)
            return
        self.player_id = interaction.user.id
        self.choice = select.values[0]
        await interaction.response.edit_message(embed=self.room_embed(), view=self)

    @discord.ui.button(label="💰 Nhập tiền cược", style=discord.ButtonStyle.success)
    async def bet_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.is_closed or self.remaining_seconds() <= 0:
            await interaction.response.send_message("⌛ Ván này đã đóng cược.", ephemeral=True)
            return
        await interaction.response.send_modal(BauCuaBetModal(self))


@bot.tree.command(name="baucua", description="Chơi bầu cua đánh với BOT")
async def bau_cua(interaction: discord.Interaction):
    existing_room = active_bau_cua_rooms.get(interaction.channel_id)
    if existing_room and not existing_room.is_closed:
        await interaction.response.send_message("❌ Kênh này đang có một ván bầu cua rồi.", ephemeral=True)
        return

    room = BauCuaVsBotView(interaction.user.id)
    active_bau_cua_rooms[interaction.channel_id] = room

    embed = room.room_embed()
    file = build_bau_cua_file()
    if file is not None:
        embed.set_image(url="attachment://bau_cua_board.jpg")
        await interaction.response.send_message(embed=embed, view=room, file=file)
    else:
        await interaction.response.send_message(embed=embed, view=room)

    room.message = await interaction.original_response()

    async def run_room():
        try:
            await room.countdown_loop()
        finally:
            if active_bau_cua_rooms.get(interaction.channel_id) is room:
                del active_bau_cua_rooms[interaction.channel_id]

    bot.loop.create_task(run_room())


# ================== GAME NỐI TỪ ==================
async def finalize_noitu_after_timeout(channel: discord.abc.Messageable, channel_id: int, round_id: int):
    await asyncio.sleep(60)
    game = bot.noitu_games.get(channel_id)
    if not game or game["round_id"] != round_id:
        return

    winner_id = game["last_player_id"]
    if not winner_id:
        bot.noitu_games.pop(channel_id, None)
        return

    add_coins(winner_id, 400)
    embed = make_embed("🏆 KẾT THÚC GAME NỐI TỪ", color=0xF1C40F)
    embed.add_field(name="Người thắng", value=f"<@{winner_id}>", inline=False)
    embed.add_field(name="Từ cuối cùng", value=f"**{game['current_word']}**", inline=False)
    embed.add_field(name="Phần thưởng", value=f"+{fmt_coin(400)}", inline=True)
    embed.add_field(name="Tổng số từ đã dùng", value=str(len(game["used_words"])), inline=True)
    embed.add_field(name="Lý do", value="Không còn từ nối tiếp hợp lệ trong 60 giây.", inline=False)
    await channel.send(embed=embed)
    bot.noitu_games.pop(channel_id, None)


@bot.tree.command(name="noitu", description="Bắt đầu game nối từ")
async def noitu(interaction: discord.Interaction):
    if interaction.channel_id in bot.noitu_games:
        await interaction.response.send_message("❌ Kênh này đang có game nối từ rồi.", ephemeral=True)
        return

    words = ["con mèo", "cái bàn", "học sinh", "trường học", "bầu trời", "mặt đất", "thành phố", "vũ trụ"]
    start_word = random.choice(words)
    round_id = random.randint(1000, 99999)
    bot.noitu_games[interaction.channel_id] = {
        "current_word": start_word,
        "last_player_id": None,
        "used_words": {normalize_phrase(start_word)},
        "round_id": round_id,
    }

    embed = make_embed("🔗 GAME NỐI TỪ", color=0x1ABC9C)
    embed.add_field(name="Từ bắt đầu", value=f"**{start_word}**", inline=False)
    embed.add_field(
        name="Luật chơi",
        value=(
            "- Người chơi trả lời trực tiếp trong khung chat\n"
            "- Không được lặp từ đã dùng\n"
            "- Không được chơi 2 lượt liên tiếp\n"
            "- Chỉ từ cuối cùng khi không ai nối tiếp được mới nhận **400 xu**"
        ),
        inline=False,
    )
    await interaction.response.send_message(embed=embed)
    bot.loop.create_task(finalize_noitu_after_timeout(interaction.channel, interaction.channel_id, round_id))


# ================== GAME GHÉP TỪ ==================
@bot.tree.command(name="gheptu", description="Ghép chữ thành từ")
async def gheptu(interaction: discord.Interaction):
    if interaction.channel_id in bot.gheptu_games:
        await interaction.response.send_message("❌ Kênh này đang có một câu ghép từ chưa giải.", ephemeral=True)
        return

    words = [
        "cá tính",
        "quê hương",
        "chăm chỉ",
        "nghệ sĩ",
        "hạnh phúc",
        "kiên trì",
        "bình minh",
        "thành công",
        "hi vọng",
        "tài năng",
    ]
    word = random.choice(words)
    cleaned_word = word.replace(" ", "")
    round_id = random.randint(1000, 99999)

    bot.correct_word = cleaned_word
    bot.gheptu_channel_id = interaction.channel_id
    bot.gheptu_games[interaction.channel_id] = {
        "answer": cleaned_word,
        "round_id": round_id,
    }

    embed = make_gheptu_embed(format_scrambled_letters(word), len(cleaned_word))
    await interaction.response.send_message(embed=embed)
    bot.loop.create_task(finalize_gheptu_after_timeout(interaction.channel, interaction.channel_id, round_id))


# ================== GAME TÀI XỈU ==================
class TaiXiuNumberSelect(discord.ui.Select):
    def __init__(self, parent_view: "TaiXiuView"):
        self.parent_view = parent_view
        options = [
            discord.SelectOption(label=f"Số {number}", value=str(number))
            for number in range(3, 19)
        ]
        super().__init__(
            placeholder="Chọn số cụ thể (3-18)...",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.is_closed or self.parent_view.remaining_seconds() <= 0:
            await interaction.response.send_message("⌛ Ván này đã đóng cược.", ephemeral=True)
            return
        await self.parent_view.set_selection(interaction, "number", int(self.values[0]))


class TaiXiuBetModal(discord.ui.Modal, title="Nhập số xu cược tài xỉu"):
    amount = discord.ui.TextInput(
        label="Số xu muốn cược",
        placeholder="Ví dụ: 1000",
        required=True,
        max_length=10,
    )

    def __init__(self, view: "TaiXiuView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        if self.view_ref.is_closed or self.view_ref.remaining_seconds() <= 0:
            await interaction.response.send_message("⌛ Ván này đã đóng cược.", ephemeral=True)
            return
        if not self.view_ref.selection:
            await interaction.response.send_message("❌ Hãy chọn cửa trước khi nhập tiền cược.", ephemeral=True)
            return

        raw_amount = str(self.amount).strip().replace(".", "").replace(",", "")
        if not raw_amount.isdigit():
            await interaction.response.send_message("❌ Số xu phải là số nguyên dương.", ephemeral=True)
            return

        amount = int(raw_amount)
        if amount <= 0:
            await interaction.response.send_message("❌ Số xu phải lớn hơn 0.", ephemeral=True)
            return
        if amount > get_balance(interaction.user.id):
            await interaction.response.send_message("❌ Bạn không đủ xu.", ephemeral=True)
            return

        self.view_ref.player_id = interaction.user.id
        self.view_ref.bet = amount
        await interaction.response.send_message(
            f"✅ Bạn đã cược **{fmt_coin(amount)}** vào cửa **{self.view_ref.selection_label()}**.",
            ephemeral=True,
        )
        await self.view_ref.refresh_message()


class TaiXiuView(discord.ui.View):
    def __init__(self, host_id: int):
        super().__init__(timeout=45)
        self.host_id = host_id
        self.player_id: Optional[int] = None
        self.selection: Optional[tuple[str, int]] = None
        self.bet: Optional[int] = None
        self.round_id = random.randint(1000, 99999)
        self.end_time = datetime.now(UTC7) + timedelta(seconds=45)
        self.message: Optional[discord.Message] = None
        self.is_closed = False
        self.dice: list[int] = []
        self.add_item(TaiXiuNumberSelect(self))

    def remaining_seconds(self) -> int:
        return max(0, int((self.end_time - datetime.now(UTC7)).total_seconds()))

    def selection_label(self) -> str:
        if not self.selection:
            return "Chưa chọn"
        key, value = self.selection
        mapping = {
            "tai": "Tài (11-18)",
            "xiu": "Xỉu (3-10)",
            "chan": "Chẵn",
            "le": "Lẻ",
        }
        if key == "number":
            return f"Số {value}"
        return mapping.get(key, "Chưa chọn")

    def intro_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎲 Tài Xỉu Nekô - Nhà cái đến từ Châu Á! 🔥🔥🔥",
            description=(
                "Chọn **Tài (11-18)**, **Xỉu (3-10)**, **Chẵn/Lẻ** hoặc một **số cụ thể (3-18)** để đặt cược.\n"
                "Sau khi chọn, bấm **Nhập tiền cược** và nhập số xu bạn muốn cược.\n"
                "Tỉ lệ trả thưởng:\n"
                "• Tài/Xỉu/Chẵn/Lẻ: **1:1**\n"
                "• Số cụ thể (3-18): **1:10**"
            ),
            color=0x8E44AD,
            timestamp=datetime.now(UTC7),
        )
        embed.add_field(name="⏳ Còn lại", value=f"**{self.remaining_seconds()}s**", inline=True)
        embed.add_field(name="🎯 Cửa đã chọn", value=self.selection_label(), inline=True)
        embed.add_field(name="💰 Tiền cược", value=(fmt_coin(self.bet) if self.bet else "Chưa nhập"), inline=True)
        embed.add_field(name="👤 Người chơi", value=(f"<@{self.player_id}>" if self.player_id else "Chưa có"), inline=True)
        embed.add_field(name="🤖 Nhà cái", value="Nekô APP", inline=True)
        embed.add_field(name="📌 Trạng thái", value="Đang nhận cược", inline=True)
        embed.set_footer(text=f"Round #{self.round_id} • Hôm nay lúc {datetime.now(UTC7).strftime('%H:%M')}")
        return embed

    def result_embed(self) -> discord.Embed:
        total = sum(self.dice)
        parity = "Chẵn" if total % 2 == 0 else "Lẻ"
        size = "Tài" if total >= 11 else "Xỉu"
        won = False
        payout_multiplier = 1

        if self.selection:
            key, value = self.selection
            if key == "tai" and total >= 11:
                won = True
            elif key == "xiu" and total <= 10:
                won = True
            elif key == "chan" and total % 2 == 0:
                won = True
            elif key == "le" and total % 2 == 1:
                won = True
            elif key == "number" and total == value:
                won = True
                payout_multiplier = 10

        gross = (self.bet or 0) * payout_multiplier if won else 0
        net = gross - (self.bet or 0)
        color = 0x2ECC71 if won else 0xE74C3C

        embed = discord.Embed(
            title=f"🎯 Kết quả Tài Xỉu • Round #{self.round_id}",
            color=color,
            timestamp=datetime.now(UTC7),
        )
        embed.add_field(name="Kết quả", value=f"[{self.dice[0]}] [{self.dice[1]}] [{self.dice[2]}] = **{total}**", inline=False)
        embed.add_field(name="Tài/Xỉu", value=size, inline=True)
        embed.add_field(name="Chẵn/Lẻ", value=parity, inline=True)
        embed.add_field(name="Cửa chọn", value=self.selection_label(), inline=True)
        embed.add_field(
            name="Tổng kết",
            value=(
                f"<@{self.player_id}> đã cược **{self.selection_label()}**: **{fmt_coin(self.bet or 0)}**\n"
                + (f"và thắng **{fmt_coin(net)}**" if won else f"và thua **{fmt_coin(self.bet or 0)}**")
            ),
            inline=False,
        )
        if self.player_id is not None:
            embed.add_field(name="Số dư hiện tại", value=fmt_coin(get_balance(self.player_id)), inline=False)
        embed.set_footer(text=f"Hôm nay lúc {datetime.now(UTC7).strftime('%H:%M')}")
        return embed

    async def refresh_message(self):
        if self.message is None or self.is_closed:
            return
        try:
            await self.message.edit(embed=self.intro_embed(), view=self)
        except discord.HTTPException:
            return

    async def countdown_loop(self):
        while not self.is_closed:
            await asyncio.sleep(5)
            if self.remaining_seconds() <= 0:
                break
            await self.refresh_message()
        await self.close_round()

    async def close_round(self):
        if self.is_closed:
            return
        self.is_closed = True
        for item in self.children:
            item.disabled = True

        if not self.player_id or not self.selection or not self.bet:
            embed = discord.Embed(
                title=f"⌛ Hủy ván Tài Xỉu #{self.round_id}",
                description="Hết 45 giây nhưng chưa nhập đủ cửa và tiền cược.",
                color=0xE67E22,
                timestamp=datetime.now(UTC7),
            )
            if self.message is not None:
                await self.message.edit(embed=embed, view=self)
            self.stop()
            return

        self.dice = [random.randint(1, 6) for _ in range(3)]
        total = sum(self.dice)
        won = False
        multiplier = 1
        key, value = self.selection
        if key == "tai" and total >= 11:
            won = True
        elif key == "xiu" and total <= 10:
            won = True
        elif key == "chan" and total % 2 == 0:
            won = True
        elif key == "le" and total % 2 == 1:
            won = True
        elif key == "number" and total == value:
            won = True
            multiplier = 10

        gross = self.bet * multiplier if won else 0
        net = gross - self.bet
        add_coins(self.player_id, net)

        if self.message is not None:
            await self.message.edit(embed=self.result_embed(), view=self)
        self.stop()

    async def set_selection(self, interaction: discord.Interaction, key: str, value: int = 0):
        if self.is_closed or self.remaining_seconds() <= 0:
            await interaction.response.send_message("⌛ Ván này đã đóng cược.", ephemeral=True)
            return
        self.player_id = interaction.user.id
        self.selection = (key, value)
        await interaction.response.edit_message(embed=self.intro_embed(), view=self)

    @discord.ui.button(label="Xỉu (3-10)", style=discord.ButtonStyle.success, row=0)
    async def pick_xiu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_selection(interaction, "xiu")

    @discord.ui.button(label="Tài (11-18)", style=discord.ButtonStyle.success, row=0)
    async def pick_tai(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_selection(interaction, "tai")

    @discord.ui.button(label="Chẵn", style=discord.ButtonStyle.danger, row=0)
    async def pick_chan(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_selection(interaction, "chan")

    @discord.ui.button(label="Lẻ", style=discord.ButtonStyle.danger, row=0)
    async def pick_le(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_selection(interaction, "le")

    @discord.ui.button(label="Nhập tiền cược", style=discord.ButtonStyle.secondary, row=2)
    async def input_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.is_closed or self.remaining_seconds() <= 0:
            await interaction.response.send_message("⌛ Ván này đã đóng cược.", ephemeral=True)
            return
        await interaction.response.send_modal(TaiXiuBetModal(self))


@bot.tree.command(name="taixiu", description="Chơi tài xỉu theo giao diện nút bấm")
async def taixiu(interaction: discord.Interaction):
    existing_room = active_taixiu_rooms.get(interaction.channel_id)
    if existing_room and not existing_room.is_closed:
        await interaction.response.send_message("❌ Kênh này đang có một ván tài xỉu rồi.", ephemeral=True)
        return

    room = TaiXiuView(interaction.user.id)
    active_taixiu_rooms[interaction.channel_id] = room
    await interaction.response.send_message(embed=room.intro_embed(), view=room)
    room.message = await interaction.original_response()

    async def run_room():
        try:
            await room.countdown_loop()
        finally:
            if active_taixiu_rooms.get(interaction.channel_id) is room:
                del active_taixiu_rooms[interaction.channel_id]

    bot.loop.create_task(run_room())


# ================== GAME XÌ DÁCH ==================
class XiDachView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.bet = bet
        self.player = [draw_card(), draw_card()]
        self.dealer = [draw_card(), draw_card()]

    def lock_buttons(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    def build_embed(self, reveal_dealer: bool = False, result: str = "") -> discord.Embed:
        player_score = calculate_score(self.player)
        dealer_score = calculate_score(self.dealer)

        if not result:
            color = 0x3498DB
        elif "thắng" in result.lower():
            color = 0x2ECC71
        elif "thua" in result.lower() or "quắc" in result.lower():
            color = 0xE74C3C
        else:
            color = 0xF1C40F

        embed = make_embed("🃏 XÌ DÁCH VIP", color=color)
        embed.add_field(name="💵 Tiền cược", value=fmt_coin(self.bet), inline=False)
        embed.add_field(name="🙋 Bài của bạn", value=f"{display_hand(self.player)}\nĐiểm: **{player_score}**", inline=False)

        if reveal_dealer:
            embed.add_field(name="🤖 Bài nhà cái", value=f"{display_hand(self.dealer)}\nĐiểm: **{dealer_score}**", inline=False)
        else:
            hidden = "[`?`]" if len(self.dealer) > 1 else ""
            embed.add_field(name="🤖 Bài nhà cái", value=f"{display_hand([self.dealer[0]])} {hidden}\nĐiểm hiện: **?**", inline=False)

        if result:
            embed.add_field(name="🏁 Kết quả", value=result, inline=False)

        embed.add_field(name="💰 Số dư", value=fmt_coin(get_balance(self.user_id)), inline=False)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Đây không phải ván của bạn.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🎯 Hit", style=discord.ButtonStyle.success)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.append(draw_card())
        player_score = calculate_score(self.player)

        if player_score > 21:
            add_coins(self.user_id, -self.bet)
            self.lock_buttons()
            await interaction.response.edit_message(
                embed=self.build_embed(reveal_dealer=True, result=f"💸 Bạn quắc **{player_score}** điểm và thua **{fmt_coin(self.bet)}**."),
                view=self,
            )
            self.stop()
            return

        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🛑 Stand", style=discord.ButtonStyle.danger)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        while calculate_score(self.dealer) < 17:
            self.dealer.append(draw_card())

        player_score = calculate_score(self.player)
        dealer_score = calculate_score(self.dealer)

        if dealer_score > 21 or player_score > dealer_score:
            add_coins(self.user_id, self.bet)
            result = f"🎉 Bạn thắng **{fmt_coin(self.bet)}**. ({player_score} vs {dealer_score})"
        elif player_score == dealer_score:
            result = f"⚖️ Hòa. Cả hai đều **{player_score}** điểm."
        else:
            add_coins(self.user_id, -self.bet)
            result = f"💸 Bạn thua **{fmt_coin(self.bet)}**. ({player_score} vs {dealer_score})"

        self.lock_buttons()
        await interaction.response.edit_message(embed=self.build_embed(reveal_dealer=True, result=result), view=self)
        self.stop()

    async def on_timeout(self):
        self.lock_buttons()


@bot.tree.command(name="xidach", description="Chơi xì dách bằng nút bấm")
@app_commands.describe(bet="Số xu muốn cược")
async def xidach(interaction: discord.Interaction, bet: app_commands.Range[int, 10, 100000]):
    balance_now = get_balance(interaction.user.id)
    if bet > balance_now:
        await interaction.response.send_message("❌ Bạn không đủ xu để chơi xì dách.", ephemeral=True)
        return

    view = XiDachView(interaction.user.id, bet)
    await interaction.response.send_message(embed=view.build_embed(), view=view)


# ================== CHAT MESSAGE GAMES ==================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    channel_id = message.channel.id
    content = message.content.strip()

    noitu_game = bot.noitu_games.get(channel_id)
    if noitu_game and content:
        normalized = normalize_phrase(content)
        if normalized in noitu_game["used_words"] or noitu_game["last_player_id"] == message.author.id:
            try:
                await message.add_reaction(CROSS_EMOJI)
            except discord.HTTPException:
                pass
            await bot.process_commands(message)
            return

        if is_valid_noitu(noitu_game["current_word"], content):
            noitu_game["current_word"] = content.strip()
            noitu_game["last_player_id"] = message.author.id
            noitu_game["used_words"].add(normalized)
            noitu_game["round_id"] += 1
            try:
                await message.add_reaction(CHECK_EMOJI)
            except discord.HTTPException:
                pass

            bot.loop.create_task(finalize_noitu_after_timeout(message.channel, channel_id, noitu_game["round_id"]))
            await bot.process_commands(message)
            return
        else:
            try:
                await message.add_reaction(CROSS_EMOJI)
            except discord.HTTPException:
                pass
            await bot.process_commands(message)
            return

    gheptu_game = bot.gheptu_games.get(channel_id)
    if gheptu_game and content:
        normalized_answer = normalize_phrase(gheptu_game["answer"])
        if normalize_phrase(content).replace(" ", "") == normalized_answer.replace(" ", ""):
            add_coins(message.author.id, 50)
            solved_word = gheptu_game["answer"]
            bot.gheptu_games.pop(channel_id, None)
            bot.correct_word = None
            bot.gheptu_channel_id = None
            try:
                await message.add_reaction(CHECK_EMOJI)
            except discord.HTTPException:
                pass
            embed = discord.Embed(
                title="🎉 Có người đoán đúng rồi!",
                description=(
                    f"**Đáp án:** `{solved_word}`\n"
                    f"**Người trả lời đúng:** {message.author.mention}\n"
                    f"**Thưởng:** +{fmt_coin(50)}"
                ),
                color=0x2ECC71,
                timestamp=datetime.now(UTC7),
            )
            embed.set_footer(text="Kim Long MiniGame")
            await message.channel.send(embed=embed)
            await bot.process_commands(message)
            return
        else:
            try:
                await message.add_reaction(CROSS_EMOJI)
            except discord.HTTPException:
                pass

    await bot.process_commands(message)


# ================== TESTS ==================
def _test_is_valid_noitu():
    assert is_valid_noitu("con mèo", "mèo mun") is True
    assert is_valid_noitu("trường học", "học sinh") is True
    assert is_valid_noitu("cái bàn", "ghế gỗ") is False
    assert is_valid_noitu(None, "gì đó") is False


def _test_normalize_phrase():
    assert normalize_phrase("  mèo   mun ") == "mèo mun"


def _test_format_bau_cua_results():
    text = format_bau_cua_results(["bầu", "cua", "nai"])
    assert "🍐" in text
    assert "🦀" in text
    assert "🦌" in text


def _test_scramble_word():
    word = "python"
    scrambled = scramble_word(word)
    assert sorted(scrambled) == sorted(word)
    assert len(scrambled) == len(word)


def _test_calculate_score():
    assert calculate_score([10, 11]) == 21
    assert calculate_score([10, 11, 5]) == 16
    assert calculate_score([11, 11, 9]) == 21


def run_tests():
    _test_is_valid_noitu()
    _test_normalize_phrase()
    _test_format_bau_cua_results()
    _test_scramble_word()
    _test_calculate_score()
    print("All tests passed.")


if __name__ == "__main__":
    if os.getenv("RUN_TESTS") == "1":
        run_tests()
    else:
        if not TOKEN:
            raise RuntimeError("Hãy đặt biến môi trường DISCORD_BOT_TOKEN trước khi chạy bot.")
        bot.run(TOKEN)
