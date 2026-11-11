# ConPLex DTI adapter

2026-11-11: `ConPLex_v1_BindingDB`를 공통 `predict_dta` 도구에 추가했다. 약물의 Morgan fingerprint와 단백질 ProtBert embedding을 공식 projection checkpoint에 넣어 **cosine interaction score**를 계산한다. DTA의 Kd·IC50 또는 보정된 결합 확률이 아니다.

## 모델과 전처리 근거

- [공식 저장소](https://github.com/samsledje/ConPLex)의 revision `ccd8c804a76dff41649e58f692293b55c8907129`를 고정했다. `SimpleCoembeddingNoSigmoid` 원본 클래스를 사용하며, 모델 파라미터를 `strict=True`로 로드한다. 학습 전용 의존성을 설치하지 않도록 필요한 원본 파일만 체크포인트 캐시에 보존한다. MIT LICENSE도 함께 저장한다.
- [공식 추론 CLI](https://github.com/samsledje/ConPLex/blob/ccd8c804a76dff41649e58f692293b55c8907129/conplex_dti/cli/predict.py)는 2048차원 Morgan, 1024차원 ProtBert, 1024차원 projection과 cosine 출력을 사용한다.
- [Morgan 전처리](https://github.com/samsledje/ConPLex/blob/ccd8c804a76dff41649e58f692293b55c8907129/conplex_dti/featurizer/molecule.py)는 radius=2, 2048 bits, `useChirality=False`다. 입력 SMILES를 임의로 바꾸지 않지만 이 표현으로는 입체이성질체가 같은 특징을 가질 수 있다. upstream의 영벡터 fallback은 wrapper가 거절한다.
- [단백질 전처리](https://github.com/samsledje/ConPLex/blob/ccd8c804a76dff41649e58f692293b55c8907129/conplex_dti/featurizer/protein.py)는 잔기 사이에 공백을 넣고 `[CLS]`, `[SEP]`를 제외한 마지막 hidden states를 평균한다. 모델의 1022잔기 한계를 그대로 검사하되, 초과 서열을 자르지 않고 거절한다. 표준 아미노산 20종만 받는다.
- [Rostlab/prot_bert](https://huggingface.co/Rostlab/prot_bert/tree/7a894481acdc12202f0a415dd567f6cfdb698908)의 revision을 고정했다. 원본 파일에는 encoder와 학습용 MLM/NSP heads가 들어 있다. `torch.load(weights_only=True)`로 읽고 encoder tensor를 모두 `strict=True`로 로드한다. feature extraction에 쓰지 않는 학습 head와 pooler는 실행하지 않는다.

## 설치와 준비

기존 DeepPurpose 환경을 유지하기 위해 별도 환경을 사용한다.

```powershell
uv venv .venv-conplex --python 3.10 --cache-dir .uv-cache
uv pip install --python .venv-conplex/Scripts/python.exe --cache-dir .uv-cache -r requirements-conplex.txt
.venv\Scripts\python.exe scripts/setup_conplex.py
```

준비 단계에서만 공식 projection checkpoint, pinned GitHub 코드, pinned ProtBert 가중치·config를 다운로드한다. ProtBert 가중치는 약 1.68 GB이며 CPU 메모리에는 추가 로딩·계산 공간이 필요하다. 기본 환경은 PyTorch 2.5.1 CPU, Transformers 4.45.2, RDKit 2024.9.6이다. 다른 interpreter를 사용하려면 `DTI_CONPLEX_PYTHON`으로 지정한다.

기존 공식 파일을 가져올 수도 있다.

```powershell
.venv\Scripts\python.exe scripts/setup_conplex.py --archive C:\path\BindingDB_ExperimentalValidModel.pt --local-protbert C:\path\prot_bert
```

`--archive`는 ZIP이 아닌 공식 `.pt` 파일을 받는다. `--local-protbert`는 게시된 SHA-256과 일치하는 `pytorch_model.bin`만 재사용하며, 작은 tokenizer/config 파일은 고정된 공식 revision에서 가져온다. 이번 설치는 다른 프로젝트의 원본 캐시를 **읽어서 복사**했고, 해당 프로젝트 파일은 변경하지 않았다. 이후 공식 HTTPS checkpoint도 별도로 내려받아 원본과 SHA-256이 같음을 확인했다.

캐시는 `.model-cache/ConPLex_v1_BindingDB/`이며 `DTI_MODEL_CACHE`를 따른다. `manifest.json`에 전체 코드·가중치·config의 SHA-256을 남긴다. 상태 조회에서는 각 파일을 처음 읽거나 파일 메타데이터가 바뀔 때 다시 해시 검증하여, 매 웹 폴링마다 1.68 GB를 읽지 않는다.

| 파일 | 확인한 SHA-256 |
| --- | --- |
| 공식 ConPLex checkpoint | `c28f0e64907e2cec786f2fdefd0ee75ac991b971671a49f896611dc192e6d39c` |
| 공식 ProtBert encoder 파일 | `6ea3edd26cfefc3111176100ee2a027ed510f9c86b63e5b53a2a050b59f2af9d` |

ConPLex 해시는 [공식 다운로드 URL](https://cb.csail.mit.edu/cb/conplex/data/models/BindingDB_ExperimentalValidModel.pt)에서 이번에 받은 파일로 고정했다. ProtBert 해시는 [HF 파일 메타데이터](https://huggingface.co/api/models/Rostlab/prot_bert/tree/7a894481acdc12202f0a415dd567f6cfdb698908)에 게시된 LFS SHA-256과 일치한다. 이 검사는 게시자의 디지털 서명 검증과 다르다.

## 실행과 출력

기존 요청에 `"model": "ConPLex_v1_BindingDB"`를 넣는다. `device=auto`는 CPU로 선택된다. `cuda`는 별도 ConPLex 환경에 호환되는 CUDA PyTorch가 설치되어 있을 때만 쓸 수 있다. 이번 검증은 CPU 실행이다.

```powershell
.venv\Scripts\python.exe -m dti_tool run --source agent --input runs/conplex-smoke-request.json --output runs/conplex-smoke-result.json
```

실제 추론은 별도 subprocess에서 실행하며 `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `local_files_only=True`를 사용한다. 입력 서열을 외부 서비스로 보내지 않는다. 900초 제한을 적용하고 worker의 입력·출력·stdout·stderr를 `runs/conplex/<작업 ID>/`에 보존한다. 공통 skill/tool 로그는 기존 `runs/predictions/<run_id>/`에 기록된다.

주요 출력 필드:

- `task=DTI`
- `prediction.scale=cosine_similarity`
- `prediction.endpoint=interaction_score`
- `prediction.interpretation_status=upstream_dti_score_not_calibrated_probability`
- `derived=null`, `uncertainty.status=not_calibrated`, `uncertainty.interval=null`
- `quality.ood_status=not_assessed`

2026-11-11 실제 Trimethoprim–대장균 K-12 DHFR (`P0ABQ4`, 159 aa) 예시의 CPU 출력은 **0.08126738667488098**이었다. direct adapter 실행은 약 36.6초였으며 `runs/conplex-smoke.json`에 저장했다. 공통 CLI로 반복한 실행도 같은 값을 반환했고 약 18.9초가 걸렸다. 실행 ID는 `f4b10781df554db197fc5b8b6d16e9e4`, 결과는 `runs/conplex-smoke-result.json`, 스킬·도구 로그는 `runs/predictions/f4b10781df554db197fc5b8b6d16e9e4/events.jsonl`에 있다. 이 값은 모델 실행 확인 결과로서 실험 정답이나 생물학적 정확도 검증을 뜻하지 않는다. 다른 모델의 affinity 수치와 평균하지 않는다.

## 검증

`tests/test_conplex.py`는 가중치 미준비 시 다운로드 금지, manifest 경로 제한, 파일 변경 후 해시 재검증을 검사한다. 실제 pretrained 추론 검사는 별도로 opt-in한다.

이번 검증에서는 실제 추론까지 포함한 **4개 검사 모두 통과**했다. 보고서는 `runs/conplex-verification.xml`이다. upstream RDKit Morgan 호출은 deprecation 경고를 내지만, 기존 학습 전처리와 같은 호출을 유지한다.

```powershell
$env:DTI_RUN_CONPLEX_LIVE = "1"
.venv\Scripts\python.exe -m pytest tests/test_conplex.py -q
Remove-Item Env:DTI_RUN_CONPLEX_LIVE
```

모델 소스, 가중치, 전처리의 고정과 실행 검증을 제공한다. 독립 평가, 확률 보정, conformal prediction은 구현하지 않았다.
