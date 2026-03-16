# Security Rules for GTM Engine Development

When working with vault/ files:
- Never log or print API key values
- Never return key values from any function
- Always use fingerprints for identification
- The proxy pattern is mandatory: keys go IN but never come OUT
- Test that no key material appears in any return value

When handling user-provided keys:
- Store immediately via gtm_add_key, do not hold in variables
- Remind users that keys shown in chat context should be rotated
- Never include keys in commit messages or comments

When modifying .vault/ code:
- Run the full security test suite: python3 tests/test_vault_security.py
- Run multi-tenant tests: python3 tests/test_multi_tenant.py
