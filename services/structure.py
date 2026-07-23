"""Turn raw extracted question text (+ optional source images) into the
strict schema services/render.py consumes.

This is the one step in the pipeline that's inherently approximate (the LLM
is inferring a diagram spec from prose/an image), so its output always goes
through the review gate in main.py before anything is rendered — this
module only produces a best-effort structured guess, never a final answer.
"""

from services.ai_client import call_ai_json

SYSTEM = (
    "You are an expert PW (Physics Wallah) content editor structuring exam "
    "MCQs for narrated walkthrough videos aimed at Indian students. Be precise "
    "with numeric values — these come from a real question bank and errors "
    "will end up in a published video.\n\n"
    "All \"spoken\" fields must be written in proper Hinglish using this exact "
    "convention — Hindi words in DEVANAGARI SCRIPT, English academic/technical "
    "terms kept in English (Latin script), Hindi grammar carrying the sentence:\n"
    "  | Area | Rule |\n"
    "  |---|---|\n"
    "  | Hindi words | Devanagari: बच्चो, चलो, हमें, समझते हैं, देखते हैं |\n"
    "  | English terms | Keep in English: force, velocity, mass, option, formula, "
    "reaction, question, solve |\n"
    "  | Sentence style | Hindi grammar flow + English subject/technical terms |\n"
    "  | Avoid | Roman-script Hindi like 'bachcho', 'samajhte hain', 'hume' — "
    "NEVER transliterate Hindi into Latin letters |\n\n"
    "Correct example:\n"
    "  Question में हमें दिया है कि एक object constant velocity से move कर रहा है। "
    "अब हमें देखना है कि force लगने पर velocity का magnitude कैसे change होगा। "
    "अगर net force motion की direction में लगेगा, तो velocity increase होगी। "
    "इसलिए correct answer option (ii) होगा।\n"
    "Wrong (do not do this):\n"
    "  Question mein hume diya hai ki ek object constant velocity se move kar raha hai.\n\n"
    "Write like a calm, patient PW faculty explaining on a whiteboard — "
    "conversational connectors like 'तो देखो', 'यहाँ पे', 'इसका मतलब है', "
    "'अब हम क्या करेंगे' are expected, not a dry translated textbook sentence. "
    "Medium pace, short sentences.\n\n"
    "NUMBERS IN \"spoken\" FIELDS: always spell every number out as a word, "
    "never a bare digit — this is a TTS pronunciation rule, not just style. "
    "The digit 0 is the one that most often gets mispronounced as the letter "
    "'oh' when left as a numeral, so it must ALWAYS be written as the word "
    "'zero' (e.g. 'friction zero hoga', 'x equals zero', never 'friction 0 "
    "hoga' or 'x = 0'). This applies even inside an otherwise-fine sentence — "
    "spell out every number that will be spoken, not just zero.\n\n"
    "\"spoken\" is AUDIO ONLY — it is narrated but never shown on screen, so it "
    "can be a full explaining sentence. What IS shown on screen is only the "
    "\"note\"/\"label\"/\"latex\" fields — like a teacher's board work, not a "
    "transcript of what they're saying: short, in English, just the key "
    "term/value/equation, never a full Hinglish sentence.\n\n"
    "\"keyPhrases\" must be listed in the same order they appear in the question "
    "text (2-4 of them) — the video underlines each one, in list order, while "
    "questionIntro.spoken is playing, like a teacher's finger moving through the "
    "question as they talk. questionIntro.spoken should stay a natural teaching "
    "length (a few sentences, not a one-liner and not a monologue)."
)

_SCHEMA_DOC = """
Return ONLY a JSON object with this exact shape:

{
  "subject": "Physics" | "Chemistry" | "Maths" | "Biology" | "English" | ...,
  "question": "<question stem, plain text, no markdown>",
  "keyPhrases": ["<important clause/value in the question, verbatim substring>", "..."],
  "questionIntro": {
    "spoken": "<Hinglish narration that reads AND explains the question out loud like "
              "a teacher going through it with a class — not a flat recitation. Walk "
              "through what's given, pausing on the values/conditions in keyPhrases "
              "roughly in the order they appear, the way a teacher's voice and pointing "
              "finger would move through the question. Weave in the actual English "
              "question content naturally (don't skip the numbers/technical terms) but "
              "narrate it, don't just repeat it verbatim word-for-word.>"
  },
  "options": ["<A text>", "<B text>", "<C text>", "<D text>"],
  "answer": "A" | "B" | "C" | "D",
  "concept": {
    "note": "<short English board-note for the concept/rule this question tests, "
            "e.g. 'Capacitor = open circuit at DC' — a few words, not a sentence>",
    "spoken": "<Hinglish narration explaining that concept, audio only, can be a "
              "full sentence — NOT shown on screen>"
  },
  "diagram": {
    "type": "none" | "circuit" | "molecule" | "image",
    "spoken": "<Hinglish narration introducing the diagram, audio only, or omit if type is none>",
    "spec": <see below, or omit if type is none or image>
  },
  "solution_steps": [
    {
      "label": "<short English heading for this step, e.g. 'Nodal Analysis (KCL) — At Node A'>",
      "latex": "<KaTeX-compatible LaTeX for this step's math/result, or null if none>",
      "note": "<short English board-note ONLY if there's no latex for this step, "
              "e.g. 'Friction = 0' — a few words, not a sentence, or omit if latex is set>",
      "spoken": "<Hinglish narration explaining this step like a teacher walking "
                "a student through it, audio only — NOT shown on screen, can be a "
                "full sentence or two>"
    }
  ]
}

DIAGRAM SPEC — only for "type": "circuit":
A left-to-right ladder: a list of named top-rail nodes, resistor/source/wire
elements connecting consecutive nodes along the top rail, and one or more
parallel branches hanging from each node down to a shared ground rail. This
covers standard series/parallel/nodal-analysis circuits — do NOT use it for
non-ladder topologies (bridges, multi-loop meshes); if the circuit doesn't
fit, set diagram.type to "none" instead of forcing a wrong spec.

  "spec": {
    "nodes": ["L", "A", "B"],
    "horizontals": [
      {"from": "L", "to": "A", "type": "resistor", "value": "10Ω"},
      {"from": "A", "to": "B", "type": "resistor", "value": "50Ω"}
    ],
    "verticals": [
      {"at": "L", "elements": [{"type": "resistor", "value": "30Ω"}]},
      {"at": "L", "elements": [{"type": "capacitor", "value": "C1"}]},
      {"at": "A", "elements": [{"type": "resistor", "value": "20Ω"},
                                {"type": "sourcev", "value": "60V"}]},
      {"at": "B", "elements": [{"type": "capacitor", "value": "C2"}]}
    ]
  }

  element "type" must be one of: resistor, capacitor, inductor, sourcev, sourcei, wire.
  A node may have multiple entries in "verticals" (parallel branches at that node).

DIAGRAM SPEC — only for "type": "molecule":
  "spec": "<SMILES string>"

"type": "image" — use this whenever the question includes a figure that is
NOT a circuit or a molecule (geometry figures, generic diagrams, graphs,
photos, anything hand-drawn) — i.e. this is the default figure type, and
"circuit"/"molecule" are the two special cases we can redraw precisely.
Do NOT try to force a geometry/generic figure into the circuit ladder spec.
No "spec" is needed for "image" — the original source image is used as-is.
"""


IMAGE_ONLY_PLACEHOLDER = (
    "(no extracted text — the question is provided ONLY as an attached image; "
    "read the question stem, options, answer key if shown, and any diagram "
    "directly off the image itself)"
)


def _build_prompt(raw_text: str, has_images: bool) -> str:
    image_note = (
        "\nAn image is attached. If the source text above is missing or "
        "incomplete, read the actual question text/options/diagram directly "
        "off the image — don't guess at content the image doesn't show.\n"
        if has_images else ""
    )
    return (
        "Structure the following exam question into the JSON schema below.\n\n"
        f"{_SCHEMA_DOC}\n\n"
        "SOURCE QUESTION (raw extracted text, may include OCR noise):\n"
        "-----\n"
        f"{raw_text}\n"
        "-----\n"
        f"{image_note}"
        "If a circuit or molecule diagram is referenced in the text or shown in "
        "an attached image, infer its spec as precisely as you can from the "
        "described component values — do not invent values that aren't stated "
        "or clearly shown. If the question includes any OTHER kind of figure "
        "(geometry, generic diagram, graph, photo), set diagram.type to "
        "\"image\" — never drop a figure by setting diagram.type to \"none\" "
        "just because it isn't a circuit or molecule."
    )


def structure_question(raw_text: str, images: list[bytes] | None = None) -> dict:
    """Return the structured question dict. Raises on malformed LLM output
    (caller should surface this as a job error, not guess)."""
    prompt = _build_prompt(raw_text, has_images=bool(images))
    result = call_ai_json(prompt, system=SYSTEM, max_tokens=4000, images=images)
    if not isinstance(result, dict) or "question" not in result or "options" not in result:
        raise ValueError(f"structured output missing required fields: {result!r}")
    result.setdefault("diagram", {"type": "none"})
    result.setdefault("solution_steps", [])
    result.setdefault("keyPhrases", [])
    result.setdefault("questionIntro", {"spoken": result["question"]})
    return result
