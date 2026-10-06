"""Lost-in-the-Middle context reordering.

Ported verbatim from raggles. LLMs attend most strongly to content at the
beginning and end of the context window and least to content in the middle.
The sandwich layout places the highest-relevance chunks at both ends, pushing
lower-relevance chunks to the middle where attention is weakest.
"""

from ragline.vectorstore.base import SearchResult


def sandwich_reorder(results: list[SearchResult]) -> list[SearchResult]:
    """Reorder retrieved results to mitigate Lost-in-the-Middle attention loss.

    Input (ranked best→worst):  [1st, 2nd, 3rd, 4th, 5th, 6th]
    Output:                      [1st, 3rd, 5th, 6th, 4th, 2nd]

    Even-indexed items (highest scores) go to the front half;
    odd-indexed items (lower scores) are reversed onto the back half.
    """
    # Nothing to gain below 3 items.
    if len(results) <= 2:
        return results
    top_half = results[::2]      # indices 0, 2, 4, … (best scores)
    bottom_half = results[1::2]  # indices 1, 3, 5, … (lower scores)
    return top_half + list(reversed(bottom_half))
