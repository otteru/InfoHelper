# 직행 RAG 평가 데이터 수집기

직행의 공개 목록·상세 API를 사용한다. 운영 크롤러, Supabase, 임베딩 및 이메일 발송과는 독립적으로 실행한다.

```bash
conda activate infohelper
python RAG_evaluation/crawler/zighang.py --limit 20
python RAG_evaluation/crawler/zighang.py --limit 100
python RAG_evaluation/crawler/zighang.py --limit 500
python RAG_evaluation/crawler/zighang.py --limit 5000
```

같은 명령을 다시 실행하면 체크포인트에서 이어서 수집한다. 목표 건수를 늘려도 이미 성공한 상세 공고는 재요청하지 않는다. `Ctrl+C`로 중단하면 현재까지의 결과를 내보낸다. 강제 종료된 경우에도 SQLite에 저장된 작업은 재사용한다.

현재 `--limit`은 **중복 제거 후 원문 또는 요약 텍스트가 있는 공고 수**다. 텍스트 원문을 우선 사용하고, 원문이 이미지뿐이거나 비어 있으면 API의 `summary`로 보완한다. `content_source`가 `content`인지 `summary`인지로 구분한다. 둘 다 비어 있는 공고만 제외한다. 원문에 이미지와 텍스트가 함께 있으면 텍스트와 이미지 URL을 함께 보존한다. OCR이나 외부 채용 사이트 재수집은 수행하지 않는다.

## 저장 파일

기본 경로는 실행 디렉터리와 관계없이 `RAG_evaluation/dataset/zighang/`이다. `--output 경로`로 별도 데이터셋을 만들 수 있다.

| 파일 | 용도 |
| --- | --- |
| `corpus.jsonl` | 한 줄에 한 공고: id, url, title, content, content_source, content_sha256, image_urls, fetched_at, metadata |
| `checkpoint.sqlite3` | 원본 응답, 페이지 위치, 공고별 성공·제외·실패 상태 |
| `raw_pages.jsonl` | 수집한 목록 API 원본 응답 |
| `raw_details.jsonl` | 이미지 원문·요약을 포함한 상세 API 원본 응답 |
| `issues.json` | 빈 본문·외부 URL 중복·요청 실패의 공고 ID와 사유 |
| `report.json` | 고정한 필터·정렬·시작 시각·목표·진행 건수 |

생성 데이터는 Git에서 제외한다. JSONL과 보고서는 정상 종료·Ctrl+C·예외 종료 시 생성하며, 실행 중 최신 진행 상황은 SQLite에 있다. 네트워크 요청 없이 저장된 결과만 다시 내보내려면 다음 명령을 사용한다.

```bash
python RAG_evaluation/crawler/zighang.py --export-only --limit 5000
```

## 수집 기준과 한계

- 첫 실행에서 `/recruitments/job-categories`의 `IT_개발.depthTwos`를 읽고 고정한다. 재개 시 필터를 새로 바꾸지 않는다.
- `/recruitments`에 반복 `depthTwos`, `page`, `size=20`, `sortCondition=LATEST`, `orderCondition=DESC`를 전달한다.
- `/recruitments/{id}`의 `content` 또는 `summary` Tiptap 문서를 텍스트로 바꾼다. 두 필드 모두 원본 응답에 보관한다. 경력·학력·채용 유형·지역·마감일은 문서의 `metadata`에도 보존한다.
- 공고 ID와 동일한 외부 원본 URL을 중복 제거한다. 문구가 같은 서로 다른 공고는 자동 삭제하지 않고 `content_sha256`으로 후속 분석할 수 있게 한다.
- 목록과 상세 ID를 대조하고, 목록의 하위 직무가 IT 필터와 겹치는지 검증한다.
- 요청마다 기본 0.2초 대기한다. timeout·연결 오류·429·5xx는 최대 4회 시도하며 지수 대기를 적용한다. 숫자형 `Retry-After`도 따른다.
- 401·403·재시도 후 429는 즉시 중단한다. 상세 실패는 기록 후 계속하되 연속 5회 실패하면 중단하고, 다음 실행에서 실패 항목을 다시 시도한다.
- 페이지가 반복되거나 응답 구조가 예상과 다르면 중단한다. API의 마지막 페이지에 도달해 목표가 부족하면 종료 코드 2를 반환한다.
- 최신순 페이지 번호 방식은 수집 중 신규 등록·삭제에 따른 위치 변동이 가능하다. ID 중복은 제거하지만 전체 목록의 특정 시점 스냅샷이나 누락 없는 전수 수집을 보장하지 않는다.
- 데이터는 최신순 IT·개발 공고 표본이다. 전체 채용 시장의 무작위 표본이 아니다. 직행이 제공한 요약은 원문 정보를 생략할 수 있으므로 평가 시 `content_source`별 성능도 구분할 수 있다.
- 동시 실행은 출력 폴더별 파일 잠금으로 차단한다. 현재 macOS/Linux에서 실행한다.

## 검증

```bash
python -m pytest RAG_evaluation/crawler/test_zighang.py -q
```

외부 네트워크 없이 문단 추출, 원문 우선·요약 대체·출처 구분, ID 정합성, 필터 검증, 페이지 롤백, 중복 제거, 중단 후 재개, 429 재시도, HTTP 200 실패 응답을 검증한다. 실제 수집 결과는 `dataset/zighang/report.json`에서 확인한다.

기존 원문 전용 v1 체크포인트는 다음 수집 실행 시 v2로 자동 전환한다. 저장된 원본 응답에서 요약을 복원하므로 이미 받은 공고를 재요청하지 않는다.

## 실제 수집 검증 결과 (2026-09-07)

- `corpus.jsonl`에 5,000건 저장: 원문 221건, 직행 요약 4,779건.
- 전체 5,000건의 ID·제목·본문·메타데이터를 원본 응답과 대조했다. IT 필터, 본문 해시, SQLite 무결성도 통과했다.
- 공고 ID·직행 URL·외부 원본 URL 중복과 빈 제목·빈 본문은 0건이다.
- 원문 1건·요약 2건은 실제 상세 웹페이지의 제목·전체 텍스트와 일치했다.
- 완료된 수집을 다시 실행했을 때 네트워크 요청 없이 동일한 corpus 해시를 유지했다.
- 단위 테스트 11개가 통과했다. 상세 결과는 `dataset/zighang/e2e_verification.json`, 웹페이지 대조 기록은 `live_page_verification.json`에 있다.
- 50자 미만 본문 318건이 있으며, 일부는 `마감기한 / 상시채용`만 담고 있다. 동일 본문은 29그룹이며 첫 문서를 제외한 중복 문서 수는 269건이다. ID가 다른 공고는 그대로 보존했으므로 RAG 평가 전 정보가 부족한 본문과 동일 본문을 별도로 정제해야 한다.
- 마지막 목록 페이지에 남은 18건은 목표 5,000건 도달로 상세 수집을 하지 않은 대기 항목이며 실패가 아니다.

JSONL은 파일을 한 줄씩 읽어 파싱한다. 원본 문자열 안에 Unicode 줄 구분 문자가 있을 수 있으므로 전체 문자열에 `splitlines()`를 적용하는 방식은 피한다.

```python
import json

with open("RAG_evaluation/dataset/zighang/corpus.jsonl", encoding="utf-8") as stream:
    documents = tuple(json.loads(line) for line in stream)
```
