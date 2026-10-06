# HPV Bot: Cost, Concurrency and Latency

**As of:** 6 Oct 2026 · **Scales:** 100, 1,000 and 10,000 users · **Interactive version:** [HPV Bot Running Costs](https://claude.ai/artifact/8umrUUNPizdULT5geYxXgJ) (change any assumption and the tables update)

Prices are list prices found on 6 Oct 2026 (sources at the end). Latency is measured on the current bot unless marked as an estimate. All figures in USD unless shown as Rs; PKR at an assumed 280 per USD.

## Summary

- **WhatsApp's own fees, not the AI model, decide the bill.** From 1 Oct 2026 Meta charges every bot reply in Pakistan ($0.015 each) after 1,000 free per phone number per month. At 1,000+ users Meta is 93–97% of the total.
- **Cost per conversation is about Rs 52–62**, well above the Rs 14–15 estimate from the 6 Oct meeting.
- **Answering voice notes with one voice note instead of text + voice note cuts the bill by about a third** (Rs 52 → Rs 35 per conversation at 10,000 users).
- **GPT-4o mini vs Claude Haiku 4.5:** Haiku adds about 9% to the total at 10,000 users. GPT-5 nano is cheaper than 4o mini. Urdu quality is untested for all of them.
- **Concurrency is not a constraint up to 10,000 users:** about 6 WhatsApp messages per second at a 5× burst, against Meta's limit of 80.
- **Voice replies take about 12 s today**, mostly WhatsApp API round trips from a PC in Pakistan. Target: p95 ≤ 10 s.

## Assumptions

| Assumption | Value | Why |
| --- | --- | --- |
| Conversations per user per month | 4 | Placeholder; replace with pilot data |
| Questions per conversation | 8 | The "16 messages" (8 user + 8 bot) from the meeting |
| Asked by voice note | 50% | Placeholder |
| Voice note length | 10 s | Placeholder; real test notes were short questions |
| Bot replies per question | Text question: 1. Voice question: 2 (text + voice note) | Current bot behaviour |
| AI model | GPT-4o mini, 1,500 input + 200 output tokens per question | Prompt + knowledge-base passages + history |
| Answer audio | Pre-recorded per answer | Current bot; live TTS shown as a variant |
| Hosting | $30 per month | One small VM |
| Busiest hour | 15% of a day's traffic, with a 5× burst inside it | E.g. right after an SMS or LHW campaign |
| Conversation length | 10 minutes | For concurrent-conversation count |

## Monthly cost

| | 100 users | 1,000 users | 10,000 users |
| --- | ---: | ---: | ---: |
| Conversations | 400 | 4,000 | 40,000 |
| User messages | 3,200 | 32,000 | 320,000 |
| Bot replies (first 1,000 free) | 4,800 | 48,000 | 480,000 |
| **WhatsApp (Meta)** | **$57.00** | **$705.00** | **$7,185.00** |
| Speech-to-text (ElevenLabs Scribe v2) | $0.98 | $9.78 | $97.78 |
| Answer audio (pre-recorded) | $0.00 | $0.00 | $0.00 |
| AI model (GPT-4o mini) | $1.10 | $11.04 | $110.40 |
| ElevenLabs plan (by concurrency needed) | $0 (Free) | $0 (Free) | $0 (Free) |
| Hosting | $30.00 | $30.00 | $30.00 |
| **Total per month** | **$89** | **$756** | **$7,423** |
| Total per month, PKR | Rs 24,943 | Rs 211,629 | Rs 2,078,490 |
| Per conversation, PKR | Rs 62.4 | Rs 52.9 | Rs 52.0 |
| Per user per month, PKR | Rs 249 | Rs 212 | Rs 208 |
| WhatsApp share of total | 64% | 93% | 97% |

### Variants (total per month, and Rs per conversation)

| Change from the defaults | 100 users | 1,000 users | 10,000 users |
| --- | ---: | ---: | ---: |
| Defaults (above) | $89 · Rs 62.4 | $756 · Rs 52.9 | $7,423 · Rs 52.0 |
| **Voice note only, no text copy** | $65 · Rs 45.6 | $516 · Rs 36.1 | $5,023 · Rs 35.2 |
| Voice note only + GPT-5 nano | $64 · Rs 45.1 | $510 · Rs 35.7 | $4,962 · Rs 34.7 |
| No AI model (retrieval only, today) | $88 · Rs 61.6 | $745 · Rs 52.1 | $7,313 · Rs 51.2 |
| GPT-5 nano | $88 · Rs 61.9 | $750 · Rs 52.5 | $7,362 · Rs 51.5 |
| GPT-5 mini | $90 · Rs 63.3 | $770 · Rs 53.9 | $7,561 · Rs 52.9 |
| Claude Haiku 4.5 | $96 · Rs 67.2 | $825 · Rs 57.7 | $8,113 · Rs 56.8 |
| Live TTS per reply (Uplift, $2 per audio hour) | $102 · Rs 71.7 | $889 · Rs 62.2 | $8,757 · Rs 61.3 |

## Concurrency at peak

Concurrent requests = arrival rate × time each request takes (speech-to-text 3.3 s and live TTS 2.3 s measured; model time estimated at 2.4 s).

| At the busiest moment | 100 users | 1,000 users | 10,000 users | Limit |
| --- | ---: | ---: | ---: | --- |
| User messages per second | 0.02 | 0.22 | 2.2 | — |
| WhatsApp messages per second (in + out) | 0.06 | 0.56 | 5.6 | 80 per number (auto-upgrade to 1,000) |
| Speech-to-text requests in flight | 0.04 | 0.37 | 3.7 | ElevenLabs: Free 8, Starter 12, Creator 20, Pro 40, Scale 60 |
| AI model requests in flight | 0.05 | 0.53 | 5.3 | Provider rate limits by account tier |
| Live TTS requests in flight (if used) | 0.03 | 0.26 | 2.6 | Uplift does not publish a limit |
| Conversations open at once | 1.7 | 17 | 167 | — |

All three scales sit well inside every published limit. The real scaling constraint is the bot itself: it keeps per-user state (dedupe, language, uploaded media ids) in memory, so running more than one server process needs Redis or similar first.

## Response time

Measured on the live bot, 1–6 Oct 2026: server on a PC in Pakistan behind an ngrok tunnel; n = 4 voice, 6 text, 10 button turns. Treat these as early numbers.

| Path | Measured today | Added by an AI model (est.) | Added by live TTS (measured) | What it includes |
| --- | ---: | ---: | ---: | --- |
| Voice note → answer | 12.3 s | +2.4 s | +2.3 s | Media download, speech-to-text (3.3 s), send text, send voice note |
| Typed question → answer | 4.0 s | +2.4 s | — | Mark read, send |
| Button tap → answer | 2.1 s | — | — | Send only |

Each WhatsApp API call from the test PC takes about 1–2 s, and a voice answer makes five (mark read, media lookup, media download, send text, send voice). Hosting the bot close to Meta's API and the speech vendors should remove most of that; measure again once hosted. A voice-note-only reply also removes one call. Target from [POC_TECH_ANALYSIS.md](POC_TECH_ANALYSIS.md): voice-note reply p95 ≤ 10 s.

## GPT-4o mini vs Claude Haiku 4.5

Per conversation = 8 questions × (1,500 input + 200 output tokens).

| Model | $ / 1M input | $ / 1M output | Per conversation | 10,000 users / month | Est. added latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| GPT-5 nano | 0.05 | 0.40 | Rs 0.35 | $49.60 | 2.4 s |
| **GPT-4o mini** | 0.15 | 0.60 | Rs 0.77 | $110.40 | 2.4 s |
| GPT-5 mini | 0.25 | 2.00 | Rs 1.74 | $248.00 | 2.5 s |
| **Claude Haiku 4.5** | 1.00 | 5.00 | Rs 5.60 | $800.00 | 2.6 s |

- **Price:** Haiku 4.5 is 6.7× GPT-4o mini per input token and 8.3× per output token, close to the "~9×" quoted in the meeting. At 10,000 users that is +$690 a month, about 9% of the total.
- **Availability:** GPT-4o mini has no API shutdown date announced, but OpenAI retired GPT-4o from ChatGPT in Feb 2026 and is moving users to the GPT-5 family. Test GPT-5 nano alongside it.
- **Latency:** published time-to-first-token for this class is roughly 0.2–0.6 s and varies by load; the estimate above adds 2 s to generate 200 tokens. Not measured.
- **Quality: not tested.** No public benchmark covers Urdu, Roman Urdu or code-switched questions. Next step: run `evaluate.py` with each model on the same Urdu / mixed / Pashto-accented set. That needs `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` in `.env`.

## Open questions

- Confirm the 1 Oct 2026 service-message charge in WhatsApp Manager billing. Partner sources report it; Meta's pricing page did not yet show it when checked.
- Replace usage assumptions (conversations per user, voice share) with pilot data.
- Does Meta count a reply's text and voice note as two service messages? Per-message charging implies yes; confirm on the first invoice.
- Uplift concurrency limits and per-hour overage pricing: ask Uplift.

## Sources

1. [360dialog: service message charging from 1 Oct 2026](https://360dialog.com/blog/whatsapp-service-message-charging-october-2026/) (Pakistan $0.0150, 1,000 free per number per month) · [Meta: WhatsApp pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing)
2. [Meta: Cloud API throughput](https://developers.facebook.com/documentation/business-messaging/whatsapp/throughput) (80 mps default, 1,000 mps upgrade)
3. [ElevenLabs API pricing](https://elevenlabs.io/pricing/api) (Scribe v2 $0.22/h; speech-to-text concurrency by plan)
4. [Uplift AI](https://upliftai.org/) (Starter $5 / 100 min, Pro $50 / 25 h, Growth $300 / 200 h)
5. [GPT-4o mini pricing](https://pecollective.com/tools/gpt-4o-mini-pricing/) · [GPT-5 nano](https://openrouter.ai/openai/gpt-5-nano) · [GPT-5 mini](https://pricepertoken.com/pricing-page/model/openai-gpt-5-mini)
6. [Claude Haiku 4.5 pricing](https://pricepertoken.com/pricing-page/model/anthropic-claude-haiku-4.5)
7. [OpenAI community: GPT-4o mini sunset date](https://community.openai.com/t/what-is-the-sunset-date-for-gpt-4o-mini/1371206) · [OpenAI: retiring GPT-4o in ChatGPT](https://help.openai.com/en/articles/20001051-retiring-gpt-4o-and-other-chatgpt-models)
8. [LLM API latency tests, 2026](https://www.kunalganglani.com/blog/llm-api-latency-benchmarks-2026.md) · [GPT-4.1 mini vs Claude Haiku](https://deploybase.ai/articles/gpt-4.1-mini-vs-claude-haiku)
