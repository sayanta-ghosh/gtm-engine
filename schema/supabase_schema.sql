-- ============================================================
-- GTM Engine — Supabase Schema with Multi-Tenancy (RLS)
-- ============================================================
--
-- Architecture:
-- - Every table has a tenant_id column
-- - RLS policies ensure tenant A can never see tenant B's data
-- - auth.uid() maps to a tenant via the tenants table
-- - Platform admin role bypasses RLS for management
--
-- Tables:
-- 1. tenants — Tenant registry
-- 2. api_key_metadata — Key config (no actual secrets)
-- 3. enrichment_results — Waterfall enrichment outputs
-- 4. provider_performance — Which provider wins per field
-- 5. cost_ledger — Per-call cost tracking
-- 6. campaign_outcomes — Track what happened after enrichment
-- 7. hitl_approvals — Human-in-the-loop audit trail
-- ============================================================


-- ============================================================
-- 1. TENANTS
-- ============================================================

CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    auth_user_id UUID REFERENCES auth.users(id),  -- Supabase auth link
    plan TEXT NOT NULL DEFAULT 'byok',  -- 'byok' | 'managed' | 'both'
    monthly_spend_cap_cents INTEGER DEFAULT NULL,  -- null = unlimited
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RLS: users can only see their own tenant
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users see own tenant" ON tenants
    FOR SELECT USING (auth_user_id = auth.uid());

CREATE POLICY "Users update own tenant" ON tenants
    FOR UPDATE USING (auth_user_id = auth.uid());


-- ============================================================
-- 2. API KEY METADATA (no actual secrets stored here!)
-- ============================================================
-- The actual encrypted keys live in the vault (local or server).
-- This table tracks WHAT keys exist and their status, for the
-- dashboard and key management UI.

CREATE TABLE IF NOT EXISTS api_key_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,           -- 'apollo', 'pdl', 'hunter', etc.
    key_source TEXT NOT NULL,         -- 'byok' | 'platform'
    key_fingerprint TEXT NOT NULL,    -- SHA256 hash prefix, NOT the key
    status TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'revoked' | 'expired'
    stored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    total_calls INTEGER NOT NULL DEFAULT 0,
    total_cost_cents INTEGER NOT NULL DEFAULT 0,

    UNIQUE(tenant_id, provider, key_source)
);

ALTER TABLE api_key_metadata ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenants see own keys" ON api_key_metadata
    FOR SELECT USING (
        tenant_id IN (SELECT id FROM tenants WHERE auth_user_id = auth.uid())
    );

CREATE POLICY "Tenants manage own keys" ON api_key_metadata
    FOR ALL USING (
        tenant_id IN (SELECT id FROM tenants WHERE auth_user_id = auth.uid())
    );


-- ============================================================
-- 3. ENRICHMENT RESULTS
-- ============================================================
-- Every enrichment call writes its results here.
-- This is the core data table that dashboards query.

CREATE TABLE IF NOT EXISTS enrichment_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Input
    input_type TEXT NOT NULL,          -- 'email' | 'domain' | 'linkedin' | 'company'
    input_value TEXT NOT NULL,

    -- Result
    provider_used TEXT NOT NULL,        -- Which provider returned the match
    key_source TEXT NOT NULL,           -- 'byok' | 'platform'
    waterfall_position INTEGER,         -- 1 = first provider tried, 2 = second, etc.
    providers_tried TEXT[],             -- All providers attempted in order

    -- Enriched data (JSONB for flexibility)
    enriched_data JSONB NOT NULL DEFAULT '{}',

    -- Scoring
    icp_score REAL,                     -- 0.0 to 1.0
    icp_tier TEXT,                      -- 'tier_1' | 'tier_2' | 'tier_3'

    -- Cost
    cost_cents INTEGER NOT NULL DEFAULT 0,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    batch_id UUID,                      -- Group enrichments from same run
    context_hash TEXT                   -- Hash of ICP context used for this enrichment
);

ALTER TABLE enrichment_results ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenants see own enrichments" ON enrichment_results
    FOR SELECT USING (
        tenant_id IN (SELECT id FROM tenants WHERE auth_user_id = auth.uid())
    );

CREATE POLICY "Tenants insert own enrichments" ON enrichment_results
    FOR INSERT WITH CHECK (
        tenant_id IN (SELECT id FROM tenants WHERE auth_user_id = auth.uid())
    );

-- Indexes for dashboard queries
CREATE INDEX IF NOT EXISTS idx_enrichment_tenant_created
    ON enrichment_results(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_enrichment_batch
    ON enrichment_results(batch_id) WHERE batch_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_enrichment_provider
    ON enrichment_results(tenant_id, provider_used);

CREATE INDEX IF NOT EXISTS idx_enrichment_icp_tier
    ON enrichment_results(tenant_id, icp_tier);


-- ============================================================
-- 4. PROVIDER PERFORMANCE
-- ============================================================
-- Aggregated stats on which provider performs best per field.
-- Used by the waterfall engine to optimize ordering.

CREATE TABLE IF NOT EXISTS provider_performance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    field_name TEXT NOT NULL,           -- 'email' | 'phone' | 'title' | 'company_size' etc.
    match_count INTEGER NOT NULL DEFAULT 0,
    miss_count INTEGER NOT NULL DEFAULT 0,
    hit_rate REAL GENERATED ALWAYS AS (
        CASE WHEN (match_count + miss_count) > 0
            THEN match_count::REAL / (match_count + miss_count)
            ELSE 0.0
        END
    ) STORED,
    avg_cost_cents REAL NOT NULL DEFAULT 0,
    avg_latency_ms REAL NOT NULL DEFAULT 0,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(tenant_id, provider, field_name)
);

ALTER TABLE provider_performance ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenants see own perf" ON provider_performance
    FOR ALL USING (
        tenant_id IN (SELECT id FROM tenants WHERE auth_user_id = auth.uid())
    );

CREATE INDEX IF NOT EXISTS idx_perf_tenant_provider
    ON provider_performance(tenant_id, provider);


-- ============================================================
-- 5. COST LEDGER
-- ============================================================
-- Every API call that costs money gets a line item here.
-- Used for billing, spend cap enforcement, and ROI dashboards.

CREATE TABLE IF NOT EXISTS cost_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    key_source TEXT NOT NULL,           -- 'byok' | 'platform'
    endpoint TEXT NOT NULL,
    cost_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    batch_id UUID,
    enrichment_id UUID REFERENCES enrichment_results(id)
);

ALTER TABLE cost_ledger ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenants see own costs" ON cost_ledger
    FOR ALL USING (
        tenant_id IN (SELECT id FROM tenants WHERE auth_user_id = auth.uid())
    );

CREATE INDEX IF NOT EXISTS idx_cost_tenant_created
    ON cost_ledger(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_cost_tenant_provider
    ON cost_ledger(tenant_id, provider);


-- ============================================================
-- 6. CAMPAIGN OUTCOMES (the learning loop)
-- ============================================================
-- Links enrichment results to actual campaign outcomes.
-- Did the enriched lead reply? Book a meeting? Close?
-- This powers the feedback loop that makes the engine smarter.

CREATE TABLE IF NOT EXISTS campaign_outcomes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    enrichment_id UUID REFERENCES enrichment_results(id),

    -- What happened
    campaign_name TEXT,
    sequence_tool TEXT,                 -- 'instantly' | 'smartlead' | 'lemlist'
    outcome TEXT NOT NULL,              -- 'sent' | 'opened' | 'replied' | 'booked' | 'closed_won' | 'closed_lost' | 'bounced'
    outcome_value_cents INTEGER,        -- Revenue if closed_won

    -- Attribution
    enrichment_provider TEXT,           -- Which provider's data led to this outcome
    icp_tier_at_send TEXT,             -- What tier was this lead when we sent

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    outcome_at TIMESTAMPTZ             -- When the outcome actually happened
);

ALTER TABLE campaign_outcomes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenants see own outcomes" ON campaign_outcomes
    FOR ALL USING (
        tenant_id IN (SELECT id FROM tenants WHERE auth_user_id = auth.uid())
    );

CREATE INDEX IF NOT EXISTS idx_outcome_tenant_created
    ON campaign_outcomes(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_outcome_enrichment
    ON campaign_outcomes(enrichment_id) WHERE enrichment_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_outcome_tenant_outcome
    ON campaign_outcomes(tenant_id, outcome);


-- ============================================================
-- 7. HITL APPROVALS (Human-in-the-loop audit trail)
-- ============================================================
-- Every time a workflow pauses for human approval, a record is
-- created here. When the human acts, it's updated.

CREATE TABLE IF NOT EXISTS hitl_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- What needs approval
    workflow_name TEXT NOT NULL,
    approval_type TEXT NOT NULL,        -- 'sequence_copy' | 'lead_qualification' | 'campaign_launch' | 'data_delete'
    payload JSONB NOT NULL DEFAULT '{}', -- The data being approved (e.g., personalized copy)
    item_count INTEGER NOT NULL DEFAULT 1,

    -- Status
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'approved' | 'rejected' | 'expired' | 'edited'

    -- Notification
    notification_channel TEXT,          -- 'slack' | 'email' | 'browser'
    notification_sent_at TIMESTAMPTZ,
    notification_id TEXT,               -- Slack message_ts or email message_id

    -- Resolution
    resolved_by TEXT,                   -- User who approved/rejected
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT,
    edited_payload JSONB,              -- If the human edited before approving

    -- Timeout
    timeout_at TIMESTAMPTZ,            -- When this approval expires
    timeout_action TEXT DEFAULT 'reject',  -- 'reject' | 'approve' | 'escalate'

    -- Resume
    resume_token TEXT UNIQUE,           -- Webhook token to resume the workflow
    resumed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE hitl_approvals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenants see own approvals" ON hitl_approvals
    FOR ALL USING (
        tenant_id IN (SELECT id FROM tenants WHERE auth_user_id = auth.uid())
    );

CREATE INDEX IF NOT EXISTS idx_hitl_tenant_status
    ON hitl_approvals(tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_hitl_resume_token
    ON hitl_approvals(resume_token) WHERE resume_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_hitl_timeout
    ON hitl_approvals(timeout_at) WHERE status = 'pending';


-- ============================================================
-- HELPER VIEWS (for dashboards)
-- ============================================================

-- Daily enrichment summary
CREATE OR REPLACE VIEW daily_enrichment_summary AS
SELECT
    tenant_id,
    DATE(created_at) AS day,
    COUNT(*) AS total_enrichments,
    COUNT(*) FILTER (WHERE enriched_data != '{}') AS successful,
    COUNT(*) FILTER (WHERE enriched_data = '{}') AS failed,
    AVG(icp_score) AS avg_icp_score,
    COUNT(*) FILTER (WHERE icp_tier = 'tier_1') AS tier_1_count,
    COUNT(*) FILTER (WHERE icp_tier = 'tier_2') AS tier_2_count,
    COUNT(*) FILTER (WHERE icp_tier = 'tier_3') AS tier_3_count,
    SUM(cost_cents) AS total_cost_cents,
    AVG(waterfall_position) AS avg_waterfall_depth
FROM enrichment_results
GROUP BY tenant_id, DATE(created_at);

-- Provider ROI (which provider's enrichments lead to the best outcomes)
CREATE OR REPLACE VIEW provider_roi AS
SELECT
    e.tenant_id,
    e.provider_used,
    COUNT(DISTINCT e.id) AS enrichments,
    COUNT(DISTINCT co.id) AS outcomes,
    COUNT(DISTINCT co.id) FILTER (WHERE co.outcome = 'replied') AS replies,
    COUNT(DISTINCT co.id) FILTER (WHERE co.outcome = 'booked') AS meetings,
    COUNT(DISTINCT co.id) FILTER (WHERE co.outcome = 'closed_won') AS deals,
    SUM(co.outcome_value_cents) FILTER (WHERE co.outcome = 'closed_won') AS revenue_cents,
    SUM(e.cost_cents) AS enrichment_cost_cents,
    CASE WHEN SUM(e.cost_cents) > 0
        THEN (SUM(co.outcome_value_cents) FILTER (WHERE co.outcome = 'closed_won'))::REAL
             / SUM(e.cost_cents)
        ELSE 0
    END AS roi_ratio
FROM enrichment_results e
LEFT JOIN campaign_outcomes co ON co.enrichment_id = e.id
GROUP BY e.tenant_id, e.provider_used;

-- Monthly spend by tenant
CREATE OR REPLACE VIEW monthly_spend AS
SELECT
    tenant_id,
    DATE_TRUNC('month', created_at) AS month,
    provider,
    key_source,
    SUM(cost_cents) AS total_cents,
    COUNT(*) AS total_calls
FROM cost_ledger
GROUP BY tenant_id, DATE_TRUNC('month', created_at), provider, key_source;


-- ============================================================
-- FUNCTIONS
-- ============================================================

-- Check if tenant is within spend cap
CREATE OR REPLACE FUNCTION check_spend_cap(p_tenant_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_cap INTEGER;
    v_spent INTEGER;
BEGIN
    SELECT monthly_spend_cap_cents INTO v_cap
    FROM tenants WHERE id = p_tenant_id;

    IF v_cap IS NULL THEN
        RETURN jsonb_build_object('within_cap', true, 'cap', null, 'spent', 0);
    END IF;

    SELECT COALESCE(SUM(cost_cents), 0) INTO v_spent
    FROM cost_ledger
    WHERE tenant_id = p_tenant_id
      AND created_at >= DATE_TRUNC('month', now());

    RETURN jsonb_build_object(
        'within_cap', v_spent < v_cap,
        'cap_cents', v_cap,
        'spent_cents', v_spent,
        'remaining_cents', GREATEST(v_cap - v_spent, 0),
        'utilization_pct', ROUND((v_spent::REAL / v_cap) * 100, 1)
    );
END;
$$;
