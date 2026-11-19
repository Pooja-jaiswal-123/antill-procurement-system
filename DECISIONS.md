# DECISIONS.md

Format: **noticed → decided → why.** Every item below is implemented in code or policy JSON (not just written down).

## A. Policy text and examples that needed interpretation

1. **Rule 5.3 limit symbol is garbled in the PDF** ("≥ ₹5,00,000"). _Decided:_ Emergency PO when value **≤ ₹5,00,000**. _Why:_ worked example 8 (₹2,53,184 → EMERGENCY_PO) and the intent (an emergency allowance with an upper cap); ≥ would make every large emergency a PO.
2. **Rule order.** _Decided:_ new item (1.2) → capex (5.1) → contract (5.2) → emergency (5.3) → spot (5.4) → RFQ (5.5) → RFP (5.6). _Why:_ 1.2 says new items _always_ go to sourcing; example 12 says capex is checked before contracts.
3. **"Within 14 calendar days" of clubbing.** _Decided:_ difference between the **dates** (not hours) of the line and the requirement's first line ≤ 14; need-by within ±7 days of the **first line's** need-by (not the latest line). A line joins the earliest requirement it qualifies for. _Why:_ 2.2 says "first line" for both tests.
4. **Example 14 looked inconsistent with 24 h consolidation, but it is not.** Clubbing gives R1 = {PR-34, PR-32} (₹32,547) and R2 = {PR-31, PR-35} (₹23,227: PR-35 joins PR-31 because need-by differs by 5 days). R2's first line (3 Nov 10:30) is within 24 h of R1's (2 Nov 14:05), so both requirements sit on one PO. Reproduced exactly by the engine (test included).
5. **Requirement date** = date of the first line. Contract validity, PO history, supplier lists and the _policy version_ are all evaluated as of that date. A requirement is an emergency if **any** line is Emergency.
6. **Free-text "urgent"** (e.g. "nitrile coated gloves - urgent" with Urgency=Normal). _Decided:_ the Urgency column is the only source of emergency status; "urgent", "as per sample", "(repeat)" are noise words stripped before matching. _Why:_ 2.3 says "marked Emergency"; guessing emergency from prose would let people dodge sourcing.

## B. Valuation and contracts

7. **Unit price for valuation (3.1b)** = price on the most recent PO in the 365 days before the requirement date from **any** supplier (even one that is now Blocked) — it is a price benchmark, not a purchase. The PO's own `unit_price` is the first preferred supplier's reference price (6.3), so `group_value_inr` ≠ qty × unit_price on spot POs; that matches example 5 (₹126,472 value vs ₹166 shown).
8. **Contract eligibility (4.1):** covers item, start ≤ requirement date ≤ end, supplier Active. So the contract of blocked supplier S004 (RC-2026-005, aluminium plate) is **not** applicable (matches example 10 valued at ₹365/kg, not the contract rate), expired contracts are not usable but _do_ put their supplier on the preferred list (6.1b), and RC-2026-033 (starts 20 Nov) only applies to requirements created on/after 20 Nov.
9. **Ceiling consumption (4.2):** requirements are processed in creation order; a contract's ceiling is reduced **only when a requirement is actually placed on it** (route CONTRACT_PO). PDF-only contracts start at zero. A requirement that uses nothing consumes nothing. Ceiling check is inclusive (`consumed + value ≤ cap`). Ties on rate → lower contract id. Ceilings are recomputed from the register baseline on every run (idempotent reprocessing); approvals of earlier runs do not change the baseline.
10. If all applicable contracts are out of ceiling the requirement is valued at the lowest applicable contract rate and falls through to 5.3+ (example 3).

## C. Preferred supplier ranking (6.2) — my design

`score = 0.35·frequency + 0.25·recency + 0.15·contract + 0.15·on-time + 0.10·quality`

- _frequency_ = POs in the 548 days ÷ the largest PO count among suppliers on the list (so it is relative to the item); _recency_ = 1 if last PO ≤ 90 d, 0.5 if ≤ 365 d, else 0 (exactly the buckets in the worked examples); _contract_ = 1 if the supplier has held a contract for the item that started on/before the date (even expired); _on-time_ = on_time_pct/100 and _quality_ = rating/5 from the supplier master.
- Tie-breaks: higher on-time %, higher quality, lower supplier id.
- **Why these weights:** how often we buy is the strongest evidence of a proven supplier (35), recency shows the relationship is live (25); a contract is a negotiated price but should not outrank a supplier we use constantly (15); delivery matters more than quality for a direct PO without quotes (15 vs 10). **Validated** against all three lists in Worked_Examples (ITM-1048, 1036, 1016) — same order; tests included. Weights, recency buckets and window are in the policy JSON, so a policy amendment can change them without code.
- _Reference price (6.3):_ most recent PO price in the window (ties: later PO number); else the rate of the most recent contract for the item.
- _Window:_ POs dated from (date − 548 days) up to and including the date.
- Buyers see every term of the score ("why") in the workspace and on the Preferred suppliers screen.

## D. Suggestions for sourcing (6.4)

11. Preferred list first, in order. Top-up from Active suppliers whose categories include the item's category, ordered by **mean of on-time/100 and quality/5** (equal weights). _Why:_ "best delivery and quality record first" is ambiguous; this ordering reproduces examples 9, 10 and 11, while on-time-only does not.
12. If fewer Active candidates exist than 3/5, I suggest fewer rather than pad with Blocked/Inactive suppliers (5.7) or off-category ones (e.g. lubricants have only two Active suppliers).
13. 5.3/5.4 "bought from an Active supplier in the last 365 days" = a PO in the 365 days before the requirement date from an Active supplier. The "1st preferred supplier" may be a different supplier (e.g. contract-only or 548 d window); that is what 5.3/5.4 literally say. If the preferred list were ever empty the rule is skipped (never a PO without an Active supplier).

## E. Data problems → NOT_PROCESSED or special handling

14. **Quantity ≤ 0 or missing** (PR-26-00172, qty 0) → `NOT_PROCESSED`: value is 0 and any limit would be meaningless; returned to requester. Not clubbed with others.
15. **Unknown plant** (PR-26-00173, plant PUN2 is not in plants.csv) → `NOT_PROCESSED`; I will not guess a plant. Missing need-by date → `NOT_PROCESSED` too.
16. **Item code given but not in the master** → try the description, else new item. **Description that is ambiguous** (two close candidates) → treated as NEW item with the candidates written in the reason, never a coin-flip match; numbers/sizes are decisive in matching (6308 ≠ 6205).
17. **New item without estimated price** → still NEW_ITEM_SOURCING (route does not depend on value) with value 0 and a note. (No such line in the sample batch.)
18. Item master UoM vs PR UoM: no mismatches in the data; not enforced.

## F. Consolidation (7)

19. Only requirements that end in a PO are combined, never across routes (an EMERGENCY_PO and a SPOT_PO to the same supplier stay separate), plants or suppliers. 24 h is measured from the first requirement on that PO to each candidate's first-line creation time (not a sliding window). Sourcing requests are never combined.
20. PO ids are sequential in creation order (`PO-0001…`). The worked examples show other numbers (e.g. PO-0011); those cannot be derived from the policy, so I only guarantee that lines sharing a PO share a `po_id`.

## G. Policy as data (versions, dates, new rule kinds)

21. A policy = params (windows, limits' inputs, clubbing/consolidation settings, valuation order, ranking weights) + ordered rules `{when: all/any/not of {field, op, value}, outcome: {decision, route, supplier: contract|preferred_1|none, suggest N}}`. Fields available to conditions: item_type, category, plant, value, is_emergency/urgency, contract_usable, bought_recently, is_new_item, item_code, quantity, department, line_count. So "only CHK1 Lubricants → RFQ" or "Safety items: spot limit ₹5 L" are new rules, not code. Policy v5.0 is stored as JSON (`policies/policy_v5_0.json`).
22. **Versioning:** draft → (validated + plain-language diff) → approved/active. The version applied to a requirement is the latest active version whose effective date ≤ the requirement date, so an amendment effective 10 Nov changes only requirements created from 10 Nov and leaves earlier ones under v5.0; one batch can therefore mix versions (shown in `policy_version`). Clubbing/consolidation parameters come from the version of the first line.
23. **Invalid drafts are never activatable** (unknown field/operator, a PO rule without a supplier mode, …). New _routes_ (names) are allowed because routes are labels; new _facts_ (a new field) would need a small code change — the one limit of "no code change".
24. Reading amendment documents uses Grok (strict JSON, then validated and diffed deterministically by code, never trusted blindly). Without an API key, JSON import still works.
25. Blocked/Inactive exclusion (5.7) is enforced in the engine, not in policy data, so no amendment can switch it off. Overrides can't pick a non-Active supplier either.

## H. Chat intake

26. The LLM (when configured) only **extracts fields**; the dialogue, item matching and PR creation are deterministic code, so the assistant cannot invent an item, skip a question or create a PR without confirmation. Items come only from the master: confident match → accept; unsure → show up to 5 real candidates + "none – new item"; unknown → new item (asks for estimated price).
27. "next Friday" = Friday of next week; "Friday" = the coming Friday. Past dates are rejected. Chat PRs get the server time as `created_at`; they are numbered `PR-CH-nnnnn` and live in a persistent "Chat PRs" batch that the buyer processes (clubbing then applies across them).

## I. Known limits / next steps

- Approved POs are recorded (and audited) but do not add to contract consumed value for later runs (decision 9).
- Policy documents with entirely new _facts_ need a developer to expose the fact.
- Free-text matching is token/fuzzy based; Grok is only used for chat extraction and policy reading, so batch results are reproducible and offline.
