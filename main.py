import discord
import redis
import os
from discord.ext import tasks

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Połączenie z bazą Redis na Railway
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
            
    # Poprawne sortowanie po bilansie (indeks 3 w krotce)
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

# Bezpieczne zadanie startowe, które czeka na połączenie i generuje tabelę
@tasks.loop(count=1)
async def inicjalizacja_tabeli():
    # ID kanału tabeli wpisane na sztywno jako tekst
    tabela_chan_id = "1543677152589910107"

    try:
        # Czekamy, aż bot pobierze pełną listę kanałów z serwera
        await client.wait_until_ready()
        
        kanal = await client.fetch_channel(int(tabela_chan_id))
        if not kanal:
            print("Nie można odnaleźć wskazanego kanału dla tabeli!")
            return

        msg_id = r.get("config:tabela_message_id")
        embed = generuj_embed_tabeli()

        if msg_id:
            try:
                # Jeśli tabela już wisi na kanale, po prostu ją edytujemy
                wiadomosc = await kanal.fetch_message(int(msg_id))
                await wiadomosc.edit(embed=embed)
                print("Tabela została pomyślnie zaktualizowana.")
                return
            except Exception:
                print("Stara tabela nie została znaleziona w kanale, generuję nową...")
        
        # Generowanie nowej tabeli na kanale
        wyslana_msg = await kanal.send(embed=embed)
        r.set("config:tabela_message_id", str(wyslana_msg.id))
        print("Tabela została wygenerowana pomyślnie na Discordzie!")

    except discord.Forbidden:
        print("BŁĄD: Bot nie ma uprawnień do tego kanału! Dodaj mu rolę na kanale na Discordzie.")
    except Exception as e:
        print(f"Błąd podczas startowej obsługi tabeli: {e}")

@client.event
async def on_ready():
    print(f"Zalogowano pomyślnie jako {client.user}")
    # Uruchomienie zadania w tle, jeśli jeszcze nie działa
    if not inicjalizacja_tabeli.is_running():
        inicjalizacja_tabeli.start()

@client.event
async def on_message(message):
    if message.author.bot:
        return

    # ID kanału do zliczania punktów wpisane na sztywno
    kanal_punktow_id = "1530914459135119445"
    if str(message.channel.id) != kanal_punktow_id:
        return

    if message.mentions:
        liczba_plusow = message.content.count("+")
        liczba_minusow = message.content.count("-")
        
        if integer_plusow == 0 and liczba_minusow == 0:
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
            # Szybkie odświeżenie istniejącej tabeli po wysłaniu punktu
            try:
                tabela_chan_id = "1543677152589910107"
                kanal = await client.fetch_channel(int(tabela_chan_id))
                msg_id = r.get("config:tabela_message_id")
                if kanal and msg_id:
                    wiadomosc = await kanal.fetch_message(int(msg_id))
                    await wiadomosc.edit(embed=generuj_embed_tabeli())
                    print("Tabela zaktualizowana po przyznaniu punktów.")
            except Exception as e:
                print(f"Błąd szybkiej aktualizacji: {e}")

client.run(os.getenv("DISCORD_TOKEN"))
