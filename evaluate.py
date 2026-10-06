"""Score how well the bot understands a labelled set: python evaluate.py [eval/cases.yaml]

Each case is typed text or a voice note plus the expected outcome (a unit id, or "clarify"). Voice notes go
through the same STT as the live bot. Prints every case, then accuracy against each confidence threshold
so STT_CONFIRM_BELOW (app.py) and ANSWER_THRESHOLD (brain.py) are set from data. Writes data/eval_report.csv.
"""
import csv
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

import app
import brain
import speech

STT_SWEEP = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95)
ANSWER_SWEEP = (0.3, 0.4, 0.5, 0.6, 0.7)


def run_case(case):
    if "audio" in case:
        transcript, conf = speech.transcribe((app.ROOT / case["audio"]).read_bytes())
    else:
        transcript, conf = case["text"], 1.0
    action, unit, ranked = app.content.decide(transcript)
    scores = [s for _, s in ranked] + [0.0, 0.0]
    predicted = unit["id"] if unit else action
    return {"source": case.get("audio", "text"), "note": case.get("note", ""), "expect": case["expect"],
            "predicted": predicted, "ok": predicted == case["expect"], "stt_conf": round(conf, 3),
            "top_unit": ranked[0][0]["id"] if ranked else "", "top": round(scores[0], 3), "margin": round(scores[0] - scores[1], 3), "transcript": transcript}


def main():
    load_dotenv(app.ROOT / ".env")
    cases = yaml.safe_load(Path(sys.argv[1] if len(sys.argv) > 1 else app.ROOT / "eval" / "cases.yaml").read_text(encoding="utf-8"))
    missing = [c["audio"] for c in cases if "audio" in c and not (app.ROOT / c["audio"]).exists()]
    rows = [run_case(c) for c in cases if not ("audio" in c and c["audio"] in missing)]

    for r in rows:
        print(f"{'ok ' if r['ok'] else 'BAD'} conf={r['stt_conf']:.2f} top={r['top']:.2f} margin={r['margin']:.2f} "
              f"{r['expect']:>20} <- {r['predicted']:<20} {r['transcript'][:60]}")
    if missing:
        print(f"skipped {len(missing)} missing audio file(s): {missing}")
    print(f"\naccuracy {sum(r['ok'] for r in rows)}/{len(rows)}")

    voice = [r for r in rows if r["source"] != "text"]
    if voice:
        print("\nSTT confirm threshold (voice cases): answered directly = conf >= t; the rest get confirm-back")
        for t in STT_SWEEP:
            direct = [r for r in voice if r["stt_conf"] >= t]
            wrong = sum(not r["ok"] for r in direct)
            print(f"  t={t:.2f}  direct {len(direct)}/{len(voice)}  wrong-but-direct {wrong}  "
                  f"caught-by-confirm {sum(not r['ok'] for r in voice) - wrong}")

    answerable = [r for r in rows if r["expect"].startswith("hpv.")]
    print(f"\nANSWER_THRESHOLD (now {brain.ANSWER_THRESHOLD}, margin {brain.ANSWER_MARGIN}) on {len(answerable)} answerable cases:")
    for a in ANSWER_SWEEP:
        auto = [r for r in answerable if r["top"] >= a and r["margin"] >= brain.ANSWER_MARGIN]
        print(f"  a={a:.2f}  auto-answered {len(auto)}/{len(answerable)}  of which correct {sum(r['top_unit'] == r['expect'] for r in auto)}")

    out = app.DATA_DIR / "eval_report.csv"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
