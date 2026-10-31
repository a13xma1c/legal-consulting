"""AI legal assistant.

The assistant is provider-agnostic.  ``AnthropicProvider`` talks to the
Anthropic Messages API; ``FallbackProvider`` is a deterministic, offline
responder used when no API key is configured (and in the test-suite).

Usage::

    assistant = get_assistant()          # cached on the current app
    reply = assistant.reply(history)     # history = [{"role": "user", "content": "..."}]
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Protocol

from flask import current_app

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are LexCounsel's virtual legal information assistant on a legal
consulting website.

Your job:
- Help visitors understand general legal concepts and their options in plain English.
- Ask clarifying questions when the situation is unclear.
- Point out when a matter is urgent or time-sensitive (limitation periods, deadlines).
- Encourage users to book a consultation with one of our qualified lawyers for advice
  about their specific situation.

Rules you must follow:
- You provide general legal INFORMATION, not legal ADVICE. Say so when appropriate but
  do not repeat the disclaimer in every single message.
- Laws differ by jurisdiction. If the jurisdiction is unknown and it matters, ask.
- Never invent statutes, case names or citations. If unsure, say so.
- Never ask for or store sensitive identifiers (ID numbers, card numbers, passwords).
- Keep answers concise: short paragraphs or bullet points, under ~250 words.
- Be warm, professional and non-judgemental.
"""

DISCLAIMER = (
    "This assistant provides general legal information only and is not a substitute "
    "for advice from a qualified lawyer about your specific circumstances."
)

MAX_MESSAGE_LENGTH = 4000


class AIError(RuntimeError):
    """Raised when the AI provider fails."""


class AIProvider(Protocol):
    """Anything that can turn a conversation into a reply."""

    name: str

    def complete(self, system: str, messages: List[dict]) -> str:
        """Return the assistant's reply for ``messages``."""
        ...  # pragma: no cover


# --------------------------------------------------------------------------- #
# Anthropic
# --------------------------------------------------------------------------- #
class AnthropicProvider:
    """Provider backed by the Anthropic Messages API."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str, max_tokens: int = 700, client=None):
        self.model = model
        self.max_tokens = max_tokens
        if client is None:
            try:
                import anthropic  # pylint: disable=import-outside-toplevel
            except ImportError as exc:  # pragma: no cover - depends on env
                raise AIError("The 'anthropic' package is not installed.") from exc
            client = anthropic.Anthropic(api_key=api_key)
        self._client = client

    def complete(self, system: str, messages: List[dict]) -> str:
        """Call the Messages API and join all text blocks of the reply."""
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=messages,
            )
        except Exception as exc:  # noqa: BLE001 - surface a uniform error
            logger.exception("Anthropic request failed")
            raise AIError(str(exc)) from exc

        parts = [
            block.text
            for block in getattr(response, "content", [])
            if getattr(block, "type", None) == "text"
        ]
        text = "\n".join(parts).strip()
        if not text:
            raise AIError("Empty response from model.")
        return text


# --------------------------------------------------------------------------- #
# Offline fallback
# --------------------------------------------------------------------------- #
@dataclass
class Topic:
    """A keyword-matched topic for the fallback responder."""

    name: str
    keywords: Iterable[str]
    answer: str
    follow_up: str = ""
    patterns: List[re.Pattern] = field(default_factory=list, init=False)

    def __post_init__(self):
        self.patterns = [
            re.compile(rf"\b{re.escape(k)}\w*", re.IGNORECASE) for k in self.keywords
        ]

    def score(self, text: str) -> int:
        """Number of keyword hits in ``text``."""
        return sum(1 for p in self.patterns if p.search(text))


TOPICS: List[Topic] = [
    Topic(
        "tenancy",
        ["landlord", "tenant", "rent", "lease", "evict", "deposit", "tenancy"],
        "Tenancy disputes are very common. A few general points:\n\n"
        "- Your written lease (and local tenancy law) governs notice periods, rent "
        "increases and deposit returns.\n"
        "- Landlords generally must follow a formal legal process before evicting - "
        "changing locks or removing belongings without a court order is usually unlawful.\n"
        "- Keep copies of all correspondence, photos of the property and proof of payments.",
        "Is this about a deposit, an eviction notice, repairs, or something else?",
    ),
    Topic(
        "employment",
        ["employer", "employee", "fired", "dismiss", "redundan", "wage", "salary",
         "workplace", "harass", "unfair", "contract of employment", "notice period"],
        "Employment matters often have **strict deadlines** - in many jurisdictions a "
        "claim for unfair dismissal must be filed within weeks, not months.\n\n"
        "- Check your employment contract and any staff handbook.\n"
        "- Write down a timeline of events while it is fresh.\n"
        "- Keep payslips, emails and written warnings.\n"
        "- Raising a formal grievance is often a required first step.",
        "Are you still employed, or has your employment already ended?",
    ),
    Topic(
        "family",
        ["divorce", "custody", "child", "spouse", "marriage", "separat", "alimony",
         "maintenance", "prenup", "adopt"],
        "Family law is deeply personal, and the best outcome usually comes from a clear "
        "understanding of your rights early on.\n\n"
        "- Courts focus on the **best interests of the child** when deciding custody and "
        "contact.\n"
        "- Financial settlements consider the length of the marriage, contributions and "
        "future needs.\n"
        "- Mediation is often encouraged (and sometimes required) before going to court.",
        "Would you like general information on separation, children, or finances?",
    ),
    Topic(
        "contract",
        ["contract", "agreement", "breach", "terms", "signed", "invoice", "refund",
         "supplier", "client owes", "unpaid"],
        "For a contract dispute, the key questions are usually:\n\n"
        "1. What exactly did the parties agree (written terms, emails, conduct)?\n"
        "2. Was there a breach, and what loss did it cause?\n"
        "3. What remedies does the contract or the law provide?\n\n"
        "A well-drafted letter before action often resolves matters without litigation.",
        "Is the agreement in writing, and roughly what value is in dispute?",
    ),
    Topic(
        "wills",
        ["will", "estate", "inherit", "probate", "executor", "trust", "beneficiar",
         "power of attorney", "passed away", "died"],
        "Wills and estates:\n\n"
        "- A valid will normally needs to be in writing, signed and properly witnessed.\n"
        "- If someone dies without a will, intestacy rules decide who inherits.\n"
        "- Executors have legal duties and can be personally liable for mistakes.\n"
        "- Challenging a will usually has a time limit from the grant of probate.",
        "Are you planning your own estate or dealing with someone else's?",
    ),
    Topic(
        "property",
        ["property", "house", "mortgage", "conveyanc", "boundary", "neighbour",
         "neighbor", "easement", "title deed", "buy a home", "selling"],
        "Property transactions and disputes:\n\n"
        "- Always get the title checked before buying; hidden charges or restrictions "
        "can be costly.\n"
        "- Boundary and neighbour disputes are best resolved by negotiation or mediation "
        "first - litigation is expensive relative to the value involved.\n"
        "- Keep a written record of any agreements with neighbours.",
        "Is this about buying/selling, or a dispute over an existing property?",
    ),
    Topic(
        "criminal",
        ["arrest", "police", "charged", "criminal", "bail", "court date", "offence",
         "offense", "theft", "assault", "drink driving", "dui"],
        "If you have been arrested or charged, a few important things:\n\n"
        "- You generally have the **right to remain silent** and the right to a lawyer. "
        "Use both.\n"
        "- Do not discuss the case on social media or with witnesses.\n"
        "- Attend every court date - missing one can lead to a warrant.\n\n"
        "Criminal matters are urgent; please speak to a defence lawyer as soon as possible.",
        "Has a court date already been set?",
    ),
    Topic(
        "business",
        ["company", "business", "startup", "shareholder", "director", "partnership",
         "incorporat", "llc", "limited company", "trademark", "copyright", "patent"],
        "Business and commercial matters:\n\n"
        "- Choosing the right structure (sole trader, partnership, company) affects tax "
        "and personal liability.\n"
        "- Shareholder or partnership agreements prevent most future disputes.\n"
        "- Register trade marks early - rights are generally first-to-file in many "
        "jurisdictions.",
        "Are you setting up a business, or dealing with an existing one?",
    ),
    Topic(
        "immigration",
        ["visa", "immigra", "citizenship", "deport", "residence permit", "asylum",
         "work permit", "sponsor"],
        "Immigration rules change frequently and deadlines are strict.\n\n"
        "- Never let a visa lapse while waiting - apply for an extension before expiry.\n"
        "- Keep certified copies of every document you submit.\n"
        "- Refusals can often be appealed or reviewed, but only within a short window.",
        "Which country's immigration system does your question relate to?",
    ),
    Topic(
        "injury",
        ["accident", "injur", "negligen", "compensation", "medical malpractice",
         "slip", "car crash", "whiplash"],
        "Personal injury claims generally require showing that someone owed you a duty of "
        "care, breached it, and caused your injury.\n\n"
        "- Seek medical attention and keep all records.\n"
        "- Photograph the scene and get witness details.\n"
        "- Limitation periods apply - often a few years from the incident, but shorter "
        "for some claims.",
        "When did the incident happen, and have you received medical treatment?",
    ),
    Topic(
        "consultation",
        ["book", "appointment", "consult", "speak to a lawyer", "talk to a lawyer",
         "hire", "cost", "fee", "price", "how much"],
        "You can request a consultation with one of our lawyers from the **Consultations** "
        "page once you are logged in. Tell us a little about your matter and a lawyer "
        "in the relevant practice area will respond.\n\n"
        "Initial consultations are a chance to understand your options and the likely "
        "costs before committing to anything.",
        "Would you like me to summarise what information to have ready for your first meeting?",
    ),
]

GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|good (morning|afternoon|evening)|greetings)\b[\s!.,]*$",
    re.IGNORECASE,
)
THANKS_RE = re.compile(r"\b(thank(s| you)|cheers|appreciate)\b", re.IGNORECASE)


class FallbackProvider:
    """Deterministic keyword-based responder for offline / keyless operation."""

    name = "fallback"

    def __init__(self, topics: Optional[List[Topic]] = None):
        self.topics = topics or TOPICS

    def match_topic(self, text: str) -> Optional[Topic]:
        """Return the best-matching topic, or ``None``."""
        best, best_score = None, 0
        for topic in self.topics:
            score = topic.score(text)
            if score > best_score:
                best, best_score = topic, score
        return best

    def complete(self, system: str, messages: List[dict]) -> str:  # pylint: disable=unused-argument
        """Answer based on keyword matching of the latest user message."""
        user_messages = [m for m in messages if m.get("role") == "user"]
        if not user_messages:
            return self._greeting()
        last = user_messages[-1].get("content", "")

        if GREETING_RE.match(last):
            return self._greeting()
        if THANKS_RE.search(last) and len(last) < 80:
            return (
                "You're very welcome. If you'd like tailored advice, our lawyers are "
                "happy to help - just request a consultation. Take care!"
            )

        topic = self.match_topic(last)
        if topic is None:
            return (
                "Thanks for your message. I can share general information on areas such as "
                "tenancy, employment, family law, contracts, wills and estates, property, "
                "criminal matters, business law, immigration and personal injury.\n\n"
                "Could you tell me a bit more about your situation - what happened, and "
                "what outcome you're hoping for?\n\n"
                f"_{DISCLAIMER}_"
            )

        reply = topic.answer
        if topic.follow_up:
            reply += f"\n\n{topic.follow_up}"
        if len(user_messages) == 1:
            reply += f"\n\n_{DISCLAIMER}_"
        return reply

    @staticmethod
    def _greeting() -> str:
        return (
            "Hello! I'm LexCounsel's virtual assistant. I can explain general legal "
            "concepts and help you work out your next step.\n\n"
            "What can I help you with today?"
        )


# --------------------------------------------------------------------------- #
# Assistant facade
# --------------------------------------------------------------------------- #
class LegalAssistant:
    """High-level API used by the chat blueprint."""

    def __init__(self, provider: AIProvider, history_limit: int = 20,
                 system_prompt: str = SYSTEM_PROMPT):
        self.provider = provider
        self.history_limit = history_limit
        self.system_prompt = system_prompt

    @property
    def provider_name(self) -> str:
        """Name of the active provider (``anthropic`` or ``fallback``)."""
        return self.provider.name

    @staticmethod
    def sanitise_history(history: Iterable[dict]) -> List[dict]:
        """Keep only valid role/content pairs and collapse consecutive same-role turns."""
        cleaned: List[dict] = []
        for item in history:
            role = item.get("role")
            content = (item.get("content") or "").strip()
            if role not in ("user", "assistant") or not content:
                continue
            if cleaned and cleaned[-1]["role"] == role:
                cleaned[-1]["content"] += "\n\n" + content
            else:
                cleaned.append({"role": role, "content": content})
        # The API requires the conversation to start with a user turn.
        while cleaned and cleaned[0]["role"] != "user":
            cleaned.pop(0)
        return cleaned

    def reply(self, history: Iterable[dict]) -> str:
        """Generate the assistant's reply to a conversation history."""
        messages = self.sanitise_history(history)[-self.history_limit:]
        # Ensure we did not trim to a leading assistant message.
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        if not messages:
            raise ValueError("Conversation must contain at least one user message.")
        return self.provider.complete(self.system_prompt, messages)


def build_assistant(config) -> LegalAssistant:
    """Create an assistant from a Flask config mapping."""
    provider_name = (config.get("AI_PROVIDER") or "auto").lower()
    api_key = config.get("ANTHROPIC_API_KEY")

    provider: AIProvider
    if provider_name == "anthropic" or (provider_name == "auto" and api_key):
        if not api_key:
            raise AIError("AI_PROVIDER=anthropic requires ANTHROPIC_API_KEY.")
        provider = AnthropicProvider(
            api_key=api_key,
            model=config.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=int(config.get("AI_MAX_TOKENS", 700)),
        )
    else:
        provider = FallbackProvider()
    logger.info("AI assistant using provider: %s", provider.name)
    return LegalAssistant(provider, history_limit=int(config.get("AI_HISTORY_LIMIT", 20)))


def get_assistant() -> LegalAssistant:
    """Return the assistant cached on the current application."""
    app = current_app._get_current_object()  # pylint: disable=protected-access
    if "legal_assistant" not in app.extensions:
        app.extensions["legal_assistant"] = build_assistant(app.config)
    return app.extensions["legal_assistant"]
