"""Context-aware subtitle translation using OpenAI."""
import re
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Callable
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OPENAI_API_KEY, OPENAI_MODEL, DEFAULT_BATCH_SIZE, DEFAULT_CONTEXT_SIZE
from .subtitles import SubtitleEntry, has_chinese, write_srt


@dataclass
class TranslationResult:
    success: bool
    entries: list[SubtitleEntry] | None = None
    error: str | None = None


def generate_translation_summary(client, model: str, entries: list[SubtitleEntry]) -> str:
    """
    Generate a summary of the entire transcript for context.
    This gives the translator global understanding of topic, speakers, key terms.
    """
    # Combine all text (truncate if too long)
    full_text = " ".join([e.text for e in entries])
    if len(full_text) > 8000:  # Roughly 2k tokens
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
            max_tokens=1024,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return ""


def translate_batch_with_context(
    client,
    model: str,
    batch: list[SubtitleEntry],
    context_before: list[SubtitleEntry],
    context_after: list[SubtitleEntry],
    global_summary: str = "",
    max_retries: int = 3
) -> list[str]:
    """Translate a batch with surrounding context using markers."""

    before_text = " ".join([e.text for e in context_before]) if context_before else ""
    after_text = " ".join([e.text for e in context_after]) if context_after else ""

    lines_with_markers = [f"<{i}>{e.text}</{i}>" for i, e in enumerate(batch)]

    # Build system context if we have a global summary
    system_context = ""
    if global_summary:
        system_context = f"""GLOBAL CONTEXT (understand the full conversation):
{global_summary}

"""

    prompt = f"""{system_context}Translate English subtitles to Simplified Chinese for video subtitles.

NEARBY CONTEXT (do NOT translate, just for understanding):
Before: {before_text}
After: {after_text}

TRANSLATE THESE {len(batch)} LINES (keep the <N></N> markers exactly):
{chr(10).join(lines_with_markers)}

RULES:
1. Keep EXACTLY {len(batch)} translations with markers <0></0>, <1></1>, etc.
2. Understand the FULL context before translating - lines may be fragments of sentences
3. Translate naturally for Chinese viewers - do NOT translate word-by-word
4. Keep translations concise (subtitle length)
5. Output ONLY the translated lines with markers, nothing else"""

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
            response_text = response.choices[0].message.content.strip()

            translations = []
            for i in range(len(batch)):
                pattern = f"<{i}>(.*?)</{i}>"
                match = re.search(pattern, response_text, re.DOTALL)
                if match:
                    translations.append(match.group(1).strip())
                else:
                    raise ValueError(f"Missing marker <{i}>")

            for i, t in enumerate(translations):
                if not has_chinese(t):
                    raise ValueError(f"Line {i} has no Chinese: {t}")

            return translations

        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                raise RuntimeError(f"Batch failed after {max_retries} attempts: {e}")


def translate_chunk_with_full_context(
    client,
    model: str,
    chunk: list[SubtitleEntry],
    chunk_start_idx: int,
    full_transcript_summary: str,
    max_retries: int = 3
) -> list[str]:
    """Translate a chunk with full transcript context."""

    lines_with_markers = [f"<{i}>{e.text}</{i}>" for i, e in enumerate(chunk)]

    prompt = f"""Translate English subtitles to Simplified Chinese.

FULL TRANSCRIPT CONTEXT (understand the whole conversation):
{full_transcript_summary}

NOW TRANSLATE THESE {len(chunk)} LINES (lines {chunk_start_idx+1}-{chunk_start_idx+len(chunk)} of the video):
{chr(10).join(lines_with_markers)}

RULES:
1. Return EXACTLY {len(chunk)} translations with markers <0></0> through <{len(chunk)-1}></{len(chunk)-1}>
2. Translate naturally for Chinese viewers
3. Keep translations concise (subtitle length)
4. Output ONLY the translated lines with markers, one per line"""

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )
            response_text = response.choices[0].message.content.strip()

            translations = []
            missing = []
            for i in range(len(chunk)):
                # Try multiple patterns (with/without spaces, newlines)
                pattern = f"<{i}>\\s*(.*?)\\s*</{i}>"
                match = re.search(pattern, response_text, re.DOTALL)
                if match:
                    translations.append(match.group(1).strip())
                else:
                    missing.append(i)
                    translations.append(None)

            # If any missing, raise error to trigger retry
            if missing:
                raise ValueError(f"Missing markers: {missing[:5]}{'...' if len(missing) > 5 else ''}")

            # Validate Chinese
            for i, t in enumerate(translations):
                if not t or not has_chinese(t):
                    raise ValueError(f"Line {i} has no Chinese")

            return translations

        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 + attempt)  # Increasing backoff
            else:
                raise RuntimeError(f"Chunk translation failed after {max_retries} attempts: {e}")


def translate_subtitles(
    entries: list[SubtitleEntry],
    progress_callback: Callable[[int, int, str], None] | None = None,
    batch_size: int = 20,
    context_size: int = 10,
) -> TranslationResult:
    """
    Translate subtitle entries with summary + chunked translation.

    Approach:
    1. Generate a brief summary of the full transcript (1 API call)
    2. Translate in chunks of batch_size, with summary + local context

    Args:
        entries: Subtitle entries to translate
        progress_callback: Called with (current, total, message)
        batch_size: Lines per chunk (default 20)
        context_size: Lines before/after for local context (default 10)

    Returns entries with translations filled in.
    """
    from openai import OpenAI

    if not OPENAI_API_KEY:
        return TranslationResult(False, error="OPENAI_API_KEY not set")

    client = OpenAI(api_key=OPENAI_API_KEY)
    total = len(entries)
    total_batches = (total + batch_size - 1) // batch_size

    try:
        # Step 1: Generate summary of full transcript (one API call)
        if progress_callback:
            progress_callback(0, total_batches + 1, "Analyzing transcript...")

        summary = generate_translation_summary(client, OPENAI_MODEL, entries)

        # Step 2: Translate in chunks with summary + local context
        for i in range(0, total, batch_size):
            batch = entries[i:i + batch_size]
            batch_num = i // batch_size + 1

            context_before = entries[max(0, i - context_size):i]
            context_after = entries[i + len(batch):i + len(batch) + context_size]

            if progress_callback:
                progress_callback(batch_num, total_batches, f"Translating {batch_num}/{total_batches}")

            translations = translate_batch_with_context(
                client, OPENAI_MODEL, batch, context_before, context_after,
                global_summary=summary
            )

            for j, trans in enumerate(translations):
                entries[i + j].translation = trans

        return TranslationResult(success=True, entries=entries)

    except Exception as e:
        return TranslationResult(False, error=str(e))
