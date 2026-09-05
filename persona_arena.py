#!/usr/bin/env python3
"""
persona_arena.py
Arena testowa dla person — persony rozwiazuja pytania wymyslane przez inne persony.

Commands:
  init                                    Inicjalizuj dane (seed personas + questions)
  list-personas                           Pokaz wszystkie persony
  list-questions [--specialty X]          Pokaz pytania (opcjonalnie z filtrem)
  add-persona --name X --desc Y --specialty Z
  add-question --text "..." --specialty S --criteria '["c1","c2"]'
  generate --author P --topic T [--target-specialty S]
                                          Persona generuje nowe pytanie przez LLM
  solve --question Q --solver P           Persona rozwiazuje pytanie
  judge --challenge C --judge P           Persona ocenia rozwiazanie
  auto-batch --per-persona N              Pelna runda: losuje N pytan na persone, rozwiazuje, ocenia
  report                                  Statystyki: macierz persona x specjalnosc
  backend status                          Pokaz aktualny backend
  backend set --type T [opcje]            Ustaw backend (mock/openai_compat/subprocess)
  backend presets                         Pokaz gotowe presety (Groq/Gemini/Ollama)
  export --id X                           Eksportuj challenge do JSON
  show --challenge C                      Pokaz pelny challenge (pytanie + rozwiazanie + oceny)

Examples:
  python persona_arena.py init
  python persona_arena.py backend presets
  python persona_arena.py backend set --type mock
  python persona_arena.py backend set --type openai_compat \\
      --base-url https://api.groq.com/openai/v1 \\
      --api-key gsk_xxx \\
      --model llama-3.3-70b-versatile
  python persona_arena.py backend set --type subprocess --command gemini --arg -p
  python persona_arena.py generate --author arek --topic "metadata EXIF analysis" --target-specialty osint
  python persona_arena.py solve --question q_001 --solver zuzia
  python persona_arena.py judge --challenge ch_001 --judge marek
  python persona_arena.py auto-batch --per-persona 9
  python persona_arena.py report
"""

import os
import sys
import json
import re
import uuid
import random
import argparse
import datetime
import subprocess
from typing import Dict, Any, List

try:
    import requests
except ImportError:
    requests = None  # needed only for HTTP backend

# -----------------------
# Paths
# -----------------------
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
RUNS_DIR = os.path.join(ROOT, "runs")
PERSONAS_FILE = os.path.join(DATA_DIR, "personas.json")
QUESTIONS_FILE = os.path.join(DATA_DIR, "questions.json")
CHALLENGES_FILE = os.path.join(DATA_DIR, "challenges.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(RUNS_DIR, exist_ok=True)

# -----------------------
# Specialties & adjacency
# -----------------------
SPECIALTIES = ["osint", "data_analysis", "critical_thinking", "synthesis", "creative"]

ADJACENCY = {
    "osint": {"data_analysis", "critical_thinking"},
    "data_analysis": {"osint", "critical_thinking", "synthesis"},
    "critical_thinking": {"osint", "data_analysis", "synthesis"},
    "synthesis": {"data_analysis", "critical_thinking", "creative"},
    "creative": {"synthesis"},
}

def classify_question_for_persona(question_specialty: str, persona_specialty: str) -> str:
    """Returns 'in', 'adjacent', or 'cross'."""
    if question_specialty == persona_specialty:
        return "in"
    if question_specialty in ADJACENCY.get(persona_specialty, set()):
        return "adjacent"
    return "cross"


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# -----------------------
# Storage
# -----------------------
def _load_json(path: str, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# -----------------------
# Backends
# -----------------------
class MockBackend:
    """No-LLM backend. Returns a clear marker so user knows to configure something real."""
    def name(self):
        return "mock"

    def generate(self, system, user, max_tokens=2000):
        return (
            "[MOCK BACKEND — no LLM configured]\n"
            f"System prompt (first 200 chars): {system[:200]}\n"
            f"User prompt (first 300 chars): {user[:300]}\n\n"
            "Configure a real backend: python persona_arena.py backend presets"
        )


class OpenAICompatBackend:
    """Works with OpenAI, Groq, OpenRouter, Together, Ollama (OpenAI-compat), vLLM, etc."""
    def __init__(self, base_url, api_key, model):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model = model

    def name(self):
        return f"openai_compat:{self.model}"

    def generate(self, system, user, max_tokens=2000):
        if not requests:
            raise RuntimeError("requests library not installed. pip install requests")
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7
        }
        r = requests.post(url, headers=headers, json=payload, timeout=180)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} from {self.base_url}: {r.text[:500]}")
        data = r.json()
        return data["choices"][0]["message"]["content"]


class SubprocessBackend:
    """Generic CLI backend. Runs: <command> <args> <prompt>. Captures stdout.
    Examples:
      gemini -p "prompt"        -> command=["gemini"], args=["-p"]
      ollama run llama3 "prompt" -> command=["ollama", "run", "llama3"], args=[]
      llm -m gpt-4o "prompt"    -> command=["llm"], args=["-m", "gpt-4o"]
    """
    def __init__(self, command, args=None):
        if isinstance(command, str):
            command = [command]
        self.command = command
        self.args = args or []

    def name(self):
        return f"subprocess:{self.command[0]}"

    def generate(self, system, user, max_tokens=2000):
        full_prompt = f"[SYSTEM]\n{system}\n\n[USER]\n{user}"
        cmd = self.command + self.args + [full_prompt]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=240, encoding='utf-8'
            )
        except FileNotFoundError:
            raise RuntimeError(f"Command not found: {self.command[0]}. Is it installed and on PATH?")
        if result.returncode != 0:
            raise RuntimeError(
                f"Subprocess {self.command[0]} failed (rc={result.returncode}): {result.stderr[:500]}"
            )
        return result.stdout.strip()


def get_backend() -> Any:
    config = _load_json(CONFIG_FILE, {"backend": "mock"})
    backend_type = config.get("backend", "mock")

    if backend_type == "mock":
        return MockBackend()
    elif backend_type == "openai_compat":
        cfg = config.get("openai_compat", {})
        if not cfg.get("base_url") or not cfg.get("model"):
            raise RuntimeError("openai_compat backend requires base_url and model. Run: backend set --type openai_compat ...")
        if not cfg.get("api_key"):
            raise RuntimeError("openai_compat backend requires api_key.")
        return OpenAICompatBackend(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            model=cfg["model"]
        )
    elif backend_type == "subprocess":
        cfg = config.get("subprocess", {})
        if not cfg.get("command"):
            raise RuntimeError("subprocess backend requires command.")
        return SubprocessBackend(command=cfg["command"], args=cfg.get("args", []))
    else:
        raise RuntimeError(f"Unknown backend type: {backend_type}")


# -----------------------
# Presets for free backends
# -----------------------
BACKEND_PRESETS = {
    "groq": {
        "type": "openai_compat",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "env_var": "GROQ_API_KEY",
        "notes": "Darmowy tier. Zaloz konto na console.groq.com, wygeneruj API key."
    },
    "gemini_api": {
        "type": "openai_compat",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.0-flash",
        "env_var": "GEMINI_API_KEY",
        "notes": "Darmowy tier Google AI Studio. Zaloz key na aistudio.google.com."
    },
    "openrouter_free": {
        "type": "openai_compat",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "env_var": "OPENROUTER_API_KEY",
        "notes": "OpenRouter ma kilka darmowych modeli (szukaj ':free' w nazwie)."
    },
    "ollama_local": {
        "type": "subprocess",
        "command": ["ollama", "run", "llama3.1"],
        "notes": "Lokalnie, darmowo. Najpierw: ollama pull llama3.1"
    },
    "gemini_cli": {
        "type": "subprocess",
        "command": ["gemini"],
        "args": ["-p"],
        "notes": "Gemini CLI (npm install -g @google/gemini-cli). Logowanie przez Google account."
    },
}


# -----------------------
# Persona / Question / Challenge accessors
# -----------------------
def get_persona(persona_id: str) -> Dict:
    personas = _load_json(PERSONAS_FILE, {})
    pid = persona_id.lower().replace(" ", "_")
    if pid not in personas:
        raise ValueError(f"Persona '{persona_id}' not found. Available: {list(personas.keys())}")
    return personas[pid]


def get_question(question_id: str) -> Dict:
    questions = _load_json(QUESTIONS_FILE, {})
    if question_id not in questions:
        raise ValueError(f"Question '{question_id}' not found. Available: {list(questions.keys())[:5]}...")
    return questions[question_id]


def get_challenge(challenge_id: str) -> Dict:
    challenges = _load_json(CHALLENGES_FILE, {})
    if challenge_id not in challenges:
        raise ValueError(f"Challenge '{challenge_id}' not found.")
    return challenges[challenge_id]


# -----------------------
# LLM prompts
# -----------------------
def make_system_prompt(persona: Dict) -> str:
    return (
        f"You are {persona['name']}. {persona['description']}\n"
        f"Twoja specjalnosc: {persona.get('specialty', 'general')}.\n"
        f"Stay in character. Mysli po polsku, pisz po polsku. Badz konkretny."
    )


PROMPT_GENERATE_QUESTION = """\
Zaprojektuj TRUDNE pytanie dla innego eksperta do rozwiazania.

Temat: {topic}
Specjalnosc docelowa do przetestowania: {target_specialty}

Pytanie ma:
- testowac prawdziwa wiedze ekspercka, nie trivial facts
- wymagac rozumowania, nie tylko recallu
- miec jasny kierunek poprawnej odpowiedzi (nie czysta opinia)
- byc rozwiazywalne w 200-400 slowach

Odpowiedz TYLKO jako JSON, bez markdown fences:
{{
  "question": "<tresc pytania po polsku>",
  "criteria": ["kryterium 1", "kryterium 2", "kryterium 3"],
  "expected_answer_summary": "<krotki zarys dobrej odpowiedzi>"
}}
"""


PROMPT_SOLVE = """\
Rozwiaz nastepujace pytanie. Pokaz krok po kroku swoje rozumowanie, potem podaj finalna odpowiedz.

PYTANIE:
{question}

Uzyj swojej wiedzy eksperckiej. Jesli czegos nie wiesz, powiedz to wprost — nie zmyzlaj.
"""


PROMPT_JUDGE = """\
Ocen rozwiazanie innego eksperta na zadane pytanie.

PYTANIE:
{question}

ROZWIAZANIE:
{solution}

KRYTERIA OCENY:
{criteria}

Ocen rozwiazanie wzgledem kazdego kryterium. Potem podaj werdykt.

Odpowiedz TYLKO jako JSON, bez markdown fences:
{{
  "criterion_scores": [{{"criterion": "<tresc>", "score": <0-10>, "comment": "<krotki komentarz>"}}],
  "overall_score": <0-10>,
  "verdict": "pass|partial|fail",
  "reasoning": "<2-3 zdania wyjasniajace werdykt>"
}}
"""


# -----------------------
# JSON parsing from LLM output (robust)
# -----------------------
def parse_json_response(text: str) -> Dict:
    """Try multiple strategies to extract JSON from LLM output."""
    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Markdown fenced block
    fence_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. First balanced { ... } block
    brace_match = re.search(r'\{.*\}', text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return {"error": "nie_udalo_sie_sparsowac_json", "oryginalny_tekst": text[:300]}


# -----------------------
# LLM call with audit trail
# -----------------------
def call_llm(persona: Dict, prompt_template: str, **kwargs) -> str:
    backend = get_backend()
    system = make_system_prompt(persona)
    user = prompt_template.format(persona_name=persona["name"], **kwargs)

    run_id = uuid.uuid4().hex
    ts = now_iso()

    try:
        output = backend.generate(system, user)
        success = True
        error = None
    except Exception as e:
        output = ""
        success = False
        error = str(e)

    # Save raw run for audit/reproducibility
    run_path = os.path.join(RUNS_DIR, f"{run_id}.json")
    _save_json(run_path, {
        "id": run_id,
        "ts": ts,
        "backend": backend.name(),
        "persona_id": persona.get("id"),
        "system_prompt": system,
        "user_prompt": user,
        "output": output,
        "success": success,
        "error": error
    })

    if not success:
        raise RuntimeError(f"LLM call failed (run_id={run_id}): {error}")

    return output


# -----------------------
# Core operations
# -----------------------
def init_store(force: bool = False):
    """Initialize data files with seed personas and questions."""
    if not os.path.exists(PERSONAS_FILE) or force:
        _save_json(PERSONAS_FILE, SEED_PERSONAS)
        print(f"Written {len(SEED_PERSONAS)} personas to {PERSONAS_FILE}")
    else:
        print(f"personas.json already exists ({len(_load_json(PERSONAS_FILE))} entries). Use --force to overwrite.")

    if not os.path.exists(QUESTIONS_FILE) or force:
        _save_json(QUESTIONS_FILE, SEED_QUESTIONS)
        print(f"Written {len(SEED_QUESTIONS)} questions to {QUESTIONS_FILE}")
    else:
        print(f"questions.json already exists ({len(_load_json(QUESTIONS_FILE))} entries). Use --force to overwrite.")

    if not os.path.exists(CHALLENGES_FILE) or force:
        _save_json(CHALLENGES_FILE, {})
        print(f"Initialized {CHALLENGES_FILE}")

    if not os.path.exists(CONFIG_FILE) or force:
        _save_json(CONFIG_FILE, {"backend": "mock"})
        print(f"Initialized {CONFIG_FILE} with mock backend")
        print("\n  >>> Configure a real backend: python persona_arena.py backend presets")


def add_persona(name: str, description: str, specialty: str):
    if specialty not in SPECIALTIES:
        raise ValueError(f"Specialty must be one of: {SPECIALTIES}")
    personas = _load_json(PERSONAS_FILE, {})
    pid = name.lower().replace(" ", "_")
    personas[pid] = {
        "id": pid,
        "name": name,
        "description": description,
        "specialty": specialty,
        "created": now_iso()
    }
    _save_json(PERSONAS_FILE, personas)
    print(f"Persona '{name}' saved as '{pid}'.")


def add_question(text: str, specialty: str, criteria: List[str], author: str = "system",
                 expected: str = ""):
    if specialty not in SPECIALTIES:
        raise ValueError(f"Specialty must be one of: {SPECIALTIES}")
    questions = _load_json(QUESTIONS_FILE, {})
    qid = f"q_{len(questions) + 1:03d}"
    while qid in questions:
        qid = f"q_{int(qid.split('_')[1]) + 1:03d}"
    questions[qid] = {
        "id": qid,
        "question": text,
        "specialty": specialty,
        "criteria": criteria,
        "author": author,
        "expected_answer_summary": expected,
        "created": now_iso()
    }
    _save_json(QUESTIONS_FILE, questions)
    print(f"Question saved as '{qid}'.")


def generate_question(author_id: str, topic: str, target_specialty: str) -> str:
    """Persona generates a new question via LLM. Returns new question_id."""
    if target_specialty not in SPECIALTIES:
        raise ValueError(f"target_specialty must be one of: {SPECIALTIES}")
    author = get_persona(author_id)
    print(f"[generate] {author_id} generating question on '{topic}' for specialty '{target_specialty}'...")

    raw = call_llm(
        author,
        PROMPT_GENERATE_QUESTION,
        topic=topic,
        target_specialty=target_specialty
    )
    parsed = parse_json_response(raw)

    if isinstance(parsed, dict) and parsed.get("error"):
        print(f"[generate] !!! LLM nie zwrocil poprawnego JSON (backend nie jest skonfigurowany?).")
        print(f"[generate]     Odpowiedz (pierwsze 100 znakow): {str(parsed.get('oryginalny_tekst', ''))[:100]!r}")
        return None

    required = ["question", "criteria"]
    for k in required:
        if k not in parsed:
            raise ValueError(f"LLM response missing required field '{k}'. Raw:\n{raw[:500]}")

    questions = _load_json(QUESTIONS_FILE, {})
    qid = f"q_{len(questions) + 1:03d}"
    while qid in questions:
        qid = f"q_{int(qid.split('_')[1]) + 1:03d}"

    questions[qid] = {
        "id": qid,
        "question": parsed["question"],
        "specialty": target_specialty,
        "criteria": parsed["criteria"],
        "author": author_id,
        "expected_answer_summary": parsed.get("expected_answer_summary", ""),
        "created": now_iso(),
        "source": "llm_generated"
    }
    _save_json(QUESTIONS_FILE, questions)
    print(f"[generate] New question saved as {qid}:")
    print(f"  Q: {parsed['question'][:150]}...")
    print(f"  Criteria: {len(parsed['criteria'])} items")
    return qid


def solve_question(question_id: str, solver_id: str) -> str:
    """Persona solves a question. Returns challenge_id."""
    question = get_question(question_id)
    solver = get_persona(solver_id)

    print(f"[solve] {solver_id} solving {question_id}...")
    solution = call_llm(
        solver,
        PROMPT_SOLVE,
        question=question["question"]
    )

    challenges = _load_json(CHALLENGES_FILE, {})
    cid = f"ch_{len(challenges) + 1:03d}"
    while cid in challenges:
        cid = f"ch_{int(cid.split('_')[1]) + 1:03d}"

    challenges[cid] = {
        "id": cid,
        "question_id": question_id,
        "question_specialty": question.get("specialty"),
        "author_id": question.get("author"),
        "solver_id": solver_id,
        "solver_specialty": solver.get("specialty"),
        "classification": classify_question_for_persona(
            question.get("specialty", ""),
            solver.get("specialty", "")
        ),
        "solution": solution,
        "verdicts": [],
        "status": "solved",
        "created": now_iso()
    }
    _save_json(CHALLENGES_FILE, challenges)
    print(f"[solve] Challenge {cid} created (status: solved, pending judging).")
    return cid


def judge_challenge(challenge_id: str, judge_id: str) -> Dict:
    """Persona judges a challenge. Returns the verdict dict."""
    challenge = get_challenge(challenge_id)
    question = get_question(challenge["question_id"])
    judge = get_persona(judge_id)

    if challenge.get("status") not in ("solved", "judged"):
        raise RuntimeError(f"Challenge {challenge_id} status is '{challenge.get('status')}', cannot judge.")

    print(f"[judge] {judge_id} judging {challenge_id}...")
    criteria_str = "\n".join(f"- {c}" for c in question.get("criteria", []))
    raw = call_llm(
        judge,
        PROMPT_JUDGE,
        question=question["question"],
        solution=challenge["solution"],
        criteria=criteria_str
    )
    verdict = parse_json_response(raw)

    challenges = _load_json(CHALLENGES_FILE, {})
    challenges[challenge_id].setdefault("verdicts", []).append({
        "judge_id": judge_id,
        "judge_specialty": judge.get("specialty"),
        "ts": now_iso(),
        "criterion_scores": verdict.get("criterion_scores", []),
        "overall_score": verdict.get("overall_score"),
        "verdict": verdict.get("verdict"),
        "reasoning": verdict.get("reasoning", "")
    })
    challenges[challenge_id]["status"] = "judged"
    _save_json(CHALLENGES_FILE, challenges)

    print(f"[judge] Verdict: {verdict.get('verdict')} (score: {verdict.get('overall_score')})")
    return verdict


def auto_batch(per_persona: int, seed: int = 42):
    """Run a full round: pick N questions per persona, solve all, judge all."""
    personas = _load_json(PERSONAS_FILE, {})
    questions = _load_json(QUESTIONS_FILE, {})
    _load_json(CHALLENGES_FILE, {})

    if not personas:
        raise RuntimeError("No personas. Run: init")
    if not questions:
        raise RuntimeError("No questions. Run: init or add-question")

    # Group question IDs by specialty
    by_specialty: Dict[str, List[str]] = {}
    for qid, q in questions.items():
        by_specialty.setdefault(q.get("specialty", ""), []).append(qid)

    # Distribution: 1/3 in, 1/3 adjacent, 1/3 cross
    n_in = max(1, per_persona // 3)
    n_adj = max(1, per_persona // 3)
    n_cross = max(0, per_persona - n_in - n_adj)

    random.seed(seed)

    plan: List[Dict] = []
    for pid, persona in personas.items():
        p_specialty = persona.get("specialty", "")

        in_qs = by_specialty.get(p_specialty, [])
        adj_specialties = ADJACENCY.get(p_specialty, set())
        adj_qs = []
        for s in adj_specialties:
            adj_qs.extend(by_specialty.get(s, []))
        cross_specialties = set(SPECIALTIES) - {p_specialty} - adj_specialties
        cross_qs = []
        for s in cross_specialties:
            cross_qs.extend(by_specialty.get(s, []))

        picked_in = random.sample(in_qs, min(n_in, len(in_qs)))
        picked_adj = random.sample(adj_qs, min(n_adj, len(adj_qs)))
        picked_cross = random.sample(cross_qs, min(n_cross, len(cross_qs)))

        for qid in picked_in + picked_adj + picked_cross:
            plan.append({"solver_id": pid, "question_id": qid, "category": "in" if qid in picked_in else ("adjacent" if qid in picked_adj else "cross")})

    print("\n=== AUTO-BATCH PLAN ===")
    print(f"Personas: {len(personas)}")
    print(f"Planned solves: {len(plan)} (target {per_persona} per persona)")
    print(f"Distribution per persona: in={n_in}, adjacent={n_adj}, cross={n_cross}")
    print("Each solve judged by: author of question + 1 neutral persona")
    print()

    solved = 0
    judged = 0
    for i, item in enumerate(plan, 1):
        print(f"\n[{i}/{len(plan)}] {item['solver_id']} ({item['category']}) <- {item['question_id']}")
        try:
            ch_id = solve_question(item["question_id"], item["solver_id"])
            solved += 1

            # Judge 1: author of the question (if known and different from solver)
            q = get_question(item["question_id"])
            author_id = q.get("author")
            if author_id and author_id != item["solver_id"] and author_id in personas:
                try:
                    judge_challenge(ch_id, author_id)
                    judged += 1
                except Exception as e:
                    print(f"  [warn] author judge failed: {e}")

            # Judge 2: neutral persona (different from solver and author)
            candidates = [p for p in personas.keys()
                          if p != item["solver_id"] and p != author_id]
            if candidates:
                neutral = random.choice(candidates)
                try:
                    judge_challenge(ch_id, neutral)
                    judged += 1
                except Exception as e:
                    print(f"  [warn] neutral judge failed: {e}")
        except Exception as e:
            print(f"  [error] solve failed: {e}")

    print("\n=== BATCH COMPLETE ===")
    print(f"Solved: {solved}/{len(plan)}")
    print(f"Judged: {judged}")
    print("Run: python persona_arena.py report")


def report():
    """Print the persona x specialty matrix + verdict counts."""
    personas = _load_json(PERSONAS_FILE, {})
    questions = _load_json(QUESTIONS_FILE, {})
    challenges = _load_json(CHALLENGES_FILE, {})

    # matrix[solver_id][specialty] = list of scores (averaged across all verdicts per challenge)
    matrix: Dict[str, Dict[str, List[float]]] = {
        pid: {s: [] for s in SPECIALTIES} for pid in personas
    }
    verdict_counts: Dict[str, Dict[str, int]] = {
        pid: {"pass": 0, "partial": 0, "fail": 0} for pid in personas
    }

    for ch in challenges.values():
        if ch.get("status") != "judged":
            continue
        solver = ch.get("solver_id")
        q = questions.get(ch.get("question_id"), {})
        specialty = q.get("specialty")
        if not solver or not specialty or solver not in matrix:
            continue

        for v in ch.get("verdicts", []):
            score = v.get("overall_score")
            if isinstance(score, (int, float)):
                matrix[solver][specialty].append(float(score))
            vd = v.get("verdict")
            if vd in verdict_counts[solver]:
                verdict_counts[solver][vd] += 1

    print("\n=== PERSONA ARENA REPORT ===\n")
    print("Macierz srednich ocen (im wyzej tym lepiej, skala 0-10):\n")

    header = f"{'Persona':<14}" + "".join(f"{s[:12]:<14}" for s in SPECIALTIES)
    print(header)
    print("-" * len(header))

    for pid in personas:
        row = f"{pid[:13]:<14}"
        for s in SPECIALTIES:
            scores = matrix[pid][s]
            if scores:
                avg = sum(scores) / len(scores)
                row += f"{avg:.1f} (n={len(scores)})".ljust(14)
            else:
                row += "-".ljust(14)
        print(row)

    print("\nWerdykty:\n")
    for pid, counts in verdict_counts.items():
        total = sum(counts.values())
        print(f"  {pid:<14} pass={counts['pass']:<3} partial={counts['partial']:<3} fail={counts['fail']:<3} (total: {total})")

    print(f"\nLacznie challenges: {len(challenges)} (judged: {sum(1 for c in challenges.values() if c.get('status') == 'judged')})")
    print(f"Pytania w bazie: {len(questions)}")
    print(f"Persony: {len(personas)}")


# -----------------------
# CLI
# -----------------------
def cmd_backend(args):
    if args.action == "status":
        config = _load_json(CONFIG_FILE, {"backend": "mock"})
        print(f"Current backend: {config.get('backend', 'mock')}")
        if config.get("backend") == "openai_compat":
            cfg = config.get("openai_compat", {})
            print(f"  base_url: {cfg.get('base_url')}")
            print(f"  model: {cfg.get('model')}")
            print(f"  api_key: {'***' + cfg.get('api_key', '')[-4:] if cfg.get('api_key') else '(not set)'}")
        elif config.get("backend") == "subprocess":
            cfg = config.get("subprocess", {})
            print(f"  command: {cfg.get('command')}")
            print(f"  args: {cfg.get('args', [])}")
        # Test it
        try:
            b = get_backend()
            print(f"  Active: {b.name()}")
        except Exception as e:
            print(f"  [error] {e}")

    elif args.action == "set":
        config = _load_json(CONFIG_FILE, {"backend": "mock"})
        if args.type == "mock":
            config["backend"] = "mock"
        elif args.type == "openai_compat":
            if not args.base_url or not args.model:
                raise SystemExit("openai_compat requires --base-url and --model")
            api_key = args.api_key or os.environ.get("API_KEY") or os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise SystemExit("openai_compat requires --api-key (or API_KEY env var)")
            config["backend"] = "openai_compat"
            config["openai_compat"] = {
                "base_url": args.base_url,
                "api_key": api_key,
                "model": args.model
            }
        elif args.type == "subprocess":
            if not args.command:
                raise SystemExit("subprocess requires --command")
            cmd = args.command.split() if isinstance(args.command, str) else args.command
            arg_list = args.arg.split() if args.arg else []
            config["backend"] = "subprocess"
            config["subprocess"] = {"command": cmd, "args": arg_list}
        else:
            raise SystemExit(f"Unknown backend type: {args.type}")
        _save_json(CONFIG_FILE, config)
        print(f"Backend set to: {config['backend']}")
        print("Test with: python persona_arena.py backend status")

    elif args.action == "presets":
        print("\n=== BACKEND PRESETS (darmowe) ===\n")
        for name, p in BACKEND_PRESETS.items():
            print(f"[{name}] type={p['type']}")
            if p['type'] == 'openai_compat':
                print(f"  base_url: {p['base_url']}")
                print(f"  model:    {p['model']}")
                print(f"  api_key:  ${{{p.get('env_var', 'API_KEY')}}} (env var)")
                print("  Setup:    python persona_arena.py backend set --type openai_compat \\")
                print(f"              --base-url {p['base_url']} \\")
                print(f"              --model {p['model']} \\")
                print(f"              --api-key ${{{p.get('env_var', 'API_KEY')}}}")
            else:
                print(f"  command: {p.get('command')} {(' '.join(p.get('args', []))).strip()}")
                print("  Setup:    python persona_arena.py backend set --type subprocess \\")
                cmd_str = ' '.join(p.get('command', []))
                args_str = ' '.join(p.get('args', []))
                if args_str:
                    print(f"              --command \"{cmd_str}\" --arg \"{args_str}\"")
                else:
                    print(f"              --command \"{cmd_str}\"")
            print(f"  Notes:    {p.get('notes', '')}")
            print()

    elif args.action == "preset":
        """Apply a named preset. Reads API key from env var."""
        if args.preset_name not in BACKEND_PRESETS:
            raise SystemExit(f"Unknown preset. Available: {list(BACKEND_PRESETS.keys())}")
        p = BACKEND_PRESETS[args.preset_name]
        config = _load_json(CONFIG_FILE, {"backend": "mock"})
        if p["type"] == "openai_compat":
            env_var = p.get("env_var", "API_KEY")
            api_key = os.environ.get(env_var)
            if not api_key:
                raise SystemExit(f"Preset '{args.preset_name}' requires env var ${env_var}. Set it and retry.")
            config["backend"] = "openai_compat"
            config["openai_compat"] = {
                "base_url": p["base_url"],
                "api_key": api_key,
                "model": p["model"]
            }
        else:
            config["backend"] = "subprocess"
            config["subprocess"] = {
                "command": p.get("command"),
                "args": p.get("args", [])
            }
        _save_json(CONFIG_FILE, config)
        print(f"Backend set to preset '{args.preset_name}' -> {config['backend']}")
    else:
        print("Usage: backend {status|set|presets|preset --preset-name X}")


def cmd_init(args):
    init_store(force=args.force)


def cmd_list_personas(args):
    personas = _load_json(PERSONAS_FILE, {})
    if not personas:
        print("No personas. Run: init")
        return
    print(f"\n=== PERSONAS ({len(personas)}) ===\n")
    for pid, p in personas.items():
        print(f"[{pid}] {p.get('name')} (specialty: {p.get('specialty')})")
        print(f"  {p.get('description', '')[:200]}")
        print()


def cmd_list_questions(args):
    questions = _load_json(QUESTIONS_FILE, {})
    if not questions:
        print("No questions. Run: init or add-question")
        return
    filtered = questions
    if args.specialty:
        if args.specialty not in SPECIALTIES:
            raise SystemExit(f"Specialty must be one of: {SPECIALTIES}")
        filtered = {k: v for k, v in questions.items() if v.get("specialty") == args.specialty}
    print(f"\n=== QUESTIONS ({len(filtered)} of {len(questions)}) ===\n")
    for qid, q in filtered.items():
        print(f"[{qid}] specialty={q.get('specialty')} author={q.get('author', 'system')}")
        print(f"  Q: {q.get('question', '')[:200]}...")
        if q.get('criteria'):
            print(f"  Criteria: {len(q['criteria'])} items")
        print()


def cmd_add_persona(args):
    add_persona(args.name, args.desc, args.specialty)


def cmd_add_question(args):
    try:
        criteria = json.loads(args.criteria)
        if not isinstance(criteria, list):
            raise ValueError("criteria must be a JSON list")
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid --criteria JSON: {e}")
    add_question(args.text, args.specialty, criteria, author=args.author or "system")


def cmd_generate(args):
    qid = generate_question(args.author, args.topic, args.target_specialty)
    if qid is None:
        print("\n[!] Nie wygenerowano pytania (LLM nie zwrocil poprawnego JSON).")
        print("    Skonfiguruj backend: python persona_arena.py backend --list / --set")
        return
    print(f"\nGenerated question: {qid}")


def cmd_solve(args):
    cid = solve_question(args.question, args.solver)
    print(f"\nChallenge created: {cid}")
    print(f"View: python persona_arena.py show --challenge {cid}")


def cmd_judge(args):
    judge_challenge(args.challenge, args.judge)


def cmd_auto_batch(args):
    auto_batch(per_persona=args.per_persona, seed=args.seed)


def cmd_report(args):
    report()


def cmd_show(args):
    challenges = _load_json(CHALLENGES_FILE, {})
    questions = _load_json(QUESTIONS_FILE, {})
    if args.challenge not in challenges:
        raise SystemExit(f"Challenge '{args.challenge}' not found. Available: {list(challenges.keys())[:5]}")
    ch = challenges[args.challenge]
    q = questions.get(ch.get("question_id"), {})
    print(f"\n=== CHALLENGE {ch['id']} ===")
    print(f"Question: {ch.get('question_id')} (specialty: {q.get('specialty')})")
    print(f"Author:   {ch.get('author_id')}")
    print(f"Solver:   {ch.get('solver_id')} (specialty: {ch.get('solver_specialty')})")
    print(f"Classification for solver: {ch.get('classification')}")
    print(f"Status:   {ch.get('status')}")
    print(f"Created:  {ch.get('created')}")
    print(f"\n--- QUESTION ---\n{q.get('question', '')}")
    print(f"\n--- SOLUTION ---\n{ch.get('solution', '')}")
    if ch.get("verdicts"):
        for i, v in enumerate(ch["verdicts"], 1):
            print(f"\n--- VERDICT {i} (judge: {v.get('judge_id')}) ---")
            print(f"Overall: {v.get('overall_score')} / 10 — verdict: {v.get('verdict')}")
            print(f"Reasoning: {v.get('reasoning')}")
            for cs in v.get("criterion_scores", []):
                print(f"  - [{cs.get('score')}/10] {cs.get('criterion')} — {cs.get('comment', '')}")
    else:
        print("\n(no verdicts yet)")


def cmd_export(args):
    """Export a challenge as JSON to stdout."""
    challenges = _load_json(CHALLENGES_FILE, {})
    if args.id not in challenges:
        raise SystemExit(f"Challenge '{args.id}' not found.")
    print(json.dumps(challenges[args.id], ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(
        prog="persona_arena",
        description="Arena testowa dla person — persony rozwiazuja pytania innych person.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd")

    # init
    p = sub.add_parser("init", help="Inicjalizuj dane")
    p.add_argument("--force", action="store_true", help="Nadpisz istniejace pliki")

    # list-personas
    sub.add_parser("list-personas", help="Pokaz persony")

    # list-questions
    p = sub.add_parser("list-questions", help="Pokaz pytania")
    p.add_argument("--specialty", choices=SPECIALTIES, help="Filtruj po specjalnosci")

    # add-persona
    p = sub.add_parser("add-persona", help="Dodaj persone")
    p.add_argument("--name", required=True)
    p.add_argument("--desc", required=True)
    p.add_argument("--specialty", required=True, choices=SPECIALTIES)

    # add-question
    p = sub.add_parser("add-question", help="Dodaj pytanie")
    p.add_argument("--text", required=True)
    p.add_argument("--specialty", required=True, choices=SPECIALTIES)
    p.add_argument("--criteria", required=True, help='JSON list: ["c1","c2"]')
    p.add_argument("--author", default=None)

    # generate
    p = sub.add_parser("generate", help="Persona generuje pytanie przez LLM")
    p.add_argument("--author", required=True, help="Persona autor (np. arek)")
    p.add_argument("--topic", required=True, help="Temat pytania")
    p.add_argument("--target-specialty", required=True, choices=SPECIALTIES, help="Specjalnosc docelowa")

    # solve
    p = sub.add_parser("solve", help="Persona rozwiazuje pytanie")
    p.add_argument("--question", required=True, help="Question ID (np. q_001)")
    p.add_argument("--solver", required=True, help="Persona solver (np. zuzia)")

    # judge
    p = sub.add_parser("judge", help="Persona ocenia rozwiazanie")
    p.add_argument("--challenge", required=True, help="Challenge ID (np. ch_001)")
    p.add_argument("--judge", required=True, help="Persona judge")

    # auto-batch
    p = sub.add_parser("auto-batch", help="Pelna runda testow")
    p.add_argument("--per-persona", type=int, default=9, help="Ile pytan na persone (default: 9)")
    p.add_argument("--seed", type=int, default=42, help="Random seed")

    # report
    sub.add_parser("report", help="Statystyki")

    # show
    p = sub.add_parser("show", help="Pokaz pelny challenge")
    p.add_argument("--challenge", required=True)

    # export
    p = sub.add_parser("export", help="Eksportuj challenge do JSON")
    p.add_argument("--id", required=True)

    # backend
    p = sub.add_parser("backend", help="Zarzadzaj backendem LLM")
    p.add_argument("action", choices=["status", "set", "presets", "preset"])
    p.add_argument("--type", choices=["mock", "openai_compat", "subprocess"])
    p.add_argument("--base-url")
    p.add_argument("--api-key")
    p.add_argument("--model")
    p.add_argument("--command", help='Komenda jako string, np. "ollama run llama3.1"')
    p.add_argument("--arg", help='Dodatkowe argumenty, np. "-p"')
    p.add_argument("--preset-name", help="Nazwa presetu (groq/gemini_api/openrouter_free/ollama_local/gemini_cli)")

    args = parser.parse_args()

    handlers = {
        "init": cmd_init,
        "list-personas": cmd_list_personas,
        "list-questions": cmd_list_questions,
        "add-persona": cmd_add_persona,
        "add-question": cmd_add_question,
        "generate": cmd_generate,
        "solve": cmd_solve,
        "judge": cmd_judge,
        "auto-batch": cmd_auto_batch,
        "report": cmd_report,
        "show": cmd_show,
        "export": cmd_export,
        "backend": cmd_backend,
    }

    if args.cmd is None:
        parser.print_help()
        sys.exit(0)

    try:
        handlers[args.cmd](args)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)


# -----------------------
# Seed data
# -----------------------
SEED_PERSONAS = {
    "arek": {
        "id": "arek",
        "name": "Arek",
        "description": "Specjalista OSINT, detektyw cyfrowy. Praktyczny, konkretowy, bez retoryki. Szuka dowodow, nie teorii. Jezyk: metadane, logi, sygnaly, timestamps.",
        "specialty": "osint",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "zuzia": {
        "id": "zuzia",
        "name": "Zuzia",
        "description": "Analityk danych. Mysli liczbami, sceptyczna wobec spekulacji. Zawsze pyta 'skad te dane?' i 'jaki jest N?'. Jezyk: korelacje, rozklady, outlier-y, p-value.",
        "specialty": "data_analysis",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "marek": {
        "id": "marek",
        "name": "Marek",
        "description": "Skeptyk. Szuka dziur w rozumowaniu. Zawsze pyta 'a co jesli odwrotnie?' i 'jak mozna to sfalszowac?'. Lubi adversarial argumenty.",
        "specialty": "critical_thinking",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "irena": {
        "id": "irena",
        "name": "Irena",
        "description": "Syntetyzator. Bierze rozproszone fakty i tworzy koherentna historie. Tlumaczy trudne na proste. Jezyk: narracje, podsumowania, rekomendacje.",
        "specialty": "synthesis",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "kuba": {
        "id": "kuba",
        "name": "Kuba",
        "description": "Kreatywny myslitel. Lateral thinking, wychodzi poza schemat. Czasem genialny, czasem dziwaczny. Szuka nietypowych polaczen.",
        "specialty": "creative",
        "created": "2026-07-18T00:00:00+00:00"
    }
}

SEED_QUESTIONS = {
    "q_001": {
        "id": "q_001",
        "question": "Masz zdjecie JPG z kompletnie wyzerowanym EXIFem. Jak ustalic, czy bylo obrabiane w Lightroomie czy w GIMP-ie, majac tylko ten jeden plik? Wymien co najmniej 3 techniki.",
        "specialty": "osint",
        "criteria": [
            "Wspomni o analizie maker notes w EXIF",
            "Wspomni o JPEG ghosts / quality estimators",
            "Nie polega wylacznie na polu software w EXIF",
            "Zaproponuje wiecej niz jedna metode"
        ],
        "author": "system",
        "expected_answer_summary": "Maker notes analysis, JPEG quality estimation, ghost artifacts, color profile hints",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "q_002": {
        "id": "q_002",
        "question": "Masz logi aktywnosci uzytkownikow na kanale Telegram (1000 wiadomości). Jak wykryc, czy czesc wiadomosci jest postowana przez bota, nie majac dostepu do API? Opisz metodyke krok po kroku.",
        "specialty": "osint",
        "criteria": [
            "Wspomni o analizie interwalow czasowych",
            "Wspomni o regularnosci wzorca postingowego",
            "Zaproponuje analize jezyka/leksykonu",
            "Nie polega wylacznie na metadanych technicznych"
        ],
        "author": "system",
        "expected_answer_summary": "Time clustering, lexicostatistics, metadata consistency, behavioral fingerprinting",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "q_003": {
        "id": "q_003",
        "question": "Masz liste 50 adresow email. Jak ustalic, ktore naleza do tej samej osoby, nie wysylajac zadnej wiadomosci? Opisz techniki korelacji.",
        "specialty": "osint",
        "criteria": [
            "Wspomni o Gravatar / avatar hash",
            "Wspomni o HaveIBeenPwned / breach correlation",
            "Wspomni o reuse username na roznych platformach",
            "Zachowa legalnosc (nie phishing)"
        ],
        "author": "system",
        "expected_answer_summary": "Gravatar MD5, breach DBs, username reuse, PGP keyservers, social media fingerprinting",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "q_004": {
        "id": "q_004",
        "question": "Masz plik CSV z 100k rekordow sprzedazy. Jedna kolumna to 'revenue' i masz 5 outlierow >3 sigma. Opisz procedure: jak zdecydowac, czy to blad, czy realne duze zamowienie? Podaj konkretne testy.",
        "specialty": "data_analysis",
        "criteria": [
            "Rozroznia detekcje anomalii od czyszczenia danych",
            "Wspomni o IQR / modified Z-score",
            "Zaproponuje sprawdzenie source data (oryginal zamowienia)",
            "Nie usuwa outlierow bez analizy przyczyny"
        ],
        "author": "system",
        "expected_answer_summary": "Modified Z-score, IQR, source verification, business context, never blind-removal",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "q_005": {
        "id": "q_005",
        "question": "Dwie kampanie marketingowe A i B mialy odpowiednio 3% i 3.5% CTR. Roznica jest statystycznie istotna? Jakie pytania musisz zadac, zanim podasz odpowiedz?",
        "specialty": "data_analysis",
        "criteria": [
            "Wspomni o wielkosci proby (N)",
            "Wspomni o confidence interval",
            "Rozroznia practical vs statistical significance",
            "Zada pytanie o baseline / seasonality"
        ],
        "author": "system",
        "expected_answer_summary": "Need N, CI, multiple testing correction, practical significance vs statistical",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "q_006": {
        "id": "q_006",
        "question": "Masz dwie time series: aktywnosc na forum i aktywnosc na Twitterze tej samej osoby. Korelacja Pearson = 0.85. Czy to znaczy, ze Twitter powoduje aktywnosc na forum? Wytlumacz.",
        "specialty": "data_analysis",
        "criteria": [
            "Cytuje 'correlation != causation'",
            "Wspomni o common cause / confounder",
            "Zaproponuje lag analysis / Granger",
            "Nie ufa samej korelacji Pearson"
        ],
        "author": "system",
        "expected_answer_summary": "Confounding, lag analysis, Granger causality, spurious correlation",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "q_007": {
        "id": "q_007",
        "question": "Artykul twierdzi: 'Osoby pijace czerwone wino zyja dluzszej. Wino wydluza zycie.' Wypunktuj co najmniej 4 alternatywne wyjasnienia, ktore podwazaja ten wniosek.",
        "specialty": "critical_thinking",
        "criteria": [
            "Wspomni o confounder (dochod, styl zycia)",
            "Wspomni o selection bias",
            "Wspomni o reverse causation",
            "Zaproponuje wiecej niz 3 alternatywy"
        ],
        "author": "system",
        "expected_answer_summary": "Confounding (income, diet, exercise), selection bias, reverse causation, publication bias",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "q_008": {
        "id": "q_008",
        "question": "Badacz podal wynik 'p < 0.05 wiec skuteczne'. Wymien co najmniej 4 problemy z tym wnioskiem, nie wdajac sie w szczegoly konkretnego badania.",
        "specialty": "critical_thinking",
        "criteria": [
            "Wspomni o problemie multiple testing",
            "Wspomni o effect size vs significance",
            "Wspomni o p-hacking",
            "Wspomni o reproducibility crisis"
        ],
        "author": "system",
        "expected_answer_summary": "Multiple testing, effect size, p-hacking, preregistration, reproducibility",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "q_009": {
        "id": "q_009",
        "question": "Ktos mowi: 'Mam 99% accuracy na moim modelu detekcji fraudow, wiec model jest dobry.' Wymien co najmniej 3 powody, dla ktorych to nie musi byc prawda.",
        "specialty": "critical_thinking",
        "criteria": [
            "Wspomni o class imbalance",
            "Wspomni o precision/recall tradeoff",
            "Wspomni o data leakage",
            "Nie ufa accuracy jako jedynej metryce"
        ],
        "author": "system",
        "expected_answer_summary": "Imbalanced classes, precision/recall, F1, ROC-AUC, data leakage, base rate fallacy",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "q_010": {
        "id": "q_010",
        "question": "Przeczytales 3 raporty techniczne o tym samym incydencie bezpieczenstwa. Kazdy mowi co innego. Opisz procedure, jak zbudowac z nich jedna koherentna relacje bez utraty informacji.",
        "specialty": "synthesis",
        "criteria": [
            "Zaproponuje matrix: fakty vs zrodla",
            "Rozroznia fakty od interpretacji",
            "Wspomni o waznosci zrodel (primary vs secondary)",
            "Zaproponuje timeline jako narzedzie"
        ],
        "author": "system",
        "expected_answer_summary": "Fact-source matrix, primary vs secondary sources, timeline, uncertainty labeling",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "q_011": {
        "id": "q_011",
        "question": "Masz 100stronicowy raport techniczny po angielsku. Twoj szef chce 1-akapitowe podsumowanie w jezyku polskim. Opisz procedure: jak zdecydowac, co wylaczyc, a co zostawic.",
        "specialty": "synthesis",
        "criteria": [
            "Wspomni o hierarchii informacji (pyramid principle)",
            "Rozroznia wnioski od danych",
            "Wspomni o audience-aware communication",
            "Nie polega wylacznie na extractive summarization"
        ],
        "author": "system",
        "expected_answer_summary": "Pyramid principle, audience analysis, abstractive summary, key findings first",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "q_012": {
        "id": "q_012",
        "question": "Opisz sytuacje, w ktorej trzeba przedstawic kontrowersyjny wniosek grupie interesariuszy o sprzecznych interesach. Jak strukturyzujesz argumenty?",
        "specialty": "synthesis",
        "criteria": [
            "Wspomni o steelmanning przeciwnych stron",
            "Zaproponuje strukture: dane -> wnioski -> rekomendacje",
            "Wspomni o eksplisitnym uncertainty",
            "Unika emotional appeal"
        ],
        "author": "system",
        "expected_answer_summary": "Steelmanning, fact-recommendation structure, uncertainty labeling, stakeholder-aware framing",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "q_013": {
        "id": "q_013",
        "question": "Wymysl nietypowy sposob na wykrycie botow na Telegramie, ktory NIE opiera sie na analizie tekstu ani metadanych technicznych. Moze byc absurdalny, ale musi miec rationale.",
        "specialty": "creative",
        "criteria": [
            "Rozwiazuje problem nietypowym kanalem",
            "Ma racjonalne uzasadnienie",
            "Nie powtarza standardowych technik",
            "Pokazuje lateral thinking"
        ],
        "author": "system",
        "expected_answer_summary": "Behavioral fingerprinting through unusual signals: emoji reactions timing, reply patterns to specific message types, etc.",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "q_014": {
        "id": "q_014",
        "question": "Jakby wygladalo 'muzeum zapomnianego internetu'? Wymysl koncepcje, ktora nie jest zwykla archiwizacja, ale mialaby realna wartosc dla badaczy.",
        "specialty": "creative",
        "criteria": [
            "Nie jest zwykla kopia archive.org",
            "Ma oryginalna koncepcje kuratorska",
            "Adresuje konkretne potrzeby badawcze",
            "Pokazuje myslenie poza schematem"
        ],
        "author": "system",
        "expected_answer_summary": "Curated dead-web exhibitions, contextual preservation, link-graph forensics, lost-design archive",
        "created": "2026-07-18T00:00:00+00:00"
    },
    "q_015": {
        "id": "q_015",
        "question": "Wymysl gre, ktora uczy krytycznego myslenia o zrodlach online. Gra ma miec realna mechanike, nie byc quizem.",
        "specialty": "creative",
        "criteria": [
            "Nie jest quizem ani flashcard",
            "Ma konkretna mechanike rozgrywki",
            "Realnie trenuje source evaluation",
            "Moze byc zaimplementowana"
        ],
        "author": "system",
        "expected_answer_summary": "Investigation game with conflicting sources, credibility scoring, deception mechanics",
        "created": "2026-07-18T00:00:00+00:00"
    }
}


if __name__ == "__main__":
    main()
