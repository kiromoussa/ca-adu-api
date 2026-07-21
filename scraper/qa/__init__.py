"""HCD compliance QA cross-check job (Prompt 6).

Pulls HCD's Housing Element APR CSV dataset and the HCD ADU ordinance review
letters, cross-references flagged jurisdictions against the adu_rules
compliance_flag field, alerts on discrepancies, and stores alert history in the
qa_alerts table.
"""
