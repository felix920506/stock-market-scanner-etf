#!/usr/bin/env python3
"""
Lightweight LLM summarization via OpenClaw.

Uses the dedicated "summarizer" agent (Gemini 3 Flash) to summarize
news snippets into 1-2 line company context blurbs.

All LLM traffic goes through OpenClaw's gateway — auth, routing, and
model selection are handled by the platform. No direct API calls.

Prerequisites:
    openclaw agents add summarizer \
      --model openrouter/google/gemini-3-flash-preview \
      --workspace /path/to/minimal-workspace \
      --non-interactive
"""

import json
import subprocess
import sys


def call_llm(prompt: str, timeout: int = 30) -> str:
    """
    Run a single LLM turn via `openclaw agent --agent summarizer`.

    Uses a dedicated session to avoid polluting the main agent,
    and --json for structured output parsing.
    """
    cmd = [
        "openclaw", "agent",
        "--agent", "summarizer",
        "--session-id", "scanner-summarizer",
        "--json",
        "--timeout", str(timeout),
        "-m", prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 10,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(f"openclaw agent failed (rc={result.returncode}): {stderr}")

        # Parse JSON output
        output = json.loads(result.stdout)

        # Extract the response text — payloads can be at top level or nested under "result"
        payloads = output.get("payloads") or output.get("result", {}).get("payloads", [])
        if payloads:
            return payloads[0].get("text", "").strip()

        return ""

    except subprocess.TimeoutExpired:
        raise RuntimeError(f"openclaw agent timed out after {timeout}s")
    except json.JSONDecodeError:
        # Fallback: treat stdout as plain text
        return result.stdout.strip() if result.stdout else ""


def summarize_news_for_ticker(
    ticker: str,
    name: str,
    articles: list[dict],
    language: str = "zh-TW",
) -> str:
    """
    Summarize a list of news articles into a 1-2 line context blurb.

    Args:
        ticker: Stock ticker
        name: Company name
        articles: List of {"title": ..., "snippet": ...} dicts
        language: Output language (zh-TW or en)

    Returns:
        A 1-2 line summary string, or empty string if no meaningful news.
    """
    if not articles:
        return ""

    # Build article text for the prompt
    article_text = ""
    for i, a in enumerate(articles[:5], 1):
        title = a.get("title", "").strip()
        snippet = a.get("snippet", "").strip()
        if title or snippet:
            article_text += f"{i}. {title}\n   {snippet}\n"

    if not article_text.strip():
        return ""

    if language == "zh-TW":
        prompt = (
            f"你是股票市場研究助手。用繁體中文回覆。簡潔扼要。\n\n"
            f"以下是 {name}（{ticker}）的近期新聞標題與摘要：\n\n"
            f"{article_text}\n"
            f"請用1-2行（不超過100字）總結這家公司最近的重要動態。"
            f"只寫最關鍵的事件或趨勢。如果沒有重要消息，回覆空白。"
            f"不要加任何前綴、標題或標點符號開頭。直接寫摘要。"
        )
    else:
        prompt = (
            f"You are a stock market research assistant. Be concise.\n\n"
            f"Here are recent news headlines and snippets for {name} ({ticker}):\n\n"
            f"{article_text}\n"
            f"Summarize the most important recent developments in 1-2 lines (max 100 words). "
            f"Only include material events or trends. If nothing significant, reply with nothing. "
            f"No prefixes or headers. Just the summary."
        )

    try:
        return call_llm(prompt)
    except Exception as e:
        print(f"  [LLM] Summarization failed for {ticker}: {e}", file=sys.stderr)
        return ""


def summarize_batch(
    news_data: dict,
    language: str = "zh-TW",
) -> dict[str, str]:
    """
    Summarize news for multiple tickers.

    Args:
        news_data: dict from news_enrichment.py {ticker: {"name": ..., "articles": [...]}}
        language: Output language

    Returns:
        {ticker: "summary text"} dict
    """
    summaries = {}
    for ticker, info in news_data.items():
        name = info.get("name") or ticker
        articles = info.get("articles", [])
        print(f"  [LLM] Summarizing {ticker} ({name})...", file=sys.stderr)
        summary = summarize_news_for_ticker(ticker, name, articles, language)
        summaries[ticker] = summary
    return summaries


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test LLM summarization via OpenClaw")
    parser.add_argument("--test", action="store_true", help="Run a quick connectivity test")
    args = parser.parse_args()

    if args.test:
        print("Testing summarizer agent (Gemini 3 Flash)...")
        result = call_llm("Say 'OK' and nothing else.")
        print(f"Response: {result}")
        print("✅ LLM via OpenClaw OK")
