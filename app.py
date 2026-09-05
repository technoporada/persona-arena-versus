#!/usr/bin/env python3
"""
Persona Arena — HuggingFace Spaces entry point
Dwie persony odpowiadają na to samo pytanie. Ty głosujesz, która lepsza.
Z TTS: możesz posłuchać odpowiedzi każdej persony.
"""

import os
import sys
import random
import traceback
from typing import Dict, List, Optional, Tuple

# Upewnij sie ze jestesmy w odpowiednim katalogu
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from persona_arena import (  # noqa: E402
    _load_json, _save_json,
    PERSONAS_FILE, QUESTIONS_FILE, init_store, get_persona, call_llm, PROMPT_SOLVE,
)
from tts_engine import synthesize as tts_synthesize  # noqa: E402

import gradio as gr  # noqa: E402

# Inicjalizuj dane jesli nie istnieja
if not os.path.exists(PERSONAS_FILE):
    init_store()

# -----------------------
# Voting
# -----------------------
VOTES_FILE = os.path.join(ROOT, "data", "votes.json")


def _load_votes() -> Dict:
    return _load_json(VOTES_FILE, {"votes": [], "stats": {}})


def _save_votes(data: Dict):
    _save_json(VOTES_FILE, data)


def _now_iso():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _update_stats(stats: Dict, persona_id: str, outcome: str):
    if persona_id not in stats:
        stats[persona_id] = {"win": 0, "loss": 0, "tie": 0, "both_bad": 0, "total": 0}
    if outcome in ("win", "loss", "tie", "both_bad"):
        if outcome == "both_bad":
            stats[persona_id]["both_bad"] += 1
        else:
            stats[persona_id][outcome] += 1
    stats[persona_id]["total"] += 1


def cast_vote(question_id: str, persona_a_id: str, persona_b_id: str,
              answer_a: str, answer_b: str, vote: str, comment: str = "") -> str:
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


# -----------------------
# Helpers
# -----------------------
def get_random_question():
    questions = _load_json(QUESTIONS_FILE, {})
    if not questions:
        return "", ""
    qid, q = random.choice(list(questions.items()))
    return qid, q.get("question", "")


def get_two_personas():
    personas = list(_load_json(PERSONAS_FILE, {}).keys())
    if len(personas) < 2:
        return "", ""
    random.shuffle(personas)
    return personas[0], personas[1]


def get_personas_list() -> List[str]:
    return list(_load_json(PERSONAS_FILE, {}).keys())


def get_questions_list() -> List[Tuple[str, str]]:
    questions = _load_json(QUESTIONS_FILE, {})
    return [(f"{qid} — {q.get('question', '')[:80]}", qid) for qid, q in questions.items()]


# -----------------------
# TTS
# -----------------------
def tts_answer(text: str, persona_id: str) -> Optional[str]:
    if not text or not text.strip():
        return None
    try:
        tts_text = text[:3000]
        if len(text) > 3000:
            tts_text += "... (skrocono)"
        path = tts_synthesize(tts_text, persona_id=persona_id)
        return path
    except Exception as e:
        print(f"TTS error: {e}")
        return None


# -----------------------
# Main flow
# -----------------------
def generate_versus(question_id: str, persona_a_id: str, persona_b_id: str, progress=gr.Progress()):
    if not question_id or not persona_a_id or not persona_b_id:
        return "❌ Wybierz pytanie i dwie persony", "", "", "", "", ""
    if persona_a_id == persona_b_id:
        return "❌ Wybierz dwie różne persony", "", "", "", "", ""

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
        return (
            "✅ Wygenerowano. Glosuj kto lepszy.",
            answer_a,
            answer_b,
            persona_a_id,
            persona_b_id,
            question_id
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
        score = wins + 0.5 * ties - 0.5 * bad
        rows.append([pid, name, specialty, wins, losses, ties, bad, total, f"{win_rate:.1f}%", f"{score:+.1f}"])
    rows.sort(key=lambda r: -float(r[-1]))
    return rows


def votes_history_table(limit: int = 50) -> List[List]:
    data = _load_votes()
    votes = data.get("votes", [])[-limit:][::-1]
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
# Build UI
# -----------------------
def build_ui():
    with gr.Blocks(
        title="Persona Arena — Versus"
    ) as app:
        gr.Markdown("""
        # ⚔️ Persona Arena — Versus
        **Dwie persony. Jedno pytanie. Twój głos decyduje.**

        Persony rozwiazuja pytania w swoich specjalnosciach. Kazdy ma swoj charakter i glos (TTS).
        """)

        # Stan sesji
        session_state_a = gr.State("")
        session_state_b = gr.State("")
        session_state_q = gr.State("")

        with gr.Tab("⚔️ Versus"):
            with gr.Row():
                with gr.Column(scale=2):
                    q_dropdown = gr.Dropdown(
                        choices=get_questions_list(),
                        label="📝 Wybierz pytanie"
                    )
                with gr.Column(scale=1):
                    random_q_btn = gr.Button("🎲 Losuj pytanie")

            with gr.Row():
                with gr.Column():
                    p_a = gr.Dropdown(choices=get_personas_list(), label="👤 Persona A")
                with gr.Column():
                    p_b = gr.Dropdown(choices=get_personas_list(), label="👤 Persona B")
                with gr.Column():
                    random_p_btn = gr.Button("🎲 Losuj persony")
                    generate_btn = gr.Button("⚡ Generuj odpowiedzi", variant="primary")

            status_box = gr.Textbox(label="Status", interactive=False)

            with gr.Row():
                with gr.Column():
                    gr.Markdown("### 🅰️ Odpowiedź A")
                    answer_a = gr.Textbox(label="", lines=15, interactive=False, elem_classes="answer-box")
                    with gr.Row():
                        tts_a_btn = gr.Button("🔊 Posłuchaj A", variant="secondary")
                    tts_a_audio = gr.Audio(label="Audio A", type="filepath", interactive=False)
                with gr.Column():
                    gr.Markdown("### 🅱️ Odpowiedź B")
                    answer_b = gr.Textbox(label="", lines=15, interactive=False, elem_classes="answer-box")
                    with gr.Row():
                        tts_b_btn = gr.Button("🔊 Posłuchaj B", variant="secondary")
                    tts_b_audio = gr.Audio(label="Audio B", type="filepath", interactive=False)

            gr.Markdown("---")
            gr.Markdown("### 🗳️ Zagłosuj")
            with gr.Row():
                vote_a_btn = gr.Button("👈 A lepsza", variant="primary", elem_classes="vote-btn")
                vote_b_btn = gr.Button("B lepsza 👉", variant="primary", elem_classes="vote-btn")
                vote_tie_btn = gr.Button("🤝 Remis", elem_classes="vote-btn")
                vote_bad_btn = gr.Button("💩 Obie złe", elem_classes="vote-btn")

            comment = gr.Textbox(label="💬 Komentarz (opcjonalny)", lines=2)
            vote_status = gr.Textbox(label="Status głosu", interactive=False)

            # Events
            random_q_btn.click(
                lambda: get_random_question()[0],
                outputs=q_dropdown
            )
            random_p_btn.click(
                lambda: get_two_personas(),
                outputs=[p_a, p_b]
            )

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

        with gr.Tab("🏆 Leaderboard"):
            gr.Markdown("""
            ## Statystyki wygranych
            - **Win** = +1 pkt
            - **Tie** = +0.5 pkt
            - **Both bad** = -0.5 pkt
            - **Loss** = 0 pkt
            """)
            lb_df = gr.Dataframe(
                value=leaderboard_table(),
                headers=["ID", "Imię", "Specjalność", "Win", "Loss", "Tie", "Both bad", "Total", "Win rate", "Score"],
                interactive=False,
                wrap=True
            )
            refresh_lb = gr.Button("🔄 Odśwież")
            refresh_lb.click(leaderboard_table, outputs=lb_df)

            gr.Markdown("---\n## 📜 Historia głosów (ostatnie 50)")
            vh_df = gr.Dataframe(
                value=votes_history_table(),
                headers=["Czas", "Pytanie", "Persona A", "Persona B", "Głos", "Komentarz"],
                interactive=False,
                wrap=True
            )
            refresh_vh = gr.Button("🔄 Odśwież historię")
            refresh_vh.click(votes_history_table, outputs=vh_df)

        with gr.Tab("ℹ️ O projekcie"):
            gr.Markdown("""
            ## Persona Arena — Versus

            Publiczna arena: 2 persony odpowiadają na to samo pytanie. Ty głosujesz, która odpowiedź lepsza.

            ### Persony
            | Persona | Specjalność | Charakter |
            |---------|-------------|-----------|
            | **Arek** | OSINT | Detektyw cyfrowy, konkret, dowody |
            | **Zuzia** | Data Analysis | Analityczka, sceptyczna, liczby |
            | **Marek** | Critical Thinking | Skeptyk, szuka dziur |
            | **Irena** | Synthesis | Syntetyzuje fakty w historie |
            | **Kuba** | Creative | Lateral thinking, nietypowe pomysły |

            ### Jak to działa
            1. Wybierz pytanie (lub losuj)
            2. Wybierz 2 persony
            3. Wygeneruj odpowiedzi — obie dostają to samo pytanie
            4. Przeczytaj obie odpowiedzi side-by-side
            5. Zagłosuj: A lepsza / B lepsza / Remis / Obie złe
            6. Opcjonalnie: posłuchaj odpowiedzi (TTS)

            ### Tech Stack
            - Python + Gradio
            - LLM: Groq / Gemini / Ollama (konfigurowalny)
            - TTS: Microsoft Edge TTS (darmowe, polskie głosy)
            - Storage: JSON + SQLite

            ### Autor
            Stworzone jako demo systemu testowania LLM-ów przez persony.
            """)

    return app


# -----------------------
# Launch
# -----------------------
app = build_ui()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    app.launch(
        server_name="0.0.0.0",
        server_port=port,
        share=True,
        inbrowser=True,
        theme=gr.themes.Soft(),
        css=".answer-box { min-height: 300px; } .vote-btn { min-width: 120px; }"
    )
