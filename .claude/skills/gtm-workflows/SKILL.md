# Common GTM Workflows

## Workflow 1: Prospect Research
1. User provides target criteria (industry, company size, titles)
2. Search Apollo /mixed_people/search with criteria
3. Enrich top results via waterfall (Apollo -> RocketReach)
4. Score against ICP
5. Export to Google Sheets (via Composio connection)

## Workflow 2: Account-Based Enrichment
1. User provides list of target domains
2. For each domain: Apollo /organizations/enrich
3. Find key contacts: Apollo /mixed_people/search per domain
4. Find/verify emails: RocketReach or Hunter
5. Push to CRM via HubSpot/Salesforce connection

## Workflow 3: Email Campaign Launch
1. Build prospect list (Workflow 1 or 2)
2. Verify all emails via ZeroBounce
3. Push to Instantly via /lead/add
4. Create campaign via /campaign/create
5. Monitor via Instantly dashboard or API

## Workflow 4: Company Research
1. Use Parallel AI for deep company research
2. Use Google Search for recent news/funding
3. Enrich company via Apollo/Crustdata
4. Find contacts at company
5. Build personalized outreach angles

## Workflow 5: Competitive Intelligence
1. Search Google for competitor info (rapidapi_google or google_search)
2. Deep research with Parallel AI
3. Find their customers via case studies
4. Build lookalike prospect list via Apollo search

## Human-in-the-Loop Checkpoints
- Before sending any campaign: require approval
- Before adding >100 leads: confirm with user
- Before spending >$10 on enrichment: confirm budget
