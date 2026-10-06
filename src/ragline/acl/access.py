"""The access decision — one boolean, computed the same way everywhere.

accessible(user, acl) is used both to paint the `accessible` flag on citation
payloads (UX) and to enforce GET /api/documents/{id}/content (the actual
security boundary). Both callers MUST go through this function so the flag
and the enforcement can never disagree.

Truth table (fail closed; denies evaluated FIRST, mirroring Windows):
  no ACL row                     -> False
  row not fresh (stale crawl)    -> False
  status != ok                   -> False
  user's oid in denied           -> False
  any user group in denied       -> False
  allow_all_authenticated        -> True
  user's oid in principals       -> True
  any user group in principals   -> True
  otherwise                      -> False
"""

from ragline.auth.dependencies import AuthedUser
from ragline.storage.acl_models import DocumentAcl


def accessible(user: AuthedUser, acl: DocumentAcl | None, groups: list[str] | None = None) -> bool:
    """groups: freshness-aware group list (auth/graph.effective_groups);
    defaults to the login-time snapshot carried on the user."""
    if acl is None:
        return False
    if acl.crawl_status != "ok" or not acl.is_fresh:
        return False
    effective = groups if groups is not None else user.groups
    # Deny-first: an explicit deny ACE on the user or any of their groups
    # beats every allow, including allow-to-everyone — Windows semantics.
    denied = set(acl.denied)
    if user.oid in denied or any(g in denied for g in effective):
        return False
    if acl.allow_all_authenticated:
        return True
    principals = set(acl.principals)
    if user.oid in principals:
        return True
    return any(g in principals for g in effective)


async def accessible_document_ids(
    user: AuthedUser | None, document_ids: list[str]
) -> set[str]:
    """Bulk variant for listing endpoints: which of these documents may this
    user see the original network path of?

    Same accessible() per document (the flag and the enforcement can never
    disagree); one ACL query + one groups lookup for the whole listing. With
    auth off (dev) everything is accessible, matching citation enrichment.
    """
    from ragline.config import settings

    if not settings.auth_enabled or user is None:
        return set(document_ids)
    if not document_ids:
        return set()

    from ragline.auth.graph import effective_groups
    from ragline.storage.acl_models import get_acls_by_document_ids

    acls = await get_acls_by_document_ids(document_ids)
    groups = await effective_groups(user)
    return {
        doc_id for doc_id in document_ids if accessible(user, acls.get(doc_id), groups=groups)
    }
