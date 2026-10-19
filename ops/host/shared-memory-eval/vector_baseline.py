#!/usr/bin/env python3
"""Rank the store's topics for every query in queries.tsv with a small Chinese embedding model, so
`run_eval.py --hits` can score a vector search against the same rows. Not part of the skill and not
stdlib: it needs numpy, onnxruntime and tokenizers (about 200 MB in a throwaway venv) and the int8
ONNX export of bge-small-zh-v1.5 (model_quantized.onnx + tokenizer.json, about 24 MB).

    vector_baseline.py <model-dir> head  out.json   # name + description + first 400 body characters
    vector_baseline.py <model-dir> chunk out.json   # whole text in 400-character chunks, best chunk
"""
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

HERE = Path(__file__).resolve().parent
model, mode, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
root = Path(os.environ.get("SHARED_MEMORY_DIR", "~/.shared-memory")).expanduser()
options = ort.SessionOptions()
options.intra_op_num_threads = 1
session = ort.InferenceSession(str(model / "model_quantized.onnx"), options, providers=["CPUExecutionProvider"])
tokenizer = Tokenizer.from_file(str(model / "tokenizer.json"))
tokenizer.enable_truncation(256)
tokenizer.enable_padding()
inputs = {i.name for i in session.get_inputs()}


def embed(texts, batch=16):
    vectors = []
    for start in range(0, len(texts), batch):
        encoded = tokenizer.encode_batch(texts[start:start + batch])
        ids = np.array([e.ids for e in encoded], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64)}
        if "token_type_ids" in inputs:
            feeds["token_type_ids"] = np.zeros_like(ids)
        cls = session.run(None, feeds)[0][:, 0]
        vectors.append(cls / np.linalg.norm(cls, axis=1, keepdims=True))
    return np.vstack(vectors)


owners, texts = [], []
for path in sorted(root.rglob("*.md")):
    rel, text = str(path.relative_to(root)), path.read_text(encoding="utf-8")
    description = (re.search(r"^description:\s*(.+)$", text, re.M) or [None, ""])[1]
    body = text.split("\n---\n", 1)[-1]
    chunks = [f"{path.stem}\n{description}\n{body[:400]}"] if mode == "head" else \
        [f"{path.stem}\n{description}"] + [body[i:i + 400] for i in range(0, len(body), 400)]
    owners += [rel] * len(chunks)
    texts += chunks
vectors = embed(texts)

hits = {}
for line in (HERE / "queries.tsv").read_text(encoding="utf-8").splitlines():
    if line.strip() and not line.startswith("#"):
        query = line.split("\t")[2]
        sims = vectors @ embed(["为这个句子生成表示以用于检索相关文章：" + query])[0]
        best = {}
        for owner, sim in zip(owners, sims):
            best[owner] = max(best.get(owner, -1.0), float(sim))
        hits[query] = sorted(best, key=lambda rel: -best[rel])[:50]
out.write_text(json.dumps(hits, ensure_ascii=False), encoding="utf-8")
