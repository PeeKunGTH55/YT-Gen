from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def extract_json(text: str) -> Any:
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        for start_char, end_char in (("{", "}"), ("[", "]")):
            start = cleaned.find(start_char)
            end = cleaned.rfind(end_char)
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError:
                    continue
        raise


def get_genai_client(location_override: str | None = None) -> Any:
    from google import genai

    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    location = (location_override or os.getenv("GOOGLE_CLOUD_LOCATION", "global")).strip()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if project:
        return genai.Client(vertexai=True, project=project, location=location)
    if api_key:
        return genai.Client(api_key=api_key)
    raise RuntimeError(
        "ไม่พบการตั้งค่า GOOGLE_CLOUD_PROJECT (สำหรับ Vertex AI) หรือ GEMINI_API_KEY ใน .env"
    )


def call_llm_json(
    prompt: str,
    *,
    system_prompt: str = "คุณเป็นผู้ช่วยผลิตสื่อความรู้ภาษาไทย ตอบกลับเป็น JSON ที่ถูกต้องตามที่ระบุเท่านั้น",
    mock_response: Any = None,
    force_mock: bool = False,
) -> Any:
    provider = "mock" if force_mock else os.getenv("LLM_PROVIDER", "vertex").lower()
    model = os.getenv("LLM_MODEL", "gemini-2.5-flash")

    if provider == "mock":
        if mock_response is not None:
            return mock_response
        raise RuntimeError("เรียกใช้โหมด mock แต่ไม่ได้ระบุ mock_response")

    if provider in ("vertex", "gemini"):
        try:
            from google.genai import types

            cfg = types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=0.4,
            )
            try:
                client = get_genai_client()
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=cfg,
                )
            except Exception as e:
                if "404" in str(e) and os.getenv("GOOGLE_CLOUD_LOCATION", "global") != "global":
                    client = get_genai_client(location_override="global")
                    resp = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=cfg,
                    )
                else:
                    raise
            return extract_json(resp.text or "{}")
        except Exception:
            if mock_response is not None and not os.getenv("GOOGLE_CLOUD_PROJECT") and not os.getenv("GEMINI_API_KEY"):
                return mock_response
            raise

    if provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            if mock_response is not None:
                return mock_response
            raise RuntimeError("ไม่พบ ANTHROPIC_API_KEY ใน .env")
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model if "claude" in model else "claude-3-7-sonnet-latest",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in msg.content if hasattr(block, "text"))
        return extract_json(text)

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            if mock_response is not None:
                return mock_response
            raise RuntimeError("ไม่พบ OPENAI_API_KEY ใน .env")
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model if "gpt" in model or "o" in model else "gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )
        return extract_json(resp.choices[0].message.content or "{}")

    raise ValueError(f"ไม่รองรับ LLM_PROVIDER: {provider}")


def fetch_page_snippet(url: str, max_chars: int = 2000) -> str:
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; EduShortsFactChecker/1.0)"},
            )
            resp.raise_for_status()
            text = re.sub(r"<script.*?</script>", " ", resp.text, flags=re.DOTALL)
            text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:max_chars]
    except Exception as exc:
        return f"[ไม่สามารถเปิดอ่านหน้าเว็บได้: {exc}]"


def search_and_fetch_claims_batch(
    claims: list[str], *, force_mock: bool = False
) -> list[dict[str, Any]]:
    if not claims:
        return []
    if force_mock or os.getenv("LLM_PROVIDER", "").lower() == "mock":
        return [
            {
                "claim": c,
                "sources": search_and_fetch_claim(c, force_mock=True),
            }
            for c in claims
        ]

    search_provider = os.getenv("SEARCH_PROVIDER", "vertex_grounding").lower()
    if search_provider in ("vertex_grounding", "gemini_grounding"):
        try:
            from google.genai import types

            client = get_genai_client()
            model = os.getenv("LLM_MODEL", "gemini-2.5-flash")
            claims_bullet = "\n".join(f"- {c}" for c in claims)
            resp = client.models.generate_content(
                model=model,
                contents=(
                    "ค้นหาข้อเท็จจริงทางวิชาการและแหล่งอ้างอิงที่เชื่อถือได้สำหรับรายการข้อเท็จจริงต่อไปนี้:\n"
                    f"{claims_bullet}"
                ),
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.1,
                ),
            )
            summary_text = resp.text or ""
            grounded_sources: list[dict[str, str]] = []
            candidates = getattr(resp, "candidates", None) or []
            if candidates:
                gm = getattr(candidates[0], "grounding_metadata", None)
                chunks = getattr(gm, "grounding_chunks", None) or []
                for ch in chunks[:5]:
                    web = getattr(ch, "web", None)
                    if web and getattr(web, "uri", None):
                        grounded_sources.append(
                            {
                                "title": getattr(web, "title", "Grounded Source") or "Grounded Source",
                                "url": web.uri,
                                "content": summary_text[:2000],
                            }
                        )
            if grounded_sources:
                return [{"claims": claims, "sources": grounded_sources}]
        except Exception:
            pass

    return [
        {"claim": c, "sources": search_and_fetch_claim(c, force_mock=force_mock)}
        for c in claims[:5]
    ]


def search_and_fetch_claim(claim: str, *, force_mock: bool = False) -> list[dict[str, str]]:
    if force_mock or os.getenv("LLM_PROVIDER", "").lower() == "mock":
        return [
            {
                "title": "NASA Space Place — Why Is the Sky Blue?",
                "url": "https://spaceplace.nasa.gov/blue-sky/en/",
                "content": (
                    "Sunlight reaches Earth's atmosphere and is scattered in all directions by "
                    "all the gases and particles in the air. Blue light is scattered more than "
                    "the other colors because it travels as shorter, smaller waves. This is called Rayleigh scattering."
                ),
            }
        ]

    search_provider = os.getenv("SEARCH_PROVIDER", "vertex_grounding").lower()

    # 1. Vertex AI / Gemini Google Search Grounding
    if search_provider in ("vertex_grounding", "gemini_grounding"):
        try:
            from google.genai import types

            client = get_genai_client()
            model = os.getenv("LLM_MODEL", "gemini-2.5-flash")
            resp = client.models.generate_content(
                model=model,
                contents=f"ค้นหาข้อเท็จจริงทางวิชาการและแหล่งอ้างอิงที่เชื่อถือได้สำหรับข้อความนี้: {claim}",
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.1,
                ),
            )
            summary_text = resp.text or ""
            grounded_sources: list[dict[str, str]] = []
            candidates = getattr(resp, "candidates", None) or []
            if candidates:
                gm = getattr(candidates[0], "grounding_metadata", None)
                chunks = getattr(gm, "grounding_chunks", None) or []
                for ch in chunks[:3]:
                    web = getattr(ch, "web", None)
                    if web and getattr(web, "uri", None):
                        grounded_sources.append(
                            {
                                "title": getattr(web, "title", "Grounded Source") or "Grounded Source",
                                "url": web.uri,
                                "content": summary_text[:1500],
                            }
                        )
            if grounded_sources:
                return grounded_sources
        except Exception:
            pass

    tavily_key = os.getenv("TAVILY_API_KEY", "")
    brave_key = os.getenv("BRAVE_SEARCH_API_KEY", "")

    if search_provider == "tavily" and tavily_key:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": tavily_key,
                    "query": claim,
                    "search_depth": "advanced",
                    "max_results": 3,
                    "include_raw_content": False,
                },
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            enriched = []
            for r in results[:3]:
                url = r.get("url", "")
                snippet = r.get("content", "") or fetch_page_snippet(url)
                enriched.append(
                    {
                        "title": r.get("title", ""),
                        "url": url,
                        "content": snippet[:1500],
                    }
                )
            return enriched

    if search_provider == "brave" and brave_key:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": claim, "count": 3},
                headers={"X-Subscription-Token": brave_key, "Accept": "application/json"},
            )
            resp.raise_for_status()
            web_results = resp.json().get("web", {}).get("results", [])
            enriched = []
            for r in web_results[:3]:
                url = r.get("url", "")
                page_text = fetch_page_snippet(url)
                enriched.append(
                    {
                        "title": r.get("title", ""),
                        "url": url,
                        "content": f"{r.get('description', '')} | {page_text}",
                    }
                )
            return enriched

    # Fallback: Wikipedia REST search
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                "https://th.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": claim,
                    "format": "json",
                    "srlimit": 2,
                },
            )
            data = resp.json()
            hits = data.get("query", {}).get("search", [])
            results = []
            for h in hits:
                title = h.get("title", "")
                url = f"https://th.wikipedia.org/wiki/{title.replace(' ', '_')}"
                snippet = fetch_page_snippet(url, max_chars=1200)
                results.append({"title": f"Wikipedia: {title}", "url": url, "content": snippet})
            if results:
                return results
    except Exception:
        pass

    return [
        {
            "title": "NASA Space Place — Science Reference",
            "url": "https://spaceplace.nasa.gov/blue-sky/en/",
            "content": fetch_page_snippet("https://spaceplace.nasa.gov/blue-sky/en/", max_chars=1200),
        }
    ]
