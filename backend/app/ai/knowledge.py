"""Aqua AI knowledge base.

Facts about the AquaGuard system, water-quality science and the machine-learning
model, kept in one place so the assistant answers from a written source rather
than from whatever the model happens to remember.

Why this exists: a general-purpose LLM does not know that this project uses a
five-parameter Random Forest, that `moderate` is a real third verdict, or what
this deployment's alert policy is. Without grounding it will confidently invent
plausible-but-wrong specifics about *this* system, which is worse than saying it
does not know.

Everything here is static reference text derived from the application's own
constants and documented behaviour. It contains no user data and no secrets:
per-user facts are fetched at request time by the tools in `app.ai.tools`, never
baked in here.
"""

from typing import Any

from app.ai.knowledge_topics import (
    ADVANTAGES,
    CAPABILITIES,
    DOWNLOADS,
    FUTURE_ENHANCEMENTS,
    IDENTITY,
    NOT_IMPLEMENTED,
    PAGE_GUIDES,
    PREDICTION_AND_CONFIDENCE,
    SOFTWARE_TESTING,
    TECH_STACK,
    TOPIC_ALIASES,
    UI_SCREENS,
    WORKFLOW,
)
from app.constants import (
    FEATURE_BOUNDS,
    FEATURE_LABELS,
    FEATURE_NAMES,
    FEATURE_UNITS,
)

# ---------------------------------------------------------------------------
# 1. The AquaGuard application itself
# ---------------------------------------------------------------------------
PROJECT_OVERVIEW = """\
AquaGuard AI is an AI-based water quality monitoring and prediction system.
It is a single application with five screens, and this assistant is built into
it Ã¢â‚¬â€ not a separate chatbot bolted on from outside.

What the system does end to end:
1. The user enters five measured water-quality parameters on the Predict screen.
2. The backend validates them against the values they are physically allowed to
   take, then preprocesses them into the exact feature layout the model expects.
3. A trained Random Forest classifier scores the sample and returns a verdict
   of SAFE, MODERATE or UNSAFE together with a confidence score.
4. The reading, verdict and confidence are stored in MySQL against the account
   that submitted them.
5. An UNSAFE verdict automatically raises an alert for that account.
6. The Dashboard and Prediction History read those stored records back.

The five screens:
- Dashboard Ã¢â‚¬â€ totals, safety split, average confidence, recent readings and
  recent alerts.
- Predict (Water Quality Prediction) Ã¢â‚¬â€ enter a sample, get a verdict.
- Prediction History Ã¢â‚¬â€ every reading submitted, searchable and
  filterable, with a per-record detail view.
- Alerts Ã¢â‚¬â€ unsafe-water notifications, with unread and read states.

There are no user accounts. The application is open: no sign-in, no registration
and no profile, and every visitor uses every screen.

How the pieces fit together:
React (the interface) talks to a Flask REST API over HTTPS. Flask validates and
preprocesses the input, calls the model through a service layer, and persists
results with SQLAlchemy into MySQL. The trained
model artifact is loaded once per process and cached.

What this assistant can and cannot do:
- It can read the signed-in user's own predictions, statistics and alerts, and
  it can run a prediction when given all five values.
- It can ask the interface to navigate the user to a screen.
- It cannot run arbitrary SQL, cannot read another account's data, and cannot
  change system settings. It has no tool that does any of those things.
"""

# ---------------------------------------------------------------------------
# 2. Water-quality concepts
# ---------------------------------------------------------------------------
_PARAMETER_SCIENCE = {
    "ph": (
        "pH measures how acidic or alkaline the water is, on a 0-14 scale, with 7 "
        "being neutral. It matters because acidic water (low pH) can dissolve "
        "metal from pipework - lead and copper in particular - and alkaline water "
        "(high pH) can taste flat and leave scale. Drinking water is usually held "
        "between about 6.5 and 8.5. pH is also what makes a reading unstable: a "
        "small change shifts the chemistry of everything else in the sample."
    ),
    "turbidity": (
        "Turbidity measures how cloudy the water is, in NTU, from particles "
        "suspended in it - silt, clay, organic matter, or microorganisms. It "
        "matters because those particles can shelter pathogens from disinfection: "
        "a chlorine dose that clears clear water may not reach a microbe hidden "
        "inside a particle. It also makes water look unappealing. Under about 5 "
        "NTU is the usual target for drinking water."
    ),
    "tds": (
        "Total Dissolved Solids measures the combined mineral content in mg/L - "
        "salts, metals and other dissolved material. It is mostly about taste and "
        "acceptability rather than a direct health hazard: very high values taste "
        "salty or metallic, and can indicate contamination or intrusion such as "
        "seawater or agricultural runoff. Under about 600 mg/L is generally "
        "considered pleasant."
    ),
    "temperature": (
        "Temperature (in degrees Celsius) affects almost everything else in the "
        "sample. It governs how much oxygen water can hold - colder water holds "
        "more - and how quickly biological and chemical reactions proceed. Warm "
        "water is a more hospitable environment for microbial growth, which is why "
        "temperature is best considered alongside dissolved oxygen rather than on "
        "its own."
    ),
    "dissolved_oxygen": (
        "Dissolved Oxygen is the oxygen available in the water for aquatic life, "
        "in mg/L. Higher values generally indicate healthier, better-aerated water. "
        "It moves in the opposite direction to temperature (cold water holds more) "
        "and in the opposite direction to organic pollution, since decomposing "
        "material consumes oxygen."
    ),
}

# ---------------------------------------------------------------------------
# 3. Machine-learning concepts, as used by THIS system
# ---------------------------------------------------------------------------
ML_CONCEPTS = """\
How the prediction actually works, in this system specifically.

Model: a Random Forest Classifier from scikit-learn. A random forest is an
ensemble of decision trees: each tree is trained on a random subset of the rows
and considers a random subset of the features at each split, and the forest
combines their votes. That randomness is what stops any single quirky tree from
dominating, and it is why forests are more robust than a single decision tree on
data with noise in it.

The three classes:
- SAFE - the model judges the sample potable.
- MODERATE - the model is not confident enough to call it safe, but it is not
  clearly unsafe either. Treat this as "worth re-testing", not as a pass.
- UNSAFE - the model judges the sample not potable. This raises an alert.

Inputs: five features - pH, turbidity, TDS, temperature and dissolved oxygen.
They are always presented to the model in the same fixed order, which is decided
by the backend rather than by the order the values happened to arrive in.

Preprocessing: the training script and the live API import the same
preprocessing function, so a training/serving mismatch is structurally
impossible rather than merely unlikely.

Confidence: `predict_proba` returns a probability for each class. The reported
confidence is the probability of whichever class won, so a confidence of 0.94
means the model put 94% of its probability mass on that class. Confidence is not
accuracy - it says how strongly this model favours an answer for this sample, not
how often that answer is right.

Probability vs verdict: a verdict is the model's decision, and a probability is
how sure it is. A sample can be called SAFE at 0.55 confidence, meaning the
model leaned that way but barely - which is exactly the case where repeating the
measurement is worth the effort.

Feature importance: the forest reports how much each input contributed to its
decisions across the training set. Read this as a property of the model, not of
one particular reading.

Honest limitations, which should be stated plainly if asked:
- The model was trained on a synthetic water-quality dataset, and its measured
  accuracy is only around 60% - meaningfully better than guessing among three
  classes, but far from a laboratory instrument.
- It is a statistical judgement about the readings supplied to it. It is not a
  certified laboratory test and must not be treated as one.
- It can only be as good as the sample. A mis-measured reading produces a
  confident wrong answer.
"""

# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def _parameter_reference() -> str:
    """Live parameter table, generated from the shared constants."""
    lines = []
    for name in FEATURE_NAMES:
        low, high = FEATURE_BOUNDS[name]
        lines.append(
            f"- {FEATURE_LABELS[name]} (`{name}`, {FEATURE_UNITS[name]}): "
            f"accepted range {low} to {high}"
        )
    return "\n".join(lines)


def get_knowledge_base() -> dict[str, Any]:
    """Return the full reference set, keyed by topic."""
    return {
        "project": PROJECT_OVERVIEW,
        "parameters": _parameter_reference(),
        "water_quality": _PARAMETER_SCIENCE,
        "machine_learning": ML_CONCEPTS,
    }


def resolve_topic(topic: str) -> str:
    """Map a user- or model-supplied topic name onto a canonical one.

    Accepts the aliases so the assistant can ask for "random_forest" and get the
    machine-learning reference, rather than failing on a name it chose from the
    user's own wording.
    """
    if not isinstance(topic, str):
        return ""
    key = topic.strip().lower().replace(" ", "_").replace("-", "_")
    return TOPIC_ALIASES.get(key, "")


def get_topics() -> dict[str, str]:
    """Every reference topic, keyed by its canonical name.

    This is the single source the `explain_concept` tool reads from, so a topic
    can never be advertised in the tool schema and missing here.
    """
    return {
        "identity": IDENTITY,
        "project_purpose": PROJECT_OVERVIEW,
        "project_workflow": WORKFLOW,
        "advantages": ADVANTAGES,
        "tech_stack": TECH_STACK,
        "parameters": _parameter_reference(),
        "water_quality": "\n\n".join(
            _PARAMETER_SCIENCE[name] for name in FEATURE_NAMES
        ),
        "machine_learning": ML_CONCEPTS,
        "prediction": PREDICTION_AND_CONFIDENCE,
        "dashboard": UI_SCREENS,
        "history": UI_SCREENS,
        "alerts": UI_SCREENS,
        "page_guides": PAGE_GUIDES,
        "downloads": DOWNLOADS,
        "not_implemented": NOT_IMPLEMENTED,
        "testing": SOFTWARE_TESTING,
        "future": FUTURE_ENHANCEMENTS,
        "capabilities": CAPABILITIES,
    }


def build_knowledge_context() -> str:
    """Render the knowledge base as prompt reference text.

    KEPT DELIBERATELY SMALL. This is appended to every request, so its size is
    paid on every single turn - and a large system prompt is the main reason a
    reply takes seconds rather than a fraction of a second. The rule applied here
    is: inline only what a turn MUST have to answer safely or correctly, and defer
    everything else to `explain_concept`, which the model calls when the topic
    actually comes up.

    What stays inline, and why:
      * the identity line, so it never forgets it is part of this product;
      * the five parameters and their ranges, because nearly every question
        touches them;
      * one line of science per parameter, so a plain "what is turbidity?" is
        answerable without a tool round-trip;
      * a one-line-per-screen index, for the same reason;
      * NOT_IMPLEMENTED, because a model asked about hardware or exports will
        otherwise invent them, and that is the failure this assistant exists to
        avoid.

    Deferred (via the pointer at the end): the workflow, the full page guides,
    the download details, the advantages, the stack, the tests and the roadmap.
    """
    return (
        "=== REFERENCE: WHO YOU ARE ===\n"
        f"{IDENTITY}\n\n"
        "=== REFERENCE: WATER-QUALITY SCIENCE, ONE LINE EACH ===\n"
        f"{_compact_parameter_science()}\n\n"
        "=== REFERENCE: HOW THE MODEL WORKS, IN SHORT ===\n"
        f"{_compact_ml_concepts()}\n\n"
        "=== REFERENCE: WHAT A PREDICTION AND ITS CONFIDENCE MEAN ===\n"
        f"{PREDICTION_AND_CONFIDENCE}\n\n"
        "=== REFERENCE: THE SCREENS, ONE LINE EACH ===\n"
        f"{UI_SCREENS}\n\n"
        "=== REFERENCE: FEATURES THAT DO NOT EXIST ===\n"
        f"{NOT_IMPLEMENTED}\n\n"
        "=== REFERENCE: MORE DETAIL ON REQUEST ===\n"
        "The following are deliberately NOT inline here, to keep each request small"
        " and fast. When one is asked about, call `explain_concept` with the matching"
        " topic and answer from what it returns:\n"
        "- project_workflow: the step-by-step working process. Call this whenever the"
        "  user asks how the system works, the workflow, the steps, or the process.\n"
        "- page_guides: what EACH screen is for, what it contains and which buttons"
        "  it offers. Call this when the user names a page and asks what it is for,"
        "  what is on it, or what they can do on it.\n"
        "- downloads: how the CSV and PDF downloads work and where they are.\n"
        "- capabilities: the full list of what the assistant can and cannot do.\n"
        "- advantages, tech_stack, testing, future: each on request.\n"
        "- parameters: the five parameters, their units and accepted ranges, when a"
        "  question needs the full table rather than the one-line science above."
    )


def _compact_parameter_science() -> str:
    """One line per parameter: what it is, and why it matters.

    The full paragraphs live in `_PARAMETER_SCIENCE` and are served on demand by
    `explain_concept("water_quality")`; this is the grounded summary the model
    needs to answer a plain "what is turbidity?" without a tool call.
    """
    summary = {
        "ph": "how acidic or alkaline the water is, 0-14, 7 is neutral; drinking water is usually held around 6.5-8.5.",
        "turbidity": "how cloudy the water is (NTU) from suspended particles, which can shelter pathogens; under about 5 NTU is the usual target.",
        "tds": "combined dissolved mineral content (mg/L); mainly a taste and acceptability measure, under about 600 mg/L is pleasant.",
        "temperature": "affects how much oxygen the water holds and how fast reactions proceed; best read alongside dissolved oxygen.",
        "dissolved_oxygen": "oxygen available to aquatic life (mg/L); higher is generally healthier and it falls as temperature or organic pollution rises.",
    }
    return "\n".join(f"- {FEATURE_LABELS[name]}: {summary[name]}" for name in FEATURE_NAMES)


def _compact_ml_concepts() -> str:
    """The model facts that must be answerable without a tool call.

    The full write-up is `ML_CONCEPTS`, served by
    `explain_concept("machine_learning")`. Kept here: the model type (asserted by
    the tests), the three classes, the five inputs and the accuracy limitation.
    """
    return (
        "The classifier is a Random Forest Classifier (scikit-learn): an ensemble"
        " of decision trees whose votes are combined, which makes it more robust"
        " than a single tree on noisy data.\n"
        "It takes the same five parameters, always in the same fixed order, and"
        " returns one of three classes: SAFE, MODERATE or UNSAFE, with a confidence"
        " score (the probability of the winning class, not its accuracy).\n"
        "Honest limitation: it was trained on a synthetic dataset and measures only"
        " around 60% accuracy, so it is a screening aid, not a certified"
        " laboratory test."
    )
