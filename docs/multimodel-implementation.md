# CNN + MPNN 비교 실행

이 문서는 M2 구현 당시의 기록이다. 이후 추가한 ConPLex·Boltz-2와 실시간 모델 로그는 [4모델 통합 기록](expanded-models.md)을 참조한다.

2026-11-11. `DTI-first-pipeline.md`의 M2를 구현했다. 기존 서열 CNN에
`MPNN_CNN_BindingDB` 약물 그래프 + 단백질 CNN adapter를 추가했다.
두 모델의 공식 checkpoint를 모두 실제로 로드해 CPU 추론을 확인했다.

## 사용

웹의 **사용 모델**에서 CNN, MPNN, **CNN + MPNN 비교 실행**을 선택한다.
기존 서버가 실행 중이었다면 재시작하고 페이지를 새로고침한다.

```powershell
.venv\Scripts\python.exe scripts/serve_web.py
.venv\Scripts\python.exe -m dti_tool run --source agent --input examples/comparison.json --output runs/comparison.json
```

모델을 지정하지 않은 기존 API 요청은 CNN 단일 실행을 유지한다.
`model`은 단일 선택, `models`는 비교 목록이다. 두 필드를 함께 보내거나
중복·빈 목록을 보내면 거절한다. CLI, Python, MCP, 웹에서 같은 검증을 적용한다.

비교는 GPU 모델을 동시에 올리지 않도록 순차 실행한다. 각 모델은 입력 검증부터
독립적으로 실행하므로 CNN의 문자열 제한을 넘겨도 MPNN이 지원하면 그 결과를 남긴다.

| 비교 상태 | 의미 | CLI 종료 코드 |
| --- | --- | --- |
| `success` | 선택한 모든 모델 성공 | 0 |
| `partial` | 일부 모델 성공, 나머지는 실패 | 3 |
| `error` | 모두 실패 또는 요청 자체가 잘못됨 | 2 |

`results`에 모델별 성공/오류를 보관한다. 비교 응답 상위 `prediction`과
`aggregate`는 null이며, 평균 점수·확률·신뢰구간을 만들지 않는다.
개별 결과는 원시 점수, endpoint 확인 여부, calibration 상태를 별도로 기록한다.
`model.completed` / `model.failed` 로그는 비교가 반환된 뒤 기록되며,
개별 추론의 시간은 이벤트 상세와 각 결과의 `execution`에 있다.

## 입력과 추론

| 항목 | CNN | MPNN |
| --- | --- | --- |
| 약물 입력 | SMILES, 최대 100자 | SMILES → 원자·결합 그래프 |
| 그래프 제한 | 해당 없음 | 원자 ≤400, `2 × 결합 수 + 1 ≤800`, 이웃 ≤6 |
| 입체화학 문자 | `@`, `/`, `\` 미지원 | RDKit/MPNN 특징으로 처리 |
| 단백질 | 표준 아미노산 20종, ≤1000잔기 | 동일 |

두 모델 모두 salt 자동 제거, domain 자동 선택, 입력 자동 절단을 하지 않는다.
MPNN의 제한은 **설치된 DeepPurpose 0.1.5**의 실제 `MAX_ATOM=400`,
`MAX_BOND=800`, `MAX_NB=6`을 기준으로 한다. `utils.py`의 100/200 표기는
주석 속 이전 설정이고, 최신 master의 600/1200과도 구별한다.

MPNN 전처리의 영벡터 fallback, 비정상 tensor shape, 비유한 특징, 잘못된
원자·결합 수를 검사해 예측 전에 중단한다. 설치 버전과 상수도 확인한다.
`strict=True` state loading을 사용하므로 누락된 파라미터를 무작위 초기값으로
남기지 않는다. upstream MPNN의 전역 device를 요청 장치로 설정한 뒤 복원해
CUDA가 있는 PC에서도 CPU 요청이 올바르게 동작하게 했다.

모델별 캐시와 SHA-256을 분리하고, 모델 설정·가중치와 실제 사용한
`DTI.py`, `utils.py`, `encoders.py`, `chemutils.py` 해시를 기록한다.
추론은 오프라인이며 다운로드는 `prepare-model` 또는 ZIP 가져오기 단계에서만 한다.
런타임은 기존 `.venv`와 `requirements/runtime.txt`를 사용하며 추가 DGL 패키지는 필요 없다.

## 공식 가중치 검증

[DeepPurpose 공식 다운로드 매핑](https://github.com/kexinhuang12345/DeepPurpose/blob/master/DeepPurpose/utils.py)의
[MPNN 체크포인트](https://dataverse.harvard.edu/api/access/datafile/4204178)를 받았다.
셸의 직접 다운로드는 `WinError 10013`으로 차단되어, 연결된
`ToolUniverse.download_binary_file`로 공식 URL에서 HTTP 200 응답을 받아
`prepare-model --model MPNN_CNN_BindingDB --archive ...`로 가져왔다.
획득 방식은 실제 경로대로 `local_archive`로 유지한다.

- archive SHA-256: `655119c3896a773a8ccf0e711ad263a3bfbcd0bab7ea5085cccb12e13908bc0c`
- model.pt SHA-256: `f0fb70eeca5ca4744be754ebbbb63affd52acc1e34ccb22c4024554c0b37b7bf`
- 상세 출처: [MPNN](checkpoint-mpnn-bindingdb.json), [CNN](checkpoint-cnn-bindingdb.json)

형식 확인용 `examples/comparison.json`으로 실제 공식 가중치를 실행한 결과:

| 모델 | 원시 값 | scale | endpoint | calibration |
| --- | --- | --- | --- | --- |
| CNN_CNN_BindingDB | 5.010917663574219 | upstream_log_affinity | 미확인 | not_calibrated |
| MPNN_CNN_BindingDB | 3.6025195121765137 | upstream_log_affinity | 미확인 | not_calibrated |

실행 ID: `998731f8018a46d09899cc0bf2c8d157`.
결과: `runs/multimodel-smoke.json`, 로그: `runs/predictions/<실행 ID>/events.jsonl`.
이는 **실행 재현 확인**이며 생물학적 정확도 평가가 아니다. 예시 단백질은
형식 확인용이고, 점수를 실험 Kd·IC50·nM·결합 확률로 바꾸지 않는다.

## 자동 검증과 남은 범위

`python -m pytest`로 입력 제한, 모델 선택, 캐시 분리, hash/파라미터 누락,
그래프 fallback, 장치 복원, 비교 성공·일부 실패·전체 실패,
웹 subprocess, CLI 종료 코드, MCP 스키마·응답을 검증한다.
테스트용 고정 가중치는 `runs/tests` 아래 격리되며 사용자 캐시에 들어가지 않는다.
공식 가중치 테스트는 `DTI_RUN_LIVE=1`로 실행하며 출처 기록의 정확한 해시와
반복 추론 일치 여부를 검사한다. 공식 가중치를 사용하는 검사와 현재 공유 작업 폴더의
예시 검사까지 포함해 **80개 통과, 실패·생략 0개**를 확인했다.
보고서: `runs/verification-multimodel-live.xml`.

로그 조회 중 작성 중인 UTF-8 문자를 읽는 경우도 수정했다. JSONL의 완결된 줄만
디코딩하므로 한국어 로그 추가 중 실행 조회가 일시적으로 404가 되는 것을 방지한다.

JavaScript 문법 검사는 통과했다. 실제 화면 시각·클릭 검증은
agent-browser CDP 연결 실패 및 내장 브라우저 host unavailable로 완료하지 못했다.
웹 API와 실제 워커를 통한 실행 검증과 화면 시각 검증을 구분한다.

ConPLex, StructureFree-DTA, Boltz-2와 3D 모델은 이번 구현 범위에 포함하지 않았다.
다음 모델 연결 전 정확한 endpoint 근거, 독립 평가, calibration은 여전히 필요하다.
