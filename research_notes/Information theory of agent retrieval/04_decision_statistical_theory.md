# Decision-theoretic, statistical and database-theory guarantees for agent retrieval and data conversion

Scope: track 04 of 5. Covers optimal stopping and value of information, bandits and submodularity, aggregation of noisy judgments, conformal prediction and prediction-powered inference, record linkage, database-theory guarantees, and calibration. Information theory, IR theory, LIS and LLM capacity/hallucination theory are covered by other tracks.

The methods being justified come from the earlier reports in `/home/user/agent-data-retrieval/reports/`:
- **R1, "Deterministic retrieval data conversion.md"**: extract once and materialize; L3 cross-call disagreement plus a conformal threshold per field type; L4 human review of deferred fields; Fellegi–Sunter/Splink entity resolution; where/why/how provenance; snapshot pinning plus a total `ORDER BY` with a primary-key tiebreaker.
- **R2, "Searchable agent knowledge base construction.md"**: bounded 2–3 round search loops with a stopping rule ("two retrieval iterations captured 95% of the gains of five"); abstain or flag when context is insufficient; LLM judges calibrated with about 150–300 human labels via PPI (ARES); conflicts handled in the data layer.
- **R3, "Agent ready data lake toolkit.md"**: an entity-resolution-driven graph, typed tools, and permission pre-filters.

Conventions:
- Each entry gives **Result** (statement and assumptions), **Proof** (sketch or where the proof is), and **Maps to** (the method it justifies or bounds).
- Text marked *[inference]* is my own mapping or derivation, not a claim made by the cited source.

---

## Q1. When to stop searching: optimal stopping, value of information, search theory, Gittins, and adaptive retrieval

### Takeaway
Classical stopping theory supports a bounded search loop. In "monotone" problems the myopic one-step look-ahead rule is optimal: stop as soon as the expected new evidence from one more round is worth less than its cost. When the per-round discovery rate decays geometrically (Ferguson's proofreading model), that rule reduces to a **fixed, small number of rounds**, which is the structure of the "2–3 rounds" finding. Pandora's-box (Weitzman) and Gittins indices give the optimal order in which to open sources and when to stop. Expected value of free information is never negative, but it is not free: the cost term is what makes stopping optimal. Recent LLM work already instantiates Pandora's box for best-of-N, model cascades and routing, with regret and value-of-information guarantees. No theorem I found derives "2 rounds" for multi-hop RAG directly; the mapping relies on modelling assumptions (monotonicity, conditional independence, known costs) that need empirical checking.

### Cited Findings

**1.1 Optimal stopping: secretary problem (1/e rule).**
- *Result.* Applicants arrive in random order, only relative ranks are observed, there is no recall, and the payoff is 1 only for picking the overall best. Then the optimal rule is a threshold rule N_r: "Reject the first r−1 applicants and then accept the next relatively best applicant". For large n the optimal r/n → e^{-1}, and P(win) → e^{-1} ≈ 0.368 — [Ferguson, Optimal Stopping and Applications, Ch. 2](https://www.math.ucla.edu/~tom/Stopping/sr2.pdf).
- *Proof.* P_r = Σ_{k=r}^{n} (1/n)·(r−1)/(k−1). Using Σ 1/(k−1) ~ log(n/r) gives log(n/r_1) = 1 — [Ferguson Ch. 2](https://www.math.ucla.edu/~tom/Stopping/sr2.pdf). The history and attribution are in [Ferguson 1989, "Who solved the secretary problem?", Statistical Science](https://doi.org/10.1214/ss/1177012493).
- *Maps to.* The secretary assumptions (no recall, rank-only information, no per-step cost) do **not** fit agent retrieval. Retrieved passages can be recalled, scores are cardinal, and every call costs tokens. The 1/e rule should not be cited to justify an "explore 37% of the budget" heuristic. *[inference]*

**1.2 Selling an asset with recall and observation cost; Weitzman's Pandora's box.**
- *Result (i.i.d. offers, cost c per observation, with recall).* The optimal rule accepts the first offer ≥ V*, where V* solves E(X − V*)^+ = c. Recall is never used, because the problem is time-invariant — [Ferguson, Ch. 4 §4.1](https://www.math.ucla.edu/~tom/Stopping/sr4.pdf).
- *Result (Weitzman 1979).* There are k boxes; box i has a known reward distribution D_i and opening cost c_i, and the goal is to maximize (best observed reward − total cost). Give each box its "fair-cap" (reservation) value τ_i, defined by E_{v∼D_i}[(v − τ_i)^+] = c_i. Open boxes in decreasing order of τ_i, and stop when the best reward seen exceeds the largest τ among the unopened boxes. For identical boxes this is "sample until max_{i≤n} v_i ≥ τ" — [Kalayci, Raman, Dughmi 2025 (restating Weitzman)](https://arxiv.org/abs/2510.01394); original: [Weitzman 1979, Econometrica](https://doi.org/10.2307/1910412).
- *Proof.* Olszewski & Weber note that the Gittins index theorem applied to an equivalent bandit proves Pandora's rule. They also show that a generalized Pandora rule is optimal for all costs and distributions only if the objective has a special form, so it is not optimal for arbitrary functions of all discovered prizes — [Olszewski & Weber 2015](https://arxiv.org/abs/1509.09095).
- *LLM instantiations.* A UCB-style Pandora algorithm with unknown reward distributions has vanishing regret relative to Weitzman's oracle policy. It matched Best-of-N reward with 15–35% fewer generations on AlpacaFarm/HH-RLHF — [Kalayci et al. 2025](https://arxiv.org/abs/2510.01394). An online contextual Pandora's-box model for LLM API cascading achieves Õ(√T) regret — [Belloni, Chen, Wei 2026](https://arxiv.org/abs/2606.07392). "Pandora's Router" models routing with costly value estimation. Under a Gaussian signal model it gives closed-form value-of-information expressions for whether to refine an estimate, including for retrieval-augmented specialists — [Fisch, Trivedi, Huot 2026](https://arxiv.org/abs/2608.20316).
- *Maps to.* R2's search loop. Each candidate query, sub-question or source is a "box" with cost c_i (tokens, latency) and an uncertain evidence yield. The reservation-value rule says to **stop when the best evidence in hand beats every unopened option's reservation value**. That gives the stopping rule a principled form beyond a fixed round count. Caveat: in Pandora's box only the single best prize counts, whereas multi-hop QA needs *several* complementary pieces (see 1.6 and Q2). *[inference]*

**1.3 Monotone stopping problems: the one-stage look-ahead rule is optimal, and the proofreading model gives a fixed-round rule.**
- *Result.* Let A_n = {Y_n ≥ E(Y_{n+1}|F_n)}. The problem is *monotone* if A_0 ⊂ A_1 ⊂ … a.s., meaning that once myopic stopping is indicated it stays indicated. "In a finite horizon monotone stopping rule problem, the one-stage look-ahead rule is optimal". Under extra integrability conditions this extends to infinite horizons — [Ferguson, Ch. 5, Theorem 1](https://www.math.ucla.edu/~tom/Stopping/sr5.pdf).
- *Proof.* Backward induction: V_n^{(J)} = max{Y_n, E(V_{n+1}^{(J)}|F_n)}. Monotonicity means the 1-sla stopping set is absorbing, so it coincides with the optimal rule — [Ferguson Ch. 5](https://www.math.ucla.edu/~tom/Stopping/sr5.pdf).
- *Proofreading model (Yang, Wackerly & Rosalsky 1982, as solved in Ferguson Example 5.4).* Each proofreading pass costs c_1, and each undetected misprint costs c_2. The 1-sla is "stop at the first n with E{X_{n+1}|X_1..X_n} ≤ c_1/c_2", and it is optimal when the problem is monotone. Suppose M ∼ Poisson(λ) and each remaining misprint is found with probability p per pass. Then the posterior of what remains is Poisson(λ(1−p)^n), so E{X_{n+1}|·} = λp(1−p)^n. The optimal rule is N_1 = min{n : λp(1−p)^n ≤ c_1/c_2}, "a fixed sample size rule" — [Ferguson Ch. 5](https://www.math.ucla.edu/~tom/Stopping/sr5.pdf). The problem statement notes the same model applies to deciding when to stop testing software — [Ferguson Ch. 1](https://www.math.ucla.edu/~tom/Stopping/sr1.pdf).
- *Maps to.* This is the closest classical theorem to R2's "two retrieval iterations captured 95% of the gains of five" ([Shaikh 2026](https://arxiv.org/abs/2606.21553)), the "at most two or three search-and-read rounds with a stopping rule" policy, and RAAC's finding that most deep-research iterations "contribute little or no improvement" ([Soudani et al. 2026](https://arxiv.org/abs/2608.15191)). See the Inferences for a worked derivation.

**1.4 Chow–Robbins theory and the S_n/n problem.**
- *Result.* Chow and Robbins (1961, 1963) built the general existence theory for optimal stopping rules. Ferguson's Chapter 3 follows "the method of Chow and Robbins (1963)" — [Ferguson Ch. 3](https://www.math.ucla.edu/~tom/Stopping/sr3.pdf); [Chow & Robbins 1963](https://doi.org/10.1007/BF00535296).
- *The "maximize the average" problem.* With Y_n = S_n/n, an optimal rule exists if E sup_n(S_n/n) < ∞, which holds iff E X log^+ X < ∞. The optimal rule has the form "stop when S_n/n ≥ a_n" for a non-increasing sequence a_n. Chow and Robbins (1965) showed it stops with probability one in the Bernoulli case — [Ferguson Ch. 4 §4.6](https://www.math.ucla.edu/~tom/Stopping/sr4.pdf); [Chow & Robbins 1965](https://doi.org/10.1215/ijm/1256068146).
- *Maps to.* Mostly background. It shows that "stop when the running quality average is high enough" is an optimal *form*, but even simple cases (Bernoulli) have no closed-form thresholds, so thresholds must be learned or calibrated (see Q4). *[inference]*

**1.5 Value of information is non-negative when free, and value differs from Shannon information.**
- *Howard (1966).* "no theory that involves just the probabilities of outcomes without considering their consequences could possibly be adequate in describing the importance of uncertainty to a decision maker". Information value theory prices information by its effect on decisions — [Howard 1966, IEEE Trans. SSC](https://doi.org/10.1109/TSSC.1966.300074).
- *Good (1967) / Savage (1954).* "if degrees of belief are updated by conditionalization, the expected utility of information obtained at negligible cost is never negative". The result generalizes to Jeffrey's probability kinematics — [Graves 1989, Philosophy of Science](https://doi.org/10.1086/289490); original [Good 1967, BJPS](https://doi.org/10.1093/bjps/17.4.319).
- *Proof.* E_X[max_a E(U(a)|X)] ≥ max_a E_X[E(U(a)|X)] = max_a E U(a), because the expectation of a maximum is at least the maximum of expectations — [Graves 1989](https://gwern.net/doc/statistics/decision/1989-graves.pdf). The guarantee holds in expectation only. A particular retrieval can lower realized utility, as R2's evidence on misleading retrievals shows.
- *VOI and submodularity.* Information gain is monotone ("information never hurts") but **not submodular in general**. With X, Y independent fair bits and Z = X XOR Y, observing X alone or Y alone gives zero information about Z, but both together determine it. If the observed variables S are conditionally independent given the targets U, then F(A) = H(U) − H(U∖A | A) is submodular and non-decreasing, so greedy selection gets (1 − 1/e) — [Krause & Guestrin 2005](https://arxiv.org/abs/1207.1394).
- *Maps to.* R2's evidence that adding retrieved content can hurt (ClashEval, RAGuard) does not contradict Good's theorem. Good assumes Bayesian conditioning on *true* evidence with *free* processing, and LLMs violate both. The XOR example is the formal signature of multi-hop questions (see Inferences). *[inference]*

**1.6 Bayesian search theory (Stone; Blackwell): which cell to search next.**
- *Result.* After an unsuccessful search of a cell with prior p and detection probability q, the posterior is p′ = p(1−q)/(1−pq). The optimal policy is "at each stage, look into the location which maximizes" p_i·a_i/c_i (probability present × detection probability per search ÷ cost). The article attributes the solution to Blackwell and calls the rule a special case of the Gittins index; it cites Stone's *Theory of Optimal Search* (1975 Lanchester Prize) as the classical book — [Wikipedia, Bayesian search theory](https://en.wikipedia.org/wiki/Bayesian_search_theory); [Stone 1989, Operations Research](https://doi.org/10.1287/opre.37.3.501).
- *Limit of the greedy rule.* For one hidden object, searching the "most inviting" box is optimal even with Bayesian uncertainty about the distribution's parameters, and the same holds for m = 2 boxes. "for n > 1 the optimal strategy may be very different from that of the classical model, even when the uncertainty about π is very small" — [Assaf & Zamir 1985, Annals of Statistics](https://doi.org/10.1214/aos/1176349665).
- *Maps to.* Source and index selection in R2/R3 (BM25 vs dense vs graph vs file grep). Rank sources by P(answer is there) × P(found if there) ÷ cost, and after a miss, down-weight that source by Bayes' rule rather than re-querying it. Assaf–Zamir shows that greedy "most likely source" logic is only safe for **single-target** questions, and multi-evidence questions need a different policy. *[inference]*

**1.7 Gittins index: optimal allocation among independent "projects".**
- *Result.* For a discounted multi-armed bandit whose arms are independent Markov projects and where only the played arm changes state, the policy that always plays the arm with the highest dynamic allocation (Gittins) index is optimal — [Gittins 1979, JRSS-B](https://doi.org/10.1111/j.2517-6161.1979.tb01068.x).
- *Proof.* Weber (1992) gives "a new proof of the optimality of the Gittins index policy" that "is intuitive and does not require an interchange argument". He also shows "the optimal value function is a submodular set function of the available projects" — [Weber 1992, Annals of Applied Probability](https://doi.org/10.1214/aoap/1177005588).
- *Maps to.* Choosing which sub-question or source to pursue next in a multi-source agent. Arms must be independent, and pursuing one must not change the others, which cross-referencing evidence violates. Weber's submodularity result gives formal "diminishing returns in the number of available sources". *[inference]*

**1.8 Sequential tests (Wald–Wolfowitz).**
- *Result.* The SPRT minimizes expected sample size under both hypotheses among all tests with the same or smaller error probabilities — [Wald & Wolfowitz 1948, Annals of Mathematical Statistics](https://doi.org/10.1214/aoms/1177730197). Ferguson treats Bayesian sequential testing as a stopping problem, with rules of the form N_{α,β} = min{n : λ_n ≤ α or λ_n ≥ β} — [Ferguson Ch. 4 §4.5](https://www.math.ucla.edu/~tom/Stopping/sr4.pdf).
- *Maps to.* "Answer / keep searching / abstain" is a three-way sequential test on the likelihood ratio of "context sufficient" vs "insufficient". It has the same three-region structure as Fellegi–Sunter (Q5) and Chow's reject option (Q4). *[inference]*

**1.9 Adaptive retrieval for LLMs ("when to retrieve"): mostly empirical, with a few risk certificates.**
- *Empirical.* LMs "struggle with less popular factual knowledge", and retrieving "only when necessary" improves accuracy while reducing cost — [Mallen et al. 2023](https://arxiv.org/abs/2212.10511). Self-RAG trains reflection tokens to retrieve on demand — [Asai et al. 2023](https://arxiv.org/abs/2310.11511). FLARE retrieves actively during generation — [Jiang et al. 2023](https://arxiv.org/abs/2305.06983). Adaptive-RAG routes no-retrieval / single-step / iterative by a predicted complexity class — [Jeong et al. 2024](https://arxiv.org/abs/2403.14403). These are heuristics and learned policies without optimality theorems.
- *Certified risk.* C-RAG proves, under a stylized retrieval and transformer model, that the conformal generation risk of RAG is below that of the bare LLM with high probability (Theorem 1). The result extends to bounded Hellinger distribution shift (Theorems 2–3) — [Kang et al. 2024](https://arxiv.org/abs/2402.03181). TRAQ gives an end-to-end conformal guarantee that the RAG prediction set contains a semantically correct answer — [Li, Park, Lee 2023](https://arxiv.org/abs/2307.04642).
- *Calibration of the gate.* With matched trajectory replay, isotonic calibration of verbalized confidence raised accuracy among committed answers by up to 41 pp. Overall accuracy rose up to 15 pp on HotpotQA but fell up to 17 pp on MuSiQue. A calibration map fitted before retrieval degraded by retrieval depth three — [Chhikara 2026](https://arxiv.org/abs/2608.26846).
- *VOI-guided evidence selection.* ECR selects claims by expected entropy reduction and stops when H ≤ ε (single-author proposal; no comparative benchmark in the abstract) — [Di Gioia 2026](https://arxiv.org/abs/2603.28444).
- *Empirical "rounds".* Two iterations captured 95% of the gains of five (HotpotQA, 7B model, single author) — [Shaikh 2026](https://arxiv.org/abs/2606.21553). RAAC cut 14 search calls per query on BrowseComp-Plus using novelty and coverage signals — [Soudani et al. 2026](https://arxiv.org/abs/2608.15191). Insufficient-context classification supports abstention — [Joren et al. 2024](https://arxiv.org/abs/2411.06037).

### Inferences
- **Deriving "a few rounds" from the proofreading theorem.** *[inference/derivation]*
  - Model the evidence still missing after round n as Poisson(λ(1−p)^n), where p is the per-round probability of retrieving each missing piece. Ferguson's optimal rule is then to stop after n* = min{n : λp(1−p)^n ≤ c_1/c_2} rounds, a *fixed* count.
  - Example: λ = 2 missing facts, p = 0.6, and a missing fact costs 10× a round (c_1/c_2 = 0.1). Then E[new finds] = 1.2, 0.48, 0.19, 0.077, so stop after 3 rounds.
  - In a simpler geometric model where the answer is found per round with probability q, P(found by k) = 1 − (1−q)^k. "2 rounds = 95% of 5 rounds" corresponds to q ≈ 0.78.
  - The model predicts more rounds when p is low (hard corpus, weak retriever), λ is high (many hops), or misses are costly (high c_2). It predicts fewer rounds when the retriever and reranker improve, which matches R2's note that "moderate reranking often yields larger gains than increasing search-time reasoning".
  - The fixed-round result **requires monotonicity**: expected yield must be non-increasing, round after round. Query reformulation that suddenly opens a new region of the corpus breaks monotonicity, and then an adaptive (Pandora/Gittins-style) rule beats any fixed count.
- **Practical stopping rule implied by 1.2 + 1.3** *[inference]*: continue while (estimated probability the next search finds new, decision-relevant evidence) × (value of fixing the answer) > (cost of a search). Estimate the first factor from novelty and coverage signals (RAAC) and calibrate it on a golden set, not from verbalized confidence (see Q7). This is the one-step look-ahead rule, and it is optimal only if the problem is monotone.
- **Multi-hop retrieval violates the premises of the greedy guarantees.** The XOR example (1.5) and Assaf–Zamir (1.6) are formal reasons why single-query greedy retrieval fails on multi-hop questions: each hop is individually uninformative about the final answer. Query decomposition helps because it creates sub-targets U_j, each with its own conditionally independent observations. That restores the Krause–Guestrin submodularity condition, and with it the greedy guarantee *per sub-question*. This is a theoretical account of R2's "plan or decompose first" step, not a proven result about LLM agents.
- **Abstention** is the third region of a sequential test. When neither threshold is crossed within budget, Wald's framework, like Fellegi–Sunter's possible-link region, prescribes "no decision" rather than a forced answer.

### Gaps
- I found no theorem that derives an optimal number of retrieval rounds for LLM multi-hop QA directly. The "2–3 rounds" evidence remains empirical: single-author ablations and vendor reports.
- No source measures whether real agentic retrieval satisfies the monotonicity condition (non-increasing expected yield). It should be tested on logged trajectories.
- The full text of Good (1967) and Stone (1975) was not accessible. Statements rely on Graves (1989), Wikipedia and Stone (1989).

---

## Q2. Exploration vs exploitation and diminishing returns: bandits, submodularity, and budgeted coverage

### Takeaway
Bandit theory sets hard limits on adaptive source and query-rewrite selection:
- logarithmic regret is achievable (UCB1, Thompson sampling) and unavoidable (Lai–Robbins);
- the constants depend on gaps Δ_i and KL divergences, so with few queries per user and small gaps, bandits barely beat a well-chosen fixed policy.

Submodularity gives the (1 − 1/e) greedy guarantee for coverage-style objectives (diverse retrieval, budgeted reading, summarization). It extends to budgets (Sviridenko; Khuller–Moss–Naor) and adaptive policies (Golovin–Krause). It is the best possible for polynomial algorithms (Feige). Two cautions: MMR is non-monotone submodular, and information gain is not submodular without conditional independence.

### Cited Findings

**2.1 Regret upper bounds (UCB1).**
- *Result.* For K arms with rewards in [0,1], UCB1 (play argmax_j x̄_j + √(2 ln n / n_j)) has expected regret at most 8 Σ_{i: μ_i<μ*} (ln n / Δ_i) + (1 + π²/3) Σ_j Δ_j after any number n of plays. The bound holds uniformly in time, not just asymptotically — [Auer, Cesa-Bianchi, Fischer 2002, Theorem 1](https://homes.di.unimi.it/~cesabian/Pubblicazioni/ml-02.pdf) ([DOI](https://doi.org/10.1023/A:1013689704352)).
- *Proof.* A Chernoff–Hoeffding bound on each arm's confidence radius shows that a suboptimal arm i is played more than about 8 ln n / Δ_i² times only with summably small probability.

**2.2 Regret lower bound (Lai–Robbins).**
- *Result.* Any strategy with E T_i(n) = o(n^a) for all a > 0 on every Bernoulli instance satisfies liminf R_n / ln n ≥ Σ_{i: Δ_i>0} Δ_i / kl(μ_i, μ*) — [Bubeck & Cesa-Bianchi 2012, Theorem 2.2](https://arxiv.org/abs/1204.5721) (extracted from [Lai & Robbins 1985](https://doi.org/10.1016/0196-8858%2885%2990002-8)).
- *Maps to.* Learning which query rewrite or retriever works best has a sample cost of order ln n/Δ that **no algorithm can beat**. When per-domain query volume is small and arms are similar, a bandit "router" cannot pay for itself. That argues for R2's fixed hybrid RRF over learned routing at small scale. *[inference]*

**2.3 Thompson sampling.**
- *Result.* Thompson sampling achieves logarithmic expected regret: O(ln T/Δ + 1/Δ³) for two arms, and O([(Σ_{i≥2} 1/Δ_i²)²] ln T) for N arms. These are the "first" such bounds, "optimal but for the dependence on Δ_i and the constant factors" — [Agrawal & Goyal 2012](https://arxiv.org/abs/1111.1797). The idea dates to [Thompson 1933, Biometrika](https://doi.org/10.2307/2332286).
- *Bayesian regret.* Posterior sampling's Bayesian regret can be bounded by converting UCB bounds, with a general bound in terms of the "eluder dimension" — [Russo & Van Roy 2014](https://arxiv.org/abs/1301.2609). Information-directed sampling minimizes squared regret divided by the mutual information between the optimal action and the next observation, with regret scaling with the entropy of the optimal-action distribution — [Russo & Van Roy 2018](https://arxiv.org/abs/1403.5556).
- *Best-arm identification (fixed confidence).* lil'UCB identifies the best arm with a sample count within a constant factor of a law-of-the-iterated-logarithm lower bound — [Jamieson et al. 2014](https://arxiv.org/abs/1312.7308). This is the right objective for *offline* choice of a single pipeline configuration, as opposed to cumulative regret. *[inference]*

**2.4 Bandits applied to retrieval and query rewriting (empirical).**
- MBA-RAG treats retrieval strategies as arms, with a reward that penalizes extra retrieval steps, and reports state of the art on single- and multi-hop QA with lower retrieval cost — [Tang et al. 2024](https://arxiv.org/abs/2412.01572). A multi-objective bandit chooses among KG retrieval methods in non-stationary settings — [Tang, Li, Du 2024](https://arxiv.org/abs/2412.07618).
- Sub-query selection as exploration/exploitation gave +35% document precision and +15% α-nDCG — [Petcu, Murray, Khashabi 2025](https://arxiv.org/abs/2510.18633).
- QueryBandits (contextual Thompson sampling over rewrite strategies) had an 87.5% win rate over no-rewrite. Some static rewrite prompts had *higher cumulative regret than no rewrite*, and "there is no single rewrite strategy optimal for all queries" — [Cho, Watson, Koppel 2025](https://arxiv.org/abs/2508.16697).

**2.5 Monotone submodular maximization: the Nemhauser–Wolsey–Fisher greedy guarantee.**
- *Result.* For f non-negative, monotone and submodular, the greedy sets S_ℓ satisfy f(S_ℓ) ≥ (1 − e^{−ℓ/k}) max_{|S|≤k} f(S). In particular f(S_k) ≥ (1 − 1/e)·OPT, and "if we let the greedy algorithm pick 5k sensors, the approximation ratio … improves from ≈ .63 to ≈ .99" — [Krause & Golovin, survey Theorem 1.5](https://las.inf.ethz.ch/files/krause12survey.pdf), after [Nemhauser, Wolsey, Fisher 1978](https://doi.org/10.1007/BF01588971).
- *Proof.* f(S*) ≤ f(S* ∪ S_i) by monotonicity. Telescoping and submodularity give f(S*) ≤ f(S_i) + Σ_{v∈S*} Δ(v|S_i). The greedy choice gives f(S*) ≤ f(S_i) + k(f(S_{i+1}) − f(S_i)). So δ_{i+1} ≤ (1 − 1/k)δ_i, hence δ_ℓ ≤ e^{−ℓ/k} f(S*) — [Krause & Golovin](https://las.inf.ethz.ch/files/krause12survey.pdf).
- *Tightness.* For max k-cover, (1 − 1/e) is the approximation threshold unless P = NP — [Feige 1998, JACM](https://doi.org/10.1145/285055.285059). No polynomial algorithm beats (1 − 1/e) for nonmyopic VOI unless P = NP — [Krause & Guestrin 2005](https://arxiv.org/abs/1207.1394).
- *Budgets (knapsack costs).* Cost-benefit greedy alone "can still perform arbitrarily badly". max{f(S_uniform-greedy), f(S_cost-benefit)} ≥ ((1 − 1/e)/2)·OPT — [Leskovec et al. 2007 (CELF)](https://doi.org/10.1145/1281192.1281239), as summarized in [Krause & Golovin](https://las.inf.ethz.ch/files/krause12survey.pdf). Partial enumeration of all 3-sets followed by cost-benefit greedy achieves (1 − 1/e) — [Sviridenko 2004](https://doi.org/10.1016/S0167-6377%2803%2900062-2); budgeted max coverage: [Khuller, Moss, Naor 1999](https://doi.org/10.1016/S0020-0190%2899%2900031-9).
- *Adaptive version.* If f is adaptive monotone and adaptive submodular, an α-approximate greedy *policy* satisfies f_avg(π_[ℓ]) > (1 − e^{−ℓ/αk}) f_avg(π*_[k]). This "generalizes the classic result of … Nemhauser et al." — [Golovin & Krause 2011, Theorem 5](https://arxiv.org/abs/1003.3967).

**2.6 Submodularity in IR and summarization.**
- Summarization objectives that combine coverage and a diversity reward are monotone submodular, so greedy has the (1 − 1/e) guarantee. Lin & Bilmes also prove that **MMR's objective is non-monotone submodular** (their Theorem 2), so the monotone (1 − 1/e) bound does not apply to MMR as such — [Lin & Bilmes 2011, ACL](https://aclanthology.org/P11-1052.pdf); MMR: [Carbonell & Goldstein 1998](https://doi.org/10.1145/290941.291025).
- Ranked bandits learn diverse rankings online. They "maximize the probability that a relevant document is found in the top k", and one variant is asymptotically optimal in the worst case even when user interests change — [Radlinski, Kleinberg, Joachims 2008](https://doi.org/10.1145/1390156.1390255).

### Inferences
- **Diverse retrieval and budgeted reading** (R2: "match small, read large"; selecting which chunks fill a context budget). Define coverage f(S) = Σ_{facets/aspects} w_a·[1 − Π_{d∈S}(1 − P(d covers a))]. This is monotone submodular, so greedy (lazy greedy/CELF) is within (1 − 1/e) of optimal, and within ≈0.99 if allowed 5× the items. With token costs, use the Leskovec/Sviridenko variants, not plain ratio-greedy. A probabilistic-coverage objective of this kind is preferable to MMR, which has no monotone guarantee. *[inference]*
- **Diminishing returns are a theorem only for submodular objectives.** If evidence must be *combined* (XOR-like multi-hop), returns can be *increasing*: the second hop is worth more than the first. Greedy can then fail badly. This is a formal reason to plan or decompose before searching (Q1 Inferences). *[inference]*
- **Bandits for source selection:**
  - They are worth it only with many repeated, similar queries (logs) and non-trivial gaps. Use Thompson sampling with a cost-penalized reward (MBA-RAG style).
  - For one-off configuration choices, use fixed-confidence best-arm identification on the golden set instead of online regret minimization.
  - QueryBandits' finding that static rewrites can do worse than no rewrite is consistent with the Lai–Robbins framing: an untested fixed arm can be strictly suboptimal.

  *[inference]*

### Gaps
- No regret bound is specific to LLM query reformulation, where rewards come from noisy LLM judges and are non-stationary across model versions. Existing papers are empirical.
- I did not find a proof that common RAG coverage metrics (e.g., α-nDCG) are submodular in the retrieved set. That is plausible for α-nDCG-like coverage, but I did not verify it here.

---

## Q3. Aggregating noisy judgments: Condorcet, weighted majority, Dawid–Skene, Hoeffding, and correlated LLM errors

### Takeaway
Majority voting over k independent judges with competence p > 1/2 is reliable: error decays exponentially in k (Condorcet/Hoeffding), and with heterogeneous known competence, log-odds weighting is optimal. All three results **need (conditional) independence**. With correlated voters, accuracy converges to P(the shared "facts" point the right way), not 1. LLM errors are strongly correlated: models agree about 60% of the time when both are wrong. On queries where the model is more often wrong than right, more votes *hurt*. This explains R1's L3 design: two *structurally different* calls whose disagreement is used as a routing signal, not a vote, and why self-consistency gains saturate.

### Cited Findings

**3.1 Condorcet Jury Theorem (CJT).**
- *Result.* "if n=2m+1 jurists act independently, each with probability p>1/2 of making the correct decision, then the probability h_{2m+1}(p) that the jury (deciding by majority rule) makes the correct decision increases monotonically to 1 as m increases to infinity". Boland gives generalizations to varying competencies and to dependence between voters — [Boland 1989, The Statistician](https://doi.org/10.2307/2348873).
- *Proof.* Increasing reliability "follows via a non-trivial combinatorial argument". Asymptotic infallibility follows from the law of large numbers: the proportion of correct votes → p > 1/2 — [Dietrich & Spiekermann, SEP "Jury Theorems"](https://plato.stanford.edu/entries/jury-theorems/). Classical formalization: [Grofman, Owen, Feld 1983](https://doi.org/10.1007/BF00125672).
- *Heterogeneous competence.* "Asymptotic infallibility" survives if competence has a fixed lower bound above 1/2 or, more weakly, if *average* competence is above 1/2. Increasing reliability can fail: majority reliability "can even become a decreasing function of group size" — [SEP](https://plato.stanford.edu/entries/jury-theorems/).

**3.2 Optimal weighted majority (Nitzan–Paroush).**
- *Result.* Under independence, "the epistemically optimal procedure in binary choices is a weighted … majority rule", with each voter's weight "a well-defined increasing function of competence". The weight is negative for competence below 1/2. Simple majority is optimal only with equal competences and equal priors — [SEP](https://plato.stanford.edu/entries/jury-theorems/), citing [Nitzan & Paroush 1982](https://doi.org/10.2307/2526438).
- *Proof.* The weighted rule is the likelihood-ratio (Bayes) test for the binary state. With independent voters, log LR = Σ_i ±log(p_i/(1−p_i)), so the weights are log-odds of competence. This is the same Neyman–Pearson structure as Fellegi–Sunter (Q5). *[the explicit log-odds form is my derivation from the LR test; the SEP states only "increasing function of competence"]*

**3.3 Correlated voters: common causes cap accuracy below 1.**
- *Result.* Causal independence does not imply probabilistic independence: "Common causes of votes are factors influencing two or more votes. They exist in abundance". Under conditional independence given the facts x, the limiting majority accuracy is "the probability that the facts … are truth-conducive plus half the probability that the facts are neutral". So majorities "can be wrong even in asymptotically large bodies" — [SEP](https://plato.stanford.edu/entries/jury-theorems/); [Dietrich & Spiekermann 2013, Mind](https://doi.org/10.1093/mind/fzt074).
- *Earlier work.* Ladha (1992) relaxes "two overly restrictive assumptions: it assumes that individuals vote independently and that they share a common goal" — [Ladha 1992, AJPS](https://doi.org/10.2307/2111584).

**3.4 Voting with LLM calls: non-monotone scaling.**
- *Result (binary answers).* Let d_V(x) = max_{a≠y} Pr[G(x)=a] − Pr[G(x)=y]. The query is "difficult" if d_V(x) > 0. For |A| = 2, Vote's accuracy is F(K,x) = I_{(1−d_V(x))/2}((K+1)/2, (K+1)/2), the regularized incomplete beta function. It increases in K on easy queries and *decreases* on difficult ones. With a mixture of easy and hard queries, accuracy can be an inverse-U in K (Theorems 2–3). They also give a closed-form optimal K* for a two-type mixture (Theorem 4) — [Chen et al. 2024](https://arxiv.org/abs/2403.02419).
- *Empirical.* Self-consistency (sample, then majority-vote over reasoning paths) improves chain-of-thought accuracy — [Wang et al. 2022](https://arxiv.org/abs/2203.11171). With repeated sampling, coverage scales log-linearly, but "majority voting and reward models plateau beyond several hundred samples" when no verifier exists — [Brown et al. 2024](https://arxiv.org/abs/2407.21787). Self-consistency "collapse[s] toward all-positive behaviour at practical thresholds" as a field-extraction confidence signal — [ExtractConf, Kumar 2026](https://arxiv.org/abs/2606.24420).

**3.5 Correlated errors across LLMs (empirical).**
- Across 350+ LLMs, "models agree 60% of the time when both models err". Shared architectures and providers drive the correlation, and "larger and more accurate models have highly correlated errors". In LLM-as-judge settings, correlated judges "overinflate the accuracy of models that are less accurate" — [Kim et al. 2025, ICML](https://arxiv.org/abs/2506.07962).

**3.6 Latent-class aggregation: Dawid–Skene and its guarantees.**
- *Model.* Each worker has a confusion matrix, worker labels are conditionally independent given the true class, and class and confusion matrices are estimated by EM — [Dawid & Skene 1979](https://doi.org/10.2307/2346806); EM: [Dempster, Laird, Rubin 1977](https://doi.org/10.1111/j.2517-6161.1977.tb01600.x).
- *Guarantees.* EM on the non-convex likelihood can be trapped in local optima. A spectral-moment initialization plus one EM step "achieves minimax rates of convergence up to a logarithmic factor", with a matching lower bound. The analysis uses conditional independence of worker labels given y_j — [Zhang, Chen, Zhou, Jordan 2014/2016](https://arxiv.org/abs/1406.3824).
- *Budget optimality.* An inference algorithm inspired by belief propagation and low-rank structure is order-optimal in the number of labels per task needed for a target reliability, for both adaptive and non-adaptive assignment, and beats majority voting — [Karger, Oh, Shah 2014](https://arxiv.org/abs/1110.3564).

**3.7 Hoeffding's inequality.**
- *Result.* For independent X_i ∈ [0,1], P(X̄ − EX̄ ≤ −t) ≤ exp(−2nt²) — [Hoeffding 1963, JASA](https://doi.org/10.1080/01621459.1963.10500830).

### Inferences
- **Majority-vote error bound (derivation).** For k independent votes each correct with probability p > 1/2, P(majority wrong) ≤ exp(−2k(p − 1/2)²), by Hoeffding with t = p − 1/2. The bound is loose: for p = 0.8, k = 5 it gives 0.41, while the exact binomial tail is ≈0.058. Use the incomplete-beta formula of Chen et al. for exact values. *[derivation]*
- **Why correlation caps gains (derivation).** Let the correctness indicators of k calls be exchangeable with marginal p and pairwise correlation ρ. Then Var(fraction correct) = p(1−p)[ρ + (1−ρ)/k] → ρp(1−p) > 0 as k → ∞, so the law of large numbers, and with it the CJT, fails. *[derivation]*

  Equivalently, model each item x as having a latent per-call correctness θ_x. Calls are i.i.d. given x, so majority → 1{θ_x > 1/2}, and limiting accuracy = P(θ_x > 1/2) + ½P(θ_x = 1/2). This is exactly the SEP/Dietrich–Spiekermann limit, and it is Chen et al.'s "difficult query" condition (θ_x < 1/2 ⇔ d_V(x) > 0 in the binary case). *[derivation]*

  Consequence for R1: for fields where the model is systematically wrong (θ_x < 1/2, e.g., a misread table header), **more samples of the same model converge confidently to the wrong value**. This is the mechanism behind ExtractConf's "collapse toward all-positive". *[inference]*
- **Design rule for L3 cross-call disagreement** *[inference]*:
  - Make calls structurally different (different prompts or readings, as in ExtractConf's Hunter/Mapper, different models or providers, or OCR vs VLM) to reduce ρ.
  - Treat disagreement as a *routing score* to be calibrated (Q4), not as a vote.
  - If voting is used, weight by estimated log-odds competence per field type (Nitzan–Paroush), with competences estimated by Dawid–Skene on the golden set. Dawid–Skene also assumes conditional independence, so its estimated competences are biased upward when extractors share failure modes. Check the estimates against human labels.
- **LLM judges.** Kim et al.'s finding that correlated judges inflate weaker models' scores is a formal reason why R2's judges must be calibrated against human labels (Q4: PPI), and why a judge from the same family as the generator is particularly suspect. *[inference]*

### Gaps
- I did not read Kaniovski (2010) or Ladha's (1992) full theorems on correlated votes. The quantitative correlated-vote statements above are my own derivations, consistent with the SEP summary.
- No study measures per-field error correlation between extraction calls (e.g., two prompts on the same invoice) in document IE. Kim et al. measure correlation on leaderboards and hiring, not extraction.

---

## Q4. Conformal prediction, risk control, conformal selection/abstention, and prediction-powered inference

### Takeaway
Split conformal turns *any* score, such as cross-call disagreement, into a threshold with a finite-sample guarantee. The guarantee is **marginal** (averaged over documents), requires **exchangeability** between calibration and deployment data, and is exact to within 1/(n+1). For R1's "auto-accept vs human review" gate, the most directly matching theorems are:
- conformal risk control (bounds expected loss, e.g., the error rate among accepted fields);
- conformal selection / conformal alignment (FDR control: the fraction of wrong items among auto-accepted ones ≤ α);
- conformal factuality (claim back-off with a correctness guarantee).

For evaluating with LLM judges, PPI gives valid confidence intervals from a small human-labelled set plus many judge labels, without assuming the judge is accurate. It assumes the human-labelled sample is random from the target distribution.

### Cited Findings

**4.1 Split conformal coverage.**
- *Result.* Let (X_i, Y_i)_{i≤n} and (X_test, Y_test) be i.i.d. (exchangeability suffices). Set q̂ = the ⌈(n+1)(1−α)⌉/n empirical quantile of the scores s(X_i, Y_i), and C(X) = {y : s(X,y) ≤ q̂}. Then P(Y_test ∈ C(X_test)) ≥ 1 − α. If the scores have a continuous joint distribution, coverage ≤ 1 − α + 1/(n+1) — [Angelopoulos & Bates, Theorems D.1–D.2](https://arxiv.org/abs/2107.07511); upper bound from [Lei et al. 2018, Thm 2.2](https://arxiv.org/abs/1604.04173); split/inductive conformal: [Papadopoulos et al. 2002](https://doi.org/10.1007/3-540-36755-1_29); framework: [Vovk, Gammerman, Shafer 2005](https://doi.org/10.1007/b106715).
- *Proof.* By exchangeability the rank of s_test among {s_1..s_n, s_test} is uniform, so P(s_test ≤ s_(k)) = k/(n+1). Take k = ⌈(n+1)(1−α)⌉ — [Angelopoulos & Bates](https://arxiv.org/abs/2107.07511).
- *Finite-calibration variability.* Conditional on the calibration set, coverage is a random variable distributed Beta(n+1−l, l), with l = ⌊(n+1)α⌋. Empirical coverage on n_val test points is beta-binomial — [Angelopoulos & Bates](https://arxiv.org/abs/2107.07511) (the conditional-validity analysis is attributed there to Vovk 2012).
- *Limits.* Exact distribution-free conditional coverage is impossible without assumptions — [Barber, Candès, Ramdas, Tibshirani 2021](https://arxiv.org/abs/1903.04684). The marginal guarantee allows all errors to concentrate in one subgroup — [Angelopoulos & Bates §3](https://arxiv.org/abs/2107.07511).

**4.2 Beyond exchangeability (drift, model or prompt changes).**
- *Weighted conformal under covariate shift.* Valid when the likelihood ratio between test and training covariate distributions is known or accurately estimated — [Tibshirani et al. 2019](https://arxiv.org/abs/1904.06019).
- *Nonexchangeable conformal.* With fixed weights w_i, coverage ≥ 1 − α − Σ_i w̃_i·d_TV(R(Z), R(Z^i)), where Z^i swaps the test point with point i. Down-weighting old calibration points bounds the loss of coverage under drift — [Barber et al. 2023, Theorem 2](https://arxiv.org/abs/2202.13415).
- *Adaptive conformal inference.* Online updating of α_t achieves the long-run target coverage frequency "irrespective of the true data generating process" — [Gibbs & Candès 2021](https://arxiv.org/abs/2106.00170).

**4.3 Conformal risk control and risk-controlling prediction sets.**
- *Result (CRC).* Let L_i(λ) be non-increasing and right-continuous in λ, with L_i(λ_max) ≤ α and sup L_i ≤ B. Choose λ̂ = inf{λ : (n/(n+1)) R̂_n(λ) + B/(n+1) ≤ α}. Then E[L_{n+1}(λ̂)] ≤ α. If the L_i are i.i.d., non-negative and have no atoms at a given λ, then E[L_{n+1}(λ̂)] ≥ α − 2B/(n+1). With the miscoverage indicator as the loss, CRC reduces to split conformal — [Angelopoulos, Bates, Fisch, Lei 2022, Theorems 1–2](https://arxiv.org/abs/2208.02814). Non-monotone losses can be handled by monotonizing L̃_i(λ) = sup_{λ′≥λ} L_i(λ′) (Corollary 1).
- *High-probability versions.* RCPS ([Bates et al. 2021](https://arxiv.org/abs/2101.02703)) and Learn-then-Test, which recasts risk control as multiple hypothesis testing and covers FDR-type and non-monotone risks ([Angelopoulos et al. 2021](https://arxiv.org/abs/2110.01052)), give P(risk ≤ α) ≥ 1 − δ rather than control in expectation.

**4.4 Conformal selection: FDR among auto-accepted items.**
- *Result (cfBH).* Compute conformal p-values from calibration data, then apply Benjamini–Hochberg to select test units whose unobserved outcomes exceed thresholds. If the score is monotone and the calibration and test data are i.i.d. (or exchangeable in the stated sense), FDR ≤ q — [Jin & Candès 2023, Theorems 2.3/2.6](https://arxiv.org/abs/2210.01408).
- *Conformal alignment.* Applied to foundation-model outputs, the method selects units whose outputs meet an alignment criterion, with FDR ≤ α under conditional exchangeability, "regardless of the foundation model or the data" — [Gui, Jin, Ren 2024, Theorem 3.1](https://arxiv.org/abs/2405.10301).

**4.5 Conformal guarantees for LLM outputs.**
- *Conformal factuality.* "Sound" back-off sets F_t remove sub-claims as t grows. Calibrate q̂_α as the ⌈(n+1)(1−α)⌉/n quantile of the minimal back-off levels needed for correctness. Then P(Y*_{n+1} ∈ E(F_{q̂_α}(X_{n+1}))) ≥ 1 − α under exchangeability, with an upper bound 1 − α + 1/(n+1) if the sets are nested (Theorem 4.1) — [Mohri & Hashimoto 2024](https://arxiv.org/abs/2402.10978). They report 80–90% correctness guarantees while retaining most of the output, using only a few human-annotated samples (e.g., 50 inputs per dataset).
- *Conditional extension.* Conditional conformal methods "adaptively issue weaker guarantees when they are required to preserve the utility". This addresses the non-conditional validity of claim filtering — [Cherian, Gibbs, Candès 2024](https://arxiv.org/abs/2406.09714).
- *Conformal abstention.* A self-consistency similarity score plus conformal calibration bounds the hallucination rate. A high-probability variant uses an RCPS-style bound (Proposition 3.1) — [Yadkori et al. 2024](https://arxiv.org/abs/2405.01563).
- *Conformal language modeling.* A calibrated stopping rule for sampling candidates until the set contains an acceptable answer with high probability — [Quach et al. 2023](https://arxiv.org/abs/2306.10193).
- *RAG.* See C-RAG and TRAQ in Q1.9.
- *Extraction.* Clinical extraction with split conformal reached target coverage, though miscalibration direction reversed between FDA labels (underconfident, τ ≈ 0.06) and radiology reports (overconfident, τ up to 0.99) — [Shrestha & Kim 2026](https://arxiv.org/abs/2603.00924).

**4.6 The reject option: Chow's rule and selective classification.**
- *Result.* Chow (1970) "describes an optimum rejection rule": reject when the maximum posterior falls below a threshold. He "presents a general relation between the error and reject probabilities", with error rate "directly evaluated from the reject function" — [Chow 1970, IEEE Trans. IT](https://doi.org/10.1109/TIT.1970.1054406).
- *Guaranteed risk.* Selective classification for DNNs chooses a threshold so that selective risk is ≤ the target with high probability — [Geifman & El-Yaniv 2017](https://arxiv.org/abs/1705.08500).

**4.7 Prediction-powered inference (PPI) for LLM-judge evaluation.**
- *Estimator.* θ̂^PP = (1/N)Σ f(X̃_i) − (1/n)Σ(f(X_i) − Y_i), the judge mean on N unlabelled items minus a "rectifier" estimated on n human-labelled items. It is unbiased for θ* = E[Y]. Proposition 1 gives asymptotically valid coverage: liminf P(θ* ∈ C^PP) ≥ 1 − α. More accurate predictions give smaller intervals, and there are no assumptions on the ML model — [Angelopoulos et al. 2023 (Science)](https://arxiv.org/abs/2301.09633). Extensions handle covariate shift (Corollary 1, reweighted rectifier) and label shift.
- *PPI++.* Power tuning means the method "always improve[s] on classical intervals using only the labeled data" — [Angelopoulos, Duchi, Zrnic 2023](https://arxiv.org/abs/2311.01453).
- *Stratified PPI.* Gives substantially tighter intervals when autorater quality varies across strata — [Fisch et al. 2024](https://arxiv.org/abs/2406.04291).
- *Applications.* AutoEval with synthetic labels increases effective human sample size by up to 50% — [Boyeau et al. 2024](https://arxiv.org/abs/2403.07008). Prediction-powered rank-sets show that rankings built only from strong-LLM comparisons "are often inconsistent with" human preferences — [Chatzi et al. 2024](https://arxiv.org/abs/2402.17826). ARES uses PPI with a small human set for RAG judges — [Saad-Falcon et al. 2023](https://arxiv.org/abs/2311.09476).

### Inferences
- **R1's L3 threshold.** The report's "split-conformal threshold per field type" matches its goal ("auto-accept fields, send the rest to humans") most exactly when implemented as one of the following *[inference]*:
  - (a) **conformal risk control**, with loss L_i(λ) = 1{field i accepted at threshold λ and wrong}, which bounds the expected error rate *including* the rejected mass;
  - (b) **conformal selection (cfBH)**, which bounds the FDR among *accepted* fields, the quantity a downstream SQL user experiences;
  - (c) plain split conformal on a nonconformity score, which guarantees that the *prediction set* contains the truth. That is not the same as "accepted single values are right ≥ 1−α of the time".

  Pick per field type. With n calibration fields per type, the guarantee's slack is 1/(n+1), and coverage fluctuates as Beta(n+1−l, l). With n ≈ 200, the realized coverage standard deviation at α = 0.1 is about √(0.9·0.1/200) ≈ 2 pp. *[derivation from the Beta result]*
- **Version changes break exchangeability.** A new extractor model, prompt or document source invalidates the calibration set. R1's L6 "extractor fingerprint" should key the calibration set. On a version bump, either recalibrate, or use weighted/nonexchangeable conformal (Barber et al.), whose bound degrades by Σ w̃_i d_TV. Use ACI online once human corrections stream in. *[inference]*
- **Marginal ≠ per-document.** A 90% guarantee per field type still allows a few document templates to have far lower accuracy. Stratify calibration by template or source (Mondrian-style; Cherian et al.'s conditional methods) for high-stakes fields. *[inference]*
- **Abstention in R2** ("abstain when evidence is missing"). Conformal abstention (Yadkori) and conformal factuality (Mohri–Hashimoto) give a principled threshold for "answer vs I don't know" or "drop unsupported claims", with a bounded error rate on the calibrated distribution. C-RAG's Theorem 1 says when retrieval provably lowers this risk. All require labelled calibration questions from the deployment distribution. *[inference]*
- **R2's "150–300 human labels" for judges.** PPI's validity requires the human-labelled items to be a *random sample* from the same population the judge scores. Cherry-picked hard cases break the guarantee unless handled by stratified PPI or explicit weights. Interval width depends on Var(f − Y), so a judge correlated with the generator (Q3.5) still yields *valid but wider* intervals rather than biased ones. That is PPI's main advantage over raw judge scores. *[inference]*

### Gaps
- No published conformal guarantee targets *structured* multi-field extraction with dependencies between fields (e.g., total = sum of line items). Field-wise guarantees combine via union bounds at best.
- Basic PPI is asymptotic (CLT-based). I did not verify finite-sample PPI variants in the sources read.

---

## Q5. Record linkage: Fellegi–Sunter optimality, EM estimation, and transitivity/clustering

### Takeaway
Fellegi–Sunter (1969) is the Neyman–Pearson lemma for a three-decision problem. For fixed false-link and false-non-link rates, thresholding the likelihood ratio m(γ)/u(γ) *minimizes the clerical-review region*. This is the exact theoretical basis for Splink's match weights and for R1's "probabilistic match → review band → LLM among blocked candidates" ladder. The optimality is pairwise and assumes correctly specified m/u probabilities. Conditional independence (naive Bayes) across fields is what makes EM estimation feasible, and also what makes weights biased when fields are correlated. Pairwise decisions need not be transitive, so a clustering step is needed: correlation clustering is NP-hard, KwikCluster is a 3-approximation, and Bayesian bipartite models handle it natively.

### Cited Findings

**5.1 Fellegi–Sunter model and theorem.**
- *Model.* Pairs in A×B are true matches M or non-matches U. For a comparison vector γ, m(γ) = P(γ|M) and u(γ) = P(γ|U). A linkage rule maps γ to link A_1, possible link A_2 (clerical review), or non-link A_3. The two errors are A_1 given U and A_3 given M — [Fellegi & Sunter 1969, JASA](https://doi.org/10.1080/01621459.1969.10501049); [Winkler 2006 overview](https://www.census.gov/content/dam/Census/library/working-papers/2006/adrm/rrs2006-02.pdf).
- *Decision rule.* "If R > T_μ, then designate pair as a match. If T_λ ≤ R ≤ T_μ, … possible match and hold for clerical review. If R < T_λ, … nonmatch", with R = P(γ|M)/P(γ|U). The cutoffs are set by a priori error bounds — [Winkler 2006](https://www.census.gov/content/dam/Census/library/working-papers/2006/adrm/rrs2006-02.pdf).
- *Theorem (FS 1969, as restated by Winkler).* Let L′ be any rule with the same error probabilities as L_0, i.e. P(A′_3|M) = P(A_3|M) and P(A′_1|U) = P(A_1|U). Then "L_0 is optimal in that P(A_2|U) ≤ P(A′_2|U) and P(A_2|M) ≤ P(A′_2|M)". That is, it minimizes the probability of no decision — [Winkler 1990](https://www.stat.cmu.edu/NCRN/PUBLIC/RLClassFiles/HW/Winkler1990.pdf).
- *Proof.* Order the γ by R(γ) and fill A_1 from the top until P(A_1|U) = μ, and A_3 from the bottom until P(A_3|M) = λ (randomizing at boundary points). The argument is the Neyman–Pearson exchange: moving any γ from the review region into A_1 or A_3 in a different order would spend more error budget per unit of decided probability. The Neyman–Pearson lemma itself is in [Neyman & Pearson 1933](https://doi.org/10.1098/rsta.1933.0009). *[my reconstruction of the standard argument; FS's original proof not read in full]*
- *EM estimation.* Since P(γ) = P(γ|M)P(M) + P(γ|U)P(U), three conditionally independent fields give enough equations to identify m, u and P(M). "The conditional independence assumption corresponds exactly to the naïve Bayes assumption". Winkler (1988) estimated the parameters with EM, which works best when the set of pairs includes more than about 5% matches — [Winkler 2006](https://www.census.gov/content/dam/Census/library/working-papers/2006/adrm/rrs2006-02.pdf). Under dependence, "the linear weighting of the scores … is not optimal" — [Winkler 2006](https://www.census.gov/content/dam/Census/library/working-papers/2006/adrm/rrs2006-02.pdf).
- *Calibrating false-match rates.* Model the distribution of weights as a mixture for matches and non-matches, fit it by EM/SEM with posterior uncertainty, and estimate the false-match rate at every cutoff — [Belin & Rubin 1995, JASA](https://doi.org/10.1080/01621459.1995.10476563).
- *Implementations.* fastLink is a scalable FS/EM implementation that handles missing data and propagates merge uncertainty — [Enamorado, Fifield, Imai 2019, APSR](https://doi.org/10.1017/S0003055418000783). Splink builds on fastLink's EM for the Fellegi–Sunter model, adding scale (Spark, DuckDB) and customization — [Linacre et al. 2022, IJPDS](https://doi.org/10.23889/ijpds.v7i3.1794).

**5.2 One-to-one constraints, transitivity and clustering.**
- *One-to-one.* Forcing 1-1 matching via a linear sum assignment reduces greedy errors; for example, it correctly assigns wife–wife and son–son within households (Jaro 1989) — [Winkler 2006 §3.4](https://www.census.gov/content/dam/Census/library/working-papers/2006/adrm/rrs2006-02.pdf).
- *Pairwise independence is unreasonable.* FS-based techniques "usually assume independence in the matching statuses of record pairs". Sadinle instead targets a bipartite matching as the parameter, with Bayesian estimates and "partial Bayes estimates that allow uncertain parts … to be left unresolved" — [Sadinle 2017, JASA](https://arxiv.org/abs/1601.06630).
- *Latent-entity model.* Linking records to latent true entities yields "transitive linkage probabilities" and propagates linkage uncertainty to later analyses — [Steorts, Hall, Fienberg 2016](https://arxiv.org/abs/1312.4645).
- *Correlation clustering.* Minimizing disagreements with pairwise ± labels is NP-hard ([Bansal, Blum, Chawla 2004](https://doi.org/10.1023/B:MACH.0000033116.57574.95)). On complete unweighted graphs, the Ailon–Charikar–Newman random-pivot algorithm is a 3-approximation, with an LP-based 2.5-approximation and later 2.06 — [Jafarov 2022 survey](https://arxiv.org/abs/2208.12636); [Ailon, Charikar, Newman 2008, JACM](https://doi.org/10.1145/1411509.1411513).

### Inferences
- **Splink's thresholds as FS cutoffs.** R1/R3's ER ladder (exact keys → Splink → LLM selection among blocked candidates → review) is the FS three-region rule. Choose T_μ and T_λ from target false-link and false-non-link rates, estimated by Belin–Rubin-style mixture calibration or by labelled pairs, and FS guarantees the review band is as small as possible for those rates. Moving the LLM step inside the review band is consistent with FS: it is a second-stage test on the undecided region. *[inference]*
- **When FS optimality fails** *[inference]*:
  - (a) m/u are misestimated, e.g., EM converging to a non-match/match split on a different latent variable, a risk Winkler notes;
  - (b) fields are dependent, e.g., address and phone moving together, which inflates naive-Bayes weights;
  - (c) blocking changes the candidate population, so the error rates are conditional on Q, not on the full A×B.

  In all three cases the *form* of the rule survives, but its *optimality certificate* does not.
- **Transitivity is not guaranteed by pairwise optimality.** Persisted cluster IDs (R1) require a global step: connected components over high-weight edges (fast, but chaining risk), correlation clustering (pivot = 3-approx), or a Bayesian bipartite/latent-entity model. For determinism, use a fixed pivot order (e.g., sorted record IDs) rather than a random permutation, since pivot choice changes clusters. *[inference]*
- **Conformal + FS.** FS thresholds can be chosen with conformal risk control on labelled pairs to get finite-sample error control, instead of trusting EM-estimated error rates. *[inference]*

### Gaps
- The original FS 1969 PDF could not be retrieved (TLS/503 errors). The theorem is quoted from Winkler (1990), and the proof is reconstructed.
- I found no theory for FS-style optimality when the "comparison" is an LLM judgment whose error is correlated with other fields' comparisons.

---

## Q6. Database theory guarantees: provenance semirings, why/where provenance, isolation, determinism, consistent query answering and probabilistic databases

### Takeaway
Several of R1's practical choices have exact theorems behind them:
- **Provenance semirings**: any positive relational algebra (and datalog) result over annotated data factors through N[X] provenance polynomials. One stored polynomial per answer can then be specialized to counts, Boolean lineage, trust or probability by a semiring homomorphism.
- **Snapshot reads**: Iceberg-style linear commit histories make pinned-snapshot reads deterministic. Snapshot isolation (SI) on its own is not serializable (write skew, and even a read-only anomaly).
- **Total ORDER BY**: SQL order is unspecified without a total ORDER BY, and LIMIT without a unique order returns an unpredictable subset.
- **Consistent query answering (CQA)**: CQA defines "certainly true despite conflicts" as truth in every repair. It is tractable only for some query/constraint classes (FO / P / coNP-complete trichotomy for self-join-free conjunctive queries under primary keys).
- **Probabilistic databases**: exact query probability over tuple-independent databases obeys a PTIME vs #P-hard dichotomy, and the tuple-independence assumption is violated by correlated extraction errors.

### Cited Findings

**6.1 Provenance semirings.**
- *Theorem.* Annotate tuples with elements of a commutative semiring K (K-relations). If h : K → K′ is a map between commutative semirings, then h commutes with every positive relational algebra (RA⁺) query, q(h(R)) = h(q(R)), *if and only if* h is a semiring homomorphism (Prop. 3.5). For datalog, ω-continuous homomorphisms commute (Prop. 5.7) — [Green, Karvounarakis, Tannen 2007, PODS](https://web.cs.ucdavis.edu/~green/papers/pods07.pdf) ([DOI](https://doi.org/10.1145/1265530.1265535)).
- *Factorization.* For any RA⁺ query, q(R) = Eval_v ∘ q(R̄) (Theorem 4.3): compute once with abstract tuple-ids in N[X], then evaluate under any valuation. For example, the polynomial 2r² + rs evaluated at p=2, r=5, s=1 gives the bag multiplicity 55. Theorem 6.4 is the datalog analogue with formal power series — [GKT 2007](https://web.cs.ucdavis.edu/~green/papers/pods07.pdf).
- *Unification.* "relational algebra calculations for incomplete databases, probabilistic databases, bag semantics and why-provenance are particular cases of the same general algorithms involving semirings" — [GKT 2007](https://doi.org/10.1145/1265530.1265535).
- *Proof.* RA⁺ operators are defined using only + (union, projection) and · (join), and semiring homomorphisms preserve + and ·, so they commute by structural induction on the query. For the converse, single-operator queries force h to preserve + and ·.
- *Limits.* Aggregation "pose[s] novel challenges rendering this approach inapplicable". Values within tuples must be annotated (semimodules) — [Amsterdamer, Deutch, Tannen 2011](https://doi.org/10.1145/1989284.1989302). Negation/difference is not covered by the RA⁺ theorem. *[the RA⁺ restriction is stated in GKT; that difference is excluded is my reading of "positive algebra"]*
- *Why vs where provenance.* Buneman, Khanna and Tan formalize why-provenance (which source tuples justify an output) and where-provenance (where a value was copied from) — [Buneman, Khanna, Tan 2001, ICDT](https://doi.org/10.1007/3-540-44503-X_20). Why-provenance cannot distinguish alternative derivations: (f,e) and (d,e) "have the same why-provenance" even though each can be computed from a different single tuple, while N[X] polynomials can — [GKT 2007](https://web.cs.ucdavis.edu/~green/papers/pods07.pdf). Survey: [Cheney, Chiticariu, Tan 2009](https://doi.org/10.1561/1900000006).
- *Applied.* How-provenance polynomials over source-grounded RDF, linked to text spans, revealed "extraction and query errors even when the final answer is correct" in 400 multi-hop QA cases — [GraphRAGProv 2026](https://arxiv.org/abs/2610.37237).

**6.2 Isolation, serializability and snapshot reads.**
- *Serializability is hard to recognize.* Recognizing serializable histories is NP-complete, and "there can be no efficient scheduler that outputs all of serializable histories" — [Papadimitriou 1979, JACM](https://doi.org/10.1145/322154.322158).
- *SI is not serializable.* SI is defined by start/commit timestamps plus first-committer-wins. "Snapshot Isolation is non-serializable" because of write skew (A5B), e.g., history H5 with constraint x + y > 0. Results: READ COMMITTED « SI (Remark 8); REPEATABLE READ »« SI, i.e. incomparable (Remark 9); SI precludes anomalies A1–A3 (Remark 10). SI "gives the freedom to run transactions with very old timestamps, thereby allowing them to do time travel" — [Berenson et al. 1995](https://arxiv.org/abs/cs/0701157) ([DOI](https://doi.org/10.1145/223784.223785)).
- *Portable isolation definitions.* Adya et al. define isolation levels for locking, optimistic and multi-version schemes — [Adya, Liskov, O'Neil 2000](https://doi.org/10.1109/ICDE.2000.839388).
- *When SI is safe.* Fekete et al. develop "a theory that characterizes when nonserializable executions of applications can occur under SI" and show TPC-C is serializable under SI — [Fekete et al. 2005, TODS](https://doi.org/10.1145/1071610.1071615). Serializable SI detects the dangerous structures at runtime — [Cahill, Röhm, Fekete 2008](https://doi.org/10.1145/1376616.1376690); production implementation: [Ports & Grittner 2012 (PostgreSQL SSI)](https://arxiv.org/abs/1208.4179).
- *Read-only anomaly.* "It has been widely assumed that, under SI, read-only transactions always execute serializably provided the concurrent update transactions are serializable". This is false: an SI history can show a read-only transaction a state inconsistent with any serial order — [Fekete, O'Neil, O'Neil 2004](https://doi.org/10.1145/1031570.1031573).
- *Lakehouse commits.* "All table changes occur in a linear history of atomic table updates". "Readers always use a consistent snapshot of the table without holding a lock". Writers use optimistic concurrency and, on conflict, retry against the new state after checking that "the assumptions are met" — [Apache Iceberg, Reliability](https://iceberg.apache.org/docs/latest/reliability/).

**6.3 Determinism of query results.**
- *ORDER BY.* "If sorting is not chosen, the rows will be returned in an unspecified order … A particular output ordering can only be guaranteed if the sort step is explicitly chosen" — [PostgreSQL, ORDER BY](https://www.postgresql.org/docs/current/queries-order.html).
- *LIMIT.* "When using LIMIT, it is important to use an ORDER BY clause that constrains the result rows into a unique order. Otherwise you will get an unpredictable subset", and the optimizer may choose different plans, and so different row orders, for different LIMIT/OFFSET values — [PostgreSQL, LIMIT](https://www.postgresql.org/docs/current/queries-limit.html).
- *Formal SQL semantics.* A formal semantics of SELECT-FROM-WHERE with subqueries, bag/set operations and nulls, validated experimentally against real DBMSs — [Guagliardo & Libkin 2017, PVLDB](https://doi.org/10.14778/3151113.3151116).
- *Ties in search engines.* Score ties broken by internal doc ids, which multi-threaded indexing assigns inconsistently, make Lucene rankings non-repeatable — [Lin & Yang 2019](https://arxiv.org/abs/1807.05798).
- *LLM nondeterminism.* "Deterministic" LLM settings varied by up to 15% in accuracy across runs — [Atil et al. 2024](https://arxiv.org/abs/2408.04667).

**6.4 Consistent query answering over inconsistent data.**
- *Definition.* A consistent answer is one that holds in all minimal "repaired versions" of a database that violates its integrity constraints. Arenas, Bertossi and Chomicki give a rewriting method, prove it sound and complete for some classes of constraints and queries, and prove termination for several classes — [Arenas, Bertossi, Chomicki 1999, PODS](https://doi.org/10.1145/303976.303983).
- *Complexity.* A repair under primary keys selects a maximal set of tuples with no two sharing a key. For self-join-free Boolean conjunctive queries, it is decidable whether CERTAINTY(q) is in FO, in P but not FO, or coNP-complete — [Koutris & Wijsen 2017, TODS](https://doi.org/10.1145/3068334).

**6.5 Probabilistic and incomplete databases.**
- *Incomplete information.* Imieliński and Lipski give conditions for "safe" (no incorrect conclusions) and "complete" extensions of relational operators to tables with nulls and variables (c-tables) — [Imieliński & Lipski 1984, JACM](https://doi.org/10.1145/1634.1886).
- *Dichotomy.* For unions of conjunctive queries over tuple-independent probabilistic databases, query probability is either PTIME or #P-hard. The tractable case uses inclusion/exclusion plus elimination of existential variables — [Dalvi & Suciu 2012, JACM](https://doi.org/10.1145/2395116.2395119).

### Inferences
- **Provenance as a compute-once artifact (R1 §Provenance).** Store an N[X] provenance polynomial over extraction-fact IDs (each X = one extracted field with its span) for every SQL/graph answer. By Theorem 4.3 and Prop. 3.5, later questions can be answered *without re-running the query* by applying a homomorphism *[inference]*:
  - "which spans support this?" (map to why-provenance);
  - "is it supported if we distrust source S?" (Boolean semiring with x_S = 0);
  - "how many derivations?" (N);
  - "minimum trust along the best derivation" (Viterbi/tropical semiring);
  - "probability under independent extraction errors" (probability via Boolean lineage).

  Caveats: aggregates need the Amsterdamer–Deutch–Tannen extension, and negation and difference are outside the theorem.
- **Snapshot pinning (R1).** An append-only lake with a linear commit history (Iceberg/DuckLake) plus "query at snapshot v" gives each query a single serial state, so the SI anomalies, which need concurrent read-write transactions over a mutable store, do not arise for read-only queries over a *committed* snapshot. The Fekete–O'Neil–O'Neil read-only anomaly is a warning for the *operational* store: if agents read from a live OLTP database under SI while ingestion jobs write, they can see states no serial history produces. Read pinned lake snapshots, or use SERIALIZABLE (SSI). *[inference]*
- **Byte-identical results** need the following *[inference]*:
  - (i) a pinned snapshot, i.e. a fixed instance;
  - (ii) deterministic SQL semantics: a total ORDER BY on a key, no LIMIT without it, and no volatile functions such as now() or random(), all of which the docs leave unspecified;
  - (iii) deterministic float aggregation order. Parallel SUM over floats is not associative; I found no theorem in the sources read, so this belongs in Gaps.

  The Guagliardo–Libkin semantics is a reference semantics for (ii).
- **Conflicting knowledge (R2 "conflicts belong in the data layer").** CQA gives a formal meaning to "answer only what is true in every repair". Example: two extracted values for one entity's primary-key attribute make a key violation, and the certain answer to "is X's limit ≥ 10k?" is "yes" only if both values satisfy it. For simple key-join queries this is FO-rewritable, i.e. plain SQL (Koutris–Wijsen), while some queries are coNP-complete and need flagging rather than exact certain answers. This supports exposing conflicts as data rather than picking one value silently. *[inference]*
- **Probabilistic facts.** Attaching a calibrated probability to each extracted field and querying with the Dalvi–Suciu semantics is exact only if errors are tuple-independent. Correlated extractor errors (Q3) violate this, so probabilities computed this way are not guaranteed to be calibrated. Lineage/c-table representations (GKT, Imieliński–Lipski) record the dependence and allow exact but potentially #P-hard computation. A practical middle ground: probabilities for ranking and review priority, certain answers (CQA) for gating. *[inference]*

### Gaps
- No source read here proves determinism of floating-point aggregation across parallel plans. This is engineering knowledge, not a cited theorem.
- I did not find formal work on provenance semirings for LLM-produced derivations (semantic operators). GraphRAGProv is a demo, not a theorem.
- The Suciu et al. (2011) book and Bertossi (2011) were not readable (paywall). Coverage relies on the JACM/TODS papers.

---

## Q7. Calibration theory: proper scoring rules and the calibration/refinement decomposition, for confidence scores on extracted fields

### Takeaway
A confidence score is "honest" under a strictly proper scoring rule (Brier, log score), whose expected score is optimized only by reporting the true probability. All proper scores are generated by convex functions (Savage/Gneiting–Raftery). Expected proper score decomposes into calibration (reliability) plus refinement (sharpness/resolution). Calibration alone is weak: a coherent Bayesian *expects* to be calibrated, and a randomized forecaster can be asymptotically calibrated on *any* sequence without knowing anything. So field confidences should be evaluated by a proper score, *plus* calibration curves, on a labelled set. Calibration maps should be refit per extractor version. LLM verbalized confidence fails these tests in R1's sources.

### Cited Findings

**7.1 Characterization of proper scoring rules.**
- *Result.* A regular scoring rule S is proper iff S(P, ω) = G(P) − ∫G*(P,ω)dP(ω) + G*(P,ω) for some convex G, with G* a subtangent. It is strictly proper iff G is strictly convex (Theorem 1). For categorical forecasts (McCarthy, Savage; Theorem 2): S(p,i) = G(p) − ⟨G′(p), p⟩ + G′_i(p) — [Gneiting & Raftery 2007, JASA](https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf) ([DOI](https://doi.org/10.1198/016214506000001437)).
- *Examples.* G(p) = Σp_j² − 1 yields the quadratic (Brier) score, and G = negative entropy yields the log score — [Gneiting & Raftery](https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf); [Brier 1950](https://doi.org/10.1175/1520-0493%281950%29078%3C0001:VOFEIT%3E2.0.CO;2); [Savage 1971, JASA](https://doi.org/10.1080/01621459.1971.10482346).
- *Goal.* "maximize the sharpness of the predictive distributions subject to calibration". Skill scores are "generally improper, even if the underlying scoring rule S is proper" — [Gneiting & Raftery](https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf).

**7.2 Decompositions.**
- *Result.* Murphy's partition: Brier = reliability − resolution + uncertainty — [Murphy 1973](https://doi.org/10.1175/1520-0450%281973%29012%3C0595:ANVPOT%3E2.0.CO;2). DeGroot & Fienberg compare and evaluate forecasters through calibration and refinement — [DeGroot & Fienberg 1983](https://doi.org/10.2307/2987588). Kull & Flach give general decompositions of proper scoring rules, treating score adjustment as a precursor to calibration — [Kull & Flach 2015](https://doi.org/10.1007/978-3-319-23528-8_5). *[decomposition formulas are standard; I read titles and abstracts or metadata only for these three]*

**7.3 Calibration is necessary but cheap.**
- *Coherent Bayesians.* "a coherent Bayesian expects to be well calibrated", and the paper discusses this result's "destructive implications for the theory of coherence" — [Dawid 1982, JASA](https://doi.org/10.1080/01621459.1982.10477856).
- *Randomized forecasters.* "if the forecaster can randomise, the forecaster wins in the sense that the forecasted probabilities and the empirical probabilities can be made arbitrarily close". A deterministic forecaster can always be defeated — [Foster & Vohra 1998, Biometrika](https://doi.org/10.1093/biomet/85.2.379).

**7.4 Neural and LLM calibration (empirical).**
- Modern deep networks are poorly calibrated, and simple post-hoc temperature scaling fixes much of this — [Guo et al. 2017](https://arxiv.org/abs/1706.04599).
- Larger LMs are well-calibrated on multiple choice when given the right format, and P(True) self-evaluation is informative — [Kadavath et al. 2022](https://arxiv.org/abs/2207.05221).
- For entity extraction, verbalized ECE was 0.53–0.94, and single-sentence counterfactuals flipped 95.6–100% of high-confidence judgments — [Qian 2026](https://arxiv.org/abs/2610.20417).
- Token log-probs, verbalized confidence and self-consistency "collapse toward all-positive behaviour at practical thresholds" — [ExtractConf 2026](https://arxiv.org/abs/2606.24420).
- Isotonic calibration of verbalized confidence changes which questions an agent commits to, not the ranking quality — [Chhikara 2026](https://arxiv.org/abs/2608.26846).

### Inferences
- **Metric choice for the field-confidence gate** *[inference]*:
  - Score field confidences with a strictly proper rule (Brier or log loss) on the golden set, decomposed into reliability (calibration error) and resolution (separation).
  - Gating quality depends on *resolution* (ranking), while thresholds depend on *calibration*.
  - Conformal thresholds (Q4) need only a ranking-quality score, not a calibrated one. That is why R1's conformal approach works even when raw LLM confidence is miscalibrated in opposite directions across domains (Shrestha & Kim). What conformal cannot fix is *low resolution*: if scores do not separate right from wrong, the guaranteed threshold rejects almost everything.
- **Calibration maps are version-specific.** Post-hoc maps (temperature, isotonic) are fit on one extractor fingerprint and one document distribution. Foster–Vohra shows calibration can be achieved without information, so a calibrated but unsharp score is useless; report both components. *[inference]*

### Gaps
- No published calibration curves exist for commercial extraction APIs (R1 noted this as well). The theory cannot substitute for per-deployment measurement.
- I read DeGroot–Fienberg, Murphy and Kull–Flach only at the title or abstract level. The decomposition statements rely on standard knowledge consistent with Gneiting–Raftery.

---

### Cross-cutting mapping table (method → result that justifies or bounds it)

| Report method | Justifying / bounding result | Key assumption that can fail |
|---|---|---|
| R2: 2–3 search rounds with a stopping rule | Monotone stopping: 1-sla optimal; proofreading → fixed n* = min{n: λp(1−p)^n ≤ c1/c2} (Ferguson Ch. 5); Pandora/Weitzman reservation values | Non-increasing expected yield; known costs; single-target vs multi-target |
| R2: decompose first | Krause–Guestrin: info gain submodular only under conditional independence (XOR counterexample); Assaf–Zamir: greedy fails for n>1 targets | Sub-questions really make evidence conditionally independent |
| R2: abstain when evidence is missing | Sequential test three-region rule (Wald–Wolfowitz); Chow reject option; conformal abstention/factuality; C-RAG | Exchangeable calibration questions |
| R2/R3: diverse retrieval, budgeted reading | NWF (1−1/e); Sviridenko knapsack; Golovin–Krause adaptive greedy; Feige tightness | Objective monotone submodular (MMR is not monotone) |
| R2/R3: routing among retrievers | UCB/TS log regret; Lai–Robbins lower bound | Enough repeated traffic; stationarity |
| R1 L3: cross-call disagreement | CJT + Hoeffding (independent); correlated-vote limit P(θ>1/2); Chen et al. non-monotone K | Low error correlation between calls |
| R1 L3/L4: conformal threshold → human review | Split conformal; CRC; cfBH/conformal alignment FDR | Exchangeability per extractor version; marginal only |
| R2: judges calibrated with ~150–300 human labels | PPI/PPI++ validity; stratified PPI | Labelled set is a random sample of the target population |
| R1/R3: Fellegi–Sunter / Splink | FS 1969 theorem (minimal review region at fixed error rates); EM under conditional independence | Correct m/u; field independence; blocking-conditional rates |
| R1: persisted cluster IDs | Correlation clustering NP-hard; pivot 3-approx; Bayesian bipartite/latent-entity | Deterministic pivot order needed for reproducibility |
| R1: where/why/how provenance | GKT homomorphism commutation and factorization (RA⁺, datalog); Buneman why/where | No aggregation or negation without extensions |
| R1: snapshot pinning | Iceberg linear history; SI ≠ serializable (Berenson); read-only SI anomaly (Fekete et al.) | Reads from committed snapshots only |
| R1: total ORDER BY + PK tiebreak | PostgreSQL docs (unspecified order; LIMIT unpredictable subset); Lin & Yang score ties | Volatile functions, float aggregation order |
| R2: conflicts in the data layer | CQA (ABC 1999) and Koutris–Wijsen FO/P/coNP trichotomy | Query class |
| R1: uncertain extracted facts | Dalvi–Suciu dichotomy (tuple-independent); c-tables/lineage | Independence of extraction errors |
| R1: confidence scores | Proper scoring rules (Gneiting–Raftery); calibration vs refinement; Foster–Vohra | Version-specific calibration |
