"""Pagination helpers for Twilio's v1/v2 meta-envelope list responses."""

from urllib.parse import urlencode

from fastapi import Request


def meta_page(request: Request, items: list, key: str, path: str) -> dict:
    """Slice items by PageSize/Page and wrap in the v1/v2 {key, meta} envelope."""
    query = request.query_params
    page_size = min(int(query.get("PageSize") or 50), 1000)
    page = int(query.get("Page") or 0)

    start = page * page_size
    chunk = items[start : start + page_size]
    has_more = len(items) > start + page_size

    def page_url(page_num: int) -> str:
        return f"{path}?{urlencode({'PageSize': page_size, 'Page': page_num})}"

    return {
        key: chunk,
        "meta": {
            "page": page,
            "page_size": page_size,
            "first_page_url": page_url(0),
            "previous_page_url": page_url(page - 1) if page > 0 else None,
            "next_page_url": page_url(page + 1) if has_more else None,
            "url": page_url(page),
            "key": key,
        },
    }
