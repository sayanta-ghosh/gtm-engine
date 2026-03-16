# Prospect List Building

## Step 1: Define ICP Criteria
Gather from user:
- Target titles (VP Sales, CRO, Head of Growth)
- Company size (51-200, 201-1000)
- Industries (SaaS, FinTech)
- Locations (US, SF Bay Area)
- Technologies used (optional)

## Step 2: Search for Prospects
Apollo /mixed_people/search:
  data={"person_titles": ["VP Sales", "CRO"],
        "organization_num_employees_ranges": ["51,200"],
        "person_locations": ["United States"],
        "per_page": 100, "page": 1}

Or RocketReach /search:
  params={"current_title": ["VP Sales"],
          "company_size": "51-200",
          "location": ["United States"]}

## Step 3: Enrich Each Prospect
For each result, enrich with additional data:
- Phone numbers (RocketReach /lookupProfile)
- Email verification (ZeroBounce /validate)
- Company data (Apollo /organizations/enrich)

## Step 4: Score Against ICP
Score each prospect 0-100 based on:
- Title match (40 points)
- Company size match (20 points)
- Industry match (20 points)
- Location match (10 points)
- Data completeness (10 points)

## Step 5: Export
- Google Sheets (via Composio connection)
- CSV (direct output)
- HubSpot/Salesforce (via Composio connection)
- Instantly (for email campaigns)

## Cost Awareness
Show the user: "Building a list of N people will cost approximately $X.XX"
Track actual cost and report: "List complete: N people for $X.XX (Y% hit rate)"
