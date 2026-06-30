# Research Dossier — iris as a Call-Aversion Co-Pilot

> Status: RESEARCH INPUT (not a decision). Produced 2026-06-30 via a 6-thread deep-research pass — aversion mechanism, call-prep best-practice, structured-extraction tooling, third-voice/handoff patterns, calm-proxy negotiation, and the competitive landscape — synthesized with citations. It informs (does not replace) an architecture decision. Target-user north-star: bd memory `iris-target-user-call-averse`.

---

# iris DOSSIER: "The Call-Aversion Co-Pilot / Speakerphone++"
*Synthesis of 6 research threads. Confidence flags inline. Today: 2026-06-29.*

---

## 1. THESIS VERDICT

**Holds for the co-pilot framing; weaker than hoped for the full-handoff framing; the market window is narrow and closing.**

**Well-supported:**
- The *mechanism* of call aversion is exactly what iris claims to attack. Aversion is a tight cluster: real-time pressure with no edit window, lost visual cues (→ ambiguity + raw listening effort), loss of control/unpredictability, and fear of judgment in an unscripted "performance" ([BBC Science Focus](https://www.sciencefocus.com/the-human-body/telephobia), [Social Anxiety Alliance](https://socialanxietyalliance.org.uk/telephone-calls-and-social-anxiety/)). iris's three levers — offload cognition, restore control, supply non-judgmental co-presence — map 1:1 onto this.
- The **listening-effort** finding is the single strongest pillar: degraded phone audio draws on the *same* verbal working-memory pool you need to think and recall ([PMC5821557](https://pmc.ncbi.nlm.nih.gov/articles/PMC5821557/)). This is universal (not just neurodivergent users) and validates "offload cognition." It also carries a hard design constraint: a second *audio* stream competes for that pool, so iris talking in your ear while you listen can **increase** load.
- The dread is a **three-phase cycle** (Clark & Wells; [PMC11018455](https://pmc.ncbi.nlm.nih.gov/articles/PMC11018455/)): anticipatory dread → in-call self-focus → post-event rumination that replays the call as worse than it was and feeds the next dread. This means iris has *distinct* value at prep, live, AND post-call — and the **objective post-call record** (puncturing "did I mess up / what did they even say") is an evidence-backed feature most "AI on your call" pitches miss.
- **Non-judgmental co-presence is a genuine, defensible edge.** Social-facilitation theory says a present audience helps *unless* it's evaluative, in which case it impairs hard tasks ([simplypsychology](https://www.simplypsychology.org/social-facilitation.html)). A hard call is a hard task. A private, disclosed, non-judging AI can deliver "not alone" *without* the evaluation penalty a human-in-the-room adds. **(Flagged: sound deduction from theory, NOT directly tested for AI call co-pilots — validate with iris's own users.)**

**Shaky / weaker than hoped:**
- **The full-handoff ("take it for you") default is in direct tension with the clinical evidence.** Avoidance and "safety behaviors" *maintain* social anxiety ([Social Anxiety Alliance](https://socialanxietyalliance.org.uk/avoidance-and-safety-behaviours/)); a default-proxy is, clinically, a safety behavior that risks deepening the fear. Separately, people **miswant** calls — they predict awkwardness, then bond more by voice than by text with no more awkwardness (Kumar & Epley, [UT Austin](https://news.utexas.edu/2020/09/11/phone-calls-create-stronger-bonds-than-text-based-communications/)). So habitual avoidance forfeits real connection. Co-pilot-with-fading-support is therapeutic (graded exposure); full handoff is relief, not treatment. Scope handoff as a *fallback/relief valve*, not the standard mode.
- **The "speakerphone" metaphor survives only if grounded in mechanisms, not audio.** No research found that speakerphone *per se* reduces anxiety; its documented uses are physical comfort + multitasking. The metaphor works as "hands free to take notes (offload) + call de-isolated (co-presence) + not pinned to your ear (de-trapping) + a competent co-present party." **Avoid the "less intimate voice in your ear" claim — unsupported.**
- **The novel social surface is the riskiest.** A third voice speaking *alongside a present principal* on an ordinary call has essentially **no accepted precedent** — interpreters, answering services, and Duplex all operate as the sole channel or when the principal is absent. iris's "speak-with-you" mode is genuinely unproven socially.

**Prevalence honesty:** The viral "40%/70%/90% of Gen Z" figures come from survey/marketing-grade sources. The best polling (YouGov) scopes the anxiety to **strangers and high-evaluation contexts** — 65% of Gen Z uncomfortable calling strangers vs. only 15% calling friends/family ([YouGov](https://yougov.com/en-gb/articles/54114-mythbusting-claims-about-gen-z-and-their-phone-habits)). **The bullseye is the high-evaluation, unpredictable call (strangers, institutions, admin, customer service, disputes) — not "all calls."** It concentrates heavily in social anxiety, autism ([245-adult study](https://arrionline.org/individuals-with-asd-rate-phone-calls-as-worst-communication-mode/)), and ADHD populations.

**Net:** Lead with the *silent co-pilot across all three phases* for the high-evaluation call — that is where evidence, precedent, and white space align. Treat handoff/proxy as a guarded fallback. The thesis is real but more modest than "speakerphone++ that handles your calls," and iris is **racing Google and Deutsche Telekom** to the same architecture (see §7).

---

## 2. CALL-PREP CHECKLIST

A typed plan object iris infers from a one-line intent ("I have to call about a wrong charge"), auto-fills from the contact/notes store, and **scales to stakes** (3-field plan for routine calls; full checklist only for high-stakes). Sourced from a convergent prep "core" across Harvard PON, FTC/CFPB, Crucial Conversations, Getting to Yes, Judy Ringer, and phone-anxiety practitioners.

**Section A — FRAME**
- `objective`: one sentence — the single thing that makes the call worth it
- `success_criteria`: **ideal outcome AND minimum-acceptable outcome** (gradient, not binary — lowers stakes; load-bearing for disputes)
- `call_type` enum: dispute/service · outbound-ask/sales · negotiation · difficult-personal · interview · admin/appointment (selects which downstream fields show)
- For difficult/dispute: the Crucial-Conversations triple — what I want *for myself / for them / for the relationship*

**Section B — FACTS AT YOUR FINGERTIPS** *(flagship; maps 1:1 to the notes store; ship first)*
- Identity: account #, claim/case/ticket/reference #, policy/order/confirmation #, member ID
- Dates: charge/incident date, dates+times of prior calls, any deadline
- Figures: amounts in dispute, quoted prices, balances
- **`prior_commitments`: "rep X promised Y on date Z" — auto-sourced from iris's own prior-call capture** (the compounding moat)
- Documents to open: bill + past bills, contract, receipt, resume + job description, confirmation emails
- The other party: who, role/company, relevant history
- *(FTC/CFPB explicitly: have bills, receipts, dates, amounts, the specific disputed-charge list ready; keep a dated file of who-you-spoke-to-and-when — [CFPB](https://www.consumerfinance.gov/ask-cfpb/how-do-i-dispute-a-charge-on-my-credit-card-bill-en-61/), [FTC](https://consumer.ftc.gov/articles/what-do-if-youre-billed-things-you-never-got-or-you-get-unordered-products))*

**Section C — WHAT TO SAY**
- `opening_line`: literally drafted, 1–2 sentences (highest-value artifact for the call-averse; keep pinned on-screen)
- `agenda`: 3–5 bullets to cover — **NOT a full script** (read-aloud scripts sound robotic and shatter on divergence)
- `questions`: open-ended, prioritized, must-get answers flagged
- `the_ask`: the desired resolution stated plainly ("I want this $43 charge reversed")

**Section D — CONTINGENCIES / BRANCHES**
- `objections`: if-they-say-X / you-say-Y table (dual-purpose: shown in prep AND surfaced live)
- `walk_away`/BATNA + `reservation_point`; `target`/aspiration point ([Harvard PON 32-item checklist](https://www.pon.harvard.edu/daily/negotiation-skills-daily/negotiation-preparation-checklist/))
- `escalation_path`: ask for supervisor → follow up in writing/certified mail → file complaint
- `fallback`/bail-out: leave a message, reschedule, or hand to iris **(bridge to HANDOFF mode)**

**Section E — DELIVERY / STATE**
- `tone`: explicitly chosen — calm / firm / warm / neutral-professional
- Pacing reminders: pause, breathe, ~50/50 talk-listen on discovery calls
- `buy_time_line`: "I don't know — can I put you on a brief hold and get that?"
- Optional pre-call breathing reset (4-7-8 / box) when anxiety is flagged

**Section F — CAPTURE (during + after)**
- Live: rep/agent name, call date+time, reference/ticket #, every commitment, agreed next step + deadline
- After: write all of it back to the contact record → **next call's Section B is pre-populated.** Prep compounds.

**Caveat (medium-confidence, my synthesis):** the typed schema and the "captured prior-commitments = compounding moat" claim are reasoned, not directly measured. And **scale prep to stakes** — for a 5-minute admin call, heavy prep becomes the new procrastination ritual ("I'll call once I've prepped"), which betrays the friction-reducing promise.

---

## 3. STRUCTURED EXTRACTION — BUILD vs. ADOPT

**Recommendation: ADOPT, hard. Build only the trust/verification layer.** A mature, mostly-local stack already covers every extraction layer; bespoke action-item ML is a money pit (best model ~41 F1; humans agree only at Kappa 0.36 — [arXiv 2303.16763](https://ar5iv.labs.arxiv.org/html/2303.16763)).

**Three-layer pipeline:**
- **Layer 1 — deterministic, on-device (high precision, private):** Google [libphonenumber](https://github.com/google/libphonenumber) / Python [phonenumbers](https://pypi.org/project/phonenumbers/) for phone numbers (near-perfect, returns offsets); Facebook [Duckling](https://github.com/facebook/duckling) or `dateparser` for dates/times/money/durations (beats both regex and LLM on relative expressions like "by Friday"); **small context-anchored regexes** for case/reference IDs — anchor on the *spoken cue words* ("reference," "confirmation code," "claim," "ticket"), not the digit shape, and expect per-domain tuning.
- **Layer 2 — LLM, post-call:** one function-calling/JSON-schema pass for action items + entities the rules missed. Every modern product (Otter, Fireflies, Fathom, Granola) uses off-the-shelf LLMs here — nobody builds bespoke action-item models.
- **Layer 3 — iris's actual differentiator: verification & trust UX.**

**Concrete "don't start from scratch" starting point:**
- Python **[instructor](https://python.useinstructor.com/) + Pydantic** (auto-validation + retry, 15+ providers) wrapping **Anthropic tool use**.
- Schemas: `ActionItem{description, owner, due_date, source_span, confidence}` and `CapturedFact{type(phone|case-id|date|amount), raw_text, normalized_value, transcript_offset, confidence}`.
- **Run Layer 1 first and feed its high-precision hits into the prompt as ground-truth anchors** so the LLM corrects/links rather than re-guesses numbers.

**Realistic accuracy caveats (these are the product-defining ones):**
- **Schema-compliance ≠ value-correctness.** Constrained decoding gives ~99.7–100% valid JSON, but **value accuracy drops from ~0.83 on text sources to ~0.24 on audio sources** ([OpenAI Structured Outputs](https://openai.com/index/introducing-structured-outputs-in-the-api/); value-accuracy figures from [arXiv 2604.25359](https://arxiv.org/html/2604.25359v1) and related — *moderate confidence, dataset-dependent*). iris's input is audio — the worst case. **Schema-valid is not correct.**
- **STT mangles exactly the tokens iris cares about.** Names/numbers/dates/IDs have disproportionate error rates masked by good overall WER (Whisper ~2.7% clean but **8–12% real audio** — *vendor-adjacent, indicative*); a transposed digit is unrecoverable downstream ([arXiv 2506.22858](https://arxiv.org/pdf/2506.22858)). **A confidently wrong confirmation number is worse than no number** — this is the single biggest threat to iris's core promise.
- **Ownership errors + name bias.** LLM recaps misassign owners, worse for non-Western names ([arXiv 2307.15793](https://arxiv.org/html/2307.15793v2)). Show inferred owner; let user fix; **test attribution on non-Western names explicitly.**

**Mandatory build choices:** (1) every extracted item carries confidence + a **transcript-span + timestamp** provenance pointer ("tap to replay the 4 seconds where iris heard this") — what makes Otter/Fathom trustworthy; (2) **read critical numbers back in real time** (prompt user to confirm, or in handoff mode read back on the line) — converts the worst failure into a caught error; (3) **bias the STT** with expected vocab (user name, company called, likely ID formats) rather than only post-processing — higher leverage than any regex; (4) present action items as **editable suggestions** from day one (products only hit ~90% catch after ~2 weeks of correction); (5) keep the LLM out of the real-time hot path — fast local deterministic + spaCy live, heavy LLM pass post-call.

*spaCy NER note: ~0.85 F1 (small/large), ~0.90 transformer on OntoNotes, but sags to ~0.75 out-of-domain and worse on conversational/accented speech — treat as candidates, not facts.*

---

## 4. THIRD VOICE & HANDOFF *(feeds the later design session)*

**Principles for a third voice participating naturally:**
- **Silent is the proven model.** The entire mature category (Cresta, Balto) coaches the human *on-screen only* — the other party never hears it ("Agent Assist recommends, the human decides"; [Cresta](https://cresta.com/agent-assist)). Make the silent co-pilot the flagship/default; treat speaking modes as the experimental frontier.
- **Disclose, verbatim and upfront.** Duplex's backlash was about *deception*, not capability; Google reversed within a day to force self-identification ([MIT Tech Review](https://www.technologyreview.com/2018/06/27/141823/)). It's now also law — **CA AB 2905 requires disclosure at the *beginning*** of an artificial-voice call; never bury it 30 seconds in. Open every spoken turn: "Hi, this is [user]'s AI assistant; they asked me to help — if you'd like a person at any time, just say so."
- **Mark the role aloud** (interpreter convention — the one socially-accepted speaking third voice). Flag who you speak for: "this is the assistant speaking" vs. relaying the user. Ambiguity about who's talking is the biggest driver of "intrusive" ([EthnoMed](https://ethnomed.org/resource/interpreting-pre-session/)).
- **Hit the turn-taking numbers or it reads as a robot** (pass/fail, not nice-to-have): enter only at pauses/TRPs (~200ms gaps); backchannel instead of barging; keep >2s dead air under 5% of turns; detect barge-in ~200ms and **stop speaking ~300ms**; use "Are you still there?" instead of silence ([MDPI turn-taking review](https://www.mdpi.com/2227-7080/13/12/591); [voice-agent checklist](https://altersquare.io/voice-agent-production-readiness-checklist-stress-test-enterprise-deployment/)).
- **Keep spoken turns short** — the other party "often prefers a human," and length amplifies the uncanny reaction even when honestly disclosed.
- **Honest filler, never human-mimicry-to-deceive.** "One moment, let me check that" is fine from a disclosed assistant; Duplex's um/aah were condemned because they simulated humanity to fool an undisclosed listener.

**EXPLICIT-HANDOFF cases → expected outcomes** (four first-class, user-visible outcomes; reuse the answering-service field schema + SLA + readback for message-taking — [AnswerNet](https://answernet.com/receptionist-message-taking-scripts-7-winners-for-better-messages-more-customers/)):

| Case | Expected outcome |
|---|---|
| **RESOLVED** | Only for narrow, scoped tasks (Duplex shows automation works for simple info exchange) |
| **MESSAGE-TAKEN** | Capture name/number/reason/urgency/callback-time/mood + set SLA + read back to confirm |
| **SCHEDULED-CALLBACK** | Pre-planned reschedule; a control-restoration tool framed as such |
| **ESCALATE-BACK** | **Normal, frequent (~20%+) outcome, designed as a first-class path, not a failure.** Even SOTA Duplex looped in a human ~1-in-5 calls. One-tap: iris says "one moment, I'll bring [user] in" and yields. Trip-wire: **two low-confidence turns → hand back.** |

**Warm-transfer caution that feeds the anger design:** call-center practice routes *emotional* calls to **more** human attention, not less ([VirtualPBX](https://www.virtualpbx.com/blog/general-telephony/warm-transfer-call-scripts/)). A fully-AI proxy on a hot call inverts this and may read to the *other party* as "they won't even deal with me." **Flagged speculative:** this poor-reception prediction is inferred from the warm-transfer norm + Duplex's "people prefer humans," not from a study of AI-proxy reception. The "speak-alongside-a-present-principal" mode has no precedent at all — this is iris's least-validated surface and should ship behind disclosure + brevity + easy human fallback.

---

## 5. ANGER / CALM-PROXY

**Verdict: the "hand a too-angry dispute to a calm, prepared proxy" lever holds, and holds *strongest exactly at the flooded-anger trigger it targets* — with one counter-argument to engage honestly.**

**The honest counter-argument (engage, don't ignore):** expressed anger CAN extract larger concessions, and the effect is **largest over voice** — iris's exact channel (M=17.84 voice vs. 9.57 neutral; [Frontiers 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9201715/)). *(Single study — magnitudes indicative.)*

**Why it doesn't hold for iris's user (four convergent reasons):**
1. **Gains are short-term and clawed back** via retaliation, sabotage, guilt, distrust; angry negotiators did NOT beat happy/neutral and over-corrected later, erasing gains (Campagna/Mislin/Bottom 2019, [Harvard PON](https://www.pon.harvard.edu/daily/negotiation-skills-daily/negotiation-research-you-can-use-why-displays-of-anger-can-backfire-nb/)). iris's calls are overwhelmingly **repeated-relationship** (landlord, insurer, employer, co-parent) — where backfire dominates.
2. **Power-moderated:** anger wins only for the high-power party with a strong BATNA. iris's user is the **low-power individual vs. an institution** that can set boundaries or hang up for "abuse" → reciprocal anger, not concessions.
3. **Anger degrades the angry person's OWN cognition** — shallow heuristic processing, false certainty, illusion of control, risk-optimism, rush to blame individuals (Lerner & Tiedens). **"Too angry to be effective" is literally a cognitive-impairment state** — this is the core justification, and it's the strongest. Lead with it.
4. **Venting amplifies, doesn't discharge** — the catharsis myth (Bushman 2002, [154 studies](https://websites.umich.edu/~bbushman/PSPB02.pdf)): the better people feel after venting, the more aggressive they get. A user who "lets them have it" spirals mid-call.

**Concrete techniques iris should embody (calm-but-FIRM, never calm-but-passive):**
- **Sequence first (FBI BCSM):** Active Listening → Empathy → Rapport → Influence → Behavioral Change. Never lead with the demand; bank listening + labeling, *then* ask ([crisis negotiation](https://en.wikipedia.org/wiki/Crisis_negotiation)).
- **De-escalation primitives:** *lower* your voice (don't match volume — they follow); validate the emotion ("I can hear how frustrating this is"); replace bare "no" with **"no, but here's what I CAN do"**; set firm boundaries against abuse ([de-escalation playbook](https://contactpoint360.com/blog/de-escalation-techniques-for-customer-service/)).
- **Voss toolkit (deployable templates):** tactical empathy; slow low "late-night FM DJ voice"; mirroring (repeat last 1–3 words + silence); labeling ("It sounds like…"); accusation audit; calibrated how/what questions ("How am I supposed to do that?"); aim for "that's right"; loss-aversion framing; Ackerman anchors ([notes](https://grahammann.net/book-notes/never-split-the-difference-chris-voss)).
- **Broken-record (the key primitive):** one pinned, prepared sentence ("I'm requesting a refund of $X") calmly repeated, ignoring red herrings and guilt-trips — explicitly taught as a way to hold a boundary *without* getting angry (Manuel J. Smith, 1975).

**Why the AI proxy is a *superior* dispassionate agent (flagged: reasoned extension of principal-agent theory, not directly studied):** "never represent yourself" is about emotional detachment buying objectivity + BATNA-clarity ([Harvard PON](https://www.pon.harvard.edu/daily/business-negotiations/when-their-agent-is-the-problem/)). The classic human-agent downsides are **agency costs** — commission siphons value, self-interest, drift. iris's proxy **uniquely removes these** (no commission, perfect alignment, briefed by the user, on the user's own call) while **inheriting only two gaps: no domain expertise, no relationship/clout.** So iris must win on **preparation**, not expertise.

**Design rules:** make "too angry to be effective" a first-class trigger, justified in *cognitive* terms ("anger is degrading your judgment and will trigger reciprocal anger from a low-power position"), not "calm down." Ship two graduated interventions: silent regulated co-pilot (user can self-regulate → preserves agency, avoids "talk to a human" friction) vs. full disclosed proxy (genuinely flooded). **Route venting OFF the live line** ("tell me how angry you are, then I'll say it the way that actually works"). Capture-during-dispute is a first-class lever — anger narrows attention, so the user misses the commitments/names/reference-numbers they'll need for the likely repeat call.

---

## 6. SUPPORTING OTHERS *(the aspirational dimension)*

**The real human picture:**
- **It's a spectrum, not a niche:** mild dislike → clinical telephobia. One study ~42% overall (33% mild / 7.7% moderate / 1.3% severe; [PMC11213418](https://pmc.ncbi.nlm.nih.gov/articles/PMC11213418/)); ~62% of UK office workers have avoided a work call; ~25% of UK 18–34s say they never answer; **~56% of non-answerers assume bad news** — a framing gift, because surfacing caller context/intent directly lowers dread.
- **Concentrated in identifiable, underserved groups** (a real target market, and the right people to design *for first*):
  - **Social anxiety disorder** — telephobia is a recognized situational expression; the anticipatory→post-event rumination cycle is the engine.
  - **Autism** — a 245-adult study ranked phone calls the **least-preferred of six communication modes in every scenario** (auditory processing, anxiety, unpredictability, difficulty reading tone/intent), independent of age/anxiety/camouflaging ([ARRI](https://arrionline.org/individuals-with-asd-rate-phone-calls-as-worst-communication-mode/)). This segment may genuinely want **delegation**, where full handoff is more clearly welcome.
  - **ADHD** — working-memory/attention drop-out + rejection sensitivity ([Inflow](https://www.getinflow.io/post/phone-anxiety-and-adhd)).
- **What actually helps** (convergent across clinical + practitioner sources): bullet **agendas** not rigid scripts; restored **control** ("can I call you back?", scheduling, a pause); **graded exposure** from low-stakes calls; **note-taking**; and **co-presence** — "tasks seem less daunting when you're not facing them alone" ([body doubling](https://adhdonline.com/articles/what-is-body-doubling-and-how-does-it-help-with-adhd/)). Texting's appeal is the mirror image of the aversion (asynchrony, editability, thinking time) — **iris's job is to reproduce those texting affordances inside a live synchronous call.**
- **People want to get *better*, not only to avoid:** Gen Z are paying for **telephobia courses** ([CNBC](https://www.cnbc.com/2025/02/17/gen-z-are-taking-telephobia-courses-to-learn-the-lost-art-of-a-call.html)). Appetite for mastery exists. This is the anti-dark-pattern north star: **a tool that makes you need it less.** Designing for the neurodivergent core (offloaded memory, no time pressure, decoded tone, predictability) lifts the whole mild-aversion majority too.

**The aspirational frame:** iris isn't "skip the call"; it's the *accompanied, supported* version of doing the hard thing — graded-exposure-with-a-support-person — plus an objective record that puts the lie to the post-call "I messed up" loop. Use the affective-forecasting gap as built-in coaching ("how did that go vs. how you feared?") to build durable corrective learning.

---

## 7. MARKET GAP

**Real but NARROW and fast-closing white space. No incumbent holds iris's exact position — a consumer-facing, disclosed, real-time, *in-the-live-call* accompaniment spanning silent-copilot → disclosed-handoff → take-a-message → proxy, framed for the call-averse, cross-platform. But every flank is held, and the two best-resourced flanks erase iris's hardest technical problem.**

**The flanks (who holds each):**
- **Silent in-ear copilot → [TalkPilot](https://www.talkpilot.co/)** ($99/mo — proves willingness-to-pay). Closest direct competitor, BUT **covert** (hidden from the other party, not disclosed), performance-framed, and **cannot speak or hand off**. iris's disclosed + can-speak + escalation + call-averse framing is genuinely differentiated.
- **Full delegation → Pine AI ([19pine.ai](https://www.19pine.ai/))**, Safina, Mitra, Kally. Pine is a strong autonomous pure-play for the bill/anger use-case (claims 93% success, $300+/yr, $30/mo, disclosed, TEE). **This is where iris is weakest** — a too-angry user likely wants to be *off* the call, and Pine does that better.
- **On-device consumer in-call help → [Google Pixel Call Assist](https://blog.google/products-and-platforms/devices/pixel/pixel-call-assist-call-notes-tips/)** (Hold for Me, Direct My Call, Call Notes via on-device Gemini Nano, Call Screen). Exactly the "reduce phone-call burden" features, **free** — but Pixel-only, fragmented single-purpose utilities, no unified disclosed-handoff, no speak-for-you on an emotional call, no call-averse framing.
- **Call-aversion brand → Ghosty ([ihatecalling.ai](https://ihatecalling.ai/en/ghosty/blog/phone-call-anxiety)), Kally.** Emotional positioning is **contested, not virgin** — but they're lighter (transcription/screening/practice), not disclosed-speaking-handoff + silent copilot.
- **MOST THREATENING — [Deutsche Telekom "Magenta AI Call Assistant"](https://www.telekom.com/en/media/media-information/archive/deutsche-telekom-reimagines-phone-calls-with-ai-embedded-in-the-network-1102890)** (MWC 2026, with ElevenLabs). **Network-embedded, app-free, device-agnostic, real-time, disclosed, can speak AND act on the call.** This is architecturally iris's vision with **no app and no hardware.** Differences iris can exploit: carrier-locked (DT/Germany 2026 first), generic-utility-framed, invocation-based, no silent-while-you-talk mode, no emotional accompaniment/graceful fallback.

**iris's defensible wedge:** the **integrated, disclosed, emotionally-framed escalation spectrum** ("you're never alone AND never trapped on the call") — the one position no incumbent holds — **plus cross-platform/cross-carrier reach** (Magenta is DT-locked; Pixel is Pixel-only).

**Where iris loses / honest weak spots:**
- **Note-taking is commoditized** (Otter/Fathom/Granola for meetings; Pixel Call Notes free; Plaud hardware) — don't lead with it.
- **Anger/dispute proxy** loses to Pine as a pure play unless "supervised + take-back + you-stay-on" is genuinely what users want.
- **The audio-access moat is real today but time-limited.** iOS blocks third-party apps from cellular call audio (CallKit doesn't process call audio) — which neuters software-only rivals; iris's Bluetooth bridge sits in the audio path and solves it. **But carriers (network) and OS vendors (on-device) can erase it.** Plan a software / carrier-OEM-partnership path *before* the hardware edge evaporates; treat Google/Apple/Telekom as potential partners or acquirers of the emotional-UX layer.
- **Overclaim is fatal:** DoNotPay was [FTC-fined $193K](https://www.ftc.gov/news-events/news/press-releases/2025/02/ftc-finalizes-order-donotpay-prohibits-deceptive-ai-lawyer-claims-imposes-monetary-relief-requires) for an untested "AI lawyer." Claim *accompaniment*, not expertise.

**Legitimacy precedents to borrow in messaging:** "captioned telephone for the call-averse" (InnoCaption/CaptionCall — real-time in-call AI is normal, trusted, federally funded for hearing loss; but the call-averse aren't a funded protected class, so iris is a commercial play without that subsidy); and the agent-assist asymmetry ("the call center has had a real-time copilot for years; now the person calling them does too").

**Truer than the slogan:** "iris is racing Google and Deutsche Telekom to get there, with a head start only on emotional framing and graceful escalation."

---

## 8. TOP DESIGN IMPLICATIONS

**Highest-leverage takeaways (7):**
1. **Bullseye the high-evaluation, unpredictable call** (strangers/institutions/admin/disputes), not "all calls." Don't anchor the pitch on friends/family calls — not the pain point.
2. **The silent, visual co-pilot is the flagship and default.** It's the only third-on-a-call pattern with mass commercial proof, and the listening-effort evidence says iris-in-your-ear competes for the same working memory — reserve iris's *voice* for handoff segments and dead air; make spoken assist opt-in and terse.
3. **Build for all three rumination phases.** The auto-captured **post-call record** is the differentiated, evidence-backed feature most rivals miss — it directly punctures post-event rumination.
4. **Adopt extraction; build only the trust layer.** Three-layer pipeline (deterministic on-device → post-call LLM → verification UX). Mandatory: transcript-span+timestamp provenance + confidence on every field; **read critical numbers back live.** A confidently wrong confirmation number reintroduces the exact dread iris exists to remove.
5. **Make non-judgment + privacy + disclosure designed, friendly product promises.** Non-judgment is the mechanism that lets a disclosed AI deliver co-presence without the evaluation penalty — the core defensible edge. Disclosure is also law (AB 2905) and the trust wedge the DoNotPay fine proves you can't fake. **Claim accompaniment, never expertise.**
6. **Position the co-pilot as scaffolding that FADES** (coach, not crutch) — graded-exposure-with-support, anxiety-*reducing*. Default-handoff is clinically a safety behavior that entrenches the fear. Scope full handoff as a *fallback*, cleanest for the **anger/dispute** case (harm-avoidance, not skill-building) and acute distress.
7. **Treat the Bluetooth-bridge moat as time-limited; treat local-first as table stakes, not the headline.** Apple/Google/TalkPilot are already on-device. The differentiator is what iris *does* (disclosed accompaniment + escalation spectrum), not where it runs.

**Recommended FIRST build:**
**The silent co-pilot for the high-evaluation call, anchored on "Facts at your fingertips" (prep §B) + auto post-call capture (§F), with the compounding prior-commitments loop.** This is the lowest-risk, highest-precedent, most defensible surface: it rides decades of agent-assist precedent, attacks the strongest-evidenced mechanism (offload cognition), maps 1:1 to the contact/notes store, ships extraction via adopt-not-build, and creates the only thing no checklist app or note-taker can do — *next call's prep gets better because iris remembers what the last rep promised.* Defer the speaking/handoff and anger-proxy modes to a second phase behind disclosure + brevity + easy fallback.

**OPEN QUESTIONS for the operator (resolve when he's back):**
1. **The core untested bet:** do the call-averse want *accompaniment* or *avoidance/delegation*? No direct evidence. My read (speculative): mild-aversion middle → accompaniment; clinical telephobia/autism → may want full delegation or to not call at all. **Segment the product and test which mode each cohort actually reaches for — this gates the whole "with you, not instead of you" thesis.**
2. **Anger/dispute scope:** ship a genuine "step fully off" delegation mode and benchmark against Pine (savings, success rate), or cede that segment and keep iris as the *silent calm-script coach* + brief disclosed buffer? The warm-transfer norm ("emotional calls get more human") is a yellow flag against a speaking AI proxy.
3. **Speak-alongside-a-present-principal** has zero social precedent — is the operator comfortable making iris the validation-bearer of a novel social pattern, behind disclosure + brevity + handback? This is the riskiest UX surface.
4. **Moat horizon:** assume Apple/Google/carriers ship more on-device call assists on a 12–24mo horizon. Is the play to out-engineer, or to build the emotional/escalation UX layer that sits *above* whatever audio plumbing wins (and could be partnered/acquired)?
5. **Disclosure A/B:** does disclosing an AI proxy trigger "I want a real person"? Test disclosed-proxy vs. silent-copilot-keeping-a-calm-human-on-the-line for sensitive disputes (latter may face less resistance). *Untested.*
