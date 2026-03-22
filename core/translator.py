"""Context-aware subtitle translation using OpenAI — production-robust."""
import re
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Callable
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OPENAI_API_KEY, OPENAI_MODEL
from .subtitles import SubtitleEntry, has_chinese, write_srt


@dataclass
class TranslationResult:
    success: bool
    entries: list[SubtitleEntry] | None = None
    error: str | None = None
    chunk_size_used: int | None = None
    num_chunks: int | None = None
    strategy_description: str | None = None


def compute_optimal_batch_size(entries: list[SubtitleEntry]) -> tuple[int, str]:
    """
    Compute optimal batch size based on content length and density.

    Returns (batch_size, strategy_description).
    """
    n = len(entries)
    avg_words = sum(len(e.text.split()) for e in entries) / max(n, 1)

    # Rough token estimate per entry: English input + Chinese output ≈ 3.5x words
    tokens_per_entry = avg_words * 3.5

    # Target ~1800 subtitle content tokens per batch
    target_tokens = 1800
    token_based_size = int(target_tokens / max(tokens_per_entry, 1))

    if n <= 30:
        optimal = n
        strategy = f"single batch ({n} lines) — short content, maximum context"
    elif n <= 80:
        optimal = max(min(token_based_size, 30), 20)
        strategy = f"large batches (~{optimal} lines) — short-medium content"
    elif n <= 200:
        optimal = max(min(token_based_size, 25), 15)
        strategy = f"standard batches (~{optimal} lines)"
    elif n <= 500:
        optimal = max(min(token_based_size, 20), 12)
        strategy = f"moderate batches (~{optimal} lines) — long content"
    else:
        optimal = max(min(token_based_size, 15), 10)
        strategy = f"smaller batches (~{optimal} lines) — very long content"

    if avg_words > 15:
        optimal = max(optimal - 3, 8)
        strategy += " (reduced for dense text)"

    return optimal, strategy


def split_into_semantic_chunks(
    entries: list[SubtitleEntry],
    target_size: int,
    max_lookahead: int = 5,
) -> list[list[SubtitleEntry]]:
    """
    Split entries into chunks, preferring natural sentence boundaries.
    """
    if target_size >= len(entries):
        return [list(entries)]

    chunks = []
    i = 0
    while i < len(entries):
        chunk_end = min(i + target_size, len(entries))

        if chunk_end < len(entries):
            best_break = chunk_end
            for j in range(chunk_end, min(chunk_end + max_lookahead, len(entries))):
                prev_text = entries[j - 1].text.rstrip()
                if prev_text.endswith(('.', '?', '!', '...', '。', '？', '！')):
                    best_break = j
                    break
                next_text = entries[j].text.lstrip() if j < len(entries) else ""
                if next_text and next_text[0].isupper():
                    best_break = j
                    break
            chunk_end = best_break

        chunks.append(list(entries[i:chunk_end]))
        i = chunk_end

    return chunks


def generate_translation_summary(client, model: str, entries: list[SubtitleEntry]) -> str:
    """Generate a summary of the entire transcript for translation context."""
    full_text = " ".join([e.text for e in entries])
    if len(full_text) > 8000:
        full_text = full_text[:8000] + "..."

    prompt = f"""Analyze this English transcript and provide a brief summary for a translator.

TRANSCRIPT:
{full_text}

Provide a JSON response with:
1. "topic": What is this conversation/video about? (1 sentence)
2. "speakers": Who are the speakers and their roles? (brief)
3. "key_terms": Important names, technical terms, or concepts that need consistent translation (list 5-10 terms with suggested Chinese translations)
4. "tone": What is the tone? (formal, casual, technical, emotional, etc.)

Keep it concise - this will be used as context for translating subtitles."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=1024,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Robust parsing — try multiple strategies to extract translations
# ---------------------------------------------------------------------------

def _parse_markers(response_text: str, count: int) -> list[str | None]:
    """
    Extract numbered translations from LLM response.
    Tries 0-indexed, then 1-indexed markers, then line-order fallback.
    Returns a list of length `count` with None for any missing entries.
    """
    results = [None] * count

    # Strategy 1: 0-indexed <N>...</N>
    for i in range(count):
        pattern = f"<{i}>\\s*(.*?)\\s*</{i}>"
        match = re.search(pattern, response_text, re.DOTALL)
        if match:
            text = match.group(1).strip()
            if has_chinese(text):
                results[i] = text

    if all(r is not None for r in results):
        return results

    # Strategy 2: 1-indexed <N>...</N> (common LLM mistake)
    alt = [None] * count
    for i in range(count):
        pattern = f"<{i + 1}>\\s*(.*?)\\s*</{i + 1}>"
        match = re.search(pattern, response_text, re.DOTALL)
        if match:
            text = match.group(1).strip()
            if has_chinese(text):
                alt[i] = text

    found_orig = sum(1 for r in results if r is not None)
    found_alt = sum(1 for r in alt if r is not None)
    if found_alt > found_orig:
        results = alt

    if all(r is not None for r in results):
        return results

    # Strategy 3: no markers at all — split by lines and hope they're in order
    missing_count = sum(1 for r in results if r is None)
    if missing_count == count:
        # Model returned plain lines without markers
        lines = [
            l.strip() for l in response_text.split('\n')
            if l.strip() and has_chinese(l.strip())
        ]
        # Strip any leading numbering like "1. " or "1) " or "1: "
        cleaned = []
        for l in lines:
            cleaned.append(re.sub(r'^\d+[\.\)\:]\s*', '', l).strip())
        if len(cleaned) == count:
            return cleaned

    return results


# ---------------------------------------------------------------------------
# Translation with multi-level fallback
# ---------------------------------------------------------------------------

def _call_translate_batch(
    client, model: str, batch: list[SubtitleEntry],
    context_before: list[SubtitleEntry],
    context_after: list[SubtitleEntry],
    global_summary: str,
) -> list[str | None]:
    """Single API call to translate a batch. Returns parsed results (may have Nones)."""
    before_text = " ".join([e.text for e in context_before]) if context_before else ""
    after_text = " ".join([e.text for e in context_after]) if context_after else ""

    lines_with_markers = [f"<{i}>{e.text}</{i}>" for i, e in enumerate(batch)]

    system_context = ""
    if global_summary:
        system_context = f"""GLOBAL CONTEXT (understand the full conversation):
{global_summary}

"""

    prompt = f"""{system_context}Translate English subtitles to Simplified Chinese for video subtitles.

NEARBY CONTEXT (do NOT translate, just for understanding):
Before: {before_text}
After: {after_text}

TRANSLATE THESE {len(batch)} LINES.
For each line, keep the EXACT same marker tags <N>...</N> around your Chinese translation.

{chr(10).join(lines_with_markers)}

RULES:
1. Return EXACTLY {len(batch)} translations, each wrapped in its original <N></N> marker
2. Example output format: <0>中文翻译</0>
3. Translate naturally for Chinese viewers, not word-by-word
4. Keep translations concise (subtitle length)
5. Output ONLY the translated lines with markers, one per line, nothing else"""

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=4096,
    )
    response_text = response.choices[0].message.content.strip()
    return _parse_markers(response_text, len(batch))


def _translate_single(
    client, model: str, entry: SubtitleEntry,
    context_before: list[SubtitleEntry],
    context_after: list[SubtitleEntry],
    global_summary: str,
) -> str | None:
    """Last-resort fallback: translate one line at a time."""
    before_text = " ".join(e.text for e in context_before[-3:]) if context_before else ""
    after_text = " ".join(e.text for e in context_after[:3]) if context_after else ""

    prompt = f"""Translate this English subtitle to Simplified Chinese.

Context before: {before_text}
Context after: {after_text}

Translate: {entry.text}

Return ONLY the Chinese translation, nothing else."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=256,
        )
        text = response.choices[0].message.content.strip()
        # Strip any quotes or markers the model might add
        text = re.sub(r'^["\']|["\']$', '', text).strip()
        if has_chinese(text):
            return text
    except Exception:
        pass
    return None


def translate_batch_with_context(
    client,
    model: str,
    batch: list[SubtitleEntry],
    context_before: list[SubtitleEntry],
    context_after: list[SubtitleEntry],
    global_summary: str = "",
    max_retries: int = 3,
) -> list[str]:
    """
    Translate a batch with multi-level fallback:
      1. Full batch with retries (robust parsing extracts what it can)
      2. Split into halves for remaining failures
      3. Individual line translation as last resort
    """
    results = [None] * len(batch)

    # --- Phase 1: try full batch, accumulate successes across retries ---
    for attempt in range(max_retries):
        if all(r is not None for r in results):
            break
        try:
            parsed = _call_translate_batch(
                client, model, batch,
                context_before, context_after, global_summary,
            )
            # Merge: only fill in Nones
            for i, val in enumerate(parsed):
                if results[i] is None and val is not None:
                    results[i] = val
        except Exception:
            time.sleep(2 + attempt)

    if all(r is not None for r in results):
        return results

    # --- Phase 2: split remaining missing lines into a sub-batch ---
    missing_indices = [i for i, r in enumerate(results) if r is None]
    if len(missing_indices) > 1:
        sub_batch = [batch[i] for i in missing_indices]
        try:
            parsed = _call_translate_batch(
                client, model, sub_batch,
                context_before, context_after, global_summary,
            )
            for j, idx in enumerate(missing_indices):
                if parsed[j] is not None:
                    results[idx] = parsed[j]
        except Exception:
            pass

    if all(r is not None for r in results):
        return results

    # --- Phase 3: translate remaining lines individually ---
    still_missing = [i for i, r in enumerate(results) if r is None]
    for i in still_missing:
        ctx_b = context_before[-3:] + [batch[j] for j in range(i)]
        ctx_a = [batch[j] for j in range(i + 1, len(batch))] + context_after[:3]
        val = _translate_single(client, model, batch[i], ctx_b, ctx_a, global_summary)
        if val is not None:
            results[i] = val

    # Final check
    final_missing = [i for i, r in enumerate(results) if r is None]
    if final_missing:
        raise RuntimeError(
            f"Failed to translate {len(final_missing)}/{len(batch)} lines "
            f"(indices {final_missing[:5]}{'...' if len(final_missing) > 5 else ''}) "
            f"after batch retries + individual fallback"
        )

    return results


def translate_subtitles(
    entries: list[SubtitleEntry],
    progress_callback: Callable[[int, int, str], None] | None = None,
    batch_size: int | None = None,
    context_size: int = 5,
) -> TranslationResult:
    """
    Translate subtitle entries with summary + adaptive chunked translation.

    Args:
        entries: Subtitle entries to translate
        progress_callback: Called with (current, total, message)
        batch_size: Lines per chunk. None = auto-compute based on content.
        context_size: Lines before/after each chunk passed as local context

    Returns TranslationResult with entries filled in and strategy metadata.
    """
    from openai import OpenAI

    if not OPENAI_API_KEY:
        return TranslationResult(False, error="OPENAI_API_KEY not set")

    client = OpenAI(api_key=OPENAI_API_KEY)

    # Compute optimal batch size if not specified
    if batch_size is None:
        batch_size, strategy_desc = compute_optimal_batch_size(entries)
    else:
        strategy_desc = f"manual override ({batch_size} lines per batch)"

    # Split at semantic boundaries
    chunks = split_into_semantic_chunks(entries, batch_size)
    total_chunks = len(chunks)

    try:
        # Step 1: Generate full-transcript summary (1 API call)
        if progress_callback:
            progress_callback(0, total_chunks + 1, "Analyzing transcript...")

        summary = generate_translation_summary(client, OPENAI_MODEL, entries)

        # Step 2: Translate each chunk with summary + local context
        start_idx = 0
        for chunk_idx, chunk in enumerate(chunks):
            context_before = entries[max(0, start_idx - context_size):start_idx]
            context_after_start = start_idx + len(chunk)
            context_after = entries[context_after_start:context_after_start + context_size]

            if progress_callback:
                progress_callback(
                    chunk_idx + 1,
                    total_chunks,
                    f"Translating chunk {chunk_idx + 1}/{total_chunks} ({len(chunk)} lines)"
                )

            translations = translate_batch_with_context(
                client, OPENAI_MODEL, chunk,
                context_before, context_after,
                global_summary=summary,
            )

            for j, trans in enumerate(translations):
                chunk[j].translation = trans

            start_idx += len(chunk)

        return TranslationResult(
            success=True,
            entries=entries,
            chunk_size_used=batch_size,
            num_chunks=total_chunks,
            strategy_description=strategy_desc,
        )

    except Exception as e:
        return TranslationResult(False, error=str(e))
