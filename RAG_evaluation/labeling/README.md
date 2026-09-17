# 라벨링·검수 보조 도구

평가 데이터셋 제작에 사용한 로컬 웹 화면과 내보내기 스크립트다.
최종 평가용 라벨은 [`../dataset/labeling/pool_v1/`](../dataset/labeling/pool_v1/), 데이터 구성과 판정 출처는 [상위 README](../README.md)를 먼저 확인한다.

## 현재 산출물

- 파일럿 확정: `pilot_aligned_v2`, 120쌍.
- 평가용 합본: `pool_v1`, 3,022쌍. 파일럿 사람 120·holdout 사람 120·검수 사람 129·검수 에이전트 224·Grok 자동 통과 2,429건을 포함한다.
- 기준: [라벨링 가이드 v1.4](../../docs/labeling-guidelines.md), 평가 기준일 2026-09-07.
- 합본은 사람 전수 확정이 아니다. 50건 감사는 화면 확인만 했고 저장하지 않아 반영하지 않았다.
- holdout 합의 DB는 합본 입력에 포함하지 않는다. 최초 사람 점수를 보존하며, 합의 후 점수로 독립 비교 일치율을 다시 계산하지 않는다.
- 새 R7은 검수 에이전트 224건에 적용했다. 합본의 `guideline_version: 1.4`가 전체 재채점을 의미하지는 않는다.

## 파일 역할

| 파일 | 역할 |
| --- | --- |
| `app.py` | 표본 구성, 로컬 API, SQLite 판정·합의 이력 저장 |
| `index.html` | 파일럿·holdout·검수·감사 화면 |
| `align.html` | 파일럿·holdout 불일치 합의 화면 |
| `confirm.html` | 파일럿 제안 17건의 확정 화면 |
| `export_aligned.py` | 파일럿 초기 합의본 v1 내보내기 |
| `export_confirmed.py` | 파일럿 제안 확정을 반영한 v2 내보내기 |
| `export_pool.py` | 판정 출처별 우선순위를 적용한 pool_v1 합본 생성 |
| `first_pass_rules.md` | 1차 AI 판정에 사용한 당시 규칙 기록. 최신 기준은 위 가이드를 참조 |

특정 단계용 화면과 스크립트를 제작 기록으로 함께 보존한다. 범용 라벨링 서비스가 아니며, 한 명이 한 탭에서 사용하는 로컬 도구다.

## 실제 라벨링 흐름

1. Dense·BM25 top-20 합집합에서 유형별 20쌍, 총 120쌍의 파일럿을 고정했다. 쿼리별 후보를 고정 시드 해시와 라운드 로빈으로 배분해 80쿼리를 포함했다.
2. 사람과 독립 AI 판정을 비교하고, 불일치 합의·제안 확정을 거쳐 파일럿 v2를 만들었다.
3. 파일럿과 겹치지 않는 holdout 120쌍으로 기준 적용을 확인했다. 원점수와 이후 합의는 별도 저장했다.
4. 나머지 2,782쌍은 Grok 4.6 xhigh 서브에이전트로 1차 판정했다. 그 전에 시도한 Gemini 실행은 중단했으며 최종 1차 판정에 사용하지 않았다.
5. Grok이 검수를 요청한 353쌍은 사람 129건·에이전트 224건으로 검수하고, 자동 통과 2,429건과 함께 합본에 반영했다.

`first_pass.py`(Gemini 시도)와 `compare_agent.py`(개인 Downloads 경로 의존)는 공개 도구 목록에서 제외한다.
이 저장소는 Grok 서브에이전트 실행 전체를 자동 재현하는 파이프라인을 제공하지 않는다.

## 로컬 실행

프로젝트 루트에서 실행한다.

```bash
conda activate infohelper
uvicorn RAG_evaluation.labeling.app:app --host 127.0.0.1 --port 8765
```

**기존 로컬 입력이 필요하다.** corpus·쿼리는 `dataset/corpus.jsonl`과 `dataset/queries/eval_queries_80.jsonl`을 읽는다. Git에서 제외하는 `artifacts/zighang_v1/`의 검색 run·표본·판정 자료도 필요하므로 저장소를 내려받는 것만으로 화면을 실행할 수 없다.
모듈을 불러올 때 표본을 준비하므로 필요한 입력을 먼저 복원한다.

| 주소 | 용도 | 주요 로컬 저장 위치 (`artifacts/zighang_v1/` 아래) |
| --- | --- | --- |
| `/` | 파일럿 120쌍 | `labeling_pilot_v1/pilot.json`, `labels.sqlite3` |
| `/holdout` | 별도 120쌍 | `labeling_holdout_v1/holdout.json`, `labels.sqlite3` |
| `/align` | 파일럿 불일치 합의 | `labeling_pilot_v1/alignment.sqlite3` |
| `/confirm` | 파일럿 제안 17건 확정 | `labeling_pilot_v1/confirmation.sqlite3` |
| `/holdout-align` | holdout 불일치 합의 | `labeling_holdout_v1/alignment.sqlite3` |
| `/review` | Grok 검수 후보 353쌍 | `labeling_first_pass_v1/review.sqlite3` |
| `/audit` | 자동 통과 50쌍 감사 | `labeling_first_pass_v1/audit.json`, `audit.sqlite3` |

파일럿·holdout은 검색 순위·점수·검색기 정보를 숨긴다. 검수 화면은 Grok 제안 점수·근거를 보여준다.
0·1·2와 별도로 보류를 저장하며, 미평가·보류를 0점으로 내보내지 않는다. 제안을 화면에 채우는 것과 저장은 별개다.

표본은 스냅샷으로 고정하고 원점수·합의·확정 이력을 분리해 보존한다.
1차 입력은 `labeling_first_pass_v1/remaining.jsonl`, Grok 판정은 `labeling_first_pass_v1/grok_v1/judgments.jsonl`이다.
검수 화면에서 저장해도 Grok 원본 판정은 덮어쓰지 않는다.

`LABELING_OUTPUT_DIR`, `LABELING_HOLDOUT_DIR`, `LABELING_FIRST_PASS_DIR`, `LABELING_ALIGNED_DIR`로 해당 작업 경로를 변경할 수 있다.
이 설정만으로 corpus와 검색 run을 포함한 모든 입력 경로가 바뀌지는 않는다.

## 합본 내보내기

```bash
python RAG_evaluation/labeling/export_pool.py
```

필요 입력은 파일럿 v2, holdout 표본·라벨 DB, remaining 스냅샷, Grok 판정, 검수 DB, 기준 문서, Dense·BM25 run이다.
경로는 스크립트 상단에 정의되어 있다.

- 우선순위: 파일럿 → holdout → 사람 검수 → 에이전트 검수 → Grok 자동 통과.
- 합본의 쌍 ID가 검색 pool과 일치하는지 확인한다.
- `judgments.jsonl`, `qrels.txt`, `manifest.json`을 생성한다. 공고 원문과 개별 판단 근거는 합본에 포함하지 않는다.
- 입력 해시와 판정 출처를 기록하며, 기존 `pool_v1`과 결과가 다르면 덮어쓰기를 거부한다.
- 기존 DB와 중간 산출물은 삭제하지 않는다. 백업은 서버 종료 후 작업 폴더 전체를 보존한다.

## 검증

아래 테스트는 기존 로컬 corpus·표본·판정 DB가 있는 환경에서 수행하는 회귀 검증을 포함한다.
공개 저장소만으로 실행 가능한 독립 단위 테스트 묶음은 아니다.

```bash
python -m pytest test/rag_evaluation/test_labeling.py test/rag_evaluation/test_export_pool.py -q
```
