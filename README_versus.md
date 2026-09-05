# Persona Arena — Versus

Publiczna arena: 2 persony odpowiadaja na to samo pytanie. Ty glosujesz, ktora odpowiedz lepsza.
Leaderboard pokazuje ktora persona wygrywa najczesciej.

## Uruchomienie lokalne

```bash
cd persona_arena
python arena_versus.py
# Otworz: http://localhost:7861
```

## Wymagania wstepne

1. Zainicjalizuj dane (jednorazowo):
```bash
python persona_arena.py init
```

2. Skonfiguruj backend LLM (jednorazowo):
```bash
python persona_arena.py backend presets    # zobacz opcje
python persona_arena.py backend preset --preset-name groq
# (wymaga GROQ_API_KEY w srodowisku)
```

Albo przez `arena_ui.py` → zakladka Backend.

## Flow

1. **Wybierz pytanie** (lub kliknij "Losuj pytanie")
2. **Wybierz 2 persony** (lub kliknij "Losuj persony")
3. **Generuj odpowiedzi** — obie persony dostaja to samo pytanie
4. **Przeczytaj obie odpowiedzi** side-by-side
5. **Zaglosuj**: A lepsza / B lepsza / Remis / Obie zle
6. **Opcjonalny komentarz**
7. **Leaderboard** — statystyki wygranych w zakladce "Leaderboard"

## Scoring

- Win = +1 pkt
- Tie = +0.5 pkt
- Both bad = -0.5 pkt
- Loss = 0 pkt

## Deploy na HuggingFace Spaces (darmowy hosting)

### Krok 1: Repo na GitHub
1. Stworz repo `persona-arena` na GitHub
2. Wgraj zawartosc katalogu `persona_arena/`

### Krok 2: HuggingFace Space
1. Zaloguj sie na https://huggingface.co
2. New Space → name: `persona-arena` → SDK: **Gradio** → Public
3. Files → Add file → upload pliki z `persona_arena/`:
   - `persona_arena.py`
   - `arena_versus.py`
   - `requirements.txt` (dodaj `gradio` + `requests`)
   - `README.md` (HF Spaces README)

### Krok 3: README.md dla HF Spaces

Stworz plik `README.md` w root z front matter:

```markdown
---
title: Persona Arena
emoji: ⚔️
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: "6.0"
app_file: arena_versus.py
pinned: false
---

# Persona Arena — Versus

Publiczna arena: 2 persony odpowiadaja na to samo pytanie, Ty glosujesz.
Leaderboard pokazuje ktora persona wygrywa najczesciej.

## Jak uzywac

1. Backend konfigurujesz w `data/config.json` albo przez UI w `arena_ui.py`
2. Dla deployu publicznego uzytkownicy podaja wlasny API key w UI
3. Wszystkie glosy sa zapisywane w `data/votes.json`
```

### Krok 4: Persystencja danych na HF Spaces

HF Spaces ma ephemeral filesystem — po restarcie trace dane. Opcje:

**A. Tylko ephemeral** (najprostsze)
- Persony i pytania sa w repo (git tracked)
- Glosy sie resetuja po restarcie — OK na poczatek

**B. HF Datasets jako storage**
- Exportuj glosy do datasetu co noc (cron)
- Importujesz przy starcie
- Patrz: `export_votes.py` (do zrobienia)

**C. HF Space persistent storage** (dla PRO kont)
- $5/mies za 20GB
- Real persistence

Rekomendacja na start: **opcja A**. Jak sie rozrosnie — B.

## Konfiguracja dla uzytkownikow publicznych

Problem: na publicznym spacie nie mozesz trzymac swojego API key w kodzie.

**Rozwiazanie**: kazdy uzytkownik wpisuje wlasny API key w UI.

Aktualna wersja `arena_versus.py` nie ma tego — trzeba dodac pole "API key" w UI i przekazywac do backendu per-request. To jest TODO przed publicznym deployem.

Szkic:

```python
# W arena_versus.py — dodaj w Versus tab:
with gr.Accordion("Twoj API key (opcjonalny dla deployu publicznego)"):
    user_api_key = gr.Textbox(label="API key", type="password")
    user_backend = gr.Dropdown(choices=["groq", "gemini_api", "openrouter_free", "ollama_local"])

# W generate_versus — sprawdzaj czy user podal key, jesli tak — nadpisz config tymczasowo
```

## TODO przed publicznym deployem

- [ ] Dodaj pole "wlasny API key" w UI (per-session)
- [ ] Whitelabel: zmien tytul, kolory, opis
- [ ] Eksport glosow do JSON (przycisk)
- [ ] Reset glosow (przycisk admin)
- [ ] Captcha lub rate limit (anti-spam)
- [ ] Markdown explanation pod leaderboardem

## Licencja

MIT. Rob co chcesz.
