# The Voice AI Eval Strategy Playbook

### Getting a voice agent from 70% to 99% in production, on purpose

You can reach 70% out of the box. Getting to 99% is a discipline, not a launch. This playbook is the working version of our complete evaluation guide: the maturity curve, the base cases, the persona ladder, the metrics, the gates, and the loop that keeps quality from sliding as volume grows. Use it to find where you are and run the next climb.

It is vendor agnostic. The principles hold whatever stack you are on. Where a step is easier with a platform built for it, we say so plainly.

---

## 1. Find your stage

Every voice AI team moves along the same curve. Locate yourself before you plan anything.

| Stage | You are here when | What got you here | The next jump |
|---|---|---|---|
| **1 · ~70%** | Works in a demo, breaks on real calls | The model and platform are good enough out of the box | Effort |
| **2 · ~85%** | A few people listen to calls and grind on fixes | Manual QA, dedication, hustle | The wall (2→3): make it programmatic |
| **3 · ~95%** | Automated evals run on every change | A diligent, repeatable evaluation strategy | Judgment: the right tests at the right time |
| **4 · ~99%** | The right tests run at the right time, in front of the right people | Continuous, calibrated improvement | Stay there as the world changes |

> Even at 99%, 200,000 calls a month is still 2,000 bad calls. Each one is a real person. Scale changes the stakes, and evaluation is how you hold quality as volume grows.

**Self-check.** Circle the highest row that is true for you today. That is your stage. The rest of this playbook is the climb from there.

---

## 2. Know what each jump takes

- **1 → 2 is effort.** Put your headphones on. At a dozen calls a day you can and should listen to every one. You are building the intuition that makes everything else possible: the failure modes you would never have thought to test for, a feel for what "good" actually sounds like, and a reality check on the calls you imagined versus the calls you get.
- **2 → 3 is the wall.** Manual effort runs out. You cannot listen to 2,000 calls a week or run 200 test calls before every deploy. You need evals that are programmatic, automated, and repeatable. Most of this playbook lives here.
- **3 → 4 is judgment.** Less about running more tests, more about running the right tests at the right time and cost, and putting the results in front of the right people.

**The signal you have outgrown manual QA:** you catch yourself thinking "we need more QA people" instead of "we need better tooling." Do not rush it. If you are at a dozen calls a day, keep listening.

---

## 3. Lock your base cases

Your first automated evals are two lists: what your agent must **ALWAYS** do, and what it must **NEVER** do. These are the floor. Get them to a 100% pass rate against easy callers before anything else.

**The floor by vertical (starter set, adapt to your business):**

| Vertical | Must ALWAYS | Must NEVER |
|---|---|---|
| Healthcare | Verify patient identity; route emergencies immediately; deliver required disclosures | Give medical advice; confirm a diagnosis; share PHI with unverified callers |
| Fintech | Verify identity before account access; disclose recording; follow required collections language | Give investment advice; disclose account details to unverified parties; skip state disclosures |
| Insurance | Capture claim details accurately; route to an adjuster when required; confirm coverage scope | Guarantee claim outcomes; interpret policy language as legal advice; skip fraud screening |
| QSR / Retail | Confirm the order back to the caller; apply correct pricing; handle allergy questions accurately | Charge without confirmation; ignore allergy questions; take orders for closed locations |

**Start in easy mode.** Your first personas are the simplest possible callers: even tone, no interruptions, no background noise, clear enunciation, one intent per call. It is a driving test in an empty parking lot. If the agent cannot nail greetings, identity, intent, task, and sign-off here, nothing downstream matters.

✅ **Checklist:** ALWAYS list written · NEVER list written · easy-mode personas built · 100% pass rate reached · this is now your regression floor.

---

## 4. Climb the persona ladder

Real traffic does not sound like easy mode. Broaden and deepen on purpose, and sequence it so you never play whack-a-mole.

**Broaden (harder callers).** Layer in accents and languages, background environments (a drive-thru lane, a car in traffic, a noisy cafe), emotional states, interruptions, and stammering. Production voices are messy; clean-room tests hide the gap.

**Deepen (more under test).** Multi-turn context across 5, 10, 15 turns. Tool-call accuracy (an agent can understand intent perfectly and still inject a malformed order). Conversation pivots ("actually, change that"). Escalation judgment. Concurrency and load at 10x and 100x.

**The discipline that prevents whack-a-mole:** lock the floor first, then add medium-difficulty personas and run the full suite. If a new persona breaks something easy mode caught, that is a real regression. If it breaks something new, that is a coverage gap. Add it and keep going.

> Watch the LLM people-pleaser trap: if you simulate callers with an LLM, it will bend over backwards to make the call succeed. Real callers do not. Your test personas have to misbehave on purpose.

---

## 5. Make metrics you can trust

**One dimension per metric.** Do not bundle. A "conversation quality" score that blends tone, pacing, and resolution tells you nothing when it fails. Break it down: task completion, factual accuracy, compliance adherence, conversation flow, escalation appropriateness. Each metric measures exactly one thing.

**Calibrate your judge before you trust it.** LLM-as-judge is what lets evaluation scale past human review, but judges can be too generous, miss tone, or apply rubrics unevenly. Run the loop:

1. Run the automated evals on a batch (50 to 100 calls is a good start).
2. Sample a subset for human review against the same rubrics.
3. Compare. Where do judge and human agree, where do they diverge, and is the disagreement random or systematic.
4. Tighten the rubric on the disagreements. Add edge-case examples. Add a metric where the judge missed a failure mode.
5. Repeat until agreement is high enough to act on without double-checking every result.

**Practical:** start with binary metrics (verified identity, yes or no). Graduate to scalar metrics carefully, with explicit rubrics per score level. Use every judge-versus-human disagreement as a rubric improvement. Do not expect 100%; aim for above 85% on binary and within one point on scalar.

---

## 6. Gate every deploy

Once you have evals, the question becomes when they run. The answer is automatically, on every change that could move agent behavior: code, prompt, or model.

**Structure the suite by cadence so the per-deploy gate stays fast:**

| Cadence | What runs | Why |
|---|---|---|
| Per-deploy | Core regression — must-always / never + easy-mode personas | The gate. Block bad releases. Minutes, not hours |
| Nightly | Extended regression + medium-difficulty personas | Catch what slips past the fast per-deploy checks |
| Weekly | Full suite incl. hard + adversarial personas + edge cases | Comprehensive coverage sweep, not blocking a deploy |
| On-demand | Targeted tests for a specific change (prompt, tool, model) | Validate a hypothesis before it graduates to regression |

**Set threshold gates** with quantitative pass/fail criteria (task completion above 95%, compliance at 100%, latency under your bar) and block the deploy when any threshold is breached.

> The litmus test for whether evals actually run in CI: if running one requires logging into a dashboard, clicking a wizard, and waiting in a separate tab, it will not run on every deploy. It will run when someone remembers, which means it will not run. Meet engineers where they work: CLI, API, and the coding assistants they already use.

---

## 7. Close the loop

The same metrics and personas you built for selection and dev are the ones you point at production. Run the same suite on live traffic, not a lighter version of it.

- **10 to 20% of calls** get full eval-suite coverage.
- **100% of calls** get lightweight anomaly detection (latency spikes, early hang-ups, escalation triggers).
- **Flagged calls** get full eval plus human review.

Then feed every production failure back into the test set. A failure that slips through regression gets caught in production, routed to human review, and turned into a regression test so it cannot recur. That is the simulation-to-monitoring loop, and it is the same idea that made autonomous vehicles viable: you reach reliability through simulation, not by driving more miles.

**The practical starting point:** you do not need the full loop on day one. Start with one thing, a human review queue for anomalous production calls. Even 20 to 30 flagged calls a week surfaces patterns no amount of pre-production testing would have caught.

---

## The one-page eval strategy checklist

- [ ] I know my stage on the maturity curve.
- [ ] ALWAYS and NEVER lists are written and passing at 100% in easy mode.
- [ ] Easy-mode regression floor is locked before any harder personas were added.
- [ ] Personas broaden (accents, noise, interruptions) and deepen (multi-turn, tools, load).
- [ ] Every metric measures exactly one dimension.
- [ ] The LLM judge is calibrated against human review (above 85% binary agreement).
- [ ] Evals run automatically on every deploy, with threshold gates that block bad releases.
- [ ] The same suite runs on production traffic, with anomaly detection on 100% of calls.
- [ ] Production failures feed back into the regression suite.
- [ ] One named owner maintains the suite and reports results to each stakeholder in their language.

---

### Want a second set of eyes on your eval strategy?

A Coval solutions engineer will map where you are on the maturity curve and what the climb looks like for your stack. **Book a working session:** https://cal.com/coval-henry/eval-strategy-solutions-engineering

Prefer to run it yourself? The companion **Claude Code skill** scaffolds your eval strategy from this playbook, right in your terminal.

*Coval is the neutral measurement layer for voice AI: simulation, monitoring, and human review on one platform. coval.ai*
