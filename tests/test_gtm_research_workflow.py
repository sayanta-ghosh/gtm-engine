"""GTM Engineering Research Workflow Demo.

End-to-end pipeline:
1. Google Search for top GTM Engineering LinkedIn posts
2. Parallel Extract to scrape post content
3. Parallel Search to research the founders/posters

Run: python3 tests/test_gtm_research_workflow.py
"""

import asyncio
import json
import os
import sys

import httpx

# Load .env
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

RAPIDAPI_KEY = os.getenv("X_RAPIDAPI_KEY")
PARALLEL_KEY = os.getenv("PARALLEL_KEY") or os.getenv("parallel_key")

DIVIDER = "\n" + "=" * 70 + "\n"


async def step1_google_search() -> list[dict]:
    """Search Google for top GTM Engineering posts on LinkedIn."""
    print(DIVIDER + "STEP 1: Google Search — Top GTM Engineering Posts" + DIVIDER)

    if not RAPIDAPI_KEY:
        print("ERROR: X_RAPIDAPI_KEY not set")
        return []

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            "https://real-time-web-search.p.rapidapi.com/search",
            headers={
                "X-RapidAPI-Key": RAPIDAPI_KEY,
                "X-RapidAPI-Host": "real-time-web-search.p.rapidapi.com",
            },
            params={
                "q": 'site:linkedin.com/posts "GTM Engineering" OR "GTM engineer"',
                "limit": "10",
            },
        )
        print(f"Status: {resp.status_code}")
        data = resp.json()

        raw_data = data.get("data", {})
        results = raw_data.get("organic_results", []) if isinstance(raw_data, dict) else raw_data
        print(f"Found {len(results)} results\n")

        posts = []
        for i, r in enumerate(results[:5], 1):
            url = r.get("url", "")
            title = r.get("title", "")
            snippet = r.get("snippet", "")[:200]
            print(f"  {i}. {title}")
            print(f"     URL: {url}")
            print(f"     Snippet: {snippet}")
            print()
            posts.append({"url": url, "title": title, "snippet": snippet})

        return posts


async def step2_extract_posts(posts: list[dict]) -> list[dict]:
    """Use Parallel Extract API to scrape the LinkedIn posts."""
    print(DIVIDER + "STEP 2: Parallel Extract — Scrape Post Content" + DIVIDER)

    if not PARALLEL_KEY:
        print("ERROR: PARALLEL_KEY not set")
        return posts

    urls = [p["url"] for p in posts[:5] if p.get("url")]
    if not urls:
        print("No URLs to extract")
        return posts

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.parallel.ai/v1beta/extract",
            headers={
                "x-api-key": PARALLEL_KEY,
                "Content-Type": "application/json",
            },
            json={
                "urls": urls,
                "output_format": "markdown",
            },
        )
        print(f"Status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            print(f"Extracted {len(results)} pages\n")

            for i, result in enumerate(results):
                url = result.get("url", "")
                # Content may be in 'excerpts' (list), 'content', or 'text'
                excerpts = result.get("excerpts", [])
                content = "\n".join(excerpts) if excerpts else result.get("content", "") or result.get("text", "")
                title = result.get("title", "")
                matching_post = next((p for p in posts if p["url"] == url), None)
                if matching_post and content:
                    matching_post["extracted_content"] = content[:1500]
                print(f"  {i+1}. {title or url}")
                print(f"     URL: {url}")
                print(f"     Content ({len(content)} chars): {content[:400]}...")
                print()
        else:
            print(f"Extract failed: {resp.text[:300]}")

    return posts


async def step3_research_founders(posts: list[dict]) -> list[dict]:
    """Use Parallel Search to research the founders/posters."""
    print(DIVIDER + "STEP 3: Parallel Search — Research the Posters" + DIVIDER)

    if not PARALLEL_KEY:
        print("ERROR: PARALLEL_KEY not set")
        return posts

    # Extract poster names from URLs and titles
    research_queries = []
    for p in posts[:3]:
        title = p.get("title", "")
        url = p.get("url", "")
        name = ""

        # Try to extract from LinkedIn URL: /posts/username_...
        if "/posts/" in url:
            slug = url.split("/posts/")[1].split("_")[0] if "_" in url.split("/posts/")[1] else ""
            # Convert slug like "collincadmus" to "Collin Cadmus"
            if slug and not slug.startswith("activity"):
                name = slug.replace("-", " ").title()

        # Fallback: extract from title patterns
        if not name:
            if " posted on" in title:
                name = title.split(" posted on")[0].strip()
            elif "'s Post" in title:
                name = title.split("'s Post")[0].strip()
            elif " | " in title:
                parts = title.split(" | ")
                for part in parts:
                    if "post" not in part.lower() and "linkedin" not in part.lower():
                        name = part.strip()
                        break

        if name and len(name) < 40:
            research_queries.append({
                "name": name,
                "post_url": p["url"],
                "query": f"{name} founder CEO background company role",
            })

    if not research_queries:
        print("Could not extract poster names from titles")
        # Fall back to searching about GTM Engineering in general
        research_queries = [{"name": "GTM Engineering", "query": "GTM Engineering movement founders key people 2024 2025", "post_url": ""}]

    async with httpx.AsyncClient(timeout=30) as client:
        for rq in research_queries:
            print(f"  Researching: {rq['name']}")
            resp = await client.post(
                "https://api.parallel.ai/v1beta/search",
                headers={
                    "x-api-key": PARALLEL_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "objective": rq["query"],
                    "mode": "fast",
                    "max_results": 5,
                },
            )

            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                print(f"  Found {len(results)} results")

                for r in results[:3]:
                    excerpts = r.get("excerpts", [])
                    snippet = excerpts[0][:300] if excerpts else r.get("snippet", "")[:300]
                    print(f"    - {r.get('title', 'N/A')}")
                    print(f"      {r.get('url', '')}")
                    print(f"      {snippet}")
                    print()

                # Also try to find their company
                if rq.get("name") and rq["name"] != "GTM Engineering":
                    print(f"  Researching company for: {rq['name']}")
                    company_resp = await client.post(
                        "https://api.parallel.ai/v1beta/search",
                        headers={
                            "x-api-key": PARALLEL_KEY,
                            "Content-Type": "application/json",
                        },
                        json={
                            "objective": f"{rq['name']} company LinkedIn profile role",
                            "mode": "fast",
                            "max_results": 3,
                        },
                    )
                    if company_resp.status_code == 200:
                        cdata = company_resp.json()
                        cresults = cdata.get("results", [])
                        for cr in cresults[:2]:
                            cexcerpts = cr.get("excerpts", [])
                            csnippet = cexcerpts[0][:300] if cexcerpts else cr.get("snippet", "")[:300]
                            print(f"    Company: {cr.get('title', 'N/A')}")
                            print(f"      {csnippet}")
                            print()
            else:
                print(f"  Search failed: {resp.status_code} {resp.text[:200]}")
            print()

    return posts


async def main():
    print("\n" + "#" * 70)
    print("#  GTM ENGINEERING RESEARCH WORKFLOW DEMO")
    print("#  Google Search → Parallel Extract → Parallel Research")
    print("#" * 70)

    # Step 1: Find top posts
    posts = await step1_google_search()
    if not posts:
        print("\nNo posts found. Exiting.")
        return

    # Step 2: Extract post content
    posts = await step2_extract_posts(posts)

    # Step 3: Research the founders
    posts = await step3_research_founders(posts)

    # Summary
    print(DIVIDER + "SUMMARY" + DIVIDER)
    for i, p in enumerate(posts[:5], 1):
        print(f"{i}. {p.get('title', 'Unknown')[:80]}")
        print(f"   URL: {p.get('url', '')}")
        has_content = bool(p.get("extracted_content"))
        print(f"   Content extracted: {'Yes' if has_content else 'No'}")
        if has_content:
            print(f"   Preview: {p['extracted_content'][:150]}...")
        print()

    print("Workflow complete!")


if __name__ == "__main__":
    asyncio.run(main())
