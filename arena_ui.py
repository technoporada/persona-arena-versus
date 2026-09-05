#!/usr/bin/env python3
"""
arena_ui.py — Gradio UI dla persona_arena.
Uruchom: python arena_ui.py
Otworz: http://localhost:7860
"""

import os
import sys
import json
import traceback

# Import logiki z persona_arena.py (musi byc w tym samym katalogu)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from persona_arena import (
    _load_json, _save_json,
    PERSONAS_FILE, QUESTIONS_FILE, CHALLENGES_FILE, CONFIG_FILE,
    SPECIALTIES, BACKEND_PRESETS,
    init_store, add_persona, add_question,
    generate_question, solve_question, judge_challenge,
    auto_batch, report, get_backend
)
from tts_engine import synthesize as tts_synthesize, list_available_voices

import gradio as gr

# -----------------------
# Helpery UI
# -----------------------

def _safe_call(fn, *args, **kwargs):
    """Wywolaj fn, lapanie wyjatkow, zwroc (result, error_message)."""
    try:
        return fn(*args, **kwargs), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def get_backend_info() -> dict:
    config = _load_json(CONFIG_FILE, {"backend": "mock"})
    info = {"type": config.get("backend", "mock"), "details": {}}
    if config.get("backend") == "openai_compat":
        cfg = config.get("openai_compat", {})
        info["details"] = {
            "base_url": cfg.get("base_url", ""),
            "model": cfg.get("model", ""),
            "api_key_set": bool(cfg.get("api_key"))
        }
    elif config.get("backend") == "subprocess":
        cfg = config.get("subprocess", {})
        info["details"] = {
            "command": " ".join(cfg.get("command", [])),
            "args": " ".join(cfg.get("args", []))
        }
    return info


def test_backend() -> str:
    try:
        b = get_backend()
        out = b.generate("You are a test assistant.", "Reply with: OK", max_tokens=10)
        return f"✅ Backend: {b.name()}\nOdpowiedź: {out[:200]}"
    except Exception as e:
        return f"❌ Błąd: {e}"


# -----------------------
# Backend tab
# -----------------------

def backend_status_text() -> str:
    info = get_backend_info()
    lines = [f"Aktualny backend: **{info['type']}**"]
    for k, v in info["details"].items():
        lines.append(f"- {k}: `{v}`")
    return "\n".join(lines)


def backend_presets_table():
    rows = []
    for name, p in BACKEND_PRESETS.items():
        if p["type"] == "openai_compat":
            details = f"model: {p['model']}"
            needs = f"env: ${p.get('env_var', 'API_KEY')}"
        else:
            details = f"cmd: {' '.join(p.get('command', []))}"
            needs = "lokalnie"
        rows.append([name, p["type"], details, needs, p.get("notes", "")])
    return rows


def apply_preset(preset_name: str, api_key: str) -> str:
    if not preset_name:
        return "Wybierz preset."
    if preset_name not in BACKEND_PRESETS:
        return f"Nieznany preset: {preset_name}"
    p = BACKEND_PRESETS[preset_name]
    config = _load_json(CONFIG_FILE, {"backend": "mock"})

    if p["type"] == "openai_compat":
        env_var = p.get("env_var", "API_KEY")
        key = api_key.strip() or os.environ.get(env_var)
        if not key:
            return f"Podaj API key (lub ustaw env ${env_var})"
        config["backend"] = "openai_compat"
        config["openai_compat"] = {
            "base_url": p["base_url"],
            "api_key": key,
            "model": p["model"]
        }
    else:
        config["backend"] = "subprocess"
        config["subprocess"] = {
            "command": p.get("command"),
            "args": p.get("args", [])
        }
    _save_json(CONFIG_FILE, config)
    return f"✅ Zastosowano preset '{preset_name}'. Kliknij 'Testuj'."


def apply_custom_backend(b_type, base_url, api_key, model, command, arg):
    config = _load_json(CONFIG_FILE, {"backend": "mock"})
    if b_type == "mock":
        config["backend"] = "mock"
    elif b_type == "openai_compat":
        if not base_url or not model or not api_key:
            return "❌ openai_compat wymaga: base_url, model, api_key"
        config["backend"] = "openai_compat"
        config["openai_compat"] = {"base_url": base_url, "api_key": api_key, "model": model}
    elif b_type == "subprocess":
        if not command:
            return "❌ subprocess wymaga: command"
        cmd = command.split() if isinstance(command, str) else command
        arg_list = arg.split() if arg else []
        config["backend"] = "subprocess"
        config["subprocess"] = {"command": cmd, "args": arg_list}
    else:
        return f"Nieznany typ: {b_type}"
    _save_json(CONFIG_FILE, config)
    return f"✅ Backend ustawiony na: {b_type}"


# -----------------------
# Personas tab
# -----------------------

def personas_table():
    personas = _load_json(PERSONAS_FILE, {})
    rows = []
    for pid, p in personas.items():
        rows.append([pid, p.get("name", ""), p.get("specialty", ""), p.get("description", "")[:120]])
    return rows


def add_persona_ui(name, desc, specialty):
    if not name or not desc or not specialty:
        return "❌ Wszystkie pola wymagane", personas_table()
    err = None
    try:
        add_persona(name, desc, specialty)
    except Exception as e:
        err = str(e)
    if err:
        return f"❌ {err}", personas_table()
    return f"✅ Dodano '{name}'", personas_table()


def delete_persona(pid):
    if not pid:
        return "Podaj ID", personas_table()
    personas = _load_json(PERSONAS_FILE, {})
    if pid not in personas:
        return f"Nie ma '{pid}'", personas_table()
    del personas[pid]
    _save_json(PERSONAS_FILE, personas)
    return f"✅ Usunięto '{pid}'", personas_table()


# -----------------------
# Questions tab
# -----------------------

def questions_table(specialty_filter):
    questions = _load_json(QUESTIONS_FILE, {})
    rows = []
    for qid, q in questions.items():
        if specialty_filter and specialty_filter != "all" and q.get("specialty") != specialty_filter:
            continue
        rows.append([
            qid,
            q.get("specialty", ""),
            q.get("author", ""),
            q.get("question", "")[:150]
        ])
    return rows


def add_question_ui(text, specialty, criteria_json, author):
    if not text or not specialty or not criteria_json:
        return "❌ Brakuje pól", questions_table("all")
    try:
        criteria = json.loads(criteria_json)
        if not isinstance(criteria, list):
            raise ValueError("criteria musi byc lista")
    except Exception as e:
        return f"❌ Zly JSON criteria: {e}", questions_table("all")
    try:
        add_question(text, specialty, criteria, author=author or "manual")
    except Exception as e:
        return f"❌ {e}", questions_table("all")
    return "✅ Dodano pytanie", questions_table("all")


def generate_question_ui(author, topic, target_specialty):
    if not author or not topic or not target_specialty:
        return "❌ Brakuje pól", questions_table("all")
    try:
        qid = generate_question(author, topic, target_specialty)
        if qid is None:
            return "❌ LLM nie zwrocil poprawnego JSON (nie skonfigurowano backendu?)", questions_table("all")
        return f"✅ Wygenerowano {qid}", questions_table("all")
    except Exception as e:
        return f"❌ {e}", questions_table("all")


# -----------------------
# Run tab
# -----------------------

def solve_ui(question_id, solver_id):
    if not question_id or not solver_id:
        return "❌ Brakuje pól", ""
    try:
        cid = solve_question(question_id, solver_id)
        ch = _load_json(CHALLENGES_FILE, {}).get(cid, {})
        return f"✅ Challenge {cid} utworzony", ch.get("solution", "")
    except Exception as e:
        return f"❌ {e}", ""


def judge_ui(challenge_id, judge_id):
    if not challenge_id or not judge_id:
        return "❌ Brakuje pól", ""
    try:
        verdict = judge_challenge(challenge_id, judge_id)
        return f"✅ Ocena: {verdict.get('verdict')} ({verdict.get('overall_score')}/10)", json.dumps(verdict, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"❌ {e}", ""


def auto_batch_ui(per_persona, single_judge, seed):
    """Generator zwracajacy progres."""
    yield f"Start: {per_persona} pytan na persone, single_judge={single_judge}, seed={seed}..."
    try:
        #TODO: real single_judge support — na razie info
        if single_judge:
            yield "Uwaga: --single-judge nie jest jeszcze zaimplementowane w backendzie. Uruchamiam standardowo..."

        # Przechwyc output printow
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            auto_batch(per_persona=per_persona, seed=seed)
        yield "Batch zakonczony. Generuje raport..."

        # Raport
        import io as _io
        buf2 = _io.StringIO()
        with contextlib.redirect_stdout(buf2):
            report()
        yield buf2.getvalue()
    except Exception:
        yield f"❌ BŁĄD:\n{traceback.format_exc()}"


# -----------------------
# Report tab
# -----------------------

def report_text():
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report()
    return buf.getvalue()


def challenges_table():
    challenges = _load_json(CHALLENGES_FILE, {})
    questions = _load_json(QUESTIONS_FILE, {})
    rows = []
    for cid, ch in challenges.items():
        q = questions.get(ch.get("question_id"), {})
        n_verdicts = len(ch.get("verdicts", []))
        avg_score = ""
        scores = [v.get("overall_score") for v in ch.get("verdicts", []) if isinstance(v.get("overall_score"), (int, float))]
        if scores:
            avg_score = f"{sum(scores)/len(scores):.1f}"
        rows.append([
            cid,
            ch.get("question_id", ""),
            q.get("specialty", ""),
            ch.get("solver_id", ""),
            ch.get("classification", ""),
            ch.get("status", ""),
            n_verdicts,
            avg_score
        ])
    return rows


# -----------------------
# Build UI
# -----------------------

def build_ui():
    with gr.Blocks(title="Persona Arena") as app:
        gr.Markdown("# Persona Arena\nTestuj persony — rozwiazuja pytania innych person.")

        # ----- Backend tab -----
        with gr.Tab("Backend"):
            gr.Markdown("## Aktualny backend")
            status_box = gr.Markdown(backend_status_text)
            refresh_btn = gr.Button("Odswierz")
            test_btn = gr.Button("Testuj backend")
            test_out = gr.Textbox(label="Wynik testu", lines=4)

            gr.Markdown("---\n## Presety (darmowe + platne)")
            gr.Dataframe(
                value=backend_presets_table(),
                headers=["preset", "typ", "szczegoly", "wymaga", "uwagi"],
                interactive=False,
                wrap=True
            )
            with gr.Row():
                preset_name = gr.Dropdown(
                    choices=list(BACKEND_PRESETS.keys()),
                    label="Wybierz preset"
                )
                preset_api_key = gr.Textbox(label="API key (opcjonalnie jesli env ustawiony)", type="password")
                apply_preset_btn = gr.Button("Zastosuj preset")

            preset_out = gr.Textbox(label="Status")

            gr.Markdown("---\n## Wlasny backend")
            with gr.Row():
                cb_type = gr.Dropdown(choices=["mock", "openai_compat", "subprocess"], label="typ")
                cb_base = gr.Textbox(label="base_url (openai_compat)")
                cb_key = gr.Textbox(label="api_key (openai_compat)", type="password")
                cb_model = gr.Textbox(label="model (openai_compat)")
            with gr.Row():
                cb_cmd = gr.Textbox(label='command (subprocess) np. "ollama run llama3.1"')
                cb_arg = gr.Textbox(label='arg (subprocess) np. "-p"')
            apply_custom_btn = gr.Button("Zastosuj wlasny")
            custom_out = gr.Textbox(label="Status")

            # Events
            refresh_btn.click(backend_status_text, outputs=status_box)
            test_btn.click(test_backend, outputs=test_out)
            apply_preset_btn.click(apply_preset, inputs=[preset_name, preset_api_key], outputs=preset_out).then(
                backend_status_text, outputs=status_box
            )
            apply_custom_btn.click(
                apply_custom_backend,
                inputs=[cb_type, cb_base, cb_key, cb_model, cb_cmd, cb_arg],
                outputs=custom_out
            ).then(backend_status_text, outputs=status_box)

        # ----- Personas tab -----
        with gr.Tab("Persony"):
            personas_df = gr.Dataframe(
                value=personas_table(),
                headers=["id", "imie", "specialnosc", "opis (skrocony)"],
                interactive=False,
                wrap=True
            )
            with gr.Accordion("Dodaj persone", open=False):
                with gr.Row():
                    p_name = gr.Textbox(label="Imie")
                    p_specialty = gr.Dropdown(choices=SPECIALTIES, label="Specialnosc")
                p_desc = gr.Textbox(label="Opis (2-3 zdania)", lines=3)
                add_p_btn = gr.Button("Dodaj")
                add_p_out = gr.Textbox(label="Status")
            with gr.Accordion("Usun persone", open=False):
                p_del = gr.Textbox(label="ID do usuniecia")
                del_p_btn = gr.Button("Usun")
                del_p_out = gr.Textbox(label="Status")

            add_p_btn.click(add_persona_ui, inputs=[p_name, p_desc, p_specialty], outputs=[add_p_out, personas_df])
            del_p_btn.click(delete_persona, inputs=p_del, outputs=[del_p_out, personas_df])

        # ----- Questions tab -----
        with gr.Tab("Pytania"):
            with gr.Row():
                q_filter = gr.Dropdown(choices=["all"] + SPECIALTIES, value="all", label="Filtr specialnosci")
                q_refresh = gr.Button("Odswierz")
            questions_df = gr.Dataframe(
                value=questions_table("all"),
                headers=["id", "specialnosc", "autor", "pytanie (skrocone)"],
                interactive=False,
                wrap=True
            )
            with gr.Accordion("Dodaj pytanie recznie", open=False):
                q_text = gr.Textbox(label="Tresc pytania", lines=4)
                with gr.Row():
                    q_spec = gr.Dropdown(choices=SPECIALTIES, label="Specialnosc")
                    q_author = gr.Textbox(label="Autor (ID persony, opcjonalnie)")
                q_crit = gr.Textbox(label='Kryteria jako JSON lista', value='["kryterium 1", "kryterium 2"]')
                add_q_btn = gr.Button("Dodaj")
                add_q_out = gr.Textbox(label="Status")
            with gr.Accordion("Generuj pytanie przez LLM", open=False):
                with gr.Row():
                    g_author = gr.Textbox(label="Autor (persona ID)")
                    g_topic = gr.Textbox(label="Temat")
                    g_target = gr.Dropdown(choices=SPECIALTIES, label="Specialnosc docelowa")
                gen_q_btn = gr.Button("Generuj (wymaga dzialajacego backendu)")
                gen_q_out = gr.Textbox(label="Status")

            q_refresh.click(questions_table, inputs=q_filter, outputs=questions_df)
            add_q_btn.click(add_question_ui, inputs=[q_text, q_spec, q_crit, q_author], outputs=[add_q_out, questions_df])
            gen_q_btn.click(generate_question_ui, inputs=[g_author, g_topic, g_target], outputs=[gen_q_out, questions_df])

        # ----- Run tab -----
        with gr.Tab("Uruchom"):
            with gr.Accordion("Pojedynczy solve", open=True):
                with gr.Row():
                    s_qid = gr.Textbox(label="Question ID (np. q_001)")
                    s_solver = gr.Textbox(label="Solver persona ID")
                solve_btn = gr.Button("Rozwiaz")
                solve_out = gr.Textbox(label="Status", interactive=False)
                solve_solution = gr.Textbox(label="Rozwiazanie", lines=10, interactive=False)

            with gr.Accordion("Pojedynczy judge", open=True):
                with gr.Row():
                    j_cid = gr.Textbox(label="Challenge ID (np. ch_001)")
                    j_judge = gr.Textbox(label="Judge persona ID")
                judge_btn = gr.Button("Ocen")
                judge_out = gr.Textbox(label="Status")
                judge_verdict = gr.Textbox(label="Werdykt JSON", lines=12)

            with gr.Accordion("Auto-batch (pelna runda)", open=True):
                with gr.Row():
                    ab_n = gr.Slider(minimum=3, maximum=21, value=9, step=3, label="Pytan na persone")
                    ab_single = gr.Checkbox(label="Tylko 1 sędzia (tansze)", value=False)
                    ab_seed = gr.Number(label="Seed", value=42, precision=0)
                ab_btn = gr.Button("Uruchom batch")
                ab_out = gr.Textbox(label="Progres / wynik", lines=20)

            solve_btn.click(solve_ui, inputs=[s_qid, s_solver], outputs=[solve_out, solve_solution])
            judge_btn.click(judge_ui, inputs=[j_cid, j_judge], outputs=[judge_out, judge_verdict])
            ab_btn.click(auto_batch_ui, inputs=[ab_n, ab_single, ab_seed], outputs=ab_out)

        # ----- Report tab -----
        with gr.Tab("Raport"):
            rep_btn = gr.Button("Generuj raport")
            rep_text = gr.Textbox(label="Raport", lines=25, interactive=False)
            rep_btn.click(report_text, outputs=rep_text)

            gr.Markdown("## Wszystkie challenges")
            ch_btn = gr.Button("Odswierz tabele")
            ch_df = gr.Dataframe(
                value=challenges_table(),
                headers=["id", "pytanie", "specialnosc", "solver", "kategoria", "status", "oceny", "srednia"],
                interactive=False,
                wrap=True
            )
            ch_btn.click(challenges_table, outputs=ch_df)

        # ----- TTS tab -----
        with gr.Tab("TTS (Głos)"):
            gr.Markdown("## Text-to-Speech\nSynteza mowy z odpowiedzi person.")

            gr.Markdown("### Dostępne głosy")
            voices_data = list_available_voices()
            gr.Dataframe(
                value=[[v["persona"], v["name"], v["gender"], v["edge_voice"], v["description"]] for v in voices_data],
                headers=["Persona", "Nazwa", "Płeć", "Edge Voice", "Opis"],
                interactive=False,
                wrap=True
            )

            gr.Markdown("### Test TTS")
            with gr.Row():
                tts_persona = gr.Dropdown(
                    choices=list(_load_json(PERSONAS_FILE, {}).keys()),
                    label="Persona"
                )
                tts_text = gr.Textbox(label="Tekst do przeczytania", lines=3, value="Cześć, jestem Arek. Specjalizuję się w OSINT.")
            tts_btn = gr.Button("🔊 Syntezuj", variant="primary")
            tts_audio = gr.Audio(label="Wynik audio", type="filepath", interactive=False)
            tts_out = gr.Textbox(label="Status")

            def tts_test(text, persona):
                if not text or not persona:
                    return None, "❌ Podaj tekst i persone"
                try:
                    path = tts_synthesize(text, persona_id=persona)
                    return path, f"✅ Audio: {path}"
                except Exception as e:
                    return None, f"❌ {e}"

            tts_btn.click(tts_test, inputs=[tts_text, tts_persona], outputs=[tts_audio, tts_out])

        # Init check on launch
        if not os.path.exists(PERSONAS_FILE):
            init_store()

    return app


if __name__ == "__main__":
    app = build_ui()
    app.launch(server_name="127.0.0.1", server_port=7860, share=False, inbrowser=True, theme=gr.themes.Soft())
