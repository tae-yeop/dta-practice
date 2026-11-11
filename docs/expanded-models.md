# CNN·MPNN·ConPLex·Boltz-2 통합

2026-11-11. Boltz-2 adapter·실행 환경, ConPLex adapter·실행 환경, 웹 모델 선택 UI를 병렬로 구현하고 공통 `predict_dta` 도구에 통합했다. 네 모델의 준비 상태는 현재 모두 `ready`이며 실제 사전학습 추론을 확인했다. CPU와 GPU 계산은 런타임에서 순차 처리한다.

## 사용

웹 `http://127.0.0.1:8765`를 새로고침하고 원하는 모델을 체크한다. 기본값은 CNN·MPNN이며 ConPLex와 Boltz-2는 따로 선택한다. 장치를 `자동`으로 두면 Boltz-2는 CUDA, 나머지는 CPU를 사용한다. 명시적인 CPU/CUDA 요청은 조용히 변경하지 않는다.

에이전트는 [predict-dta 스킬](../skills/predict-dta/SKILL.md)을 읽고 같은 도구를 사용한다.

```powershell
.venv\Scripts\python.exe -m dti_tool run --source agent --input examples/conplex.json --output runs/conplex-result.json
.venv\Scripts\python.exe -m dti_tool run --source agent --input examples/boltz2.json --output runs/boltz2-result.json
```

두 예시는 Trimethoprim–대장균 K-12 DHFR 전체 서열 159 aa를 사용한다. 비교 요청은 `model` 대신 `models` 배열로 지정한다. 원본 입력, 사용한 입력, 모델·코드·가중치 해시, 장치와 실행 시간을 결과에 기록한다.

## 모델별 출력

| 모델 | 실제 입력 표현 | 원시 출력 | 기본 실행 환경 |
| --- | --- | --- | --- |
| CNN_CNN_BindingDB | SMILES CNN + 서열 CNN | upstream_log_affinity, endpoint 미확인 | .venv / CPU |
| MPNN_CNN_BindingDB | 약물 2D 그래프 + 서열 CNN | upstream_log_affinity, endpoint 미확인 | .venv / CPU |
| ConPLex_v1_BindingDB | Morgan + ProtBert | cosine_similarity 상호작용 점수 | .venv-conplex / CPU |
| Boltz2 | 단일 서열과 리간드의 복합체 공동 예측 | log10_IC50_uM와 별도 binder probability | .venv-boltz2 / CUDA |

ConPLex는 [공식 추론 코드](https://github.com/samsledje/ConPLex/blob/ccd8c804a76dff41649e58f692293b55c8907129/conplex_dti/cli/predict.py)의 projection architecture와 cosine 출력을 사용한다. Boltz-2의 단위·출력 구분은 [공식 예측 문서](https://github.com/jwohlwend/boltz/blob/main/docs/prediction.md)를 따른다. 서로 다른 점수를 평균하거나 통합 확률을 만들지 않는다. `aggregate=null`이며 모든 모델은 `uncertainty.status=not_calibrated`다.

Boltz-2의 구조 confidence는 `quality.structure_confidence`, 복합체 CIF는 `artifacts.complex_cif`에 기록한다. 구조 confidence를 affinity 구간이나 결합 확률로 해석하지 않는다. 현재는 `msa: empty`로 실행하므로 MSA가 있을 때와 정확도가 다를 수 있다. 원격 MSA 요청·사용자 입력 업로드는 하지 않는다.

## 실제 실행 증거

모든 아래 수치는 모델 출력이며 실험 affinity 정답이나 독립 성능 평가가 아니다.

| 실행 경로 | 입력 | 출력 | 결과 위치 |
| --- | --- | --- | --- |
| ConPLex 공통 CLI / 스킬 | Trimethoprim–DHFR 159 aa | 0.08126738667488098 cosine | `runs/conplex-smoke-result.json` |
| Boltz-2 공통 CLI / 스킬 | 동일 | -2.189967632293701 log10_IC50_uM; binder 0.9944232106208801 | `runs/boltz2-smoke-result.json` |
| 실제 브라우저 3모델 비교 / 자동 장치 | 동일 | CNN 5.4885845, MPNN 5.8387799, ConPLex 0.0812674 | `runs/predictions/45b0cb9b9b514f8f89aff75e039ceb56/result.json` |

ConPLex CLI 실행 ID는 `f4b10781df554db197fc5b8b6d16e9e4`, Boltz-2 CLI 실행 ID는 `79d320044ec94914a2b074b022e684e4`다. 소요 시간은 각각 약 19초, 168초였다. Boltz-2는 RTX 2080 Ti / Python 3.12.14 / PyTorch 2.5.1+cu121 / Boltz 2.2.1에서 full 200 sampling steps, affinity 5 samples로 실행했다. 별도 runtime과 프로젝트 전용 runtime으로 두 번 계산한 결과가 일치했다.

전체 자동 검사: `DTI_RUN_LIVE=1`, `DTI_RUN_CONPLEX_LIVE=1`을 설정한 `python -m pytest`에서 **109개 통과, Boltz-2 opt-in 1개 생략**. 보고서는 `runs/verification-expanded-models.xml`이다. Boltz-2는 위의 실제 공통 CLI 실행으로 검증했으며, pytest에서도 실행하려면 `DTI_RUN_BOLTZ_LIVE=1`을 설정한다. JavaScript 문법·스킬 validator와 실제 브라우저 입력·결과·모바일 검사를 통과했다.

## 운영과 보존

- 원래 `.venv`에서 API·CLI·MCP를 실행하고 새 모델은 전용 subprocess에 위임한다. 기존 DeepPurpose 의존성을 업그레이드하지 않았다. 설치·출처·해시·해석 제한은 [ConPLex](conplex.md), [Boltz-2](boltz2.md)에 기록했다.
- 준비 단계에서만 가중치를 다운로드한다. 기존 로컬 공식 파일을 재사용할 때도 복사한 파일을 공식 다운로드·LFS 해시와 대조했다. 예측은 오프라인이다.
- 비교 실행은 모델마다 `model.started`, `model.completed` / `model.failed`를 즉시 기록한다. 한 모델이 실패해도 다른 모델의 결과를 보존한다. 스킬·도구 로그와 결과 JSON 다운로드를 유지한다.
- Boltz-2 3600초, ConPLex 900초의 adapter 예산을 적용하고 웹·MCP 워커 예산도 선택 모델에 맞춘다. 이 Windows 환경에서는 시간 초과·서버 종료 시 자식 프로세스 트리를 정리한다. CUDA 파일 잠금은 프로세스 종료 시 OS가 해제한다.
- 권한 모드 변경으로 이전 sandbox의 DeepPurpose 캐시 ACL을 읽지 못하는 문제가 있었다. 원본 디렉터리는 변경하지 않고 공식 ZIP을 `.model-cache/deeppurpose/<모델>/`에 재설치했다. 읽을 수 있는 이전 캐시는 계속 지원한다. 새 파일은 캐시 부모의 권한을 상속한다. `pytest.ini`는 수집 범위를 `tests/`로 제한해 실행 산출물을 테스트로 재수집하지 않는다.

Conformal prediction, 독립 평가, 확률 보정과 새로운 모델들의 성능 우열 판단은 아직 수행하지 않았다. 다음 단계는 endpoint와 학습 중복 여부를 확인한 평가·calibration 데이터 마련이다.
