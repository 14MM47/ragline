"""Chat prompts — memory context building plus the pre/post/confidence passes.

The memory toggle is gated in ChatAgent.chat, NOT here: with memory OFF no
context is built and no passes run (the latest query stands alone); with memory
ON the builders here fold in the ENTIRE prior conversation, including turns
taken while memory was off. A turn's memory_enabled flag records the toggle
state at that turn (for the UI frame colour) — it does NOT hide the turn from
later memory-on prompts.

Ported from raggles minus the legacy (non-structured) pre-pass prompt.
"""

import tiktoken

from ragline.chat.models import SessionMemory

# One shared encoder for all budget math (same yardstick as chunking).
_enc = tiktoken.encoding_for_model("gpt-4o")


def _count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def build_conversation_context(memory: SessionMemory, max_tokens: int = 1500) -> str:
    """Compact SessionMemory into a token-budgeted string for the RAG prompt.

    Priority order under the budget: summary > key facts > recent turns.
    Recent turns include ALL turns regardless of each turn's memory state —
    with memory ON the whole prior conversation is in scope. (This builder is
    only ever called when the current query has memory ON; the memory-off case
    is gated upstream in ChatAgent.chat, which passes no context at all.)
    """
    if memory.turn_count == 0:
        return ""

    parts: list[str] = []
    used = 0

    # 1. Summary (highest priority).
    if memory.summary:
        summary_line = f"Conversation summary: {memory.summary}"
        cost = _count_tokens(summary_line)
        if used + cost <= max_tokens:
            parts.append(summary_line)
            used += cost

    # 2. Key facts as a bullet list (whole block, or as many lines as fit).
    if memory.key_facts:
        fact_lines = [f"- {kf.fact} [from: {kf.source}]" for kf in memory.key_facts]
        header = "Key facts discussed:"
        block = header + "\n" + "\n".join(fact_lines)
        cost = _count_tokens(block)
        if used + cost <= max_tokens:
            parts.append(block)
            used += cost
        else:
            # Partial: add facts until the budget runs out.
            parts.append(header)
            used += _count_tokens(header)
            for line in fact_lines:
                cost = _count_tokens("\n" + line)
                if used + cost > max_tokens:
                    break
                parts[-1] += "\n" + line
                used += cost

    # 3. Recent turns (newest first, truncated answers) — ALL turns, including
    # ones taken while memory was toggled off. The toggle gates a turn's OWN
    # prompt (see ChatAgent.chat), not its visibility to later memory-on turns:
    # with memory ON the model sees the whole conversation.
    if memory.turns and used < max_tokens:
        turn_lines: list[str] = []
        for t in reversed(memory.turns[-5:]):
            line = f"User: {t.user_query}\nAssistant: {t.answer[:150]}"
            cost = _count_tokens(line + "\n")
            if used + cost > max_tokens:
                break
            turn_lines.append(line)
            used += cost
        if turn_lines:
            parts.append("Recent exchanges:\n" + "\n".join(turn_lines))

    return "\n\n".join(parts)


# --- Library summary prompts ------------------------------------------------

# The model writes this marker instead of retyping every file name; ChatAgent
# swaps it for a list rendered straight from the metadata DB.
FILE_LIST_PLACEHOLDER = "[[FILE_LIST]]"

LIBRARY_SYSTEM = """\
You are a helpful document library assistant. The user is asking about the contents \
of the document library itself — not about the content within any specific document. \
Answer based on the library summary data provided."""

LIBRARY_USER_TEMPLATE = """\
User question: {query}

Document library summary:
{library_summary}

Provide a clear, well-organised answer to the user's question based on the library data above. \
Keep it short. Never write out the list of file names yourself: when the user wants to see \
the files, write the line {file_list_placeholder} on its own where the list belongs and the \
system will insert the complete, correctly formatted list there. Naming a few specific files \
to answer a narrower question is fine."""

# --- Structured pre-pass ----------------------------------------------------

STRUCTURED_PRE_PASS_SYSTEM = """\
You are a query analysis and rewriting system. Given the conversation memory and a \
new user query, analyze the query and produce a structured JSON response.

You must output a JSON object with these fields:
- "mode": one of "library", "compound", or "retrieval"
  - "library": user asks about the document collection itself (file names, counts, what's uploaded)
  - "compound": user asks about a topic AND wants collection-level context
  - "retrieval": user asks about a topic, concept, process, or fact (DEFAULT)
- "rewritten_query": the query rewritten as a standalone search query for document retrieval
- "excluded_sources": list of source filenames the user wants to exclude (e.g., ["foo.pdf"])
- "target_document_hints": list of document names/keywords the user is referring to (e.g., ["M580", "PanelView"])
- "has_contrastive_intent": true if user asks for something different/new/alternative
- "is_collection_wide": true if user asks about all documents or the entire collection

Rewriting rules:
1. Resolve all pronouns and references using the conversation context.
2. Preserve the user's intent exactly — especially contrastive language.
3. Write a SEARCH QUERY, not a sentence: keep product names, part numbers, \
attributes, values and units; drop filler such as "more information about", \
"tell me", "can you", "please".
4. In "retrieval" and "compound" mode, never mention the documents, the collection, \
the library or "the context" in rewritten_query — routing is expressed by mode and \
is_collection_wide, not by words. (Only a "library" query is about the documents themselves.)
5. Copy identifiers exactly as written (part numbers, model names, units). A \
lowercase "s" after an acronym is a plural: "hmis" = HMIs = HMI, "plcs" = PLC. \
Keep the acronym and add its expansion when the meaning is clear from context \
(HMI human-machine interface). Never change one acronym into a different one.
6. For follow-ups ("more about X", "what else", "and its …", "what about the other \
one"), fold in the specific product, family or topic from the conversation.
7. Do NOT include exclusion phrases in rewritten_query — put excluded files in excluded_sources instead.
8. When in doubt, default to mode "retrieval".

Examples (conversation context -> new query -> JSON):

Context: previous turn was about the PanelView 800 operator panel.
Query: more about hmis
{"mode": "retrieval", "rewritten_query": "HMI human-machine interface operator panels PanelView 800 features specifications", \
"excluded_sources": [], "target_document_hints": ["PanelView 800"], "has_contrastive_intent": false, "is_collection_wide": false}

Context: previous turn was about the 1756-OB16E output module.
Query: what's its max output current?
{"mode": "retrieval", "rewritten_query": "1756-OB16E maximum output current per channel", \
"excluded_sources": [], "target_document_hints": ["1756-OB16E"], "has_contrastive_intent": false, "is_collection_wide": false}

Context: previous turn recommended the Modicon M580 PLC from M580_datasheet.pdf.
Query: anything else besides the M580?
{"mode": "retrieval", "rewritten_query": "PLC controllers alternatives", "excluded_sources": ["M580_datasheet.pdf"], \
"target_document_hints": [], "has_contrastive_intent": true, "is_collection_wide": false}

Context: first query in the conversation.
Query: how many datasheets have been uploaded?
{"mode": "library", "rewritten_query": "number of uploaded datasheets", "excluded_sources": [], \
"target_document_hints": [], "has_contrastive_intent": false, "is_collection_wide": true}

Output ONLY valid JSON, no explanation."""


def build_structured_pre_pass_user(memory: SessionMemory, query: str) -> str:
    """Assemble the pre-pass user message: recent history + the new query.

    Includes ALL recent turns regardless of their memory state: this builder
    only runs when the CURRENT query has memory ON, and a memory-on query sees
    the whole conversation, including turns taken while memory was off (see
    build_conversation_context).
    """
    recent_turns = memory.turns[-5:]
    history = ""
    for t in recent_turns:
        history += f"User: {t.user_query}\nAssistant: {t.answer[:500]}...\n\n"

    if memory.turn_count > 0:
        context_section = f"""\
Conversation summary: {memory.summary}
Topics discussed: {', '.join(memory.topics) if memory.topics else 'none'}

Recent conversation:
{history}"""
    else:
        context_section = "This is the first query in the conversation (no prior context)."

    return f"""\
{context_section}
New user query: {query}

JSON analysis:"""


# --- Post-pass (memory update) ----------------------------------------------

POST_PASS_SYSTEM = """\
You are a conversation memory manager. Given the current memory state, the user's query, \
and the assistant's answer, update the memory by producing a JSON object.

Output a JSON object with exactly these fields:
- "summary": a 1-2 sentence summary of the entire conversation so far
- "topics": a list of topic strings discussed
- "key_facts": a list of objects with "fact" (string) and "source" (string) fields

Output ONLY valid JSON, no markdown fences or explanation."""


def build_post_pass_user(memory: SessionMemory, query: str, answer: str) -> str:
    """Current memory + the latest exchange -> the memory-update request."""
    existing_facts = [{"fact": f.fact, "source": f.source} for f in memory.key_facts]
    return f"""\
Current memory state:
- Summary: {memory.summary or '(new conversation)'}
- Topics: {memory.topics}
- Key facts: {existing_facts}

Latest exchange:
User: {query}
Assistant: {answer[:500]}

Updated memory JSON:"""


# --- Confidence pass ---------------------------------------------------------

CONFIDENCE_SYSTEM = """\
You are a response quality evaluator. Given the conversation memory, the user's \
ORIGINAL query, and the assistant's answer, assess the answer on two dimensions:

1. INTENT ALIGNMENT (most important): Does the answer actually address what the \
user meant? Carefully consider the user's original wording. For example:
   - If the user asked for "a different example", the answer MUST discuss a \
different item than what was previously covered. Discussing the same item is a \
critical failure regardless of answer quality.
   - If the user asked to "compare X and Y", the answer must cover both.
   - If the user asked "why", the answer must explain causation, not just describe.
2. QUALITY: Is the answer accurate, well-supported by sources, and complete?

Follow-ups ("tell me more", "what about that", "and the other one?") refer to the \
MOST RECENT exchange. The conversation summary and key facts can lag behind it, so \
when they disagree with the recent exchanges, the recent exchanges win.

Scoring guide:
- 0.0-0.3: Answer does not address the user's intent (wrong topic, same item \
when user asked for different, misunderstood question)
- 0.3-0.6: Partially addresses intent but with significant gaps or drift
- 0.6-0.8: Addresses intent with minor gaps or incomplete coverage
- 0.8-1.0: Fully addresses the user's intent with good quality and sourcing

Output a JSON object with exactly these fields:
- "score": a float between 0.0 and 1.0
- "report": a brief explanation focusing on whether the answer matches the user's intent

Output ONLY valid JSON, no markdown fences or explanation."""


def build_confidence_user(
    memory: SessionMemory, query: str, answer: str, rewritten_query: str = ""
) -> str:
    """Memory + recent exchanges + original query (+ rewrite when different) + answer.

    Recent exchanges include ALL turns regardless of their memory state, like
    the pre-pass: summary/topics/key_facts are only refreshed by the post-pass,
    which memory-off turns skip, so without the verbatim turns the scorer
    judges a follow-up against a stale picture (a memory-off turn changed the
    subject; the next memory-on "tell me more" correctly followed it and was
    scored 0 for following the "wrong" topic).
    """
    rewrite_section = ""
    if rewritten_query and rewritten_query != query:
        rewrite_section = f"""
The query was rewritten for retrieval as: {rewritten_query}
If this rewrite does not match the user's original intent, the answer is likely wrong."""

    recent_section = ""
    if memory.turns:
        # Oldest -> newest so "most recent" reads naturally at the bottom.
        lines = [
            f"User: {t.user_query}\nAssistant: {t.answer[:300]}"
            for t in memory.turns[-5:]
        ]
        recent_section = (
            "\n- Recent exchanges (oldest first; the last one is the most recent):\n"
            + "\n".join(lines)
        )

    return f"""\
Conversation context:
- Summary: {memory.summary or '(new conversation)'}
- Topics: {memory.topics}
- Key facts: {[f.fact for f in memory.key_facts]}{recent_section}

User's ORIGINAL query (evaluate intent against this): {query}{rewrite_section}
Answer: {answer[:4000]}{'... [answer truncated for evaluation — do not penalize the cut-off]' if len(answer) > 4000 else ''}

Confidence assessment JSON:"""
