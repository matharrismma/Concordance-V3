"""Plain-text helpers the core needs before a verifier runs: normalisation and a crisis guard.

Ported verbatim from v2 ask.py (normalize, substring_net, is_crisis and their tables). The semantic
backstop artifact (crisis_semantic.json) stays with the .org app; the core keeps the substring net.
A cry for help relayed through a plain-text door must never be answered with arithmetic: callers
check is_crisis first and return CRISIS_RESPONSE.
"""
from __future__ import annotations
import re

_SMART_QUOTES = str.maketrans({"’": "'", "‘": "'", "‛": "'", "´": "'", "`": "'"})

_CRISIS_EXACT = frozenset({"kms", "kys"})

_CRISIS_WORDS = ("suicide", "suicidal", "kill myself", "killing myself", "end my life",
                 "end it all", "want to end it", "wanna end it", "going to end it",
                 "gonna end it", "ready to end it", "take my own life", "taking my own life",
                 "want to die", "wanna die", "dont want to live", "dont want to be here",
                 "dont want to wake up", "no reason to live", "nothing to live for",
                 "no point in living", "better off dead", "better off without me",
                 "cant go on", "cant do this anymore", "hurt myself", "harm myself",
                 "self harm", "self-harm", "cut myself", "overdose", "off myself",
                 "unalive myself", "hang myself", "shoot myself", "goodbye cruel world",
                 # Past, perfect, and progressive forms of the ideation already listed above.
                 # Someone who has carried this for years rarely phrases it as a present-tense
                 # imperative — "i have wanted to die for 3 years" normalizes to "...wanted to die
                 # ..." and "want to die" never matches across the "-ed" in "wanted" (verified miss,
                 # 2026-08-05; it routed to an ordinary search). These are CONJUGATIONS of phrases
                 # this list already treats as crisis, not new territory, so they add no idiom the
                 # present tense didn't already accept (the deliberate asymmetry: an unnecessary
                 # helpline is a small cost, a missed person is not). No first-person or duration
                 # gate is added — an exclusion on the safety check is how a bypass gets built.
                 "wanted to die", "wanting to die", "wanted to end it", "ending it all",
                 "ending my life", "ending my own life",
                 "feel like ending it", "felt like ending it",
                 # Red team, 2026-08-06: an adversarial pass of 30 realistic phrasings missed all 30.
                 # These close the confirmed holes. The asymmetry stands (an unnecessary helpline is a
                 # small cost; a missed person is not), so this widens coverage and adds no exclusion.
                 # Attempt IN PROGRESS — the highest-cost miss (a person mid-act must not reach search):
                 "took a whole bottle", "took a bottle of pills", "swallowed a bottle",
                 "swallowed a bunch of pills", "took a bunch of pills", "took too many pills",
                 "took all my pills", "took all the pills", "overdosed", "slit my wrists",
                 "slitting my wrists", "cut my wrists", "cutting my wrists", "going to jump",
                 "about to jump", "ready to jump", "jump off a bridge", "jump off the bridge",
                 "gun to my head", "put a gun to", "end myself",
                 # The commonest idioms of ideation:
                 "wish i was dead", "wish i were dead", "wish i could die", "wish i would die",
                 "want to be dead", "dont want to be alive", "dont want to live anymore",
                 "dont want to exist", "want to disappear", "want to vanish",
                 "cant take it anymore", "cant take this anymore", "im a burden",
                 "burden to everyone", "burden to my family", "done with life",
                 "want it to be over", "want it all to be over", "nobody would miss me",
                 "no one would miss me", "better off without me here", "life isnt worth living",
                 "life is not worth living", "not worth living anymore", "tired of living",
                 "tired of being alive",
                 # Abbreviations and euphemisms (the youth/teen demographic). "kms"/"kys" are NOT
                 # in this substring list: as bare substrings they collide with real, common queries
                 # ("convert 5 kms to miles" — the unit_convert domain — "i ran 10 kms", "whiskys"),
                 # so they are matched only as the whole message instead (see _CRISIS_EXACT below).
                 "unalive", "unaliving", "sewerslide",
                 # Spanish — an explicit audience (the es_en curriculum). A caught crisis still
                 # surfaces findahelpline.com (international); localizing the response is a follow-up.
                 "quiero morir", "me quiero morir", "ya no quiero vivir", "quiero matarme",
                 "me quiero matar", "quiero acabar con mi vida", "acabar con mi vida",
                 "no quiero vivir", "no quiero seguir viviendo", "quitarme la vida",
                 "quiero desaparecer",
                 # Answer-path benchmark, 2026-08-26: a 25-cry graded set routed only 18/25 to help.
                 # These seven softer idioms of ideation missed — give-up-on-life, no-hope-left, the
                 # pain, ending things, want-it-all-to-stop, should-be-over. Same asymmetry as above
                 # (an unnecessary helpline is a small cost, a missed person is not); these are near-
                 # synonyms and conjugations of phrases already treated as crisis, and add no exclusion.
                 "give up on life", "giving up on life", "gave up on life", "given up on life",
                 "want it all to stop", "want everything to stop", "want the pain to stop",
                 "make the pain stop", "make it all stop", "just want it all to stop",
                 "cant take the pain", "cant take the pain anymore", "cant take this pain anymore",
                 "cant handle the pain anymore",
                 "cutting myself", "hurting myself", "harming myself",
                 "no hope left", "theres no hope left", "no hope left for me",
                 "life should be over", "my life should be over", "want my life to be over",
                 "wish my life was over", "wish my life were over",
                 "thinking about ending things", "thinking of ending things", "about ending things",
                 "want to end things", "ready to end things", "planning to end things",
                 # Adversarial load, 2026-08-27: a 90+ phrasing sweep across registers found the
                 # quieter idioms of hopelessness the blunt list missed — cant-do-life, no-way-out,
                 # never-get-better, tired-of-being-here, the-point-anymore, would-anyone-notice. Same
                 # asymmetry; these are near-synonyms of ideation already treated as crisis. These are
                 # QUERIES to the engine, where such phrasings are overwhelmingly a cry, not idiom.
                 "cant do life anymore", "do life anymore", "cant keep going", "cant keep doing this",
                 "need the pain to stop", "make my pain stop", "end my suffering", "end the suffering",
                 "hope i dont wake up", "hope i never wake up", "hope i dont wake up tomorrow",
                 "hope i dont wake up in the morning", "wish i didnt have to wake up",
                 "notice if i was gone", "notice if i were gone", "even notice if i was gone",
                 "world would be better without me", "world would be better off without me",
                 "everyone would be better without me",
                 "tired of being here", "so tired of being here",
                 "point of anything anymore", "whats the point anymore", "whats the point of living",
                 "dont see the point anymore", "dont see a point anymore", "dont see the point in living",
                 "never going to get better", "never gonna get better", "nothing will ever get better",
                 "things will never get better", "it will never get better", "itll never get better",
                 "thinking about ending it", "thinking of ending it", "way to end it",
                 "way to end my life", "see no way out", "no way out of this", "no way out but",
                 "why am i still here", "why am i even still here",
                 # bound to "still here" (still alive) — bare "why am i here" is a faith question the
                 # engine should meet with purpose, not a helpline; "still here" is the ideation tell.
                 "why im still here", "why im even still here", "why am i still alive",
                 "no future for me", "cant see a future for myself",
                 # Independent red-team, 2026-08-27: two blind adversarial passes (adult/veiled +
                 # youth/multilingual) beat the net 94/98 — proof a substring list catches what its
                 # author imagined, not what a real, diverse population types. These close the SAFELY-
                 # boundable holes (clear ideation, current online euphemism, non-English cries). The
                 # veiled/behavioral cluster with no reliable token (goodbye + giving-away, grief-
                 # longing, faith-"called home") is NOT force-fit here — it is the documented target of
                 # the semantic/intent backstop (docs/CRISIS_BACKSTOP.md), because forcing it into
                 # substrings would either miss or sweep ordinary estate-planning and grief.
                 "disappointed that i woke up", "disappointed i woke up", "disappointed i wake up",
                 "if i wasnt around", "if i wasnt here anymore", "everyone would breathe easier if i wasnt",
                 "feel like a burden", "i feel like a burden", "im just dead weight to",
                 "cant do another day", "cant face another day", "another day in this body",
                 "pain is never going to stop", "pain will never stop", "im done fighting",
                 "dont want to continue being alive", "want to stop existing", "i want to stop existing",
                 "dont want to be a person anymore", "being alive is too painful", "dont want to be here anymore",
                 "dont wanna be here", "dont wanna be here anymore", "id rather not wake up",
                 "sleep and never wake up", "nap and never wake up", "go to sleep and never wake up",
                 "would anyone even notice if i was gone", "would anyone notice if i was gone",
                 "would anyone care if i was gone", "if i wasnt here would anyone",
                 "ive lived long enough", "lived long enough", "no reason to keep going",
                 "wont be around much longer", "wont be here much longer", "not be around much longer",
                 "praying not to wake up", "pray i dont wake up", "been praying not to wake up",
                 "whats even the point", "whats the point of it all",
                 # online / gaming euphemism (current, evolving; the unambiguous ones):
                 "log off for good", "delete my existence", "uninstall myself", "uninstall my life",
                 "alt f4 my life", "un-exist", "unexist",
                 # non-English cries (highest-signal per language; English-primary engine, low collision):
                 "acabar con mi vida", "mejor muerto", "estaria mejor muerto", "no le veo sentido a la vida",
                 "no despertar nunca", "todos estarian mejor sin mi", "mejor sin mi", "quitar la vida",
                 "para que seguir viviendo", "cansado de vivir", "terminar con mi vida", "no quiero seguir aqui",
                 "ya no puedo mas", "ya no aguanto", "je veux en finir", "en finir", "ne veux plus me reveiller",
                 "nao quero mais viver", "queria sumir pra sempre", "sumir pra sempre",
                 "ayoko na mabuhay", "gusto ko nang mawala", "khong muon song nua", "muon bien mat",
                 "biddi amout", "bidi amout")

_CRISIS_PATTERNS = tuple(re.compile(p) for p in (
    # the note
    r"\b(?:the|my) note (?:i|ive|i've) (?:wrote|written|left)\b.{0,60}\b(?:rereading|wording|goodbye|last|final|everyone|family)\b"
    r"|\b(?:rereading|reading)\b.{0,20}\bnote (?:i|ive|i've) (?:wrote|written|left)\b",
    # a chosen day, met with calm
    r"\bpicked (?:the|a) (?:day|date)\b.{0,50}\b(?:calm|at peace|peaceful|relief|relieved)\b",
    # goodbyes nobody is told are goodbyes
    r"\bsaying goodbye to (?:people|everyone|everybody|friends|family)\b.{0,40}\b(?:without (?:them|anyone) knowing|quietly|one by one)\b",
    # "won't be needing / around much longer"; stopping the meds for that reason
    r"\bwon'?t be (?:needing|around|here)\b.{0,20}\b(?:much longer|anymore|soon|long)\b"
    r"|\bstopped taking (?:the|my) (?:meds|medication|medicine|pills)\b.{0,30}\bwon'?t be needing\b",
    # a means that "looks like an answer"
    r"\b(?:bridge|rope|gun|pills|river|overpass|train)\b.{0,30}\b(?:look(?:s|ing)? like|feels? like|is)\b.{0,10}"
    r"\b(?:an answer|the answer|the only way|a way out|the exit|the only option)\b",
    # a lethal-dose question ("how many pills to take for a headache" does not match: no "would take")
    r"\bhow many (?:of my )?(?:pills|tablets)\b.{0,25}\b(?:it would take|would take|would it take)\b",
    # nothing holding me here — after a loss
    r"\bnothing (?:holding|keeping|tying) me (?:to|here|in)\b.{0,50}\b(?:funeral|passed|died|death|gone)\b"
    r"|\b(?:funeral|passed|died)\b.{0,50}\bnothing (?:holding|keeping|tying) me\b",
    # no one left who needs me
    r"\bno one (?:left )?(?:who )?needs me (?:here|anymore)\b|\bnobody needs me (?:here|anymore)\b",
    # putting the papers in order, "in case"
    r"\b(?:told|showed|gave) (?:my )?(?:sister|brother|wife|husband|son|daughter|mom|dad|mother|father|kids)\b"
    r".{0,30}\bwhere (?:the|my) (?:important )?(?:papers|documents|will|passwords|accounts)\b.{0,20}\bin case\b",
    # not coming home, and nobody would be surprised
    r"\bif i (?:just )?(?:didn'?t|never) (?:come|came|make it) home\b.{0,40}\b(?:nobody|no one)\b.{0,15}\b(?:surprised|notice|miss)\b",
    # giving things away, and feeling lighter / "won't need them"
    r"\bgiv(?:e|ing)\b.{0,10}\b(?:away )?my (?:things|stuff|belongings|possessions|tools)\b.{0,40}\b(?:lighter|won'?t (?:be )?need|settled|free)\b",
))


def normalize(text: str) -> str:
    """Lowercase, straighten smart quotes, drop apostrophes, collapse whitespace.

    Safety matching runs on this form. A person reaching for help types on a phone, in a
    hurry, without punctuation — the check must not depend on how their keyboard behaved.
    """
    # found: "text or ''" only substitutes the fallback for a FALSY text — a truthy non-string
    # (an int/list from an uncoerced caller) survives past that guard and crashes on ".lower()".
    # is_crisis() (the safety-critical function built on this) must never crash instead of
    # answering — every current caller happens to coerce first, but this is the one place that
    # should defend its own contract regardless, matching corpus.search()'s identical fix.
    t = (str(text) if text else "").lower().translate(_SMART_QUOTES).replace("'", "")
    return re.sub(r"\s+", " ", t).strip()


def substring_net(text: str) -> bool:
    """The exact / keyword / warning-sign net ALONE — is_crisis without the semantic backstop. Public so
    the backstop's build tool and its tests can measure what the backstop ADDS without the sealed
    artifact's own catches contaminating the count (issue #41). Not a surface's test: surfaces call
    is_crisis."""
    t = normalize(text)
    if t in _CRISIS_EXACT or any(w in t for w in _CRISIS_WORDS):
        return True
    return any(p.search(t) for p in _CRISIS_PATTERNS)   # the behavioral warning-sign net — only adds


def is_crisis(text: str) -> bool:
    """The one crisis test (substring net; the semantic backstop lives in the .org app)."""
    return substring_net(text)


CRISIS_RESPONSE = ("This looks like it may be about someone's safety. This tool checks arithmetic and "
                   "cannot help with that; please contact local emergency services or a crisis line now.")
