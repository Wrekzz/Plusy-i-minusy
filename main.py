import discord
import redis
import os
import re
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

# REAKCJA NA NOWĄ WIADOMOŚĆ (Zliczanie punktów oraz komendy ręczne)
@client.event
async def on_message(message):
    if message.author.bot:
        return

    # --- SEKCOJA KOMEND ADMINISTRACYJNYCH (Działa na każdym kanale) ---
    if message.content.startswith("!usunplusy") or message.content.startswith("!usunminusy"):
        if not message.author.guild_permissions.administrator:
            await message.channel.send("❌ Nie masz uprawnień administratora do użycia tej komendy.")
            return

        if not message.mentions:
            await message.channel.send("❌ Musisz oznaczyć użytkownika! Przykład: `!usunplusy @Gracz 5`")
            return

        czesci = message.content.split()
        liczba = 1 
        for czesc in czesci:
            if czesc.isdigit():
                liczba = int(czesc)
                break

        uzytkownik = message.mentions[0]
        uid = uzytkownik.id
        typ_punktu = "plusy" if "plusy" in czesci[0] else "minusy"

        obecne = int(r.get(f"{uid}:{typ_punktu}") or 0)
        nowa_wartosc = max(0, obecne - liczba) 
        r.set(f"{uid}:{typ_punktu}", str(nowa_wartosc))

        await message.channel.send(f"✅ Pomyślnie usunięto {liczba} {typ_punktu} użytkownikowi {uzytkownik.mention}. Obecnie ma: {nowa_wartosc}.")
        
        try:
            tabela_chan_id = "1543677152589910107"
            kanal = await client.fetch_channel(int(tabela_chan_id))
            msg_id = r.get("config:tabela_message_id")
            if kanal and msg_id:
                wiadomosc = await kanal.fetch_message(int(msg_id))
                await wiadomosc.edit(embed=generuj_embed_tabeli())
        except Exception as e:
            print(f"Błąd aktualizacji tabeli po komendzie: {e}")
        return


    # --- SEKCJA AUTOMATYCZNEGO ZLICZANIA PUNKTÓW (Tylko na wskazanym kanale) ---
    kanal_punktow_id = "1530914459135119445"
    if str(message.channel.id) != kanal_punktow_id:
        return

    if message.mentions:
        # Rozbijamy tekst na bloki oddzielone wzmiankami użytkowników
        czesci_tekstu = re.split(r'<@!?\d+>', message.content)
        zaktualizowano = False

        for index, uzytkownik in enumerate(message.mentions):
            uid = uzytkownik.id
            
            # Pobieramy fragment wiadomości znajdujący się przed tym konkretnym graczem
            fragment_przed = czesci_tekstu[index] if index < len(czesci_tekstu) else ""
            
            liczba_plusow = fragment_przed.count("+")
            liczba_minusow = fragment_przed.count("-")
            
            # Jeśli przed graczem nie ma plusów/minusów (bo oznaczono ich ciągiem),
            # szukamy punktów przypisanych do poprzedniego gracza w tej samej wiadomości
            if liczba_plusow == 0 and liczba_minusow == 0 and index > 0:
                for i in range(index - 1, -1, -1):
                    poprzedni_fragment = czesci_tekstu[i]
                    p = poprzedni_fragment.count("+")
                    m = poprzedni_fragment.count("-")
                    if p > 0 or m > 0:
                        liczba_plusow = p
                        liczba_minusow = m
                        break

            if liczba_plusow == 0 and liczba_minusow == 0:
                continue

            if liczba_minusow > 0:
                r.incrby(f"{uid}:minusy", liczba_minusow)
                zaktualizowano = True

            if liczba_plusow > 0:
                skasowane_minusy_w_tej_wiadomosci = 0
                for _ in range(liczba_plusow):
                    nowe_historyczne_plusy = r.incr(f"{uid}:plusy")
                    
                    if nowe_historyczne_plusy % 2 == 0:
                        obecne_minusy = int(r.get(f"{uid}:minusy") or 0)
                        if obecne_minusy > 0:
                            r.decrby(f"{uid}:minusy", 1)
                            skasowane_minusy_w_tej_wiadomosci += 1
                
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

# REAKCJA NA USUNIĘCIE WIADOMOŚCI
@client.event
async def on_message_delete(message):
    if message.author.bot:
        return

    kanal_punktow_id = "1530914459135119445"
    if str(message.channel.id) != kanal_punktow_id:
        return

    if message.mentions:
        # Przy usuwaniu wiadomości stosujemy dokładnie tę samą logikę podziału
        # tak, aby bot odjął dokładnie tyle punktów, ile przed chwilą przyznał
        czesci_tekstu = re.split(r'<@!?\d+>', message.content)
        zaktualizowano = False

        for index, uzytkownik in enumerate(message.mentions):
            uid = uzytkownik.id
            
            fragment_przed = czesci_tekstu[index] if index < len(czesci_tekstu) else ""
            liczba_plusow = fragment_przed.count("+")
            liczba_minusow = fragment_przed.count("-")
            
            if liczba_plusow == 0 and liczba_minusow == 0 and index > 0:
                for i in range(index - 1, -1, -1):
                    poprzedni_fragment = czesci_tekstu[i]
                    p = poprzedni_fragment.count("+")
                    m = poprzedni_fragment.count("-")
                    if p > 0 or m > 0:
                        liczba_plusow = p
                        liczba_minusow = m
                        break
        
            if liczba_plusow == 0 and liczba_minusow == 0:
                continue

            if liczba_minusow > 0:
                r.decrby(f"{uid}:minusy", liczba_minusow)
                zaktualizowano = True

            if liczba_plusow > 0:
                r.decrby(f"{uid}:plusy", liczba_plusow)
                
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
