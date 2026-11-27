"""Obtenção e extração de cláusulas autorizadas do corpus local."""

import json
import re
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from .dataset import dataset_digest

DOCUMENTS = Path("data/rag/documentos")
CHUNK_CHARS = 1000
OVERLAP_CHARS = 120
MIN_TEXT = 80
MANIFEST = json.loads(files("oran_lab").joinpath("rag_manifest.json").read_text(encoding="utf-8"))
HEADING = re.compile(r"^([0-9]+(?:\.[0-9]+)+)\s+([A-Z][^\n]*|[a-z][^\n]*)$")


def verify_document(path, document):
    if dataset_digest(path) != document["sha256"]:
        raise ValueError(f"SHA-256 divergente para {path.name}")


def prepare_corpus(folder, *, download=False, source=None):
    """Confere todas as entradas ou instala cópias verificadas via download/importação."""
    if download or source is not None:
        folder.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=folder) as stage:
            pending = []
            for document in MANIFEST:
                path = folder / document["arquivo"]
                if path.exists():
                    verify_document(path, document)
                    continue
                staged = Path(stage) / path.name
                if source is not None:
                    data = (source / path.name).read_bytes()
                else:
                    with urlopen(document["url"], timeout=45) as response:
                        data = response.read(20_000_001)
                if len(data) > 20_000_000 or sha256(data).hexdigest() != document["sha256"]:
                    raise ValueError(f"Cópia incompatível com o manifesto para {path.name}")
                staged.write_bytes(data)
                pending.append((staged, path))
            for staged, path in pending:
                if not path.exists():
                    staged.replace(path)
    for document in MANIFEST:
        verify_document(folder / document["arquivo"], document)
    return MANIFEST


def section_text(pages, section):
    """Extrai linhas com a posição física no PDF (base 1)."""
    title = None
    body = []
    for page, text in pages:
        for raw in text.splitlines():
            line = " ".join(raw.split())
            if not line or line.startswith("ETSI") or re.search(r"\.{5,}\s*\d+$", line):
                continue
            heading = HEADING.fullmatch(line)
            if heading:
                if title is not None:
                    return title, body
                if heading[1] == section:
                    title = heading[2]
                continue
            if title is not None:
                line = re.sub(r"/g\d+", " ", line)
                line = "".join(c for c in line if c.isprintable())
                if any(c.isalpha() for c in line):
                    body.append((page, line))
    return title, body


def split_section(lines):
    words = [(word, page) for page, line in lines for word in line.split()]
    start = 0
    while start < len(words):
        end, size = start, 0
        while end < len(words) and size + len(words[end][0]) <= CHUNK_CHARS:
            size += len(words[end][0]) + 1
            end += 1
        if end == start:
            raise ValueError("Palavra excede o tamanho do fragmento")
        block = words[start:end]
        if size >= MIN_TEXT:
            yield " ".join(word for word, _ in block), sorted({page for _, page in block})
        if end == len(words):
            break
        keep = end
        overlap = 0
        while keep > start + 1 and overlap + len(words[keep - 1][0]) < OVERLAP_CHARS:
            keep -= 1
            overlap += len(words[keep][0]) + 1
        start = keep


def extract_fragments(path, document):
    try:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
    except ImportError as error:
        raise ValueError('Instale o extra rag com python -m pip install -e ".[rag]"') from error
    with path.open("rb") as source:
        if sha256(source.read()).hexdigest() != document["sha256"]:
            raise ValueError(f"SHA-256 divergente para {path.name}")
        source.seek(0)
        try:
            reader = PdfReader(source)
            if len(reader.pages) != document["total_paginas_pdf"]:
                raise ValueError(f"Número de páginas inesperado em {path.name}")
            cover = " ".join(reader.pages[0].extract_text().split())
            identity = f"{document['especificacao']} version {document['versao']} Release {document['release']}"
            if identity not in cover:
                raise ValueError(f"Capa incompatível com o manifesto em {path.name}")
            for section, (first, last) in document["secoes"].items():
                pages = ((page, reader.pages[page - 1].extract_text()) for page in range(first, last + 1))
                title, lines = section_text(pages, section)
                fragments = list(split_section(lines))
                if not title or not fragments:
                    raise ValueError(f"Cláusula {section} ausente ou ilegível em {path.name}")
                for number, (text, locations) in enumerate(fragments, 1):
                    name = document["especificacao"].split()[-1]
                    yield {"id": f"{name}/{document['versao']}/{section}/{number}",
                           "documento": document["especificacao"], "versao": document["versao"],
                           "secao": section, "titulo_secao": title, "paginas_pdf": locations, "texto": text}
        except PyPdfError as error:
            raise ValueError(f"PDF ilegível {path.name}: {error}") from error
