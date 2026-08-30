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
        
        if plusy < 0: plusy = 0
        if minusy < 0: minusy = 0
        
        bilans = plusy - minusy
        wyniki.append((uid, plusy, minusy, bilans))
            
    # Sortowanie po bilansie
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

@tasks.loop(count=1)
async def inicjalizacja_tabeli():
    tabela_chan_id = "1543677152589910107"
    try:
        await client.wait_until_ready()
        kanal = await client.fetch_channel(int(tabela_chan_id))
        if not kanal:
            return

        msg_id = r.get("config:tabela_message_id")
        embed = generuj_embed_tabeli()

        if msg_id:
            try:
                wiadomosc = await kanal.fetch_message(int(msg_id))
                await wiadomosc.edit(embed=embed)
                return
            except Exception:
                print("Stara tabela nie została znaleziona w kanale, generuję nową...")
        
        wyslana_msg = await kanal.send(embed=embed)
        r.set("config:tabela_message_id", str(wyslana_msg.id))
        print("Tabela została wygenerowana pomyślnie na Discordzie!")
    except Exception as e:
        print(f"Błąd podczas startowej obsługi tabeli: {e}")

@client.event
async def on_ready():
    print(f"Zalogowano pomyślnie jako {client.user}")
    if not inicjalizacja_tabeli.is_running():
        inicjalizacja_tabeli.start()

# REAKCJA NA NOWĄ WIADOMOŚĆ (Dodawanie i sprawdzanie globalnego warunku)
@client.event
async def on_message(message):
    if message.author.bot:
        return

    kanal_punktow_id = "1530914459135119445"
    if str(message.channel.id) != kanal_punktow_id:
        return

    if message.mentions:
        liczba_plusow = message.content.count("+")
        liczba_minusow = message.content.count("-")
        
        if liczba_plusow == 0 and liczba_minusow == 0:
            return

        zaktualizowano = False
        for uzytkownik in message.mentions:
            uid = uzytkownik.id
            
            # Obsługa przyznawania minusów
            if liczba_minusow > 0:
                r.incrby(f"{uid}:minusy", liczba_minusow)
                zaktualizowano = True

            # Obsługa przyznawania plusów
            if liczba_plusow > 0:
                # Dodajemy plusy po jednym w pętli, aby precyzyjnie sprawdzić każdy kolejny historyczny plus
                skasowane_minusy_w_tej_wiadomosci = 0
                for _ in range(liczba_plusow):
                    # Zwiększamy liczbę plusów o 1 i pobieramy nowy stan licznika
                    nowe_historyczne_plusy = r.incr(f"{uid}:plusy")
                    
                    # Jeśli ten konkretny plus jest parzysty (2, 4, 6, 8 itd.)
                    if nowe_historyczne_plusy % 2 == 0:
                        obecne_minusy = int(r.get(f"{uid}:minusy") or 0)
                        if obecne_minusy > 0:
                            # Kasujemy 1 minus z bazy danych
                            r.decrby(f"{uid}:minusy", 1)
                            skasowane_minusy_w_tej_wiadomosci += 1
                
                # Zapisujemy ile minusów bot usunął w TEJ konkretnej wiadomości (potrzebne do cofnięcia przy usunięciu wpisu)
                if skasowane_minusy_w_tej_wiadomosci > 0:
                    r.set(f"msg:{message.id}:{uid}:skasowane_minusy", str(skasowane_minusy_w_tej_wiadomosci))
                
                zaktualizowano = True
            
        if zaktualizowano:
            try:
                tabela_chan_id = "1543677152589910107"
                kanal = await client.fetch_channel(int(tabela_chan_id))
                msg_id = r.get("config:tabela_message_id")
                if kanal and msg_id:
                    wiadomosc = await kanal.fetch_message(int(msg_id))
                    await wiadomosc.edit(embed=generuj_embed_tabeli())
            except Exception as e:
                print(f"Błąd szybkiej aktualizacji: {e}")

# REAKCJA NA USUNIĘCIE WIADOMOŚCI (Cofanie ze spójnością globalną)
@client.event
async def on_message_delete(message):
    if message.author.bot:
        return

    kanal_punktow_id = "1530914459135119445"
    if str(message.channel.id) != kanal_punktow_id:
        return

    if message.mentions:
        liczba_plusow = message.content.count("+")
        liczba_minusow = message.content.count("-")
        
        if liczba_plusow == 0 and liczba_minusow == 0:
            return

        zaktualizowano = False
        for uzytkownik in message.mentions:
            uid = uzytkownik.id
            
            if liczba_minusow > 0:
                r.decrby(f"{uid}:minusy", liczba_minusow)
                zaktualizowano = True

            if liczba_plusow > 0:
                # Odejmij doliczone plusy z tej wiadomości
                r.decrby(f"{uid}:plusy", liczba_plusow)
                
                # Jeśli bot przy tej wiadomości skasował jakieś minusy, musimy je teraz oddać graczowi
                skasowane = r.get(f"msg:{message.id}:{uid}:skasowane_minusy")
                if skasowane:
                    r.incrby(f"{uid}:minusy", int(skasowane))
                    r.delete(f"msg:{message.id}:{uid}:skasowane_minusy")
                    
                zaktualizowano = True
            
        if zaktualizowano:
            try:
                tabela_chan_id = "1543677152589910107"
                kanal = await client.fetch_channel(int(tabela_chan_id))
                msg_id = r.get("config:tabela_message_id")
                if kanal and msg_id:
                    wiadomosc = await kanal.fetch_message(int(msg_id))
                    await wiadomosc.edit(embed=generuj_embed_tabeli())
            except Exception as e:
                print(f"Błąd szybkiej aktualizacji po usunięciu: {e}")

client.run(os.getenv("DISCORD_TOKEN"))
