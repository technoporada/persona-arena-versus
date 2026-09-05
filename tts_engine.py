#!/usr/bin/env python3
"""
tts_engine.py — Text-to-Speech dla Persona Arena.
Glasy person: kazdy persona moze mowic swoim "glosem".

Enginee:
  - gTTS (Google) — domyslny, online, dobra jakosc
  - pyttsx3 — offline, local TTS
  - edge-tts — Microsoft Edge TTS, duzo glosow, online

Usage:
  from tts_engine import synthesize, get_voice_for_persona

  # Zsynbtyzuj mowę
  audio_path = synthesize("Cześć, jestem Arek!", persona_id="arek")

  # Dostepne glosy
  voices = list_available_voices()
"""

import os
import asyncio
from typing import Optional, Dict

# Audio dir
AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_cache")
os.makedirs(AUDIO_DIR, exist_ok=True)

# -----------------------
# Persona voice mapping
# -----------------------
# Polskie glosy — kazdy persona ma swoj glos
PERSONA_VOICES: Dict[str, Dict] = {
    "arek": {
        "name": "Arek — OSINT detektyw",
        "gtts_lang": "pl",
        "gtts_tld": "pl",
        "edge_voice": "pl-PL-MarekNeural",
        "gender": "male",
        "description": "Męski, konkretny, bez emocji"
    },
    "zuzia": {
        "name": "Zuzia — analityk danych",
        "gtts_lang": "pl",
        "gtts_tld": "pl",
        "edge_voice": "pl-PL-AgnieszkaNeural",
        "gender": "female",
        "description": "Żeński, analityczny, precyzyjny"
    },
    "marek": {
        "name": "Marek — sceptyk",
        "gtts_lang": "pl",
        "gtts_tld": "pl",
        "edge_voice": "pl-PL-JanNeural",
        "gender": "male",
        "description": "Męski, krytyczny, ironiczny"
    },
    "irena": {
        "name": "Irena — syntetyzator",
        "gtts_lang": "pl",
        "gtts_tld": "pl",
        "edge_voice": "pl-PL-AgnieszkaNeural",
        "gender": "female",
        "description": "Żeński, ciepły, narracyjny"
    },
    "kuba": {
        "name": "Kuba — kreatywny",
        "gtts_lang": "pl",
        "gtts_tld": "pl",
        "edge_voice": "pl-PL-MarekNeural",
        "gender": "male",
        "description": "Męski, ekspresyjny, dynamiczny"
    },
}

DEFAULT_VOICE = {
    "gtts_lang": "pl",
    "gtts_tld": "pl",
    "edge_voice": "pl-PL-MarekNeural",
}


def get_voice_for_persona(persona_id: str) -> Dict:
    """Zwraca konfiguracje glosu dla persony."""
    return PERSONA_VOICES.get(persona_id, DEFAULT_VOICE)


# -----------------------
# gTTS engine (online, Google)
# -----------------------

def _synthesize_gtts(text: str, output_path: str, lang: str = "pl", tld: str = "pl") -> str:
    """Synteza przez Google TTS (gTTS)."""
    from gtts import gTTS
    tts = gTTS(text=text, lang=lang, tld=tld)
    tts.save(output_path)
    return output_path


# -----------------------
# edge-tts engine (online, Microsoft)
# -----------------------

def _synthesize_edge(text: str, output_path: str, voice: str = "pl-PL-MarekNeural") -> str:
    """Synteza przez Microsoft Edge TTS — duzo glosow, dobra jakosc."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    asyncio.run(communicate.save(output_path))
    return output_path


# -----------------------
# pyttsx3 engine (offline)
# -----------------------

def _synthesize_pyttsx3(text: str, output_path: str) -> str:
    """Synteza offline przez pyttsx3."""
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", 160)
    engine.save_to_file(text, output_path)
    engine.runAndWait()
    return output_path


# -----------------------
# Main API
# -----------------------

def synthesize(
    text: str,
    persona_id: Optional[str] = None,
    engine: str = "auto",
    output_path: Optional[str] = None,
    **kwargs
) -> str:
    """
    Syntezuj tekst na mowe. Zwraca sciezke do pliku audio (MP3).

    Args:
        text: Tekst do przeczytania
        persona_id: ID persony (dobiera glos)
        engine: "auto" | "gtts" | "edge" | "pyttsx3"
        output_path: Sciezka wyjsciowa (auto-generowana jesli None)

    Returns:
        Sciezka do pliku MP3
    """
    if not text or not text.strip():
        raise ValueError("Text cannot be empty")

    voice_config = get_voice_for_persona(persona_id) if persona_id else DEFAULT_VOICE

    if output_path is None:
        import hashlib
        h = hashlib.md5(f"{persona_id}:{text[:100]}".encode()).hexdigest()[:8]
        output_path = os.path.join(AUDIO_DIR, f"{persona_id or 'default'}_{h}.mp3")

    if engine == "auto":
        engine = _pick_engine()

    if engine == "gtts":
        return _synthesize_gtts(
            text, output_path,
            lang=voice_config.get("gtts_lang", "pl"),
            tld=voice_config.get("gtts_tld", "pl")
        )
    elif engine == "edge":
        return _synthesize_edge(
            text, output_path,
            voice=voice_config.get("edge_voice", "pl-PL-MarekNeural")
        )
    elif engine == "pyttsx3":
        return _synthesize_pyttsx3(text, output_path)
    else:
        raise ValueError(f"Unknown engine: {engine}")


def _pick_engine() -> str:
    """Automatycznie wybierz najlepszy dostepny engine."""
    try:
        import importlib
        importlib.import_module("edge_tts")
        return "edge"
    except ImportError:
        pass
    try:
        import importlib
        importlib.import_module("gtts")
        return "gtts"
    except ImportError:
        pass
    return "pyttsx3"


def list_available_voices() -> list:
    """Lista dostepnych glosow per persona."""
    voices = []
    for pid, cfg in PERSONA_VOICES.items():
        voices.append({
            "persona": pid,
            "name": cfg["name"],
            "gender": cfg["gender"],
            "edge_voice": cfg.get("edge_voice", "N/A"),
            "description": cfg["description"]
        })
    return voices


def clear_cache():
    """Wyczysc cache audio."""
    import glob
    for f in glob.glob(os.path.join(AUDIO_DIR, "*.mp3")):
        os.remove(f)
    return "Cache cleared"


# -----------------------
# CLI
# -----------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TTS for Persona Arena")
    parser.add_argument("text", nargs="?", help="Text to synthesize")
    parser.add_argument("--persona", help="Persona ID for voice selection")
    parser.add_argument("--engine", default="auto", choices=["auto", "gtts", "edge", "pyttsx3"])
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--voices", action="store_true", help="List available voices")
    parser.add_argument("--clear-cache", action="store_true", help="Clear audio cache")

    args = parser.parse_args()

    if args.voices:
        print("\n=== DOSTEPNE GLOSY ===\n")
        for v in list_available_voices():
            print(f"[{v['persona']}] {v['name']}")
            print(f"  Gender: {v['gender']} | Edge: {v['edge_voice']}")
            print(f"  {v['description']}")
            print()
    elif args.clear_cache:
        print(clear_cache())
    elif args.text:
        path = synthesize(args.text, persona_id=args.persona, engine=args.engine, output_path=args.output)
        print(f"Audio saved: {path}")
    else:
        parser.print_help()
