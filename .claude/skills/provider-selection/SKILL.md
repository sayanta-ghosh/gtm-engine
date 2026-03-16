# Provider Selection Guide

This is the decision engine for choosing the right provider for any GTM task.
Use this guide BEFORE making any API call to pick the optimal provider.

## Quick Decision Matrix

| I need to... | Provider | Operation | Why |
|---|---|---|---|
| Find people by email/name | **Apollo** | enrich_person | Best email match rate, includes company context |
| Find people by school/university | **RocketReach** | search_people | Only provider with working `school` filter |
| Find alumni of a company (past employees) | **RocketReach** | search_people | `previous_employer` filter actually works |
| Search people by title + company | **Apollo** | search_people | Largest B2B database, best filters |
| Search people by department | **Apollo** | search_people | `person_department_or_subdepartments` filter |
| Get someone's phone number | **RocketReach** | enrich_person | Higher phone data coverage |
| Enrich a company by domain | **Apollo** | enrich_company | Richest company profiles (tech, funding, size) |
| Find a company's job openings | **PredictLeads** | company_jobs | Dedicated jobs API, better than scraping |
| Find a company's tech stack | **PredictLeads** | company_technologies | Detects actual usage, not just marketing |
| Get company news/signals | **PredictLeads** | company_news | Categorized business events |
| Find funding/financing events | **PredictLeads** | company_financing | Structured round data with investors |
| Find similar companies | **PredictLeads** | similar_companies | ML-based similarity scoring |
| Google search for company intel | **RapidAPI Google** | search_web | Fast Google SERP, up to 300 results |
| Find recent news about a company | **RapidAPI Google** | search_web | Use tbs=qdr:w for time filter |
| Scrape a webpage for content | **Parallel Web** | scrape_page | AI-native markdown, handles JS/PDFs |
| Scrape multiple URLs at scale | **Parallel Web** | scrape_page | Auto-batches in groups of 10, concurrent |
| AI-powered web research | **Parallel Web** | search_web | Natural language objectives, agentic mode |
| Extract structured data from pages | **Parallel Web** | extract_structured | Task API with LLM + citations |
| Bulk web extraction (100+ URLs) | **Parallel Web** | batch_extract | Task Groups, up to 2K req/min |

## Provider Deep-Dive: Strengths & Weaknesses

### Apollo (provider: `apollo`)
**Best for:** General people search, company enrichment, title/company filtering
**Strengths:**
- Largest B2B database (270M+ contacts)
- Rich company profiles (tech stack, funding, employee count)
- Best title + company + location filtering
- Bulk enrichment (up to 10 per call)
**Weaknesses:**
- School/education filter (`person_education_school_names`) is UNRELIABLE — returns generic results
- `q_keywords` free-text search is too broad for specific filtering
- `organization_past_domains` (past company search) returns poor results
- People search returns obfuscated data — needs separate enrichment for emails

### RocketReach (provider: `rocketreach`)
**Best for:** Alumni searches, phone numbers, school-based filtering
**Strengths:**
- `school` filter WORKS RELIABLY for university/education searches
- `previous_employer` filter WORKS for finding company alumni
- Higher phone number coverage than Apollo
- Email grading (A/A- grades are verified)
**Weaknesses:**
- Smaller overall database than Apollo
- No bulk enrichment in one call
- Company enrichment is less detailed than Apollo
- Async lookups: some requests return `status: "in_progress"` and need polling

**IMPORTANT for school searches:**
- Always pass BOTH variants of the school name:
  ```json
  {"school": ["IIT Kharagpur", "Indian Institute of Technology Kharagpur"]}
  ```
- Same for any school: `["MIT", "Massachusetts Institute of Technology"]`
- RocketReach matches on the school name as stored in LinkedIn profiles

### PredictLeads (provider: `predictleads`)
**Best for:** Company signals — jobs, tech, news, financing, similar companies
**Strengths:**
- Real-time company signal data (jobs refresh every 36 hours)
- Structured, categorized events (not raw text)
- Similar companies uses ML scoring
- Financing data includes investors and round types
**Weaknesses:**
- Company-only (no people data)
- Requires dual-key auth (token + key)
- Coverage varies: strong for US/EU companies, weaker for emerging markets

### RapidAPI Google (provider: `rapidapi_google`)
**Best for:** Google search results for research, news monitoring, competitive intel
**Strengths:**
- Real-time Google SERP results via RapidAPI (OpenWeb Ninja)
- Up to 300 results per query (no pagination needed)
- Google operators work in query: site:, filetype:, inurl:, intitle:, -keyword
- Time filters (qdr:h/d/w/m/y) for recent results
- Bulk search with concurrent execution
**Weaknesses:**
- Single endpoint (web search only — news/images/maps are separate RapidAPI products)
- Failed requests still consume quota
- It's Google search — results are broad, not structured B2B data
- Need to craft good queries for useful results

**Rate limits:** 10-30 req/sec depending on tier ($25-$150/mo)
**Adaptive throttling:** Response headers x-ratelimit-remaining, x-ratelimit-reset

**Query patterns that work well:**
- Funding: `"{company}" "raised" OR "series" OR "funding"`
- Hiring: `site:linkedin.com/jobs "{company}"`
- Tech stack: `"{company}" "powered by" OR "built with" OR "uses"`
- Leadership: `"{company}" "appointed" OR "new hire" OR "joins as"`
- LinkedIn: `site:linkedin.com/in "{name}" "{company}"`

### Parallel Web (provider: `parallel_web`)
**Best for:** Web scraping, content extraction, AI-powered web research at scale
**Strengths:**
- AI-native API by Parallel (parallel.ai) — purpose-built for agents
- Search API with natural language objectives + keyword queries
- Extract API: clean markdown from any URL (JS, anti-bot, PDFs)
- Task API: async structured extraction with LLM (citations + confidence)
- Task Groups: batch processing up to 2,000 req/min
- Auto-batches >10 URLs with concurrent execution
- SOC-2 Type II certified
**Weaknesses:**
- Extract capped at 10 URLs per API call (auto-batched by our provider)
- fetch_policy.max_age_seconds minimum is 600 (10 min cache)
- max_results not guaranteed on search
- Text-only output (no images)

**Rate limits:** Search/Extract 600/min, Tasks 2,000/min. GET polling is FREE.
**20,000 free requests** before paid pricing.

## Common GTM Workflows (Multi-Provider)

### 1. ICP List Building
```
Apollo search_people (title + company size + industry)
  → Apollo enrich_person (get emails for top matches)
  → PredictLeads company_jobs (verify they're hiring = budget available)
```

### 2. Alumni Network Mining
```
RocketReach search_people (school="IIT Kharagpur", title filters)
  → Filter to people at target companies
  → Apollo enrich_person (get emails + company details)
```

### 3. Company Research Brief
```
Apollo enrich_company (firmographics)
  + PredictLeads company_news (recent events)
  + PredictLeads company_jobs (hiring signals)
  + PredictLeads company_technologies (tech stack)
  + RapidAPI Google search_web (press coverage, tbs=qdr:m)
  + Parallel Web scrape_page (pricing page, about page)
```

### 4. Competitive Intelligence
```
RapidAPI Google search_web (find competitor URLs)
  → Parallel Web scrape_page (extract pricing, features from multiple URLs)
  → Parallel Web extract_structured (structured comparison via Task API)
  → PredictLeads similar_companies (find more competitors)
```

### 5. Event-Triggered Outreach
```
PredictLeads company_news (new funding, expansion, product launch)
  → Apollo search_people (find decision makers at that company)
  → Apollo enrich_person (get contact info)
```

## Auto-Selection Rules

The CLI and execution engine follow these rules:

1. **If `--school` or `--past-company` flag is used** → auto-select RocketReach
2. **If operation starts with `company_`** → auto-select PredictLeads
3. **If operation is `search_web`** → auto-select RapidAPI Google
4. **If operation is `scrape_page`, `crawl_site`, `extract_structured`, `batch_extract`** → auto-select Parallel Web
5. **Everything else (enrich, search people/companies)** → default to Apollo
6. **User can always override** with `--provider` flag

Note: Parallel Web also supports `search_web` (AI-powered objective search).
Use `--provider parallel_web` to get Parallel's agentic search instead of Google.
