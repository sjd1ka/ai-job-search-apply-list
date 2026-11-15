"""Copy a resume variant to the fixed upload name, with matching PDF title metadata.

Usage: python tools/stage_upload.py <variant-or-cover-letter.pdf> "<Upload_Name>"
Writes upload/<name>.pdf (overwriting the previous staged copy). The variant is never modified.
"""
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def stage(src: Path, name: str, out_dir: Path) -> Path:
    writer = PdfWriter(clone_from=PdfReader(src))
    # ponytail: only Title is normalised; Author/Subject left as the variant has them
    writer.add_metadata({"/Title": name})
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{name}.pdf"
    with open(dest, "wb") as f:
        writer.write(f)
    return dest


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, name = Path(sys.argv[1]), sys.argv[2]
    dest = stage(src, name, Path("upload"))
    staged = PdfReader(dest)
    assert staged.metadata["/Title"] == name
    assert len(staged.pages) == len(PdfReader(src).pages)
    print(f"Staged {src} -> {dest} (title: {name})")
