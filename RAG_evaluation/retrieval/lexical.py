"""Kiwi 토큰화와 BM25로 평가 공고를 검색하고 결과·manifest를 저장한다."""

import math
import sys
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import cast

from kiwipiepy import Kiwi, Token
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from RAG_evaluation.retrieval.common import (
    Inputs, argument_parser, collect_results, load_inputs, output_paths, save_results,
)


def normalize(text: str) -> str:
    """문서와 쿼리에 동일하게 유니코드 정규화와 대소문자 통일을 적용한다."""
    return unicodedata.normalize('NFKC', text).casefold()


def token_forms(tokens: Iterable[Token]) -> tuple[str, ...]:
    """문자·숫자가 포함된 형태소를 보존하고 문장 부호만 제외한다."""
    return tuple(token.form for token in tokens if any(char.isalnum() for char in token.form))


@dataclass(frozen=True)
class BM25Retriever:
    """공고 전체의 제목·본문에 대한 BM25Okapi 검색기."""

    doc_ids: tuple[str, ...]
    kiwi: Kiwi
    # 메모리에 만들어진 BM25 검색 모델
    index: BM25Okapi

    @classmethod
    def build(cls, inputs: Inputs, k1: float, b: float, epsilon: float) -> 'BM25Retriever':
        """공고를 ID순으로 정렬하고 동일한 전처리로 BM25 인덱스를 만든다."""
        if not all(math.isfinite(value) for value in (k1, b, epsilon)) or k1 <= 0 or not 0 <= b <= 1 or epsilon < 0:
            raise ValueError('BM25 설정은 유한한 k1>0, 0<=b<=1, epsilon>=0이어야 합니다')

        documents = tuple(sorted(inputs.documents, key=lambda doc: str(doc.id)))
        kiwi = Kiwi(num_workers=2, model_type='cong')
        texts = tuple(normalize(f'{doc.title}\n{doc.content}') for doc in documents)
        # 여기서 문서들이 흩어지지 않아서 나중에 다시 문서 id로 모을 필요 없다.
        tokens = tuple(
            token_forms(cast(list[Token], kiwi.tokenize(text)))
            for text in texts
        )

        if not any(tokens):
            raise ValueError('BM25로 색인할 토큰이 없습니다')

        # cls는 클래스 자신을 받는 관례적인 매개변수 이름
        return cls(tuple(str(doc.id) for doc in documents), kiwi, BM25Okapi(tokens, k1=k1, b=b, epsilon=epsilon))

    def search(self, query: str, top_k: int) -> tuple[tuple[str, float], ...]:
        """쿼리와 공고를 같은 방식으로 토큰화하고 점수·ID순으로 정렬한다."""
        tokens = token_forms(self.kiwi.tokenize(normalize(query)))

        scores = self.index.get_scores(tokens)

        hits = tuple((doc_id, float(score)) for doc_id, score in zip(self.doc_ids, scores, strict=True))
        # 1순위: score 내림차순 2순위: doc_id 오름차순
        return tuple(sorted(hits, key=lambda hit: (-hit[1], hit[0]))[:top_k])


def main() -> None:
    """BM25 검색을 실행하고 토크나이저·파라미터와 함께 결과를 저장한다."""
    started_at = perf_counter()
    parser = argument_parser(__doc__ or "lexical retrieval", 'bm25_kiwi_v1')
    parser.add_argument('--k1', type=float, default=1.5)
    parser.add_argument('--b', type=float, default=0.75)
    parser.add_argument('--epsilon', type=float, default=0.25)
    args = parser.parse_args()
    output_paths(args)
    inputs = load_inputs(args.corpus, args.queries)
    print(f'BM25 색인 시작: 공고 {len(inputs.documents)}건', flush=True)

    retriever = BM25Retriever.build(inputs, args.k1, args.b, args.epsilon)

    rows = collect_results(inputs, args.top_k, retriever.search)
    save_results(args, inputs, rows, {
        'retrieval_method': 'bm25', 'algorithm': 'BM25Okapi',
        'parameters': {'k1': args.k1, 'b': args.b, 'epsilon': args.epsilon},
        'document_template': '{title}\n{content}', 'chunking': None,
        'tokenizer': {'name': 'kiwi', 'model_type': 'cong', 'num_workers': 2,
                      'normalization': 'NFKC+casefold', 'keep': 'tokens containing alphanumeric characters',
                      'stopwords': None, 'custom_dictionary': None},
        'zero_score_policy': 'keep_for_pooling',
        'packages': {name: version(name) for name in ('kiwipiepy', 'kiwipiepy-model', 'rank-bm25', 'numpy')},
    }, started_at, (Path(__file__), ROOT / 'RAG_evaluation/retrieval/common.py'))


if __name__ == '__main__':
    main()
