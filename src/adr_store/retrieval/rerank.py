"""Cross-encoder reranking of fused candidates (spec §8 "Reranker").

fastembed's `TextCrossEncoder` with `Xenova/ms-marco-MiniLM-L-6-v2` (ONNX, CPU, one thread).
Each (query, passage) pair is scored on its own (batch size 1), so a passage's score does not
depend on the other candidates (no shared padding), and candidates are scored in chunk-id
order: the result is a function of the query and the set of (chunk id, text) pairs only.
Scores are rounded to six decimals; ties go to the smaller chunk id. A model that cannot be
loaded (not in the fastembed cache and no network) raises `RerankerUnavailable`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from pathlib import Path

RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
RERANK_TOP = 50  # fused candidates passed to the reranker
_BATCH = 1

Scorer = Callable[[str, list[str]], Iterable[float]]
Hits = list[tuple[str, float]]


class RerankerUnavailable(RuntimeError):
    """The cross-encoder model could not be loaded (e.g. not cached and offline)."""


def load_cross_encoder(model_name: str, cache_dir: Path):
    """fastembed's `TextCrossEncoder` (downloads the model when it is not cached)."""
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name, cache_dir=str(cache_dir), threads=1)


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class CrossEncoderReranker:
    """`rerank(query, candidates, top)` with a cross-encoder.

    `scorer(query, texts) -> scores` and `model_hash` replace the model and the hash of its
    ONNX file (for tests).
    """

    def __init__(self, model_name: str = RERANK_MODEL,
                 model_cache_dir: Path = Path(".cache/fastembed"),
                 scorer: Scorer | None = None, model_hash: str | None = None):
        self.model_name = model_name
        self.model_cache_dir = Path(model_cache_dir)
        self._scorer = scorer
        self._model_hash = model_hash
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                self._model = load_cross_encoder(self.model_name, self.model_cache_dir)
            except Exception as e:  # fastembed / huggingface_hub raise many kinds
                raise RerankerUnavailable(
                    f"reranker model {self.model_name} not available offline in "
                    f"{self.model_cache_dir} ({type(e).__name__}: {e})") from e
        return self._model

    def load(self) -> None:
        """Load the model now (nothing to load with a given scorer), so that a missing model
        fails before any query; raises `RerankerUnavailable`."""
        if self._scorer is None:
            self._get_model()

    def _score(self, query: str, texts: list[str]) -> list[float]:
        if self._scorer is not None:
            return [float(s) for s in self._scorer(query, texts)]
        return [float(s) for s in self._get_model().rerank(query, texts, batch_size=_BATCH)]

    def rerank(self, query: str, candidates: list[tuple[str, str]],
               top: int | None = None) -> Hits:
        """(chunk_id, score) for the (chunk_id, text) candidates, best first."""
        pairs = sorted(dict(candidates).items())
        if not pairs:
            return []
        scores = self._score(query, [t for _, t in pairs])
        if len(scores) != len(pairs):
            raise ValueError(f"the cross-encoder returned {len(scores)} scores for "
                             f"{len(pairs)} candidates")
        hits = [(cid, round(s, 6)) for (cid, _), s in zip(pairs, scores, strict=True)]
        hits.sort(key=lambda h: (-h[1], h[0]))
        return hits if top is None else hits[:top]

    @property
    def model_hash(self) -> str:
        """SHA-256 of the model's ONNX file in the fastembed cache (downloads it if absent)."""
        if self._model_hash is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            desc = next(m for m in TextCrossEncoder.list_supported_models()
                        if m["model"] == self.model_name)
            repo = desc["sources"]["hf"].replace("/", "--")
            pattern = f"models--{repo}/snapshots/*/{desc['model_file']}"
            found = sorted(self.model_cache_dir.glob(pattern))
            if not found:
                self._get_model()
                found = sorted(self.model_cache_dir.glob(pattern))
            if not found:
                raise FileNotFoundError(f"ONNX file for {self.model_name} not in "
                                        f"{self.model_cache_dir}")
            self._model_hash = _file_sha256(found[0])
        return self._model_hash

    def config(self) -> dict:
        return {"model": self.model_name, "model_hash": self.model_hash, "top": RERANK_TOP,
                "batch_size": _BATCH}
