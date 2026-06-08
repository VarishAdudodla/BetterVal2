import pymupdf as fitz  
from concurrent.futures import ThreadPoolExecutor
from backend.utils.upload import _is_toc_page

from config import COVER_PAGES_MAX, STATEMENT_TEXT_MAX_CHARS

STATEMENT_KEYWORDS = [
    "consolidated statements of operations",
    "consolidated statements of comprehensive income",
    "consolidated statements of income",
    "consolidated statement of operations",
    "consolidated statement of comprehensive income",
    "consolidated statement of income",
    "consolidated balance sheets",
    "consolidated balance sheet",
    "consolidated statements of cash flows",
    "statements of operations",
    "statements of income",
    "balance sheets",
    "statements of cash flows",
    "income statement",
    "balance sheet",
    "cash flow statement",
    "income statements",
    "cash flow statements",
]

COVER_KEYWORDS = [
    "shares outstanding",
    "weighted average",
    "common stock",
    "diluted",
]

COVER_TEXT_MAX_CHARS = 8000

def _extract_page(args: tuple) -> tuple[int, str]:
    page, i = args
    return i, page.get_text("text") or ""


def extract_all_text(
    file,
    max_chars: int | None = None,
    max_cover_pages: int | None = None,
) -> tuple[str, str]:
    stmt_limit = max_chars if max_chars is not None else STATEMENT_TEXT_MAX_CHARS
    cover_page_limit = max_cover_pages if max_cover_pages is not None else COVER_PAGES_MAX

    file.seek(0)
    # fitz.open() accepts a stream directly
    pdf = fitz.open(stream=file.read(), filetype="pdf")
    total_pages = len(pdf)
    cover_keyword_limit = min(cover_page_limit, total_pages // 3)

    if total_pages > 15:
        with ThreadPoolExecutor() as executor:
            pages = list(executor.map(_extract_page, ((pdf[i], i) for i in range(total_pages))))
    else:
        pages = [_extract_page((pdf[i], i)) for i in range(total_pages)]
        pdf.close()
        
    stmt_parts: list[str] = []
    cover_parts: list[str] = []
    stmt_chars = 0
    cover_chars = 0
    stmt_done = False
    cover_done = False

    for i, text in pages:
        if stmt_done and cover_done:
            break
        if not text:
            continue

        lower = text.lower()

        is_stmt = not stmt_done and not _is_toc_page(text) and any(kw in lower for kw in STATEMENT_KEYWORDS)
        is_cover = not cover_done and i < cover_keyword_limit and (
            i < cover_page_limit or any(kw in lower for kw in COVER_KEYWORDS)
        )

        if is_stmt:
            remaining = stmt_limit - stmt_chars
            stmt_parts.append(text[:remaining])
            stmt_chars += min(len(text), remaining)
            if stmt_chars >= stmt_limit:
                stmt_done = True

        if is_cover:
            remaining = COVER_TEXT_MAX_CHARS - cover_chars
            cover_parts.append(text[:remaining])
            cover_chars += min(len(text), remaining)
            if cover_chars >= COVER_TEXT_MAX_CHARS:
                cover_done = True

    statement_text = "\n".join(stmt_parts)
    if not statement_text.strip():
        raise ValueError("No financial statements found in PDF")

    return statement_text, "\n".join(cover_parts)