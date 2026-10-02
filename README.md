# HPV WhatsApp bot: Cloud API sandbox (iteration 1)

Retrieval-only bot on Meta's WhatsApp Cloud API test number. It sends pre-approved answer units verbatim; nothing is generated. Architecture and rationale: [POC_TECH_ANALYSIS.md](POC_TECH_ANALYSIS.md).

**All content in `content/hpv_placeholder.yaml` is engineering placeholder text, not medical advice.** Every message it sends starts with `[PLACEHOLDER…]`. Real content: write a file with the same schema (reviewed units need `review.reviewer_id` set) and point `CONTENT_PATH` at it.

| File | Purpose |
| --- | --- |
| `app.py` | Webhook: verify handshake, HMAC signature check, dedupe, fast ack, background handling, `data/turns.jsonl` log |
| `brain.py` | Content loading/validation, normalization + Roman Urdu lexicon, language ID, danger check, IDF-weighted trigram matching, decision |
| `wa.py` | Graph API calls and message builders |
| `speech.py` | ElevenLabs speech-to-text (voice notes in) and text-to-speech (answer audio) |
| `render_audio.py` | Pre-renders `assets/audio/<unit>.<en|ur>.ogg` for every unit; rerun after content changes |
| `content/hpv_placeholder.yaml` | Answer units, UI strings, lexicon, stopwords, danger phrases |

## Scope

In: text Q&A (EN / Urdu script / Roman Urdu), reply buttons and topic lists, danger-phrase escalation before retrieval, out-of-scope deflection, clarify on ambiguous questions, voice notes: download → ElevenLabs Scribe STT → same decision as text → text reply + pre-rendered answer voice note (`voice:true`, Spike 4).

Deferred: Calling API (Spike 2), STT/TTS vendor comparison and real-audio evaluation (Spikes 1, 5), embeddings/pgvector (Spike 3 needs real units + eval set), Redis/queue, LLM, templates, HCW verification.

## Run tests (no Meta account needed)

```
pip install -r requirements.txt
python -m pytest -q
```

## Manual test on the real test number

1. **Meta app.** developers.facebook.com → Create app → Business → add the WhatsApp product. In WhatsApp → API Setup note the test number's *Phone number ID* and the temporary access token. Add your own phone under "To" and verify it (max 5 recipients). App settings → Basic → copy *App secret*.
2. **Env.** `copy .env.example .env` and fill it in. Then `python render_audio.py` to create the answer audio.
3. **Run.**
   ```
   python -m uvicorn app:app --port 8000 --env-file .env
   cloudflared tunnel --url http://localhost:8000     # or: ngrok http 8000
   ```
   The cloudflared URL changes on every restart; re-enter it in step 4 when it does.
4. **Webhook.** WhatsApp → Configuration → Callback URL `https://<tunnel-host>/webhook`, Verify token = `WA_VERIFY_TOKEN` → Verify and save. Under Webhook fields, subscribe to `messages`.
5. **Checklist from your phone** (message the test number first; the bot can only reply inside the 24 h window you open):

   | Send | Expect |
   | --- | --- |
   | `hi` | Greeting + "Topics" list; tapping a row returns that unit with related-question buttons |
   | Tap a button | That unit, in the language you last wrote in |
   | `is hpv vaccine safe?` / `کیا ایچ پی وی ویکسین محفوظ ہے؟` / `kya hpv vacsin mehfooz hai` | Safety unit in EN / Urdu / Roman Urdu |
   | `hpv vaccine` | "Did you mean…" list |
   | `teeka lagne ke baad behosh ho gayi` | Emergency text (Rescue 1122); `escalation` line in `data/turns.jsonl` |
   | `cricket score` | Deflection + topic list |
   | A photo | "I can only read text and voice notes" + topic list |
   | A voice note asking a question (Urdu or English) | File appears in `data/inbound/`; you get the answer as text, then that answer as a **voice-note bubble with play icon**; the log line's `text` is the transcript and `audio` names the file sent; playing it logs a `played` status |
   | A silent or noise-only voice note | "Could not understand the voice note" + topic list |

   Also confirm: typing indicator shows before replies, Urdu renders right-to-left, no rate-limit errors on the text + voice pair, and `download_lag_s` in the log is well under 300 s.

## Known limits

- Retrieval is lexical (trigrams + lexicon). It handles the listed spelling variants but not unseen paraphrases; Spike 3 compares embeddings once real units exist.
- Urdu STT accuracy on real WhatsApp voice notes is unmeasured (Spike 1); verified only on synthetic speech. Speech detected as Hindi is re-transcribed as Urdu.
- Answer audio uses a premade ElevenLabs voice (`speech.VOICE_ID`) and reads the placeholder marker aloud.
- State (dedupe, language preference, uploaded media ids) is in memory; a restart forgets it. Run a single worker.
- Users are keyed by phone (`from`); move to BSUID before production.
