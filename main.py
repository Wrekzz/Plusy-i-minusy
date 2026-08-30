import discord
import redis
import os

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Bezpieczne pobranie adresu bazy danych z Railway
r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)

def generuj_embed_tabeli():
    klucze_plusy = r.keys("*:plusy")
    klucze_minusy = r.keys("*:minusy")
    
    user_ids = set()
    for k in klucze_plusy:
        user_ids.add(k.split(":")[0])
    for k in klucze_minusy:
        user_ids.add(k.split(":")[0])
    
    wyniki = []
    for uid in user_ids:
        plusy = int(r.get(f"{uid}:plusy") or 0)
        minusy = int(r.get(f"{uid}:minusy") or 0)
        bilans = plusy - minusy
        wyniki.append((uid, plusy, minusy, bilans))
            
    wyniki.sort(key=lambda x: x[3], reverse=True)
    
    embed = discord.Embed(title="🏆 TABELA PUNKTACJI GRACZY 🏆", color=0x00ff00)
    
    if not wyniki:
        embed.description = "Brak przyznanych punktów."
        return embed
        
    opis = ""
    for i, (user_id, plusy, minusy, bilans) in enumerate(wyniki, 1):
        opis += f"{i}. <@{user_id}> — Bilans: **{bilans}** `(+{plusy} / -{minusy})`\n"
        
    embed.description = opis
    return embed

async def aktualizuj_tabele():
    chan_id = r.get("config:tabela_channel_id")
    msg_id = r.get("config:tabela_message_id")
    
    if chan_id and msg_id:
        try:
            kanal = client.get_channel(int(chan_id)) or await client.fetch_channel(int(chan_id))
            wiadomosc = await kanal.fetch_message(int(msg_id))
            await wiadomosc.edit(embed=generuj_embed_tabeli())
        except Exception as e:
            print(f"Błąd aktualizacji tabeli: {e}")

@client.event
async def on_ready():
    print(f"Zalogowano pomyślnie jako {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    if message.content.startswith("!ustaw_kanal_tabeli"):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❌ Tylko administrator może użyć tej komendy.")
            return
        if not message.channel_mentions:
            await message.channel.send("❌ Musisz oznaczyć kanał, np: `!ustaw_kanal_tabeli #ranking`")
            return
        target_channel = message.channel_mentions[0]
        embed = generuj_embed_tabeli()
        wyslana_msg = await target_channel.send(embed=embed)
        r.set("config:tabela_channel_id", str(target_channel.id))
        r.set("config:tabela_message_id", str(wyslana_msg.id))
        await message.channel.send(f"✅ Tabela wygenerowana na kanale {target_channel.mention}!")
        return

    if message.content.startswith("!ustaw_kanal_punktow"):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❌ Tylko administrator może użyć tej komendy.")
            return
        if not message.channel_mentions:
            await message.channel.send("❌ Musisz oznaczyć kanał, np: `!ustaw_kanal_punktow #czat-graczy`")
            return
        target_channel = message.channel_mentions[0]
        r.set("config:punkty_channel_id", str(target_channel.id))
        await message.channel.send(f"✅ Punkty zliczane wyłącznie z kanału {target_channel.mention}!")
        return

    kanal_punktow_id = r.get("config:punkty_channel_id")
    if not kanal_punktow_id or str(message.channel.id) != kanal_punktow_id:
        return

    if message.mentions:
        liczba_plusow = message.content.count("+")
        liczba_minusow = message.content.count("-")
        
        if liczba_plusow == 0 and liczba_minusow == 0:
            return

        zaktualizowano = False
        for uzytkownik in message.mentions:
            if uzytkownik == message.author:
                continue
            
            if liczba_plusow > 0:
                r.incrby(f"{uzytkownik.id}:plusy", liczba_plusow)
                zaktualizowano = True
            
            if liczba_minusow > 0:
                r.incrby(f"{uzytkownik.id}:minusy", liczba_minusow)
                zaktualizowano = True
            
        if zaktualizowano:
            await aktualizuj_tabele()

# Bezpieczne uruchomienie bota ukrytym tokenem
client.run(os.getenv("DISCORD_TOKEN"))