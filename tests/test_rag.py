"""Fixtures sintéticas para o RAG. Nenhum teste depende de documentos ou modelos externos."""

import json
from hashlib import sha256

import pytest

from oran_lab import rag, rag_corpus
from oran_lab.agent import SYSTEM_PROMPT, parse_grounded_proposal
from oran_lab.loop import _synthetic_frame, run_loop
from oran_lab.ollama import AgentConfig
from oran_lab.replay import ReplayConfig


class Embeddings:
    def __init__(self):
        self.calls = []
        self.digest = "a" * 64
        self.values = None
        self.tag = "embeddinggemma"

    def local_model(self):
        return {"digest": self.digest}

    def info(self, path):
        assert path == "/api/version"
        return {"version": "fixture"}

    def request(self, path, payload):
        assert path == "/api/embed" and payload["truncate"] is False
        self.calls.extend(payload["input"])
        vectors = self.values
        if vectors is None:
            vectors = [[0, 1] if "Physical resources" in item else [1, 0] for item in payload["input"]]
        return 200, json.dumps({"model": self.tag, "embeddings": vectors, "prompt_eval_count": 10})


@pytest.fixture
def sample_corpus(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    folder = tmp_path / "documentos"
    folder.mkdir()
    path = folder / "fixture.pdf"
    writer = PdfWriter()
    paragraphs = [
        ["3GPP TS 00.001 version 1.0.0 Release 1", "1.1 Contents ........ 2"],
        ["ETSI synthetic header", "1.1 Throughput", " ".join(f"uplink{n:03d}" for n in range(140))],
        ["ETSI synthetic header", "Continued throughput observations use historical records and documented windows.",
         "1.2 Physical resources", "Physical blocks are recorded separately from the reference throughput measurement."],
    ]
    for lines in paragraphs:
        page = writer.add_blank_page(width=600, height=800)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        operators = " ".join(f"({line}) Tj T*" for line in lines)
        data = DecodedStreamObject()
        data.set_data(f"BT /F1 12 Tf 14 TL 20 760 Td {operators} ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(data)
    writer.write(path)
    document = {"arquivo": path.name, "especificacao": "3GPP TS 00.001", "versao": "1.0.0", "release": 1,
                "sha256": sha256(path.read_bytes()).hexdigest(), "total_paginas_pdf": 3,
                "secoes": {"1.1": [2, 3], "1.2": [3, 3]}, "url": "https://example.org/fixture.pdf"}
    for module in (rag, rag_corpus):
        monkeypatch.setattr(module, "MANIFEST", [document])
    return folder, document


def test_extracts_pdf_with_page_trace_and_overlap(sample_corpus):
    folder, document = sample_corpus
    fragments = list(rag_corpus.extract_fragments(folder / document["arquivo"], document))
    first, second, last = fragments
    assert first["id"] == "00.001/1.0.0/1.1/1"
    assert first["paginas_pdf"] == [2] and second["paginas_pdf"] == [2, 3]
    assert last["secao"] == "1.2" and last["paginas_pdf"] == [3]
    assert all(len(f["texto"]) <= rag_corpus.CHUNK_CHARS and "ETSI" not in f["texto"] for f in fragments)
    first_words, second_words = first["texto"].split(), second["texto"].split()
    overlap = first_words[first_words.index(second_words[0]):]
    assert second_words[:len(overlap)] == overlap
    assert 80 <= len(" ".join(overlap)) <= rag_corpus.OVERLAP_CHARS
    assert "Physical blocks" not in second["texto"]


def test_manual_import_checks_hash_and_preserves_valid_copy(sample_corpus, tmp_path):
    folder, document = sample_corpus
    destination = tmp_path / "importado"
    path = folder / document["arquivo"]
    content = path.read_bytes()
    path.write_bytes(b"invalido")
    with pytest.raises(ValueError, match="incompatível"):
        rag_corpus.prepare_corpus(destination, source=folder)
    assert not (destination / path.name).exists()
    path.write_bytes(content)
    rag_corpus.prepare_corpus(destination, source=folder)
    path.write_bytes(b"alterado")
    rag_corpus.prepare_corpus(destination, source=folder)
    assert (destination / path.name).read_bytes() == content


@pytest.mark.parametrize("values, dimension", [([], None), ([0, 0], 2), ([1], 2),
                                               ([True, 2], 2), ([float("nan"), 2], 2),
                                               ([float("inf"), 2], 2), (["1", 2], 2)])
def test_invalid_embedding_values(values, dimension):
    with pytest.raises(ValueError):
        rag.unit_vector(values, dimension)


@pytest.mark.parametrize("values", [[], [[1, 2], [1]], [[1, 2], [1, float("inf")]]])
def test_invalid_embedding_batch(values):
    client = Embeddings()
    client.values = values
    with pytest.raises(ValueError):
        rag.Embedder(AgentConfig(model=rag.EMBED_MODEL), client).embed(["a", "b"])


def test_index_integrity_staleness_and_retrieval(sample_corpus, tmp_path):
    folder, _ = sample_corpus
    path = tmp_path / "indice.json"
    client = Embeddings()
    embedder = rag.Embedder(AgentConfig(model=rag.EMBED_MODEL), client)
    meta = rag.build_index(folder, path, embedder)
    index = rag.load_index(path, embedder.identity())
    assert meta["dimensao"] == 2 and meta["sha256"] == index["sha256"]
    hits = rag.search(index, embedder, "uplink", top_k=2)["recuperados"]
    assert [(hit["secao"], hit["score"]) for hit in hits] == [("1.1", 1.0)]
    assert hits[0]["url"] == "https://example.org/fixture.pdf"
    client.values = [[-1, 0]]
    assert rag.search(index, embedder, "irrelevante")["recuperados"] == []
    client.digest = "b" * 64
    with pytest.raises(ValueError, match="desatualizado"):
        rag.load_index(path, embedder.identity())
    with pytest.raises(ValueError, match="diverge"):
        rag.search(index, embedder, "uplink")
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["indice"]["vetores"][0][0] = 999
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        rag.load_index(path)
    envelope["indice"]["vetores"][0] = [1]
    envelope["sha256"] = rag.digest_json(envelope["indice"])
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="Dimensão"):
        rag.load_index(path)


def test_budget_preserves_evidence_and_skips_oversized_excerpt():
    evidence = {"detector": {"sinal": "evidência " * 10}}
    hit = {"documento": "fixture", "versao": "1", "secao": "1.1", "paginas_pdf": [2], "texto": "a" * 1000}
    config = AgentConfig(num_ctx=800, num_predict=64)
    presented, budget = rag.budget_context(evidence, [hit, {**hit, "texto": "trecho curto"}], config, "Sistema")
    assert [r["ref"] for r in presented] == ["R2"]
    assert budget["entrada_estimada"] <= budget["limite_estimado"]
    assert evidence == {"detector": {"sinal": "evidência " * 10}}


class Chat:
    def __init__(self, cited=None, justification="Queda persistente no cenário"):
        self.cited = cited
        self.justification = justification
        self.payloads = []

    def metadata(self):
        return {"digest": "fixture"}

    def residency(self):
        return {}

    def request(self, path, payload):
        assert path == "/api/chat"
        self.payloads.append(payload)
        proposal = {"acao": "registrar_alerta", "parametros": {"evento_id": "alerta-5"},
                    "justificativa": self.justification}
        if self.cited is not None:
            proposal["referencias"] = self.cited
        message = {"role": "assistant", "content": json.dumps(proposal)}
        return 200, json.dumps({"done": True, "message": message, "prompt_eval_count": 100, "eval_count": 20})


@pytest.mark.parametrize("citations, origin", [(["R1"], "ollama"), (["R9"], "fallback_python"),
                                               ([], "ollama"), (["R1", "R1"], "fallback_python")])
def test_agent_keeps_citations_out_of_action(sample_corpus, tmp_path, citations, origin):
    folder, _ = sample_corpus
    embedder = rag.Embedder(AgentConfig(model=rag.EMBED_MODEL), Embeddings())
    path = tmp_path / "indice.json"
    rag.build_index(folder, path, embedder)
    session = rag.RagSession(path, embedder)
    chat = Chat(citations)
    frame, source = _synthetic_frame()
    result = run_loop(frame, source, ReplayConfig(2), agent_config=AgentConfig(num_ctx=8192, max_calls=1),
                      client=chat, rag=session)
    decision = result["agente"]["decisoes"][4]
    assert decision["origem_decisao_final"] == origin
    assert decision["rag"]["decisao_com_citacao_validada"] is (citations == ["R1"])
    assert decision["rag"]["referencias_apresentadas"][0]["ref"] == "R1"
    assert "DRB.UEThpUl" in decision["rag"]["consulta"]
    assert "referencias" not in result["simulador"]["historico"][4]["proposta"]
    assert chat.payloads[0]["messages"][0]["content"].startswith(SYSTEM_PROMPT)


@pytest.mark.parametrize("justification, origin", [("Queda persistente", "ollama"),
                                                   ("Conforme R9", "fallback_python")])
def test_missing_index_uses_original_contract_without_rag_success(tmp_path, justification, origin):
    embedder = rag.Embedder(AgentConfig(model=rag.EMBED_MODEL), Embeddings())
    chat = Chat(justification=justification)
    frame, source = _synthetic_frame()
    result = run_loop(frame, source, ReplayConfig(2), agent_config=AgentConfig(num_ctx=8192, max_calls=1),
                      client=chat, rag=rag.RagSession(tmp_path / "ausente.json", embedder))
    decision = result["agente"]["decisoes"][4]
    assert decision["rag"]["estado"] == "indisponivel"
    assert not decision["rag"]["decisao_com_citacao_validada"]
    assert decision["origem_decisao_final"] == origin
    assert "referencias_3gpp" not in json.loads(chat.payloads[0]["messages"][1]["content"])


def test_no_similar_hits_uses_original_contract(sample_corpus, tmp_path):
    folder, _ = sample_corpus
    client = Embeddings()
    embedder = rag.Embedder(AgentConfig(model=rag.EMBED_MODEL), client)
    path = tmp_path / "indice.json"
    rag.build_index(folder, path, embedder)
    client.values = [[-1, 0]]
    frame, source = _synthetic_frame()
    result = run_loop(frame, source, ReplayConfig(2), agent_config=AgentConfig(num_ctx=8192, max_calls=1),
                      client=Chat(), rag=rag.RagSession(path, embedder))
    record = result["agente"]["decisoes"][4]["rag"]
    assert record["estado"] == "sem_resultados" and not record["decisao_com_citacao_validada"]


def test_undeclared_reference_in_justification_is_rejected():
    raw = json.dumps({"acao": "nenhuma_acao", "parametros": {}, "justificativa": "Conforme R9", "referencias": ["R1"]})
    with pytest.raises(ValueError, match="não declarada"):
        parse_grounded_proposal(raw, [{"ref": "R1"}], {})
