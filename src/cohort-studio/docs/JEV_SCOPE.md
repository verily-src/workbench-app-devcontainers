# Jev fit and evaluation scope

## Join recommendation update — 2026-10-23

User requested source selection inside the join builder and Jev-assisted key
recommendations. This is now the proposed first Jev use, superseding the earlier
intent-routing priority below. Implementation is in progress; deployment and
live model inference are not verified.

- Select resource, schema and tables directly without loading dataset tabs.
  Start with Aurora; retain existing loaded/cross-source join behavior.
- Read accessible column types, PK/FK/unique constraints, indexes and table
  descriptions. Declared relationships take precedence over model suggestions.
- Use Jev typed choices to classify candidate columns as person, sample,
  variant, clinical event, concept, other or unknown, then rank a bounded list
  of compatible candidate pairs. Include abstention. Confidence is model
  confidence, not measured match rate or proof of a valid relationship.
- Inspect one projected row locally as a cheap first probe. `LIMIT 1` does not
  establish uniqueness, overlap or cardinality. If needed, use capped samples
  and indexed existence probes with read-only statement timeouts. Avoid full
  distinct counts and full joins during recommendation. Mark sampled evidence.
- Send schema metadata and local aggregate/type-shape summaries to the decision
  service, not raw records or identifiers. Use a separate validated decision
  adapter, server credentials, strict Pydantic models and existing resource access.
- Return candidate IDs, key pairs, evidence, confidence and any bridge path.
  Show up to three suggestions; users apply/edit keys and choose join type.
  No match means no recommendation. Bridge suggestions use discovered relations,
  never invented tables. Backend SQL generation remains deterministic.
- Cache within the resource/access context by schema signature and model version,
  with TTL, refresh and invalidation after imports. Do not depend on dataset IDs.
- Validate person→samples→genotypes→variants, composite keys, misleading matching
  names, unrelated cost_event_id/variant_id, null samples, duplicates, missing
  indexes, timeouts, unavailable Jev and backend restarts at API/browser boundaries.

Rechecked TypeSafe introduction and Choice documentation on 2026-10-23. The
model supports typed options and probabilities; local evidence must establish
database facts. SQL editing, autonomous execution and workflow actions remain
outside this update.

## Finding

Assumption: “Jev” means TypeSafe’s Jev System One decision model. It fits a small classifier or chooser in Cohort Studio. It does not fit as a replacement for the cohort assistant or the OMOP query engine.

Recommendation: keep this as an optional experiment. The current UI already
selects the OMOP assistant explicitly, so an extra classifier on every request
adds a network call without a demonstrated routing benefit. Intent routing
becomes useful if Studio introduces one entry point for cohort, workflow, and
app requests. Candidate ranking can be evaluated within the existing concept
search flow. Neither use is needed for the current release.

TypeSafe's API accepts a `state` and named typed questions (`choice`, `score`, or yes/no `noul`) and returns typed answers, probabilities, confidence for choice/score, and usage. Choice selects from options defined by the application; its documented limit is 255 options. Jev does not generate the prose or tool calls that the current assistant needs. See [TypeSafe introduction](https://docs.typesafe.ai/introduction), [Choice](https://docs.typesafe.ai/primitives/choice), and the [API reference](https://api.typesafe.ai/redoc).

OpenRouter documents Jev on a separate Decisions API: `POST https://openrouter.ai/api/alpha/decisions`, authenticated by the OpenRouter bearer key. The body has `model`, `state`, and `questions`; this is not the current `/chat/completions` tool loop. The OpenRouter article also documents TypeSafe's SDK pointed at `https://openrouter.ai/api`. See [OpenRouter’s Jev guide](https://openrouter.ai/blog/insights/what-is-jev/) and [TypeSafe models on OpenRouter](https://openrouter.ai/typesafe).

## Candidate use

- **Intent routing:** Evaluate a short user request against fixed, coarse options such as `omop_cohort`, `concept_search`, `workflow_status`, `app_status`, `general_question`, and `other`. Code can map a valid answer to an existing read-only handler. Jev must not choose arguments, invent tools, or run a workflow/app operation.
- **Concept candidate ranking:** Consider only after deterministic OMOP search returns a bounded candidate set. Ask Jev to choose among candidate IDs whose descriptions include the concept name, domain, and vocabulary context. Preserve the probabilities and require a user to select/apply the result. If there are too many candidates, narrow them with deterministic search first; do not send the full vocabulary. This remains a hypothesis until tested against adjudicated concept-search examples.
- **Not in scope:** Cohort membership, SQL generation, counts, attrition, eligibility, or direct data access. These are deterministic engine operations and stay authoritative. Jev cannot replace exact OMOP rules or the existing generative assistant’s explanations.

## Proposed implementation boundary

If approved after evaluation, add a separate decision-client method and strict Pydantic request/response models. Keep it separate from `providers.run` and `agent` chat/tool dispatch. Keep the API key server-side. Validate model output against the submitted option IDs, finite probabilities in range, and the expected question type before any route is selected. Reject unknown or missing answers as `other`/abstain; do not coerce malformed output.

The first use should be shadow-only: record the proposed route and confidence without changing dispatch. Do not log raw user text or patient-level data. Do not send patient records, cohort rows, or identifiers to TypeSafe/OpenRouter. Confirm the applicable data terms and retention controls before sending any user prompt or clinical text. TypeSafe says customer requests are not used to train Jev, but processing, telemetry, and retention still follow its terms and any ZDR agreement; see [TypeSafe data handling](https://help.typesafe.ai/articles/5974925716-how-is-submitted-data-used-or-retained).

## Evaluation before use

Build a labeled set from real, de-identified Cohort Studio requests. Include ambiguous, multi-intent, unsupported, workflow, app-status, and OMOP concept examples. Compare Jev with the current deterministic route and current assistant route. Measure per-class precision/recall, abstain rate, wrong-handler rate, confidence calibration, p50/p95 latency, errors, and actual billed usage. Use a pinned Jev version for evaluation; do not accept vendor speed/cost claims as project measurements. Set a confidence threshold from held-out data. Low confidence, unknown labels, API errors, or invalid responses must fall back to the existing route or ask the user. Promote only after shadow results and user-outcome tests show no wrong-handler increase.

For concept ranking, separately compare top-1 and top-k against reviewed concept IDs, including synonyms, neighboring concepts, domains, and no-match cases. Never turn the suggested concept into a cohort criterion without user review.

## Sources

- [TypeSafe System One introduction](https://docs.typesafe.ai/introduction)
- [TypeSafe Choice primitive](https://docs.typesafe.ai/primitives/choice)
- [TypeSafe model reference](https://docs.typesafe.ai/models)
- [TypeSafe API reference](https://api.typesafe.ai/redoc)
- [OpenRouter Jev guide and Decisions API](https://openrouter.ai/blog/insights/what-is-jev/)
- [OpenRouter TypeSafe model catalog](https://openrouter.ai/typesafe)
