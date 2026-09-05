#!/usr/bin/env python3
"""
arena_versus.py — Publiczna arena: 2 persony odpowiadaja na to samo pytanie, Ty glosujesz.
Host: python arena_versus.py → http://localhost:7861
HF Spaces deploy: patrz README_versus.md
"""

import os
import sys
import random
import traceback
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from persona_arena import (
    _load_json, _save_json,
    PERSONAS_FILE, QUESTIONS_FILE, CONFIG_FILE,
    init_store, get_persona, call_llm, PROMPT_SOLVE,
)
from tts_engine import synthesize as tts_synthesize

import gradio as gr

# Plik z historia glosow
VOTES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "votes.json")

# -----------------------
# Voting logic
# -----------------------

def _load_votes() -> Dict:
    return _load_json(VOTES_FILE, {"votes": [], "stats": {}})


def _save_votes(data: Dict):
    _save_json(VOTES_FILE, data)


def _update_stats(stats: Dict, persona_id: str, outcome: str):
    """outcome: 'win', 'loss', 'tie', 'both_bad'"""
    if persona_id not in stats:
        stats[persona_id] = {"win": 0, "loss": 0, "tie": 0, "both_bad": 0, "total": 0}
    if outcome in ("win", "loss", "tie", "both_bad"):
        # 'both_bad' liczymy tylko dla total, nie jako win/loss
        if outcome == "both_bad":
            stats[persona_id]["both_bad"] += 1
        else:
            stats[persona_id][outcome] += 1
    stats[persona_id]["total"] += 1


def cast_vote(question_id: str, persona_a_id: str, persona_b_id: str,
              answer_a: str, answer_b: str, vote: str, comment: str = "") -> str:
    """vote: 'A' / 'B' / 'tie' / 'both_bad'"""
    data = _load_votes()
    vote_record = {
        "question_id": question_id,
        "persona_a": persona_a_id,
        "persona_b": persona_b_id,
        "answer_a_preview": answer_a[:500],
        "answer_b_preview": answer_b[:500],
        "vote": vote,
        "comment": comment,
        "ts": _now_iso()
    }
    data["votes"].append(vote_record)

    stats = data.setdefault("stats", {})
    if vote == "A":
        _update_stats(stats, persona_a_id, "win")
        _update_stats(stats, persona_b_id, "loss")
    elif vote == "B":
        _update_stats(stats, persona_b_id, "win")
        _update_stats(stats, persona_a_id, "loss")
    elif vote == "tie":
        _update_stats(stats, persona_a_id, "tie")
        _update_stats(stats, persona_b_id, "tie")
    elif vote == "both_bad":
        _update_stats(stats, persona_a_id, "both_bad")
        _update_stats(stats, persona_b_id, "both_bad")

    _save_votes(data)
    return f"✅ Głos zapisany: {vote}"


def _now_iso():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# -----------------------
# Versus flow
# -----------------------

def get_random_question(seed: Optional[int] = None) -> Tuple[str, str]:
    questions = _load_json(QUESTIONS_FILE, {})
    if not questions:
        return "", "Brak pytan. Najpierw dodaj pytania w arena_ui.py."
    if seed is not None:
        random.seed(seed)
    qid, q = random.choice(list(questions.items()))
    return qid, q.get("question", "")


def get_two_personas(exclude_same_specialty: bool = False, seed: Optional[int] = None) -> Tuple[str, str]:
    personas = list(_load_json(PERSONAS_FILE, {}).keys())
    if len(personas) < 2:
        return "", ""
    if seed is not None:
        random.seed(seed)
    random.shuffle(personas)
    a = personas[0]
    b = personas[1]
    return a, b


def generate_versus(question_id: str, persona_a_id: str, persona_b_id: str, progress=gr.Progress()):
    """Generuje odpowiedzi obu person na to samo pytanie. Side-by-side."""
    if not question_id or not persona_a_id or not persona_b_id:
        return "❌ Brak danych", "", "", "", "", ""

    if persona_a_id == persona_b_id:
        return "❌ Wybierz dwie rozne persony", "", "", "", "", ""

    questions = _load_json(QUESTIONS_FILE, {})
    if question_id not in questions:
        return f"❌ Nie ma pytania {question_id}", "", "", "", "", ""

    q = questions[question_id]
    question_text = q.get("question", "")

    try:
        progress(0.1, desc=f"Persona {persona_a_id} pisze...")
        persona_a = get_persona(persona_a_id)
        answer_a = call_llm(persona_a, PROMPT_SOLVE, question=question_text)

        progress(0.6, desc=f"Persona {persona_b_id} pisze...")
        persona_b = get_persona(persona_b_id)
        answer_b = call_llm(persona_b, PROMPT_SOLVE, question=question_text)

        progress(1.0, desc="Gotowe")
        # Ukryj info kto jest A a kto B w UI — zeby glosujacy nie mial biasu
        # Ale zachowaj info w state (zwracamy jako ukryte)
        return (
            "✅ Wygenerowano. Glosuj kto lepszy.",
            answer_a,
            answer_b,
            persona_a_id,  # hidden state
            persona_b_id,  # hidden state
            question_id    # hidden state
        )
    except Exception:
        return f"❌ BŁĄD:\n{traceback.format_exc()}", "", "", "", "", ""


def submit_vote(vote: str, comment: str, state_a: str, state_b: str, state_q: str,
                answer_a: str, answer_b: str) -> str:
    if not state_a or not state_b or not state_q:
        return "❌ Brak danych sesji"
    try:
        return cast_vote(state_q, state_a, state_b, answer_a, answer_b, vote, comment)
    except Exception as e:
        return f"❌ {e}"


# -----------------------
# Leaderboard
# -----------------------

def leaderboard_table() -> List[List]:
    data = _load_votes()
    stats = data.get("stats", {})
    personas = _load_json(PERSONAS_FILE, {})

    rows = []
    for pid, s in stats.items():
        name = personas.get(pid, {}).get("name", pid)
        specialty = personas.get(pid, {}).get("specialty", "?")
        wins = s.get("win", 0)
        losses = s.get("loss", 0)
        ties = s.get("tie", 0)
        bad = s.get("both_bad", 0)
        total = s.get("total", 0)
        win_rate = (wins / total * 100) if total else 0
        # Score: win = +1, tie = +0.5, both_bad = -0.5, loss = 0
        score = wins + 0.5 * ties - 0.5 * bad
        rows.append([pid, name, specialty, wins, losses, ties, bad, total, f"{win_rate:.1f}%", f"{score:+.1f}"])

    # Sort by score desc
    rows.sort(key=lambda r: -float(r[-1]))
    return rows


def votes_history_table(limit: int = 50) -> List[List]:
    data = _load_votes()
    votes = data.get("votes", [])[-limit:][::-1]  # ostatnie `limit`, najnowsze pierwsze
    rows = []
    for v in votes:
        rows.append([
            v.get("ts", "")[:19],
            v.get("question_id", ""),
            v.get("persona_a", ""),
            v.get("persona_b", ""),
            v.get("vote", ""),
            v.get("comment", "")[:60]
        ])
    return rows


# -----------------------
# Helpers for UI
# -----------------------

def get_personas_list() -> List[str]:
    return list(_load_json(PERSONAS_FILE, {}).keys())


def get_questions_list() -> List[Tuple[str, str]]:
    questions = _load_json(QUESTIONS_FILE, {})
    return [(f"{qid} — {q.get('question', '')[:80]}", qid) for qid, q in questions.items()]


def backend_status_short() -> str:
    config = _load_json(CONFIG_FILE, {"backend": "mock"})
    return f"Backend: **{config.get('backend', 'mock')}**"


# -----------------------
# TTS
# -----------------------

def tts_answer(text: str, persona_id: str) -> Optional[str]:
    """Syntezuj odpowiedz persony na mowe. Zwraca sciezke do audio."""
    if not text or not text.strip():
        return None
    try:
        # Skroc tekst jesli za dlugi (max ~3000 znakow dla TTS)
        tts_text = text[:3000]
        if len(text) > 3000:
            tts_text += "... (skrocono)"
        path = tts_synthesize(tts_text, persona_id=persona_id)
        return path
    except Exception as e:
        print(f"TTS error: {e}")
        return None


# -----------------------
# UI
# -----------------------

def build_ui():
    with gr.Blocks(title="Persona Arena — Versus") as app:
        gr.Markdown("# Persona Arena — Versus\nDwie persony. Jedno pytanie. Twój głos decyduje.")

        # Stan sesji (hidden)
        session_state_a = gr.State("")
        session_state_b = gr.State("")
        session_state_q = gr.State("")

        with gr.Tab("Versus"):
            with gr.Row():
                with gr.Column():
                    q_dropdown = gr.Dropdown(
                        choices=get_questions_list(),
                        label="Wybierz pytanie"
                    )
                with gr.Column():
                    random_q_btn = gr.Button("Losuj pytanie")
                    p_a = gr.Dropdown(choices=get_personas_list(), label="Persona A")
                    p_b = gr.Dropdown(choices=get_personas_list(), label="Persona B")
                    random_p_btn = gr.Button("Losuj persony")
                with gr.Column():
                    generate_btn = gr.Button("Generuj odpowiedzi", variant="primary")
                    status_box = gr.Textbox(label="Status", interactive=False)

            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Odpowiedź A")
                    answer_a = gr.Textbox(label="", lines=18, interactive=False, elem_classes="answer-box")
                    tts_a_btn = gr.Button("🔊 Posłuchaj A", variant="secondary")
                    tts_a_audio = gr.Audio(label="Audio A", type="filepath", interactive=False)
                with gr.Column():
                    gr.Markdown("### Odpowiedź B")
                    answer_b = gr.Textbox(label="", lines=18, interactive=False, elem_classes="answer-box")
                    tts_b_btn = gr.Button("🔊 Posłuchaj B", variant="secondary")
                    tts_b_audio = gr.Audio(label="Audio B", type="filepath", interactive=False)

            with gr.Row():
                vote_a_btn = gr.Button("👈 A lepsza", variant="primary")
                vote_b_btn = gr.Button("B lepsza 👉", variant="primary")
                vote_tie_btn = gr.Button("🤝 Remis")
                vote_bad_btn = gr.Button("💩 Obie złe")

            comment = gr.Textbox(label="Komentarz (opcjonalny)", lines=2)
            vote_status = gr.Textbox(label="Status głosu", interactive=False)

            # Hidden state holders (placeholder values shown)
            gr.Markdown("", visible=False)

            # Events
            def _random_q():
                qid, _ = get_random_question()
                return qid

            def _random_p():
                a, b = get_two_personas()
                return a, b

            random_q_btn.click(_random_q, outputs=q_dropdown)
            random_p_btn.click(_random_p, outputs=[p_a, p_b])

            generate_btn.click(
                generate_versus,
                inputs=[q_dropdown, p_a, p_b],
                outputs=[status_box, answer_a, answer_b, session_state_a, session_state_b, session_state_q]
            )

            vote_a_btn.click(
                lambda c, sa, sb, sq, aa, ab: submit_vote("A", c, sa, sb, sq, aa, ab),
                inputs=[comment, session_state_a, session_state_b, session_state_q, answer_a, answer_b],
                outputs=vote_status
            )
            vote_b_btn.click(
                lambda c, sa, sb, sq, aa, ab: submit_vote("B", c, sa, sb, sq, aa, ab),
                inputs=[comment, session_state_a, session_state_b, session_state_q, answer_a, answer_b],
                outputs=vote_status
            )
            vote_tie_btn.click(
                lambda c, sa, sb, sq, aa, ab: submit_vote("tie", c, sa, sb, sq, aa, ab),
                inputs=[comment, session_state_a, session_state_b, session_state_q, answer_a, answer_b],
                outputs=vote_status
            )
            vote_bad_btn.click(
                lambda c, sa, sb, sq, aa, ab: submit_vote("both_bad", c, sa, sb, sq, aa, ab),
                inputs=[comment, session_state_a, session_state_b, session_state_q, answer_a, answer_b],
                outputs=vote_status
            )

            # TTS events
            tts_a_btn.click(
                lambda text, sid: tts_answer(text, sid),
                inputs=[answer_a, session_state_a],
                outputs=tts_a_audio
            )
            tts_b_btn.click(
                lambda text, sid: tts_answer(text, sid),
                inputs=[answer_b, session_state_b],
                outputs=tts_b_audio
            )

        with gr.Tab("Leaderboard"):
            gr.Markdown("## Statystyki wygranych\nWin = +1 pkt, Tie = +0.5, Both bad = -0.5, Loss = 0")
            lb_df = gr.Dataframe(
                value=leaderboard_table(),
                headers=["id", "imie", "specialnosc", "win", "loss", "tie", "both_bad", "total", "win_rate", "score"],
                interactive=False,
                wrap=True
            )
            refresh_lb = gr.Button("Odswierz")
            refresh_lb.click(leaderboard_table, outputs=lb_df)

            gr.Markdown("---\n## Historia glosow (ostatnie 50)")
            vh_df = gr.Dataframe(
                value=votes_history_table(),
                headers=["czas", "pytanie", "persona A", "persona B", "glos", "komentarz"],
                interactive=False,
                wrap=True
            )
            refresh_vh = gr.Button("Odswierz historie")
            refresh_vh.click(votes_history_table, outputs=vh_df)

        with gr.Tab("Backend"):
            gr.Markdown(f"Aktualny {backend_status_short()}")
            gr.Markdown(
                "Backend konfiguruje sie przez `arena_ui.py` (zakładka Backend) lub recznie w "
                "`data/config.json`.\n\n"
                "Dla publicznego deployu (HuggingFace Spaces) uzytkownik wpisuje swoj API key w UI — "
                "patrz README_versus.md."
            )

    return app


if __name__ == "__main__":
    # Inicjalizuj jesli pusto
    if not os.path.exists(PERSONAS_FILE):
        init_store()
    app = build_ui()
    app.launch(server_name="127.0.0.1", server_port=7861, share=False, inbrowser=True,
               theme=gr.themes.Soft(),
               css=".answer-box { min-height: 400px; }")
