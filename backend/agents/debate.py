"""Bull vs Bear debate engine (Task 3.4) — the stage the whole project measures.

Structure, bounded at N=2 rounds:

    round 1:  Bull opens                 (sees the specialist reports)
              Bear responds              (sees the reports + Bull's opening)
    round 2:  Bull counters              (sees everything so far)
              Bear closes                (sees everything so far)

Four LLM calls. That is the cost side of the research question, and it is why the
bound exists: an unbounded debate burns the Gemini free-tier quota in an afternoon
and, worse, makes the cost figure a function of how long the models felt like
arguing rather than a property of the architecture.

Two design choices that decide whether this measures anything:

1. EACH SIDE SEES THE SAME EVIDENCE. Bull and Bear both receive all four
   specialist reports, unfiltered. If each side were fed only the evidence
   favouring it, the debate would be theatre — the disagreement would be
   manufactured by the harness rather than discovered in the data.

2. NEITHER SIDE MAY INVENT. The roles instruct both analysts to argue the
   strongest HONEST case. Adversarial prompting is a known hallucination
   amplifier: a model told to win will manufacture the fact that wins. Everything
   they assert is re-checked downstream against the specialist reports, and the
   transcript records who said what, so a fabricated claim is traceable to a turn.

The transcript is returned as text as well as structured turns, because the Risk
Officer reads the argument and the Phase 5 dashboard renders it.
"""
from __future__ import annotations

from typing import Optional

from backend.agents.base import render_reports, run_specialist
from backend.agents.schemas import DebateArgument
from backend.context import MarketContext
from backend.prompts import BEAR_ROLE, BULL_ROLE

_ROLES = {"bull": BULL_ROLE, "bear": BEAR_ROLE}

_OPENING = """You are opening the debate on {ticker} as of {as_of}, over a
{horizon}-session horizon. The last close was {last_close} INR.

Make the strongest honest case for {direction}. Give your distinct arguments in
points, strongest first, and state {target_word} price target in plain INR with
your confidence.

Ground every point in one of the specialist reports below and say which analyst
you are relying on. If the specialists are thin or contradictory, argue from what
is actually there and lower your confidence — a case built on facts you invented
loses the moment the reconciliation gate checks it."""

_REBUTTAL = """You are in round {round_number} of the debate on {ticker} as of
{as_of}. The last close was {last_close} INR.

Read the transcript so far. Your job now is twofold:
  1. rebuttal: answer the other side's strongest point directly. Do not restate
     your opening — engage with what they actually argued. If they made a point
     you cannot answer, concede it; a concession that narrows the disagreement is
     more useful to the Risk Officer than a talking point that ignores it.
  2. points: your remaining case for {direction}, strongest first.

State {target_word} price target in plain INR and your confidence. If the other
side has genuinely moved you, your target and confidence should move too."""


def _turn(
    ctx: MarketContext,
    position: str,
    round_number: int,
    reports_block: str,
    transcript: str,
    *,
    temperature: float,
    nonce: str,
) -> tuple[Optional[DebateArgument], Optional[str]]:
    """One debate turn."""
    direction = "UPSIDE" if position == "bull" else "DOWNSIDE"
    target_word = "an upside" if position == "bull" else "a downside"
    opening = not transcript

    task = (_OPENING if opening else _REBUTTAL).format(
        ticker=ctx.ticker,
        as_of=ctx.as_of,
        horizon=ctx.horizon_sessions,
        last_close=ctx.last_close,
        direction=direction,
        target_word=target_word,
        round_number=round_number,
    )
    task += f"\n\nSet position to \"{position}\" and round_number to {round_number}."

    evidence = f"SPECIALIST REPORTS\n==================\n{reports_block}"
    if transcript:
        evidence += f"\n\nDEBATE SO FAR\n=============\n{transcript}"

    rep, err = run_specialist(
        role=_ROLES[position],
        task=task,
        evidence=evidence,
        schema=DebateArgument,
        as_of=str(ctx.as_of),
        temperature=temperature,
        nonce=nonce,
    )
    if rep is not None:
        # The model is asked for these and usually complies, but the transcript is
        # ordered by them, so they are corrected rather than trusted.
        rep.position = position  # type: ignore[assignment]
        rep.round_number = round_number
    return rep, err


def format_turn(turn: DebateArgument) -> str:
    """Render one turn for the transcript, the synthesiser and the dashboard."""
    head = f"[Round {turn.round_number}] {turn.position.upper()} "
    head += f"(target {turn.target_inr} INR, confidence {turn.confidence:.0%})"
    lines = [head]
    if turn.rebuttal:
        lines.append(f"  Rebuttal: {turn.rebuttal}")
    lines.extend(f"  - {p}" for p in turn.points)
    return "\n".join(lines)


def format_transcript(turns: list[DebateArgument]) -> str:
    return "\n\n".join(format_turn(t) for t in turns)


def run_debate(
    ctx: MarketContext,
    *,
    technical=None,
    fundamental=None,
    sentiment=None,
    macro=None,
    rounds: int = 2,
    temperature: float = 0.0,
    nonce: str = "",
) -> tuple[list[DebateArgument], str, list[str]]:
    """Run the bounded Bull/Bear exchange.

    Returns (turns, transcript, errors). A turn that fails to parse is recorded
    and skipped rather than aborting: a three-turn debate is still a debate, and
    losing the run would cost the whole forecast. The parse failure is counted in
    llm.session_usage() and reaches the report as a metric.
    """
    reports_block = render_reports(technical, fundamental, sentiment, macro)
    turns: list[DebateArgument] = []
    errors: list[str] = []

    for rnd in range(1, rounds + 1):
        for position in ("bull", "bear"):
            transcript = format_transcript(turns)
            turn, err = _turn(
                ctx, position, rnd, reports_block, transcript,
                temperature=temperature, nonce=nonce,
            )
            if turn is None:
                errors.append(f"debate round {rnd} {position}: {err}")
                continue
            turns.append(turn)

    return turns, format_transcript(turns), errors
