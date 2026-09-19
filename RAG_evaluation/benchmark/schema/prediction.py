"""벤치마크 입력용 쿼리별 검색 예측 스키마."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Hit(BaseModel):
    """검색 단계의 공고 ID, 순위, 점수."""

    model_config = ConfigDict(frozen=True, strict=True, extra='forbid')
    doc_id: str = Field(min_length=1)
    rank: int = Field(ge=1)
    score: float = Field(allow_inf_nan=False)


class RecommendedDoc(BaseModel):
    """추천 단계에 포함된 공고."""

    model_config = ConfigDict(frozen=True, strict=True, extra='forbid')
    doc_id: str = Field(min_length=1)


class Timing(BaseModel):
    """쿼리 한 건의 단계별 지연 시간(ms)."""

    model_config = ConfigDict(frozen=True, extra='forbid')
    embedding_ms: float | None = Field(default=None, ge=0)
    retrieval_ms: float | None = Field(default=None, ge=0)
    rerank_ms: float | None = Field(default=None, ge=0)
    total_ms: float | None = Field(default=None, ge=0)


class Cost(BaseModel):
    """쿼리 한 건의 처리 비용."""

    model_config = ConfigDict(frozen=True, extra='forbid')
    usd: float = Field(ge=0, allow_inf_nan=False)


class QueryPrediction(BaseModel):
    """한 쿼리의 후보·순위·추천과 선택적 지연·비용."""

    model_config = ConfigDict(frozen=True, extra='forbid')
    query_id: str = Field(min_length=1)
    candidates: tuple[Hit, ...]
    ranked: tuple[Hit, ...]
    recommended: tuple[RecommendedDoc, ...] | None = None
    timing: Timing | None = None
    cost: Cost | None = None

    @model_validator(mode='after')
    def validate_stage_lists(self) -> Self:
        """단계별 공고·순위 중복과 추천 공고의 순위 목록 포함 여부를 검사한다."""
        self._validate_hits(self.candidates, 'candidates')
        self._validate_hits(self.ranked, 'ranked')
        if self.recommended is None:
            return self
        ranked_ids = {hit.doc_id for hit in self.ranked}
        if len({doc.doc_id for doc in self.recommended}) != len(self.recommended):
            raise ValueError('recommended에 중복 공고가 있습니다')
        if any(doc.doc_id not in ranked_ids for doc in self.recommended):
            raise ValueError('recommended 공고는 ranked에 있어야 합니다')
        return self

    def _validate_hits(self, hits: tuple[Hit, ...], name: str) -> None:
        """한 단계 목록의 공고·순위 중복과 연속 rank를 검사한다."""
        if len({hit.doc_id for hit in hits}) != len(hits):
            raise ValueError(f'{name}에 중복 공고가 있습니다')
        ranks = tuple(hit.rank for hit in hits)
        if ranks != tuple(range(1, len(hits) + 1)):
            raise ValueError(f'{name}의 rank는 1부터 연속이어야 합니다')
