# Boltz-2 adapter

이 adapter는 SMILES와 단일 단백질 서열로 복합체 구조를 예측한 다음 affinity 회귀와 결합 분류 출력을 계산한다. 공식 `boltz==2.2.1`을 별도 `.venv-boltz2` 환경에서 실행한다. 기존 DeepPurpose `.venv`는 바꾸지 않는다.

근거: [공식 코드와 출력 의미](https://github.com/jwohlwend/boltz), [공식 입력·출력 규격](https://github.com/jwohlwend/boltz/blob/main/docs/prediction.md), [공식 배포 가중치](https://huggingface.co/boltz-community/boltz-2/tree/6fdef46d763fee7fbb83ca5501ccceff43b85607). 조사·설치일은 2026-11-11이다.

## 준비

Windows / NVIDIA용으로 검증하는 환경:

```powershell
uv venv .venv-boltz2 --python 3.12 --cache-dir .uv-cache
uv pip install --python .venv-boltz2/Scripts/python.exe --cache-dir .uv-cache 'torch==2.5.1+cu121' --index-url https://download.pytorch.org/whl/cu121
uv pip install --python .venv-boltz2/Scripts/python.exe --cache-dir .uv-cache -r requirements-boltz2.txt
.venv/Scripts/python.exe scripts/setup_boltz2.py
```

다른 Python 환경을 명시하려면 `DTI_BOLTZ_PYTHON`을 설정한다. CUDA가 없는 머신에서 CPU 실행 경로도 제공하지만 매우 느릴 수 있다. 이번 실제 추론 검증은 CUDA에서 수행했다. `device=auto`는 이 adapter의 기본 장치인 CUDA를 선택하며, CUDA가 없다고 조용히 CPU로 바꾸지 않는다. CPU는 명시적으로 선택한다. 설치된 전체 의존성의 스냅샷은 [requirements-boltz2-tested.lock](../requirements-boltz2-tested.lock)에 있다.

이미 받은 공식 파일이 있다면 아래처럼 가져온다. 원본은 변경하지 않고 프로젝트 캐시에 복사한다.

```powershell
.venv/Scripts/python.exe scripts/setup_boltz2.py --asset-directory C:\path\to\official-boltz-cache
```

필요한 파일은 `boltz2_conf.ckpt`, `boltz2_aff.ckpt`, `mols.tar`다. 합계 약 6.2 GB이며 모든 파일을 공식 Hugging Face LFS SHA-256·바이트 수와 대조한다. revision은 `6fdef46d763fee7fbb83ca5501ccceff43b85607`로 고정했다. `prepare-model --model Boltz2 --archive PATH`의 PATH도 ZIP이 아닌 이 세 파일을 담은 디렉터리다.

캐시는 `.model-cache/Boltz2`이며 `DTI_MODEL_CACHE`로 루트를 바꿀 수 있다. 입력 범위에 필요한 공식 canonical CCD 아미노산 21개만 `mols.tar`에서 안전하게 추출한다. 나머지 CCD 화합물·수정 잔기 입력은 받지 않는다. Windows 예약 파일명 문제를 피하면서 원본 전체 archive와 개별 canonical 파일 해시를 보존한다. 파일 크기·mtime·ctime이 같으면 같은 프로세스 안에서 확인한 SHA-256을 재사용해 웹 상태 조회 때 6.2 GB를 매번 다시 읽지 않는다.

## 실행과 결과

요청에 `"model": "Boltz2", "device": "auto"`를 넣어 공통 `predict_dta` 도구를 호출한다. `models` 비교 목록에도 넣을 수 있다. 계산은 GPU를 동시에 점유하지 않도록 직렬 실행한다.

```powershell
.venv/Scripts/python.exe -m dti_tool run --source agent --input runs/boltz2-smoke-request.json --output runs/boltz2-smoke-result.json
```

입력은 JSON을 YAML 호환 형식으로 직렬화하므로 SMILES를 쉘 명령에 끼워 넣지 않는다. 각 실행은 새 작업 디렉터리를 만들며 기존 구조·점수를 재활용하지 않는다. 설정은 seed 42, structure recycling 3 / sampling steps 200 / diffusion samples 1, affinity sampling steps 200 / diffusion samples 5다. RTX 2080 Ti 호환을 위해 커널 최적화는 끈다. 추론 상한은 3,600초이며 시간 초과 시 해당 프로세스 트리를 종료한다.

| 결과 | 보존 위치 | 의미 |
| --- | --- | --- |
| `affinity_pred_value` | `prediction.raw_value` | `log10(IC50 / µM)` 예측. 낮을수록 강함 |
| `affinity_probability_binary` | `prediction.binding_probability` | 모델의 결합 분류 확률 출력. 이 프로젝트에서 확률 보정 검증 안 됨 |
| 구조 confidence JSON | `quality.structure_confidence` | 구조 품질 추정. 결합 확률·affinity 예측 구간과 구별 |
| 예측 복합체 CIF | `artifacts.complex_cif` | 해당 실행에서 계산한 복합체 구조 |

`prediction.upstream_outputs`에는 ensemble 구성요소를 포함한 원본 affinity JSON을 보존한다. nM 변환이나 모델 간 평균은 만들지 않는다. `uncertainty.status=not_calibrated`, interval은 null이다. checkpoint·설치 코드·adapter·worker 해시, 런타임 버전, 장치, 설정과 원본 출력 경로를 기록한다.

## 입력·해석 제한

- 표준 아미노산 20종의 단일 서열과 단일 연결 SMILES 분자를 받는다. 단백질 최대 800잔기는 이 PC를 위한 자원 정책이며 Boltz 자체의 과학적 상한을 뜻하지 않는다.
- Ligand는 RDKit `RemoveHs` 후 원자 수 128개까지 허용한다. 56개 초과는 공식 권장 학습 범위 밖이라는 경고를 기록한다. 분자·서열을 조용히 자르거나 변경하지 않는다.
- `msa: empty`로 **single-sequence** 추론한다. 공식 문서도 MSA가 없으면 정확도가 낮아질 수 있다고 설명한다. 이 앱은 서열을 외부 MSA 서버로 자동 전송하지 않는다.
- 예측 중 다운로드를 하지 않는다. worker에서 upstream 다운로드 함수를 로컬 파일 확인으로 대체하고 socket 연결과 URL 다운로드를 차단한다. 모든 setup 다운로드는 별도 명령에서만 수행한다.
- 작은 ligand와 단백질 하나의 구조·점수 예측이다. assay 조건이나 실험의 전체 복합체·보조인자를 재현하지 않으며 실제 결합 판정이나 Kd 측정값을 제공하지 않는다.

## 검증

```powershell
.venv/Scripts/python.exe -m pytest tests/test_boltz2.py -q
```

단위 검사는 미준비 상태의 다운로드 차단, 공식 해시와 CCD 변경 감지, 입력 제한, 출력 스케일·확률·구조 confidence 분리, 비유한 출력 거절을 확인한다. 합성 테스트 출력은 계약 검사에만 쓰고 실제 예측으로 표시하지 않는다.

비용이 큰 실제 GPU 검사는 `DTI_RUN_BOLTZ_LIVE=1`일 때 별도로 실행한다. 예시의 Trimethoprim–대장균 DHFR 159 aa 입력을 사용하며, 성공은 실행 확인일 뿐 생물학적 정확도·독립 평가·conformal coverage 검증이 아니다.

2026-11-11 실제 검증 결과:

- 단위 테스트 10개 통과. 별도 opt-in GPU 테스트는 일반 테스트에서 생략하며, 아래 공통 CLI 실측으로 동일 입력의 실제 실행을 확인했다.
- 프로젝트 자체 `.venv-boltz2`에서 `predict_dta`의 `run --source agent` 경로가 성공했다. 런타임은 Python 3.12.14 / PyTorch 2.5.1+cu121 / Boltz 2.2.1 / RDKit 2026.9.1, GPU는 RTX 2080 Ti였다.
- Trimethoprim–대장균 DHFR (159 aa)의 affinity 원시 출력 `-2.189967632293701` (`log10_IC50_uM`), 결합 분류 출력 `0.9944232106208801`. 전체 도구 실행 시간 167.5165초, 예측 복합체 CIF 생성 확인.
- 실행 ID `79d320044ec94914a2b074b022e684e4`. 결과는 `runs/boltz2-smoke-result.json`, 기록은 `runs/predictions/79d320044ec94914a2b074b022e684e4/events.jsonl`. `skill.loaded`, `tool.started`, `tool.completed`, `run.completed`를 확인했다.
- 별도 초기 runtime 검증과 프로젝트 독립 runtime 검증의 출력이 동일했다. 입력이나 출력 재사용 없이 두 번 계산했다. MSA 없이 계산된 예측이며 값의 크기를 실제 결합 확인 또는 검증된 확률로 보고하지 않는다.
