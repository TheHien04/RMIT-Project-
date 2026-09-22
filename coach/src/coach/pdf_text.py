"""Read and write the onboarding PDF. Visible text is the citation source."""

from __future__ import annotations

from pathlib import Path

ONBOARDING_PAGES = [
    """Hướng dẫn tạo bảng ca làm

Bước 1. Mở mục "Tạo bảng".
[xong: panel tạo bảng đang mở]
""",
    """Bước 2. Bấm "Thêm cột" cho tới khi đủ cột.
[xong: bảng có cột Ca và Người]

Bước 3. Bấm "Lưu bảng".
[xong: bảng đã lưu]
""",
]

MISSING_LABEL_PAGES = [
    """Ghi chú nội bộ

Bước 1. Tự tìm chỗ tạo bảng trên hệ thống.
[xong: bảng đã lưu]
"""
]

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def load_pages(path: str | Path) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    if any("Bước" in page for page in pages):
        return pages
    subject = ""
    if reader.metadata is not None and reader.metadata.subject:
        subject = str(reader.metadata.subject)
    if "Bước" in subject:
        return [part.strip() for part in subject.split("\f") if part.strip()]
    raise ValueError(f"no lesson text found in {path}")


def write_lesson_pdf(path: str | Path, pages: list[str]) -> None:
    from fpdf import FPDF

    font = _find_font()
    pdf = FPDF()
    pdf.add_font("Lesson", fname=font)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_subject("\f".join(page.strip() for page in pages))
    for page in pages:
        pdf.add_page()
        pdf.set_font("Lesson", size=14)
        pdf.multi_cell(0, 8, page.strip())
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(destination))


def _find_font() -> str:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise FileNotFoundError(
        "No Unicode font found for the lesson PDF. Set a font at one of: "
        + ", ".join(_FONT_CANDIDATES)
    )
