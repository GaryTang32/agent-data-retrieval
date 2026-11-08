# Track 09: Quality, validation, human review, versioning and provenance for databases built from LLM extraction

Scope: how to keep an LLM-extracted database correct, versioned, auditable and reproducible, so that "same query + same snapshot -> same rows, each row traceable to source spans" holds. This track does not cover extraction methods, schema design or the query layer. "Author-reported" means the result comes from the authors of the method being evaluated. "Independent" means a third party measured it. Classic foundational papers are marked with their year.

Framing used throughout (my inference, built from the findings below): LLM extraction is a non-deterministic, drifting *measurement* process. Deterministic retrieval can only be guaranteed at the *storage/query* layer: frozen, versioned snapshots with exact predicates. The quality stack therefore has to (a) gate what enters a snapshot (validation, grounding, confidence routing, human review), (b) pin every snapshot to the exact extractor configuration that produced it (versioning), and (c) carry per-value lineage back to source spans (provenance).

---

## Q1. Validation: schema/type, constraints, cross-field consistency, data-validation frameworks, LLM-as-judge, grounding checks

### Takeaway
Deterministic, rule-based validation is cheap and exactly reproducible, and it has the best production evidence (Deequ at Amazon, TFX Data Validation at Google with more than 700 pipelines). It should be the first gate: schema/type checks, declarative constraints and cross-field rules, plus a *grounding check* that each extracted value occurs in or is entailed by its cited source span. LLM-as-judge and NLI-based grounding catch semantic errors that rules miss. They are probabilistic and biased, so they should be used to *prioritise* review, not as ground truth. Assertions mined from prompt history (SPADE) are a practical bridge between the two.

### Cited Findings

**Declarative data-quality "unit tests" (Deequ, 2018)**
- Deequ provides a declarative API that combines common quality constraints with user-defined validation code ("unit tests for data"). It compiles them into aggregation queries on Apache Spark, supports incremental validation on growing datasets, and uses ML for constraint suggestion and for anomaly detection on time series of quality metrics — [Schelter et al., PVLDB 11(12) 2018](https://www.vldb.org/pvldb/vol11/p1781-schelter.pdf)
- Its constraint vocabulary includes `hasCompleteness`, `isUnique` (including multi-column uniqueness), `hasConsistentType`, `isNonNegative`, `isInRange`, `satisfies(predicate)`, `satisfiesIf(predicate pair)` (a cross-field conditional rule) and `hasNoAnomalies(metric, detector)` — [Schelter et al. 2018](https://www.vldb.org/pvldb/vol11/p1781-schelter.pdf)
- Evaluation (author-reported) on about 120M product records (about 50GB Parquet) split into 10 deltas. For single-pass metrics (size, completeness), batch runtime grows linearly while incremental runtime stays constant. For grouping metrics (uniqueness, entropy), incremental computation has overhead but beats batch after 3–4 deltas — [Schelter et al. 2018](https://www.vldb.org/pvldb/vol11/p1781-schelter.pdf)
- Constraint suggestion from a 10% sample is useful but fallible. On a Twitter dataset it wrongly suggested `isUnique` for a column that was only 64% unique, and an `isInRange` set that missed rare languages. A classifier on column names gave the true key column 81% and the false one 2%. The authors call suggestion "human-in-the-loop" because suggested constraints may not hold for future data — [Schelter et al. 2018](https://www.vldb.org/pvldb/vol11/p1781-schelter.pdf)

**Schema-driven validation for ML data (TFX Data Validation, 2019)**
- A schema (protobuf) codifies expectations such as types, presence, domains and value counts. Single-batch validation checks each batch against the schema. Inter-batch validation detects drift and training/serving skew with distance thresholds. The schema is *inferred* initially, then curated by humans and committed to version control, and the system proposes schema edits when data evolves. It is used by "hundreds of product teams" over "several petabytes" per day — [Breck et al., MLSys 2019](https://mlsys.org/Conferences/2019/doc/2019/167.pdf)
- Production evidence (author-reported, more than 700 pipelines, 30-day window). The most frequent anomaly firings were new feature column (fired in 10% of pipelines, 65% fixed), out-of-domain categorical values (6%, 66% fixed) and missing feature column (6%, 53% fixed). Most pipelines had up to 5 schema revisions, which the authors read as data/schema co-evolution. More than 70% of pipelines defined model unit tests, which ran more than 80K times in a month with a 6% failure rate. Fixing a skew in Google Play raised app install rate by 2% — [Breck et al. 2019](https://mlsys.org/Conferences/2019/doc/2019/167.pdf)

**Dataframe-level validation libraries**
- Pandera (SciPy 2020) validates pandas dataframes at runtime against schemas covering types and statistical/distributional properties, including hypothesis-test checks — [Bantilan, SciPy 2020](https://proceedings.scipy.org/articles/Majora-342d178e-010.pdf)
- Great Expectations defines an "Expectation" as "a verifiable assertion about data". Its built-in library has more than 50 expectations (e.g., `expect_column_values_to_not_be_null`, `_to_match_regex`, `_to_be_unique`, `expect_table_row_count...`) — [Great Expectations docs](https://docs.greatexpectations.io/docs/reference/learn/terms/expectation/)
- When LLMs (GPT-3.5/GPT-4, 96 conditions each) were asked to write data-validation tests, few-shot prompting and explicit data context helped "to a point". The best configurations "complement, rather than substitute" an experienced analyst's gold-standard tests — [Alexander et al. 2023](https://arxiv.org/abs/2310.01402)

**Assertions specific to LLM pipelines**
- SPADE mines a pipeline's *prompt version history*: each instruction a developer added marks a failure mode. From these it synthesises candidate assertion functions and selects a minimal set that meets coverage and accuracy targets. Across 9 real LLM pipelines it cut the number of assertions by 14% and false failures by 21% versus simpler baselines. It was deployed in LangSmith for more than 2,000 pipelines (author-reported) — [Shankar et al. 2024](https://arxiv.org/abs/2401.03038)
- EvalGen ("who validates the validators?") generates candidate criteria and implementations (Python functions or LLM-grader prompts), asks humans to grade a sample of outputs, and keeps the implementations that best align with those grades. Users' criteria drift as they grade more outputs ("criteria drift"), so evaluation criteria cannot be fully fixed up front — [Shankar et al., UIST 2024](https://arxiv.org/abs/2404.12272)
- DocETL synthesises task-specific validation prompts as part of an agentic plan evaluation for document pipelines. It reports plans 25–80% more accurate than well-engineered baselines on 4 tasks (author-reported) — [Shankar et al. 2024](https://arxiv.org/abs/2410.12189)

**Grounding checks (does the value appear in, or follow from, the source span?)**
- LangExtract maps every extraction to its exact character location in the source. Extractions that cannot be located get `char_interval = None`, and the docs recommend filtering them out to "keep only grounded results". This catches values copied from few-shot examples rather than the input — [google/langextract README](https://github.com/google/langextract)
- MiniCheck trains small fact-checkers on synthetic GPT-4 data. MiniCheck-FT5 (770M) reaches GPT-4-level accuracy on the LLM-AggreFact grounding benchmark at about 400x lower cost (author-reported) — [Tang, Laban, Durrett, EMNLP 2024](https://arxiv.org/abs/2404.10774)
- AlignScore is a unified information-alignment function trained on 4.7M examples from 7 tasks (NLI, QA, paraphrase, fact verification, IR, semantic similarity, summarisation), used for factual-consistency checking of outputs against input — [Zha et al., ACL 2023](https://arxiv.org/abs/2305.16739)
- FActScore decomposes outputs into atomic facts and scores the fraction supported by a knowledge source. The automated estimator has less than 2% error versus human FActScore (author-reported) — [Min et al., EMNLP 2023](https://arxiv.org/abs/2305.14251)
- ContextCite attributes a generated statement to the parts of the context that caused it. It can be used to verify whether a statement is grounded, misinterpreted or fabricated — [Cohen-Wang et al., NeurIPS 2024](https://arxiv.org/abs/2409.00729)
- Self-verification for clinical IE has the LLM produce a provenance span for each extracted value and check its own output. It consistently improved accuracy across LLMs, and the spans make expert audit efficient (author-reported) — [Gero et al., IMLH 2023](https://arxiv.org/abs/2306.00024)

**Composite validation stacks in real deployments**
- In a multi-stage clinical IE validation on 919,783 notes (11 substance-use-disorder categories), rule-based plausibility filtering plus semantic grounding removed 14.59% of LLM-positive extractions as unsupported, irrelevant or structurally implausible. A higher-capacity judge LLM agreed with expert review on high-uncertainty cases at Gwet's AC1 = 0.80. With judge-evaluated outputs as reference, the primary LLM scored F1 0.80 under relaxed matching (author-reported) — [Mahbub et al. 2026](https://arxiv.org/abs/2604.06028)
- The VALID framework for LLM-extracted oncology EHR data combines (1) variable-level benchmarking against expert human abstraction, (2) automated internal-consistency and plausibility checks, and (3) replication analyses against human-abstracted or external datasets, with bias stratification by subgroup — [Estevez et al. 2025](https://arxiv.org/abs/2506.08231)
- De Jure uses LLM-as-judge over 19 explicit criteria with bounded iterative repair for regulatory-rule extraction, reaching peak quality within 3 judge-guided iterations (author-reported, no human gold) — [Guliani et al. 2026](https://arxiv.org/abs/2604.02276)

**LLM-as-judge reliability**
- GPT-4 judges reach more than 80% agreement with human preferences (about inter-human level) on open-ended chat, but show position, verbosity and self-enhancement biases — [Zheng et al., NeurIPS 2023](https://arxiv.org/abs/2306.05685)
- In a clean setting with high inter-human agreement, only the best and largest of 13 judge models aligned reasonably with humans, and they still deviated by up to 5 points from human scores — [Thakur et al., GEM 2025](https://arxiv.org/abs/2406.12624)
- CALM identifies 12 bias types in LLM-as-judge and finds that significant biases persist on specific tasks even for advanced models — [Ye et al., ICLR 2025](https://arxiv.org/abs/2410.02736)

**Structured-output validity is not correctness**
- JSONSchemaBench (10K real-world JSON schemas) evaluates constrained-decoding frameworks on efficiency, constraint-type coverage and output quality. Coverage of real schema constraints differs across frameworks — [Geng et al. 2025](https://arxiv.org/abs/2501.10868)
- Format restrictions (JSON/XML) significantly degraded LLM reasoning, and stricter constraints degraded it more — [Tam et al. 2024](https://arxiv.org/abs/2408.02442)
- SO-Bench (6.5K schemas, 1.8K image–schema pairs) finds persistent gaps in producing accurate, schema-compliant outputs from visual inputs, including documents — [Feng et al. 2025](https://arxiv.org/abs/2511.21750)

### Inferences
- **Method analysis.**
  - *Schema/type and constraint validation (Pydantic/JSON Schema, Deequ, GX, Pandera, TFDV):*
    - Determinism: fully deterministic given a pinned rule set.
    - Cost: near-zero per record, incremental on appends.
    - Failure modes: catches only *syntactic and structural* errors. A well-typed hallucinated invoice total passes.
  - *Cross-field/consistency rules* (e.g., line items sum to total, `end_date >= start_date`, foreign key exists):
    - Determinism and cost: deterministic and cheap.
    - Strength: the strongest cheap detector of semantic errors in tabular domains.
    - Failure modes: the rules must be written, and they cover only arithmetically or logically linked fields.
  - *Grounding — exact or fuzzy string match of the value to its cited span:*
    - Determinism: deterministic.
    - Effectiveness: catches fabricated values and values copied from the prompt.
    - Failure modes: fails for normalised or derived values (dates reformatted, units converted, inferred fields), which need an NLI check.
  - *Grounding — NLI/entailment checkers (MiniCheck, AlignScore):*
    - Determinism: deterministic only if the checker model and weights are pinned and run locally.
    - Cost: about 400x cheaper than GPT-4 checking (MiniCheck).
  - *LLM-as-judge:*
    - Determinism: non-deterministic (see Q3) and biased.
    - Use: best as a *triage signal* for review routing, and as an evaluator only after alignment with human grades (EvalGen).
- An extraction toolkit should store every validation result (rule id, rule version, pass/fail, metric) as data alongside the snapshot. OpenLineage's `dataQualityAssertions` facet (Q4) is a ready-made schema for this, so a snapshot's "quality certificate" is itself auditable.
- Validated-but-wrong is the dominant residual risk. Constrained decoding guarantees parseable JSON, not true values, and may even reduce accuracy (Tam et al.). Schema validity should be reported separately from field accuracy.

### Gaps
- I found no independent, head-to-head study comparing Deequ, GX, Pandera and TFDV on LLM-extracted data specifically. Evidence for these tools is author-reported and from classic tabular ML/data-engineering settings.
- I found no benchmark that measures the *recall* of grounding checks (string-match versus NLI) for normalised extracted fields (dates, currency, units) in document extraction.

---

## Q2. Uncertainty and confidence: calibration, selective prediction/abstention, conformal prediction, routing to human review, active learning and HITL costs

### Takeaway
Raw LLM confidence signals (token log-probabilities, verbalised confidence, self-consistency) are informative for *ranking* but poorly calibrated, and calibration direction varies by domain. Field-level confidence engines that fuse disagreement between differently prompted extraction calls with grounding and layout signals report the best separation (e.g., 99.1% accuracy at 80% coverage on DocILE, author-reported). Split-conformal calibration on a few hundred to a few thousand labelled fields per domain turns any score into a reject threshold with a finite-sample guarantee, at about 10% rejection rates in reported clinical extraction. Rejected fields go to human review. Reviewing LLM pre-annotations cuts human labelling time by about 50–80% in reported studies.

### Cited Findings

**Calibration of LLM confidence**
- Larger pretrained LMs are well-calibrated on multiple-choice/true-false questions in the right format. P(True) self-evaluation works and scales with model size — [Kadavath et al. 2022](https://arxiv.org/abs/2207.05221)
- For RLHF models (ChatGPT, GPT-4, Claude), *verbalised* confidences are usually better calibrated than conditional token probabilities, often cutting expected calibration error by a relative 50% (TriviaQA, SciQ, TruthfulQA) — [Tian et al., EMNLP 2023](https://arxiv.org/abs/2305.14975)
- Black-box confidence elicitation (verbalised, sampling-consistency, aggregation) is overconfident when verbalised. It improves with scale and with consistency across samples, but the white-box/black-box AUROC gap is narrow (0.522 vs 0.605) and no method consistently wins — [Xiong et al., ICLR 2024](https://arxiv.org/abs/2306.13063)
- Semantic entropy, which clusters sampled answers by meaning before computing entropy, predicts QA accuracy better than token-level baselines — [Kuhn, Gal, Farquhar, ICLR 2023](https://arxiv.org/abs/2302.09664)
- BSDetector combines sampled-answer consistency with self-reflection into a confidence score for any black-box LLM, and identifies incorrect answers better than alternatives — [Chen & Mueller, ACL 2024](https://arxiv.org/abs/2308.16175)

**Confidence for document field extraction specifically**
- ExtractConf finds that token log-probabilities, verbalised confidence and multi-sample self-consistency "collapse toward all-positive behaviour at practical thresholds" for field extraction. It fuses disagreement between two structurally different calls ("Hunter", schema-slot-driven, and "Mapper", document-driven), LLM-internal uncertainty, OCR, image quality and layout in a classifier. On DocILE (55 fields, 26% failure rate) it reports 0.928 ROC AUC, 70% lower selective risk than mean logprob, and 99.1% accuracy at 80% coverage. Zero-shot on CORD it reaches 0.858 AUC, and Lasso recalibration cuts ECE by 89% (author-reported, single-author preprint) — [Kumar 2026](https://arxiv.org/abs/2606.24420)
- HYCEDIS (pre-LLM) used a multimodal conformal predictor plus a variational anomaly detector to score confidence of document-IE outputs without modifying the host model, and generalised to OOD data (author-reported) — [Nguyen et al. 2022](https://arxiv.org/abs/2206.02628)
- In a preregistered audit of LLM entity extraction from threat-intel reports, micro-precision was 0.03–0.34 and verbalised ECE 0.53–0.94, even at flagship tier. Self-consistency frequency was useful for *prioritising* (it passed a top-30% precision-gain bar in all six test cells), yet single-sentence counterfactuals flipped 95.6–100% of high-confidence judgements. The author concludes: "confidence tiering may set review priorities, never truth" (single-author preprint) — [Qian 2026](https://arxiv.org/abs/2610.20417)

**Selective prediction and abstention**
- Selective classification lets a user set a target risk and rejects inputs to guarantee it with high probability. Example: 2% top-5 ImageNet error guaranteed with probability 99.9% at about 60% coverage (foundational, 2017) — [Geifman & El-Yaniv, NeurIPS 2017](https://arxiv.org/abs/1705.08500)
- Under domain shift, softmax-based abstention fails because models are overconfident on OOD inputs. A separately trained calibrator that predicts errors abstains better (2020) — [Kamath, Jia, Liang, ACL 2020](https://arxiv.org/abs/2006.09462)

**Conformal prediction**
- Conformal prediction gives distribution-free, finite-sample guarantees that prediction sets contain the truth with user-specified probability (e.g., 90%), for any pretrained model, given exchangeable calibration data — [Angelopoulos & Bates 2021/2023](https://arxiv.org/abs/2107.07511)
- Conformal risk control extends this to bounding the expected value of any monotone loss, e.g., false-negative rate or token-level F1 — [Angelopoulos et al., ICLR 2024](https://arxiv.org/abs/2208.02814)
- Conformal language modelling calibrates sampling-stopping and rejection rules so that the output set contains at least one acceptable answer with high probability — [Quach et al., ICLR 2024](https://arxiv.org/abs/2306.10193)
- Conformal factuality backs off LM outputs to less specific claims until a high-probability correctness guarantee holds, with few human-annotated samples — [Mohri & Hashimoto, ICML 2024](https://arxiv.org/abs/2402.10978)
- Survey of conformal prediction in NLP: model-agnostic and distribution-free, with open challenges around exchangeability and generation — [Campos et al., TACL 2024](https://arxiv.org/abs/2405.01976)
- Conformal prediction for LLM medical entity extraction (GPT-4.1, Llama-4-Maverick) covered FDA drug labels (1,000 labels, 97.7% accuracy over 128,906 entities via FactScore-style verification) and MIMIC-CXR (entity F1 0.81–0.84). Miscalibration *reversed direction* between domains: models were underconfident on structured labels (threshold about 0.06) and overconfident on free-text radiology (threshold up to 0.99). Conformal calibration still hit at least 90% coverage with 9–13% rejection (author-reported) — [Shrestha & Kim 2026](https://arxiv.org/abs/2603.00924)

**Human-in-the-loop cost and work allocation**
- GPT-3 labels cost 50–96% less than human labels for equivalent downstream performance, and mixing GPT-3 pseudo-labels with human labels does better under a fixed budget (2021) — [Wang et al., Findings EMNLP 2021](https://arxiv.org/abs/2108.13487)
- ChatGPT zero-shot beat MTurk crowd-workers on 4 of 5 tweet-annotation tasks at less than $0.003 per annotation, about 20x cheaper (independent of OpenAI) — [Gilardi et al., PNAS 2023](https://arxiv.org/abs/2303.15056)
- CoAnnotating allocates items between humans and the LLM by LLM uncertainty, up to 21% better than random allocation — [Li et al., EMNLP 2023](https://arxiv.org/abs/2310.15638)
- Using consistency-based detection of likely LLM mislabels to send those items to humans ("mixed annotation") matched or beat human-only active learning on 2 of 3 datasets — [Wang 2024](https://arxiv.org/abs/2401.07367)
- Snorkel (weak supervision via labelling functions): subject-matter experts built models 2.8x faster with 45.5% better predictive performance versus 7 hours of hand labelling (2017). It is the same weak-supervision machinery Evaporate uses to aggregate synthesised extractors — [Ratner et al., PVLDB 2017](https://arxiv.org/abs/1711.10160)
- GAIDA (HITL document annotation): OCR assistance cut region-creation and transcription time by up to 80.9%. Reviewing LLM pre-annotations cut semantic-labelling time by up to 73.7%, even though pre-annotations were only 78.86% (FUNSD) and 86.98% (WildReceipt) micro-F1. Single-annotator study, author-reported — [Mesabah et al. 2026](https://arxiv.org/abs/2610.26362)
- For systematic-review data extraction (112 studies), LLMs "struggled with extracting data accurately" and are "not ready to be used as primary data extraction tools without explicit human validation" — [Schroeder et al., ETR&D 2026](https://arxiv.org/abs/2501.11840)
- A survey of LLMs for annotation covers generation, assessment and use of LLM labels and their limitations — [Tan et al., EMNLP 2024](https://arxiv.org/abs/2402.13446)

### Inferences
- **Method analysis.**
  - *Token logprobs / verbalised confidence:*
    - Cost: free or nearly free.
    - Determinism: non-deterministic across runs.
    - Accuracy: miscalibrated in field extraction (all-positive collapse).
    - Use: fine as one feature, not as a gate.
  - *Self-consistency (k samples):*
    - Cost: k-times extraction cost.
    - Accuracy: ranks well, does not verify (Qian 2026).
  - *Cross-call disagreement* (two prompts or two models with different failure modes):
    - Cost: about 2x cost.
    - Accuracy: strongest reported field-level signal (ExtractConf).
    - Caveat: single-author, author-reported.
  - *Conformal threshold on any score:*
    - Cost: a one-time labelled calibration set per (domain × field-type × model version).
    - Guarantee: marginal (not per-field) coverage, valid only while data is exchangeable with the calibration set.
    - Recalibration: needed after any model, prompt or schema change, because the score distribution moves (Shrestha & Kim show calibration is domain- and model-specific).
- **Routing policy.** Per field, compute the score. Accept above the conformal threshold. Route below-threshold fields, and any field failing a deterministic validator or grounding check, to a review queue. Store the reviewer's decision as a versioned correction that overrides the extractor value in later snapshots, rather than editing the snapshot in place.
- **Cost model.** With about 10–20% of fields routed to review (Shrestha & Kim 9–13% rejection; ExtractConf 20% deferral at 99.1% accepted accuracy), and review of pre-filled values being about 3–4x faster than labelling from scratch (GAIDA), human cost scales roughly with (rejection rate × review time per field). It is not proportional to corpus size. This is my inference from combining separate studies, not a measured end-to-end figure.
- Reviewer decisions double as calibration and regression-test data (Q3, Q5), so HITL output should be stored as a gold set keyed by source span.

### Gaps
- I found no independent replication of ExtractConf's numbers and no public benchmark that fixes a protocol for field-level confidence in LLM document extraction.
- I found no study measuring how often conformal thresholds must be re-fit after model or prompt upgrades in production extraction.
- I found no rigorous, multi-annotator cost study ($ per accepted field) for LLM-plus-review document extraction. The GAIDA numbers come from one annotator.

---

## Q3. Versioning and reproducibility: data versioning, versioning extraction runs, re-extraction drift, regression testing, model deprecation risk

### Takeaway
LLM extraction is not reproducible even at temperature 0:
- **Provider-side** (independent studies): batch-dependent kernels, silent model updates and deprecations.
- **Prompt-side**: formatting changes alone swing accuracy by up to 76 points.
- **Model updates** cause instance-level "negative flips" that no single signal reliably predicts.

Determinism must therefore come from *materialising* extraction outputs into immutable, versioned snapshots: Iceberg/Delta snapshots, lakeFS/Nessie commits, DVC lock files. Each snapshot carries the full extractor fingerprint (model id, prompt hash, schema version, parser version, decoding parameters). Re-extraction under a new model becomes a *branch* that is diffed, regression-tested against a gold set and merged only after passing gates (write-audit-publish).

### Cited Findings

**Non-determinism of "deterministic" LLM settings**
- Five LLMs configured as deterministic, run 10 times on 8 tasks, showed accuracy variation of up to 15% across runs and a best-to-worst gap of up to 70%. None gave repeatable accuracy across all tasks, "much less identical output strings" (independent study) — [Atil et al. 2024](https://arxiv.org/abs/2408.04667)
- Root cause analysis: the forward pass is run-to-run deterministic, but inference-server kernels are not *batch-invariant*, and batch size depends on server load. With Qwen3-235B at temperature 0, 1,000 completions gave 80 unique outputs (diverging at token 103). Batch-invariant kernels made all 1,000 identical, at a cost of 26s → 42–55s (1.6–2.1x) on Qwen3-8B in vLLM — [He / Thinking Machines Lab, Sept 2025](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
- LLM outputs used as research data vary because of deliberate sampling, *silent model updates*, numerical rounding and expert routing. Temperature 0 removes only the first. "Exact reproduction is therefore generally not possible when using proprietary APIs", and outputs "should be treated as draws from a distribution rather than as fixed measurements". The authors propose a reporting standard (illustrated on sentiment classification of corporate filings feeding regressions) — [Coqueret et al. 2026](https://arxiv.org/abs/2607.24372)

**Drift across model versions (measured)**
- GPT-4 (March 2023) identified primes vs composites with 84% accuracy and GPT-4 (June 2023) with 51%. Behaviour of the "same" API model changed substantially within 3 months (independent) — [Chen, Zaharia, Zou, HDSR 2024](https://arxiv.org/abs/2307.09009)
- When base LLMs are updated, fine-tuned downstream adapters show "negative flips" (previously correct instances become wrong), even with identical training procedures. A compatibility adapter cut negative flips by up to 40% (Llama 1 → Llama 2) — [Echterhoff et al. 2024](https://arxiv.org/abs/2407.09435)
- Positive-congruent training (focal distillation, ensemble reference) reduces negative flips in classifier updates without hurting accuracy (2020, foundational for "regression-free updates") — [Yan et al., CVPR 2021](https://arxiv.org/abs/2011.09161)
- Across 6 benchmarks and 6 model-update pairs, *no universal signal* predicts sample-level regression. Confidence works best on MCQ and simple math, KL/likelihood-drift signals on harder math and code. Cross-version signals enable a "selective fallback" that routes high-risk samples back to the old model — [Sheng & Lu 2026](https://arxiv.org/abs/2608.13607)
- Prompt formatting alone (meaning-preserving) changed few-shot accuracy by up to 76 points (LLaMA-2-13B). Format sensitivity only weakly correlates across models, so a prompt tuned for model A is not portable to model B (independent) — [Sclar et al., ICLR 2024](https://arxiv.org/abs/2310.11324)
- TRAILS catalogues 38 mechanisms by which the same read-and-evaluate task (including data extraction) gives different judgements across repeated runs or fails silently. It argues that repeatability or accuracy alone "does not rule out a hidden judgement failure" — [Lunny et al. 2026](https://arxiv.org/abs/2610.39070)

**Regression testing of LLM pipelines**
- GPR-bench is an open bilingual regression suite (8 task categories × 10 scenarios) with LLM-as-judge scoring. Across gpt-4o-mini → o3-mini → o4-mini, correctness differences were small and not significant, while a prompt change (concise instruction) changed conciseness by +12.37pp (p < 0.001). Small regression suites may lack the power to detect model-version differences — [Morishige & Koshihara 2025](https://arxiv.org/abs/2505.02854)
- SPADE assertions (Q1) and EvalGen-aligned evaluators are natural regression tests: they encode past failures as executable checks — [Shankar et al. 2024](https://arxiv.org/abs/2401.03038); [Shankar et al. 2024](https://arxiv.org/abs/2404.12272)

**LLM API deprecation risk**
- OpenAI's minimum notice before retirement, unless safety or compliance requires faster: at least 6 months for generally available models and at least 3 months for specialised variants. `GET /v1/models` exposes a `shutdown_date` field for programmatic monitoring — [OpenAI deprecations page](https://platform.openai.com/docs/deprecations)
- Anthropic commits to at least 60 days' notice before retiring publicly released models, defines Active/Legacy/Deprecated/Retired states, and recommends testing newer models well before retirement dates — [Anthropic model deprecations](https://docs.anthropic.com/en/docs/about-claude/model-deprecations)
- Of 8,931 paper–model mentions in biomedical LLM papers (2022–Mar 2026), 77.7% used closed-weight commercial models. 42% involved a model already retired by publication or scheduled to retire within 2 years. Median time from publication to retirement was 538 days (independent) — [Wolfrath et al. 2026](https://arxiv.org/abs/2609.04699)

**Data versioning systems (storage layer)**
- Apache Iceberg: every write creates a snapshot. Spark SQL supports `TIMESTAMP AS OF` and `VERSION AS OF <snapshot-id | branch | tag>`, e.g., `SELECT * FROM prod.db.table VERSION AS OF 10963874102873`. Snapshots accumulate until `expireSnapshots`, which deletes unneeded data files, so an expired snapshot can no longer be time-travelled to. Tags retain historical snapshots for auditing, and branches support write-audit-publish testing — [Iceberg Spark queries](https://iceberg.apache.org/docs/latest/spark-queries/); [Iceberg maintenance](https://iceberg.apache.org/docs/latest/maintenance/); [Iceberg branching](https://iceberg.apache.org/docs/latest/branching/)
- Delta Lake stores an ACID transaction log in the object store. It provides time travel to point-in-time snapshots, rollbacks and audit logging (`DESCRIBE HISTORY`), and the authors note time travel is useful for reproducibility — [Armbrust et al., PVLDB 2020](https://www.vldb.org/pvldb/vol13/p3411-armbrust.pdf)
- lakeFS offers Git-like semantics over object stores: branching creates an isolated version, committing creates "a reproducible point in time", and merging incorporates changes "in one atomic action". It has zero-copy branching, pre-merge hooks for write-audit-publish quality gates, and the docs pitch per-agent isolated branches gated by pull requests — [lakeFS docs](https://docs.lakefs.io/)
- Project Nessie is a "Transactional Catalog for Data Lakes with Git-like semantics" for Iceberg tables, with "cross-table transactions and visibility" and branches/tags — [Project Nessie](https://projectnessie.org/)
- DVC keeps a `dvc.lock` file per pipeline that records the state (hashes) of stage dependencies and outputs. It detects when stage definitions or dependencies changed and invalidates stages that require reproduction — [DVC dvc.yaml/dvc.lock docs](https://dvc.org/doc/user-guide/project-structure/dvcyaml-files)
- Research systems:
  - DataHub proposed git-like branch/merge/diff for datasets (2014) — [Bhardwaj et al., CIDR 2015](https://arxiv.org/abs/1409.0798)
  - OrpheusDB "bolts on" versioning to a relational DB, with up to 20x faster version retrieval via LyreSplit partitioning (2017) — [Huang et al., PVLDB 2017](https://arxiv.org/abs/1703.02475)
  - The storage/recreation trade-off for version graphs is hard to approximate in general, but tractable for tree-like/low-treewidth graphs — [Guo et al. 2024](https://arxiv.org/abs/2402.11741)
  - Explain-Da-V synthesises data transformations that explain the changes between two dataset versions, i.e., *semantic* diffs — [Shraga & Miller 2023](https://arxiv.org/abs/2301.13095)

### Inferences
- **Method analysis.**
  - *Table-format snapshots (Iceberg/Delta):*
    - Determinism: exact, per-table query reproducibility by snapshot id.
    - Cost: storage of retained snapshots.
    - Failure modes: snapshot expiry or vacuum silently destroys reproducibility unless important snapshots are tagged.
  - *Catalog-level versioning (Nessie, lakeFS):*
    - Adds multi-table atomic commits. This is essential when an extraction run updates entity, relation and provenance tables together, otherwise a query could join a new entity table to an old provenance table.
  - *DVC:*
    - Good for file-level artefacts and pipeline DAG caching. It is less suited to row-level queries.
- **Extraction-run fingerprint.** Every row (or at least every snapshot) should record:
  - model id plus exact version or date (never a floating alias)
  - provider and region
  - decoding parameters
  - prompt template hash
  - few-shot example set hash
  - JSON-schema version
  - parser/OCR version
  - chunking parameters
  - validation-rule-set version
  - source document content hash

  This is my synthesis. Coqueret et al.'s reporting standard and DVC's lock-file mechanism are the closest published analogues. Because content hashes of inputs plus this fingerprint key a cache, re-running an unchanged configuration returns cached outputs, giving *deterministic replay* even though the model itself is non-deterministic.
- **Re-extraction policy.**
  1. Run the new model or prompt on a branch.
  2. Compute a field-level diff against main: negative flips on the gold set, changed values, newly null values.
  3. Gate the merge on (a) no statistically significant drop on the gold set and (b) negative flips on gold below a threshold.
  4. Optionally keep old values where the new model regresses (the "selective fallback" idea from Sheng & Lu, applied to fields).

  Because no single signal predicts regressions, a labelled gold set is indispensable.
- **Pinned open-weight models with batch-invariant kernels** are the only route to bit-exact re-extraction. They cost about 1.6–2x throughput (Thinking Machines). With closed APIs, accept non-reproducible extraction and make the *stored output* the reproducible artefact.
- Deprecation windows (60 days to 6 months) are shorter than typical data-retention needs, so the database must never depend on being able to re-run the original model.

### Gaps
- I found no published, controlled study that re-extracts the *same document corpus into the same schema* with successive commercial model versions and reports field-level churn rates. This is the most relevant missing measurement. Evidence is extrapolated from QA/classification drift (Chen et al.; Atil et al.; Sheng & Lu).
- I found no peer-reviewed evaluation of lakeFS or Nessie. Claims about them come from project documentation.

---

## Q4. Provenance and lineage: why/where/how-provenance, semirings, OpenLineage/PROV, span-level citations, attribution evaluation

### Takeaway
Database theory gives a precise vocabulary:
- **Where-provenance** answers "which source location was this value copied from?". For extracted records it is the document span.
- **Why-provenance** answers "which source facts justify this output tuple?".
- **How-provenance** (semiring polynomials) answers "how were they combined?". It survives downstream SQL/Datalog queries, so an agent's query answer can carry the exact set of source spans that produced it.

OpenLineage and W3C PROV standardise run-level lineage (which job, model and prompt produced which table version). Character-offset span grounding (LangExtract-style) supplies value-level where-provenance. Attribution metrics from QA (AIS/AutoAIS, ALCE citation recall/precision) show that model-generated citations are often unsupported, so citations must be *verified* rather than trusted.

### Cited Findings

**Foundational provenance theory**
- Buneman, Khanna and Tan distinguish *why-provenance* (source data that influenced the existence of an output) from *where-provenance* (locations in the source from which data was extracted) (2001) — [Buneman, Khanna, Tan, ICDT 2001](https://repository.upenn.edu/cis_papers/210)
- Provenance semirings: tuples are annotated with elements of a commutative semiring K (K-relations). Union adds annotations, join multiplies them, projection sums them. Set semantics, bag semantics, incomplete/probabilistic databases and why-provenance are all special cases. Provenance polynomials N[X] are the most general (universal) case: evaluation over any K "factors through" N[X] via a homomorphism. The paper extends to Datalog with formal power series (2007) — [Green, Karvounarakis, Tannen, PODS 2007](https://web.cs.ucdavis.edu/~green/papers/pods07.pdf)
- Survey structuring the field into why-, how- and where-provenance, their relationships (e.g., where-provenance is "contained" in why-provenance), and how-provenance for schema mappings (2009) — [Cheney, Chiticariu, Tan, FnT Databases 2009](https://homepages.inf.ed.ac.uk/jcheney/publications/provdbsurvey.pdf)
- Smoke integrates fine-grained lineage capture into physical operators of an in-memory engine, so that both capture overhead and lineage-query cost stay low ("lineage at interactive speed") — [Psallidas & Wu, PVLDB 2018](https://arxiv.org/abs/1801.07237)

**Run-level lineage standards**
- OpenLineage object model:
  - *Jobs* carry `sourceCodeLocation` (incl. git SHA) and `sourceCode` facets.
  - *Runs* have a client-generated UUID (v7 recommended) with START/COMPLETE events and facets such as `parent` and `errorMessage`.
  - *Datasets* have a `schema` facet, a `version` facet (e.g., Iceberg snapshot id), and input facets `dataQualityAssertions` and `dataQualityMetrics` (row/null counts, quantiles).
  - Static lineage can be emitted at design time (JobEvent, DatasetEvent).
  - A Column-Level Lineage dataset facet exists.

  [OpenLineage object model](https://openlineage.io/docs/spec/object-model); [Column lineage facet](https://openlineage.io/docs/spec/facets/dataset-facets/column_lineage_facet)
- W3C PROV-O defines core classes Entity, Activity and Agent, and properties `wasGeneratedBy`, `wasDerivedFrom`, `wasAttributedTo`, `used`, `wasAssociatedWith`, `startedAtTime`/`endedAtTime` (2013 Recommendation) — [W3C PROV-O](https://www.w3.org/TR/prov-o/)

**Span-level citations and attribution evaluation**
- AIS ("Attributable to Identified Sources") is a human-annotation framework for whether output content is supported by an identified source, with a two-stage annotation pipeline — [Rashkin et al., Computational Linguistics 2023](https://arxiv.org/abs/2112.12870)
- Attributed QA: human AIS ratings serve as gold. AutoAIS (an NLI classifier: 1 = attributable) correlates strongly with them and is suitable for development — [Bohnet et al. 2022](https://arxiv.org/abs/2212.08037)
- ALCE measures citation *recall* (is each statement fully supported by its cited passages?) and citation *precision* (is each citation needed?) using the TRUE NLI model (T5-11B). Even the best models lacked complete citation support 50% of the time on ELI5 — [Gao et al., EMNLP 2023](https://arxiv.org/abs/2305.14627)
- On the extractive-abstractive spectrum, more abstractive outputs raised perceived utility by up to 200%, cut properly cited sentences by up to 50%, and made users take up to 3x longer to verify citations — [Worledge, Hashimoto, Guestrin 2024](https://arxiv.org/abs/2411.17375)
- LangExtract's per-extraction `char_interval` offsets implement value-level where-provenance and flag ungrounded values — [google/langextract](https://github.com/google/langextract)
- Self-verification yields a short provenance span per extracted clinical value, making expert audit efficient — [Gero et al. 2023](https://arxiv.org/abs/2306.00024)

### Inferences
- **Concrete provenance model for an extraction toolkit** (my synthesis of the above):
  - **Value-level where-provenance.** Each extracted field value carries `(doc_id, doc_content_hash, page, char_start, char_end | bbox, extraction_run_id)`. Values that are derived rather than copied (normalised dates, sums) carry the list of contributing spans plus a transformation id. That list is why-provenance.
  - **Run-level lineage.** Each extraction run is an OpenLineage Run (or PROV Activity) linked to the model, prompt and schema fingerprint (Q3). It outputs a dataset version (an Iceberg snapshot id) and the `dataQualityAssertions` results (Q1).
  - **Query-level how-provenance.** If retrieval is SQL/Datalog over K-relations, annotating each base tuple with its span id lets any query answer return the provenance polynomial, i.e., exactly which spans were joined or unioned to produce each answer row. Positive-query semiring provenance is well-founded theory. Smoke-style capture shows it can be cheap. ProvSQL-style systems implement it in PostgreSQL (not verified in this session; see Gaps).
- **Determinism.** Where-provenance stored as offsets into a content-hashed document is fully deterministic and verifiable: re-slice the document and compare. Model-generated citations are not reliable (ALCE: 50% lacking full support), so citations must be *verified* (string match or NLI) before they enter the database.
- Attribution metrics (AutoAIS, ALCE citation recall/precision) can be repurposed as automated provenance-quality metrics: the fraction of stored values whose span entails the value.

### Gaps
- I did not retrieve primary documentation for ProvSQL or GProM in this session, so I cannot cite their current capabilities or overheads.
- I found no benchmark that evaluates *value-level* span attribution accuracy for structured document extraction. Attribution benchmarks (ALCE, AIS) target long-form QA text.

---

## Q5. Evaluation benchmarks and metrics for document extraction

### Takeaway
Use layered metrics:
1. Field-level exact-match precision/recall/F1 after normalisation, with ANLS/ANLS* for fuzzy string fields.
2. Table metrics: TEDS (tree edit distance over HTML) or GriTS (2D grid similarity) for table structure and content.
3. Record/graph-level alignment, which needs a matching step for unordered line items and entity IDs (VRDU matching, Object Aligner, GLIRM).
4. End-to-end "database accuracy": does the query over the extracted table return the gold answer?

Benchmarks with field-level gold: DocILE, VRDU, Kleister, FUNSD/CORD/SROIE-style KIE sets, OmniDocBench (parsing), SO-Bench and JSONSchemaBench (schema compliance).

### Cited Findings

**String-level metrics**
- ANLS (Average Normalized Levenshtein Similarity) was introduced with ST-VQA to tolerate OCR/recognition errors. Similarity below a threshold τ = 0.5 scores 0 — [Biten et al., ICCV 2019](https://arxiv.org/abs/1905.13648)
- DocVQA: 50,000 questions on 12,000+ document images. Human accuracy is 94.36% — [Mathew et al., WACV 2021](https://arxiv.org/abs/2007.00398)
- ANLS* extends ANLS to generative LLM outputs (lists, dicts, None), as a drop-in that stays compatible with prior ANLS. It was evaluated on 7 datasets and 20+ LLMs — [Peer et al. 2024](https://arxiv.org/abs/2402.03848)

**Table metrics**
- TEDS (Tree-Edit-Distance-based Similarity) compares predicted and gold tables as HTML trees. It was introduced with PubTabNet (568k table images) — [Zhong et al., ECCV 2020](https://arxiv.org/abs/1911.10683)
- GriTS evaluates tables "directly in its natural form as a matrix" via a polynomial heuristic for the 2D most-similar-substructures problem, with upper and lower bounds that are nearly identical in practice. It covers topology, content and location — [Smock et al., ICDAR 2023](https://arxiv.org/abs/2203.12555)

**Record- and graph-level metrics**
- Object Aligner scores JSON outputs deterministically by recursive tree alignment: Hungarian matching for unordered collections, sequence alignment for ordered ones, partial credit configured via JSON-Schema extensions. "Referential alignment" infers an ID bijection (Weisfeiler-Leman approximation) so scores are invariant to relabelling, and it emits ranked repair suggestions. The authors explicitly position it against LLM-judge evaluation, which is "expensive, opaque, and non-deterministic" — [Drchal 2026](https://arxiv.org/abs/2607.01972)
- RASG proposes GLIRM, a line-item metric "more aligned with practical BDIE use cases" than ANLS*, DocILE's metric and GriTS — [Cesista et al. 2024](https://arxiv.org/abs/2405.20245)

**Benchmarks with field-level gold**
- DocILE: 6.7k annotated business documents (plus 100k synthetic and about 1M unlabelled), 55 KIE classes, and line-item recognition. The test set has zero- and few-shot layouts — [Šimsa et al., ICDAR 2023](https://arxiv.org/abs/2302.05658)
- VRDU: rich schemas (diverse types, hierarchical entities), complex templates and a carefully designed matching algorithm. Generalising to new templates is still hard — [Wang et al., KDD 2023](https://arxiv.org/abs/2211.15421)
- Kleister: long documents. Charity has 2,788 reports, 61,643 pages and 21,612 entities. NDA has 540 documents. The best baseline F1 was 81.77 (NDA) and 83.57 (Charity) — [Stanisławek et al., ICDAR 2021](https://arxiv.org/abs/2105.05796)
- OmniDocBench evaluates PDF parsing across 9 document sources with 19 layout categories and 15 attribute labels, end-to-end and per task — [Ouyang et al., CVPR 2025](https://arxiv.org/abs/2412.07626)

**End-to-end table/database quality**
- Evaporate evaluates generated tables against gold attribute-value tables (Pair F1). Evaporate-Code (LLM-synthesised extraction functions) underperforms direct LLM extraction by 24.9% (13.8 F1 points). Evaporate-Code+ (many synthesised functions ensembled with weak supervision) beats direct extraction while processing about 110x fewer tokens, across 16 settings of 10k documents each (author-reported) — [Arora et al., PVLDB 2024](https://arxiv.org/abs/2304.09433)
- Downstream-utility validation: LLM-extracted diagnoses predicted later specialty-care engagement better than structured-data baselines (AUC 0.80) — [Mahbub et al. 2026](https://arxiv.org/abs/2604.06028). In De Jure, RAG answers grounded in its extracted rules were preferred over prior work in 73.8–84.0% of cases — [Guliani et al. 2026](https://arxiv.org/abs/2604.02276)

### Inferences
- **Metric determinism.**
  - Exact match, normalised F1, ANLS/ANLS*, TEDS, GriTS and Object Aligner are deterministic and suitable for CI regression gates.
  - LLM-judge scoring is not deterministic, so it should not gate merges without fixed seeds or local models plus human alignment.
- **Recommended metric set for a data-lake toolkit.**
  - Per field: precision, recall and F1 with type-aware normalisation.
  - Per field type: fuzzy ANLS* for free-text fields.
  - Per table: GriTS/TEDS.
  - Per record set: Object-Aligner-style matched F1 for line items and entity graphs.
  - Validity: schema validity rate, reported separately.
  - Provenance: grounding rate (fraction of values with a verified span).
  - Coverage: selective accuracy at the operating coverage (Q2).
  - End to end: a fixed set of SQL/Cypher queries with gold answers, executed against each snapshot (exact-match answer accuracy).

  The last item measures what agents actually experience, and it is deterministic by construction.
- **Code-synthesis extraction** (Evaporate-Code+) is attractive for reproducibility. Once functions are synthesised and frozen, extraction becomes deterministic code that can be versioned and re-run bit-exactly. The quality gap must be checked per domain.

### Gaps
- I found no standard public benchmark that scores *end-to-end query accuracy over a database built by LLM extraction* from heterogeneous documents. Evaporate's table-level Pair F1 is the closest.
- I did not independently verify the GLIRM or Object Aligner claims beyond their abstracts.

---

## Q6. Most effective quality-assurance stack and its cost

### Takeaway
The most effective stack combines evidence from production data-validation systems, field-level confidence work, conformal prediction and data-versioning practice. It is a layered gate in front of an immutable, versioned store:
1. Deterministic schema, type and cross-field validation.
2. Span grounding (string match, then a small NLI checker).
3. Calibrated field confidence from cross-call disagreement, with a conformal threshold.
4. Human review of rejected fields.
5. Commit to a branch with a full extractor fingerprint and lineage.
6. Regression tests on a gold set and query suite before merge.
7. Tagged snapshots for time travel.

Marginal cost is dominated by (a) any second extraction call (about 2x LLM cost) and (b) human review of the roughly 10–20% of fields deferred. Deterministic checks, grounding with small models, and versioning are comparatively negligible.

### Cited Findings
- Production validation is cheap and catches structural errors early: Deequ uses incremental metrics on Spark ([Schelter et al. 2018](https://www.vldb.org/pvldb/vol11/p1781-schelter.pdf)), and TFDV runs on more than 700 pipelines with 53–100% of fired anomalies fixed ([Breck et al. 2019](https://mlsys.org/Conferences/2019/doc/2019/167.pdf))
- Rule plus grounding filters removed 14.59% of positive LLM extractions as unsupported or implausible in a 919,783-note deployment — [Mahbub et al. 2026](https://arxiv.org/abs/2604.06028)
- Small grounding checkers match GPT-4 at about 400x lower cost — [Tang et al. 2024](https://arxiv.org/abs/2404.10774)
- Cross-call disagreement confidence reaches 99.1% accuracy at 80% coverage on DocILE (author-reported) — [Kumar 2026](https://arxiv.org/abs/2606.24420). Conformal thresholds give at least 90% coverage at 9–13% rejection in clinical extraction (author-reported) — [Shrestha & Kim 2026](https://arxiv.org/abs/2603.00924)
- Reviewing LLM pre-annotations cuts labelling time by up to 73.7% — [Mesabah et al. 2026](https://arxiv.org/abs/2610.26362). LLM labels are 50–96% cheaper than human labels — [Wang et al. 2021](https://arxiv.org/abs/2108.13487). LLM annotation costs under $0.003 per item, about 20x cheaper than MTurk — [Gilardi et al. 2023](https://arxiv.org/abs/2303.15056)
- Confidence should set review *priority*, not truth — [Qian 2026](https://arxiv.org/abs/2610.20417). LLMs are not ready as primary extractors without human validation in systematic reviews — [Schroeder et al. 2026](https://arxiv.org/abs/2501.11840)
- Write-audit-publish on branches with pre-merge hooks and atomic merges: [lakeFS](https://docs.lakefs.io/), [Iceberg branching](https://iceberg.apache.org/docs/latest/branching/), [Nessie](https://projectnessie.org/)
- Deterministic inference costs about 1.6–2.1x throughput with batch-invariant kernels — [Thinking Machines 2025](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
- Code-synthesis extraction cuts LLM tokens by about 110x while matching or beating direct extraction quality (author-reported) — [Arora et al. 2024](https://arxiv.org/abs/2304.09433)
- Prompt-history-mined assertions reduce false failures by 21% — [Shankar et al. 2024](https://arxiv.org/abs/2401.03038)

### Inferences
- **Recommended stack (ordered by cost-effectiveness; my synthesis).**

  | Layer | What | Deterministic? | Relative cost | Main failure mode |
  |---|---|---|---|---|
  | L0 | Constrained decoding to JSON Schema; store raw model output too | Validity yes, values no | ~0 | Valid-but-wrong; possible accuracy loss (Tam et al.) |
  | L1 | Type/schema plus declarative constraints (Pydantic/Pandera/GX/Deequ), cross-field arithmetic and logic, FK/uniqueness | Yes | ~0 | Only catches what rules encode |
  | L2 | Span grounding: exact or fuzzy match of value to cited offsets; NLI checker (MiniCheck/AlignScore, pinned locally) for normalised values | Yes (if pinned) | Low (small model) | Derived or inferred values; checker false negatives |
  | L3 | Field confidence: cross-call/cross-model disagreement plus grounding plus OCR/layout features, with a conformal threshold per field type | Threshold fixed per version | ~1–2x extraction LLM cost; one-time calibration labels | Exchangeability breaks under drift; recalibrate per model/prompt version |
  | L4 | Human review of deferred and failed fields; corrections stored as versioned overrides; also feeds gold set | Decisions recorded | Dominant variable cost (~10–20% of fields × review time) | Reviewer fatigue; criteria drift (EvalGen) |
  | L5 | LLM-as-judge on sampled outputs / high-uncertainty slices, aligned to human grades | No | Moderate | Biases; not a gate |
  | L6 | Versioned commit (Iceberg/Delta snapshot on lakeFS/Nessie branch) with extractor fingerprint and OpenLineage run plus quality facets; WAP merge gated on gold-set regression (negative flips) and query-suite exact-match | Yes | Storage | Snapshot expiry; floating model aliases |

- **Where determinism comes from.** It is achieved at L6, not by the extractor. Agents query a pinned snapshot id or tag, so identical queries return identical rows, and each row carries span offsets and the run id. Re-extraction with new models produces new snapshots, never in-place mutation.
- **Cost dominance.** For a large corpus, the LLM pass (×2 if using cross-call confidence) and human review dominate. Code-synthesis extraction (Evaporate-Code+) can cut the LLM pass by about 2 orders of magnitude for semi-structured, template-like documents, and has the side benefit of deterministic replay.
- **Minimum viable version** for an open-source toolkit:
  - L1, L2 (string grounding) and L6 are mandatory and nearly free.
  - L3 and L4 should be opt-in per field criticality.
  - A small gold set (a few hundred fields per document type) is needed for both conformal calibration and regression gating. The size is my inference from the standard split-conformal practice in [Angelopoulos & Bates](https://arxiv.org/abs/2107.07511), not a measured requirement.

### Gaps
- No source reports an end-to-end, all-in cost per correct field ($/field at a target accuracy) for a full stack like this. The cost figures above are assembled from separate studies on different tasks and are not directly additive.
- Independent (non-author) evidence for field-level confidence engines and conformal extraction is lacking. The strongest numbers are author-reported preprints from 2026.
