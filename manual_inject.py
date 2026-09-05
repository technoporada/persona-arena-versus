#!/usr/bin/env python3
"""
manual_inject.py — Ręczne wstrzykiwanie odpowiedzi LLM do systemu.
Używane gdy nie masz API key, ale chcesz testować strukturę.
Wpisz odpowiedź ręcznie (albo skopiuj z czatu z LLM) — system zapisze ją jako challenge.

Usage:
  python manual_inject.py solve --question q_001 --solver arek --answer-file answer.txt
  python manual_inject.py solve --question q_001 --solver arek --answer "Tekst odpowiedzi..."
  python manual_inject.py judge --challenge ch_001 --judge marek --verdict-file verdict.json
  python manual_inject.py vote --question q_001 --persona-a arek --persona-b zuzia --vote A --comment "Arek bardziej konkretny"
"""

import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from persona_arena import (
    _load_json, _save_json,
    PERSONAS_FILE, QUESTIONS_FILE, CHALLENGES_FILE,
    now_iso
)


def manual_solve(question_id, solver_id, answer_text):
    """Inject a pre-written answer as if it came from LLM."""
    questions = _load_json(QUESTIONS_FILE, {})
    if question_id not in questions:
        print(f"ERROR: question {question_id} not found")
        sys.exit(1)
    q = questions[question_id]

    personas = _load_json(PERSONAS_FILE, {})
    if solver_id not in personas:
        print(f"ERROR: persona {solver_id} not found")
        sys.exit(1)
    solver = personas[solver_id]

    from persona_arena import classify_question_for_persona
    classification = classify_question_for_persona(q.get("specialty", ""), solver.get("specialty", ""))

    challenges = _load_json(CHALLENGES_FILE, {})
    cid = f"ch_{len(challenges) + 1:03d}"
    while cid in challenges:
        cid = f"ch_{int(cid.split('_')[1]) + 1:03d}"

    challenges[cid] = {
        "id": cid,
        "question_id": question_id,
        "question_specialty": q.get("specialty"),
        "author_id": q.get("author"),
        "solver_id": solver_id,
        "solver_specialty": solver.get("specialty"),
        "classification": classification,
        "solution": answer_text,
        "verdicts": [],
        "status": "solved",
        "created": now_iso(),
        "source": "manual_inject"
    }
    _save_json(CHALLENGES_FILE, challenges)
    print(f"✅ Challenge {cid} created (manual inject)")
    print(f"   Solver: {solver_id} ({classification} for specialty {q.get('specialty')})")
    print(f"   Answer length: {len(answer_text)} chars")
    return cid


def manual_judge(challenge_id, judge_id, verdict_dict):
    """Inject a pre-written verdict as if it came from LLM."""
    challenges = _load_json(CHALLENGES_FILE, {})
    if challenge_id not in challenges:
        print(f"ERROR: challenge {challenge_id} not found")
        sys.exit(1)

    personas = _load_json(PERSONAS_FILE, {})
    if judge_id not in personas:
        print(f"ERROR: persona {judge_id} not found")
        sys.exit(1)
    judge = personas[judge_id]

    verdict_entry = {
        "judge_id": judge_id,
        "judge_specialty": judge.get("specialty"),
        "ts": now_iso(),
        "criterion_scores": verdict_dict.get("criterion_scores", []),
        "overall_score": verdict_dict.get("overall_score"),
        "verdict": verdict_dict.get("verdict"),
        "reasoning": verdict_dict.get("reasoning", ""),
        "source": "manual_inject"
    }
    challenges[challenge_id].setdefault("verdicts", []).append(verdict_entry)
    challenges[challenge_id]["status"] = "judged"
    _save_json(CHALLENGES_FILE, challenges)
    print(f"✅ Verdict added to {challenge_id}")
    print(f"   Judge: {judge_id}")
    print(f"   Score: {verdict_dict.get('overall_score')}/10 — {verdict_dict.get('verdict')}")


def manual_vote(question_id, persona_a, persona_b, vote, comment=""):
    """Inject a versus vote."""
    from arena_versus import cast_vote
    questions = _load_json(QUESTIONS_FILE, {})
    if question_id not in questions:
        print(f"ERROR: question {question_id} not found")
        sys.exit(1)

    # Puste odpowiedzi — bo to tylko test głosu
    cast_vote(
        question_id=question_id,
        persona_a_id=persona_a,
        persona_b_id=persona_b,
        answer_a="[manual — no answer generated]",
        answer_b="[manual — no answer generated]",
        vote=vote,
        comment=comment
    )
    print(f"✅ Vote recorded: {vote}")
    print(f"   {persona_a} vs {persona_b} on {question_id}")


def main():
    parser = argparse.ArgumentParser(prog="manual_inject")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("solve")
    s.add_argument("--question", required=True)
    s.add_argument("--solver", required=True)
    s.add_argument("--answer", help="Bezposrednio tekst")
    s.add_argument("--answer-file", help="Plik z tekst odpowiedzi")

    j = sub.add_parser("judge")
    j.add_argument("--challenge", required=True)
    j.add_argument("--judge", required=True)
    j.add_argument("--verdict", required=True, help='JSON: {"overall_score": 8, "verdict": "pass", "reasoning": "...", "criterion_scores": []}')

    v = sub.add_parser("vote")
    v.add_argument("--question", required=True)
    v.add_argument("--persona-a", required=True)
    v.add_argument("--persona-b", required=True)
    v.add_argument("--vote", required=True, choices=["A", "B", "tie", "both_bad"])
    v.add_argument("--comment", default="")

    args = parser.parse_args()

    if args.cmd == "solve":
        if args.answer:
            answer = args.answer
        elif args.answer_file:
            with open(args.answer_file, "r", encoding="utf-8") as f:
                answer = f.read()
        else:
            print("ERROR: podaj --answer lub --answer-file")
            sys.exit(1)
        manual_solve(args.question, args.solver, answer)

    elif args.cmd == "judge":
        try:
            v = json.loads(args.verdict)
        except json.JSONDecodeError as e:
            print(f"ERROR: bad JSON: {e}")
            sys.exit(1)
        manual_judge(args.challenge, args.judge, v)

    elif args.cmd == "vote":
        manual_vote(args.question, args.persona_a, args.persona_b, args.vote, args.comment)


if __name__ == "__main__":
    main()
