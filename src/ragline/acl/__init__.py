"""NTFS ACL layer — per-user gating of citation source links.

A scheduled crawler (crawler.py, run by scripts/acl_crawl.py under a systemd
timer) reads each ingested file's NTFS DACL over SMB and stores the allowed
Entra principals per document (storage/acl_models.py). At request time the
signed-in user's oid + group ids are intersected with that stored list
(access.py). Retrieval/search stays global by explicit product decision —
only the "Open copy" download and the original-path display are gated.

Everything fails closed: blank or unreachable original_path, stale crawls,
unresolvable SIDs, and Graph outages all deny, never allow.
"""
