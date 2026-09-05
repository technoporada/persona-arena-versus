---
title: Persona Arena — Versus
emoji: ⚔️
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: "6.24.0"
app_file: app.py
pinned: false
license: mit
tags:
  - text-to-speech
  - llm
  - persona
  - arena
  - polish
---

# ⚔️ Persona Arena — Versus

**Dwie persony. Jedno pytanie. Twój głos decyduje.**

Publiczna arena AI: dwie persony odpowiadają na to samo pytanie, ty głosujesz która odpowiedź lepsza. Każda persona ma swój charakter, specjalność i głos (TTS).

## 🎯 Funkcje

- **5 unikalnych person** z różnymi specjalnościami (OSINT, Data Analysis, Critical Thinking, Synthesis, Creative)
- **Tryb Versus** — dwie persony odpowiadają na jedno pytanie
- **Głosowanie** — A lepsza / B lepsza / Remis / Obie złe
- **TTS** — posłuchaj odpowiedzi każdej persony (Microsoft Edge TTS, polskie głosy)
- **Leaderboard** — statystyki wygranych w czasie rzeczywistym
- **Konfigurowalny backend LLM** — Groq (darmowy), Gemini, Ollama (lokalny)

## 🧑‍🤝‍🧑 Persony

| Persona | Specjalność | Charakter |
|---------|-------------|-----------|
| **Arek** | OSINT | Detektyw cyfrowy, konkret, dowody |
| **Zuzia** | Data Analysis | Analityczka, sceptyczna, liczby |
| **Marek** | Critical Thinking | Skeptyk, szuka dziur w rozumowaniu |
| **Irena** | Synthesis | Syntetyzuje fakty w koherentne historie |
| **Kuba** | Creative | Lateral thinking, nietypowe pomysły |

## 🚀 Szybki start

1. Wybierz pytanie (lub kliknij "Losuj")
2. Wybierz 2 persony
3. Kliknij "Generuj odpowiedzi"
4. Przeczytaj obie odpowiedzi side-by-side
5. Kliknij "🔊 Posłuchaj" aby usłyszeć odpowiedź
6. Zagłosuj kto lepszy!

## ⚙️ Konfiguracja backendu

Darmowe opcje:
- **Groq** — `GROQ_API_KEY` (darmowy tier, llama-3.3-70b)
- **Gemini** — `GEMINI_API_KEY` (darmowy tier, gemini-2.0-flash)
- **Ollama** — lokalnie, bez API key

## 🛠️ Tech Stack

- Python 3.12+
- Gradio 6.x
- LLM: OpenAI-compatible API (Groq/Gemini/Ollama)
- TTS: Microsoft Edge TTS (edge-tts)
- Storage: JSON + SQLite

## 📁 Struktura projektu

```
persona-arena/
├── app.py              # Główny plik (HF Spaces)
├── persona_arena.py    # Rdzeń systemu
├── arena_versus.py     # Tryb versus (lokalnie)
├── arena_ui.py         # Panel administracyjny
├── tts_engine.py       # Text-to-Speech
├── requirements.txt    # Zależności
├── data/               # Persony, pytania, config
└── audio_cache/        # Cache plików audio
```

## 📜 Licencja

MIT — rób co chcesz.

## 🔗 Linki

- [GitHub](https://github.com/twoj-nick/persona-arena)
- [Demo](https://huggingface.co/spaces/twoj-nick/persona-arena)
