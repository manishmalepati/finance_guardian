# Personalized ML categorization engineering guide

## 1. Product problem

The existing pipeline categorizes through explicit user choices, merchant aliases, Plaid category mappings, and a queued LLM fallback. A supervised classifier could help with merchants absent from those rules, but only if independently reviewed labels show measurable benefit. This milestone builds a local experiment and records future manual corrections as independent evidence. It does **not** automatically replace or override any production categorization path.

## 2. Data, labels, and grain

The unit is one canonical transaction. `core.transactions` supplies posted date, description, merchant, and lifecycle status. `enrichment.transaction_categorizations` stores active categories and source, but `source=user` can include up to many transactions changed by a single propagated merchant alias. It is not an independent review count. New `enrichment.categorization_corrections` records only the transaction the user selected in `CategorizationService.set_transaction_category()`. `explicit_local_examples()` selects the latest explicit correction per transaction and its label availability timestamp. Old user-propagated, Plaid, seed-rule, and LLM labels are not treated as independently verified ground truth. The local PostgreSQL connection was unavailable, so no real label count was measured or used for training.

The public benchmark uses 144 wholly synthetic transactions across four taxonomy subcategories and 12 fictional merchants. Merchant words and context text are the inputs. Numeric reference IDs are removed by `clean_text()`; category labels and Plaid hints are not fed into the text-only classifier. The fixture includes simulated Plaid-like hints with deterministic errors; these are **not** measured Plaid labels. Real descriptions remain local, and saved model vocabulary can contain private merchant tokens, so artifacts live under ignored `.local/models`.

## 3. Algorithms from first principles

### TF-IDF

Term frequency counts a word in a description. Inverse document frequency gives less weight to words appearing in nearly every description: `IDF(t) ≈ log((1 + N)/(1 + documents_with_t)) + 1`. For a tiny corpus with three documents where “market” appears once, its IDF is about `log(4/2)+1 ≈ 1.69`; a word in all three has IDF `log(4/4)+1 = 1`. `TfidfVectorizer` in `evals/categorization_experiment.py` uses one- and two-word tokens, with sublinear term frequency. It turns text into a sparse numeric vector without using the target category.

### Logistic regression

For each category, the model learns weighted token evidence. Softmax transforms class scores `z_k` into `exp(z_k) / sum_j exp(z_j)`. If class scores are 2 and 1, their normalized values are about 0.73 and 0.27. These values are **not automatically calibrated probabilities**. Training minimizes a regularized classification loss; `class_weight="balanced"` reduces domination by common classes. Pseudocode: `clean text → fit TF-IDF on training data only → fit logistic regression → score held-out examples → inspect errors and score calibration`. The implementation pins a random seed and scikit-learn version.

### Evaluation design

The chronological split trains on January–August 2025, selects a score threshold on September–October, then evaluates November–December. The merchant-held-out split removes one merchant per category from training and validation, then tests those merchants in November–December. Local data uses label availability timestamps for chronological splitting and a deterministic merchant hash for group holdout. Model fitting occurs separately for each split, so test merchants are never in the vectorizer or classifier's training set.

Accuracy is correct predictions divided by examples. Macro-F1 averages per-category F1 equally, so small classes matter. Calibration is summarized by expected calibration error: within score bins, compare mean model score with observed correctness and weight by bin size. High-score coverage is the share of predictions above a validation-selected threshold; high-score precision is accuracy on that subset. A threshold is selected on validation only and never treated as a production guarantee.

## 4. Application flow

`Manual transaction category selection → CategorizationCorrection → explicit_local_examples() → offline training/evaluation → ignored local artifact`. The existing API and UI retain their current precedence and manual editing behavior. `backend/intelligence/categorization.py` has the typed label and text contract. `evals/categorization_experiment.py` trains and evaluates models only when invoked from the command line. No scikit-learn import is added to API startup. Optional local sentence embeddings can be compared by passing a preexisting model directory; the script never downloads a model automatically. Artifact metadata records model, library, dataset, and provenance versions. Do not load model artifacts from untrusted paths because joblib uses Python object serialization.

## 5. Evaluation and measured results

Run `.\.venv\Scripts\python.exe -m evals.categorization_experiment`. The current synthetic fixture produced 24/24 correct chronological predictions and 8/8 correct merchant-held-out predictions. Both macro-F1 values were 1.0. The seen-merchant alias baseline covered 100% of chronological test cases, so the classifier adds no value there. It covered 0% of held-out merchants. The actual seeded rule baseline had 0% coverage on these fictional merchants. Simulated Plaid-like hints had 66.7% chronological and 50% held-out accuracy, which says nothing about real Plaid performance. Expected calibration error was 0.201 chronological and 0.507 held-out despite perfect classification. A validation-selected score threshold of 0.5 covered only 25% of held-out cases. The embedding comparison was skipped because no local sentence model was supplied. These simple, repeated synthetic phrases make the classification task unusually easy; results must not be advertised as real-world accuracy or as superiority to Plaid.

To save an artifact, pass `--save-artifact`; it writes only to `.local/models`. To attempt training from independent local corrections, pass `--source local`. The script abstains when fewer than 60 independent labels or fewer than three categories are available. It reports aggregate metrics and category-level errors without printing real descriptions or merchant names. No real-data training was performed here.

## 6. Tradeoffs

TF-IDF plus logistic regression is fast, interpretable, and works with small local datasets. A sentence embedding model might generalize to new merchants better, but requires a locally available model, additional memory, and a compatible license. The synthetic benchmark cannot justify serving model suggestions. Recording only explicit manual choices avoids inflating sample size through alias propagation. The classifier is offline until a trustworthy real holdout validates both precision and score calibration; explicit user choices remain highest priority.

## 7. Improvements

Collect enough independently reviewed corrections across categories and merchants. Add strict point-in-time features and stable merchant identities. Compare a local licensed embedding model on exactly the same splits. Inspect confusion for taxonomically close categories, threshold precision and coverage, and performance across account types. Only then consider a review-only suggestion UI or opt-in automatic acceptance.

## 8. Interview preparation

1. **Why is alias propagation not 100 labels?** One person made one decision; copied categories are dependent observations.
2. **What does TF-IDF do?** It turns text into weighted word features, downweighting words common to many descriptions.
3. **What does merchant-held-out evaluation measure?** Generalization to merchants never seen during training, unlike a future transaction from a known merchant.
4. **Why can 100% accuracy coexist with weak calibration?** The predicted class can be correct every time while its score systematically understates or overstates observed correctness.
5. **Why keep the classifier offline?** Synthetic examples and sparse independent real labels do not establish safe production precision or coverage.
