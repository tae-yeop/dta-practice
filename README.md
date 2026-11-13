# DTI agent: predict_dta

저장소 구조·로컬 산출물 보관 정책·작업별 커밋 방법은 [저장소 관리 안내](docs/repository-guide.md)를 참고하세요.

웹 UI는 입력과 모델별 요약 결과를 함께 보여줍니다. 점수의 척도·원시 출력·주의점은 결과의 **점수 해석** 버튼에서, 모델 비교·준비 상태·입력 안내는 각각의 모달에서 확인합니다.

SMILES와 단백질 서열을 받는 **예측 도구**, 이를 사용하는 **에이전트 스킬**, 결과와 실행 로그를 확인하는 **로컬 웹앱**이다. CNN·MPNN DTA, ConPLex DTI, Boltz-2 구조·affinity 모델을 개별 실행하거나 비교한다. 네 모델 모두 공식 가중치로 실제 추론을 확인했다. [4모델 구현·검증 기록](docs/expanded-models.md).

```text
Agent → skills/predict-dta/SKILL.md
      → predict_dta (MCP 또는 JSON CLI)
      → 입력 검증 → 체크포인트 검증 → 선택한 모델 → JSON 결과
```

계산은 `dti_tool`이 담당한다. 스킬은 호출 방법과 해석 원칙을 제공한다. `AGENTS.md`가 프로젝트 스킬의 경로를 안내하므로 CLI로 바로 사용할 수 있다. 글로벌 스킬 목록이나 현재 채팅의 MCP 서버 목록에 자동 등록한 것은 아니다.

설치 파일은 [`requirements/`](requirements/README.md)에 모았다. 공통 추론·웹·MCP는 최상위 파일, 모델 전용 의존성은 `models/`, 검증 환경의 전체 패키지 스냅샷은 `locks/`로 구분한다.

## 웹앱 실행

프로젝트 폴더에서 실행한다. 기존 추론 환경에 웹 의존성만 추가한다.

```powershell
uv pip install --python .venv\Scripts\python.exe --cache-dir .uv-cache -r requirements/web.txt
.venv\Scripts\python.exe scripts/serve_web.py
```

브라우저에서 **http://127.0.0.1:8765** 를 연다. `--port 8766`으로 포트를 바꿀 수 있다. 서버는 로컬 루프백 주소에만 바인딩한다.

- SMILES와 Protein sequence를 넣고 원하는 모델을 체크한 뒤 **예측 실행**을 누른다. CNN·MPNN만 기본 선택하며 ConPLex와 Boltz-2는 따로 선택한다. 장치 기본값 `자동`은 Boltz-2에는 CUDA, 다른 모델에는 CPU를 사용한다.
- **예시 입력 불러오기**에서 항목을 선택하면 공개 출처의 SMILES·전체 서열이 즉시 입력된다. 별도 적용 버튼은 없다. 직접 두 값을 입력해도 된다. 약물 9종·단백질 5종의 12개 예시와 출처는 [예시 안내](examples/README.md)에 있다.
- 결과에는 원시 점수·단위 해석 범위·보정 상태를 표시한다. 실패 시 점수 대신 실제 오류를 표시한다.
- 실행 로그에 `skill.loaded`, `tool.started`, `tool.completed` / `tool.partial` / `tool.failed`가 시간순으로 나타난다. 비교 시 각 모델이 시작·종료할 때 `model.started`, `model.completed` / `model.failed`를 바로 기록한다. 스킬 파일 SHA-256과 실행 ID도 남긴다.
- 최근 실행 선택, 요청 입력 확인, 결과 JSON·로그 JSONL 다운로드를 지원한다. 새 실행은 약 1.2초 간격으로 갱신한다.
- 웹을 재시작해도 이전 실행 기록이 남는다. 원본 입력과 결과는 이 컴퓨터의 `runs/predictions/`에 저장한다.

웹 버튼은 고정된 로컬 워크플로이며 별도 LLM을 호출하지 않는다. 에이전트는 사용 중인 Codex 등에서 이 프로젝트의 스킬을 읽고 같은 실행 도구를 호출한다. 웹앱에 채팅 모델이나 API 키 설정을 추가한 것은 아니다.

## 에이전트 요청과 공통 로그

이 프로젝트를 연 에이전트에게 실제 입력을 전달하고 **“predict-dta 스킬로 예측하고 결과와 로그를 보여줘”**라고 요청한다. 에이전트가 사용할 명령:

```powershell
.venv\Scripts\python.exe -m dti_tool run --source agent --input runs/request.json --output runs/result.json
```

`request.json`은 아래 CLI 절의 입력 형식을 사용한다. `run`은 스킬 문서를 읽고 그 버전을 기록한 뒤 예측 도구를 호출한다. 웹에서도 `에이전트` 출처로 즉시 조회된다. 웹 서버가 꺼져 있어도 실행·기록은 가능하다.

```text
에이전트 → SKILL.md 읽기 → CLI run 또는 MCP predict_dta ─┐
웹 입력 → 로컬 workflow ───────────────────────────────┤
                                                       ↓
                               skill.loaded → tool.started → 실제 추론
                                                       ↓
                        runs/predictions/<run_id>/{request,result,run}.json
                                                + events.jsonl
                                                       ↓
                                           웹 기록 / 에이전트 보고
```

`skill.loaded`는 래퍼가 실제 스킬 파일을 읽었다는 기록이다. LLM이 지침을 추론하거나 준수했다는 증명은 아니다. 에이전트는 스킬의 해석 지침을 따르고, 로그는 실행 사실을 제공한다. 직접 `predict` 명령이나 Python 함수를 호출하면 도구 로그만 남는다. MCP 래퍼는 스킬 로드도 기록한다.

각 결과의 `trace.run_id`로 실행을 식별한다. `events.jsonl`은 UTC 시각, 출처, 이벤트 이름, 세부 내용을 포함한다. 웹은 시각을 브라우저의 시간대로 표시한다. `DTI_RUNS_DIR` 환경변수로 기록 위치를 바꿀 수 있으며 웹과 에이전트에 같은 값을 사용해야 한다. 로그는 로컬 진단 기록이며 변조 방지 감사 로그는 아니다.

실행 장치는 **자동**을 권장한다. CNN·MPNN·ConPLex는 CPU, Boltz-2는 GPU를 사용한다. **GPU 강제**는 선택한 모든 모델에 적용되므로, GPU가 있는 컴퓨터라도 해당 모델의 Python 환경에 CPU용 PyTorch가 설치돼 있으면 `DEVICE_UNAVAILABLE`로 실패한다. 이 경우 자동으로 바꾸어 다시 실행한다. 모델별 실패 로그는 나머지 모델이 실행 중이어도 오류 코드와 해결 안내를 표시하며, 세부 정보에 실제 오류 메시지를 보존한다.

웹 API: `GET /api/status`, `GET /api/examples`, `GET /api/runs`, `POST /api/runs` (기존 도구 입력 JSON), `GET /api/runs/{id}`, `GET /api/runs/{id}/download/result`, `GET /api/runs/{id}/download/events`. POST는 실행 ID와 HTTP 202를 반환한다. JSON 요청만 받고 다른 출처의 브라우저 요청은 거부한다. 웹은 한 번에 한 요청을 처리하며, 모델별 시간 예산(CNN/MPNN 180초, ConPLex 900초, Boltz-2 3600초)의 합에 여유 시간을 더한 워커 제한을 적용한다. CUDA 작업은 CLI·MCP·웹 사이에서도 파일 잠금으로 직렬화한다. 시간 초과나 서버 종료 시 해당 워커 프로세스 트리를 정리한다.

## 현재 검증 상태

2026-11-11 기준:

- 프로젝트 `.venv`에 Python 3.10 / DeepPurpose 0.1.5 / PyTorch 2.5.1 CPU / RDKit 2024.9.6 설치, import 확인.
- 입력 검사·오류 JSON·실제 DeepPurpose 엔진의 **테스트용 가중치** 로드 경로 검증.
- MCP 1.30.0 설치. stdio 서버의 도구 목록·호출·오류 응답 검증.
- 웹·에이전트·MCP의 공통 실행 기록, 스킬 해시, JSON/JSONL 다운로드, 입력·가중치 검증, 혼합 모델 비교와 장치 잠금 검사: **109개 통과, Boltz-2 opt-in 테스트 1개 생략** (`runs/verification-expanded-models.xml`). CNN·MPNN 예시 24건 및 실제 ConPLex CPU 추론이 포함된다. Boltz-2는 별도 공통 CLI로 실제 GPU 추론을 완료했다.
- JavaScript 문법 검사와 스킬 검증 통과. 실제 브라우저에서 예시 선택·CNN 추론·로그·모바일 레이아웃을 확인했다. 이전 브라우저 연결 제한은 현재 해소되었다. 화면 검증 기록은 [웹앱 구현 메모](docs/webapp-design.md)에 있다.
- CNN·MPNN 공식 가중치 설치 완료. ToolUniverse의 파일 다운로드 도구로 Harvard Dataverse 원본을 받았고, 게시된 파일 크기·MD5와 대조한 뒤 로컬 ZIP으로 가져왔다. SHA-256 기록은 [CNN](docs/checkpoint-cnn-bindingdb.json), [MPNN](docs/checkpoint-mpnn-bindingdb.json)에 있다. 터미널의 직접 다운로드 제한과 별개로 현재 예측은 오프라인 실행된다.
- 실제 웹 API에서 Acetazolamide–CA2 비교 실행 성공: CNN `5.178440093994141`, MPNN `7.934460163116455`. `skill.loaded`, 모델별 완료 이벤트, 결과·로그 다운로드를 확인했다 (`runs/verification-web-official.json`). 두 값은 단위·endpoint가 확인되지 않은 원시 점수다.
- Trimethoprim–대장균 DHFR 159 aa 입력: ConPLex `0.08126738667488098` cosine 점수(약 19초), Boltz-2 `-2.189967632293701` log10(IC50 µM) 및 binder probability `0.9944232106208801`(약 168초), 복합체 CIF 생성. 공통 스킬·도구 경로의 결과는 `runs/conplex-smoke-result.json`, `runs/boltz2-smoke-result.json`에 있다. Boltz-2는 MSA 없는 단일 서열 모드이며 독립 확률 보정·성능 검증은 하지 않았다.
- MCP 호스트 등록용 설정을 제공한다. 현재 채팅의 네이티브 도구 목록에는 자동 등록하지 않았다. 프로젝트 에이전트는 CLI 경로로 호출할 수 있다.

테스트용 숫자를 실제 affinity 결과로 제공하지 않는다. `status`는 현재 설치와 체크포인트 상태를 확인하며, 과거의 실제 추론 성공을 증명하는 명령은 아니다.

## 설치와 모델 준비

프로젝트 루트의 PowerShell에서 실행한다. 네트워크가 허용되는 환경이 필요하다.

```powershell
uv venv .venv --python 3.10 --cache-dir .uv-cache
uv pip install --python .venv\Scripts\python.exe --cache-dir .uv-cache -r requirements/runtime.txt
uv pip install --python .venv\Scripts\python.exe --cache-dir .uv-cache --no-deps DeepPurpose==0.1.5
.venv\Scripts\python.exe -m dti_tool prepare-model
.venv\Scripts\python.exe -m dti_tool prepare-model --model MPNN_CNN_BindingDB
.venv\Scripts\python.exe -m dti_tool status
```

DeepPurpose의 전체 의존성에는 이 CNN/MPNN 추론에 쓰지 않는 training/DGL 패키지가 포함되어 있어 최소 추론 의존성을 먼저 설치한다. `requirements/locks/runtime-tested.lock`은 MCP와 테스트 도구를 포함한 이번 환경의 전체 패키지 스냅샷이다. 해당 환경을 그대로 복원하려면 `uv pip install --python .venv\Scripts\python.exe --cache-dir .uv-cache --no-deps -r requirements/locks/runtime-tested.lock`을 사용할 수 있다. 최소 설치에서는 MCP를 아래 명령으로 추가한다.

체크포인트 원본은 [DeepPurpose 다운로드 매핑](https://github.com/kexinhuang12345/DeepPurpose/blob/master/DeepPurpose/utils.py)에 지정된 [Harvard Dataverse 파일](https://dataverse.harvard.edu/api/access/datafile/4159715)이다. 네트워크를 사용할 수 없는 경우 이미 받은 원본 ZIP을 가져올 수 있다.

```powershell
.venv\Scripts\python.exe -m dti_tool prepare-model --archive C:\path\to\model_cnn_cnn_bindingdb.zip
```

`DTI_MODEL_CACHE`로 캐시 루트를 지정한다. 새 DeepPurpose 캐시는 `.model-cache/deeppurpose/<모델 이름>/`에 만들며 읽을 수 있는 기존 `.model-cache/<모델 이름>/`도 지원한다. Windows 임시 폴더의 계정 전용 권한을 그대로 옮기지 않도록 최종 파일은 캐시 부모의 권한을 상속한다. 기존 접근 불가 폴더는 보존하고 공식 ZIP에서 다시 준비했다. MPNN의 [공식 ZIP](https://dataverse.harvard.edu/api/access/datafile/4204178)은 `prepare-model --model MPNN_CNN_BindingDB --archive 파일경로`로 가져온다. 획득 방식과 SHA-256을 기록하며, 게시자의 디지털 서명 검증을 뜻하지 않는다.

ConPLex는 `.venv-conplex`, Boltz-2는 `.venv-boltz2`에서 실행한다. 공통 도구는 기존 `.venv`로 호출하고 전용 subprocess에 추론을 위임한다. 설치·공식 가중치 준비 방법은 [ConPLex](docs/conplex.md), [Boltz-2](docs/boltz2.md)를 따른다. 예측 중 다운로드나 원격 MSA 요청은 하지 않는다.

## CLI와 Python 호출

요청 JSON:

```json
{
  "smiles": "CC(=O)Oc1ccccc1C(=O)O",
  "protein_sequence": "MKTAYIAKQRQISFVKSHFSRQDILDLWIYHTQGYFPQ",
  "device": "cpu"
}
```

위 입력은 형식·실행 확인용이며, 검증된 생물학적 결합 쌍 예제가 아니다. 실제 작업에는 사용자가 제공한 쌍을 사용한다.

```powershell
.venv\Scripts\python.exe -m dti_tool schema
.venv\Scripts\python.exe -m dti_tool predict --input examples/request.json --output runs/result.json
```

성공/실패 모두 stdout에 JSON 한 개를 출력하고 진단 로그는 stderr로 보낸다. 실패 시 종료 코드는 2이고 `prediction=null`이다. `--input -`은 stdin JSON을 받는다. 쉘에서 SMILES를 명령문에 직접 삽입할 필요가 없다.

```python
from dti_tool import predict_dta

result = predict_dta(smiles=smiles, protein_sequence=sequence)
if result["status"] == "success":
    raw_score = result["prediction"]["raw_value"]
else:
    print(result["error"])
```

공통 입력은 단일 연결 분자와 표준 아미노산 20종으로 구성된 단일 서열이다. 단백질 길이 제한은 CNN/MPNN 1000, ConPLex 1022, Boltz-2 800잔기다. CNN은 SMILES 100자와 vocabulary 제한을 적용하고, MPNN은 원자 400개·방향성 결합 슬롯 800개·이웃 6개를 검사한다. Boltz-2의 리간드는 RDKit RemoveHs 후 원자 128개까지 받는다. 단백질 공백 제거·대문자 변환과 SMILES 앞뒤 공백 제거만 수행한다. salt 제거, domain 선택, 길이 절단은 자동으로 하지 않는다.

비교 실행 요청은 `examples/comparison.json`처럼 `"models": ["CNN_CNN_BindingDB", "MPNN_CNN_BindingDB"]`를 넣는다. 단일 선택 `model`과 함께 지정할 수 없다. Python에서도 `predict_dta(smiles, sequence, models=[...])`를 지원한다.

```powershell
.venv\Scripts\python.exe -m dti_tool run --source agent --input examples/comparison.json --output runs/comparison.json
```

비교 응답의 `results`에는 모델별 원본 결과가 들어가며 `status`는 전체 성공 `success`, 일부 성공 `partial`, 전체 실패 `error`다. CLI 종료 코드는 각각 0, 3, 2다. 상위 `prediction`과 `aggregate`는 null이다. 평균이나 확률을 만들지 않으며 실패한 모델의 오류를 그대로 남긴다. 모델 선택이 없는 기존 요청은 CNN 단일 실행을 유지한다.

## MCP로 연결

MCP SDK v1 API를 고정한다. 서버는 예측을 별도 subprocess에 위임하여 ML 로그가 MCP stdio를 손상시키지 않게 한다. 외부 네트워크 포트를 열지 않으며 `predict_dta` 하나만 노출한다.

```powershell
uv pip install --python .venv\Scripts\python.exe --cache-dir .uv-cache -r requirements/mcp.txt
.venv\Scripts\python.exe scripts/serve_mcp.py
```

MCP 호스트가 서버를 실행하도록 [examples/mcp-config.json](examples/mcp-config.json)의 설정을 사용한다. MCP를 별도 Python 환경에 설치했다면 `command`를 해당 interpreter로 바꾸고 `DTI_INFERENCE_PYTHON`은 이 프로젝트의 `.venv`를 가리키게 한다. 설정 파일은 등록 예시이며 호스트 설정에 자동 적용하지 않았다.

에이전트는 MCP 도구 목록에 `predict_dta`가 있으면 직접 호출하고, 없으면 스킬에 적힌 CLI를 사용한다. 글로벌 스킬 설치가 필요한 호스트에는 `skills/predict-dta`를 해당 호스트의 skill 경로에 배치하되 README 상대 경로와 프로젝트 위치를 함께 맞춰야 한다. 이 저장소에서는 프로젝트 안의 스킬을 그대로 사용하는 방식을 권장한다.

## 결과 의미와 확장

성공 결과에는 `input`, `model`, `prediction`, `derived`, `uncertainty`, `quality`, `execution`이 포함된다. 모델·설치 코드 해시, 실제 입력, runtime, 실행 시간을 기록한다.

CNN/MPNN은 정확한 checkpoint endpoint를 확인하지 못했으므로 `scale=upstream_log_affinity`, `endpoint=null`로 표시한다. ConPLex는 `cosine_similarity` DTI 점수다. Boltz-2는 공식 문서의 `log10_IC50_uM`와 별도의 binder probability를 보존한다. 구조 confidence는 `quality.structure_confidence`에 별도로 기록한다. nM 변환이나 서로 다른 점수의 평균은 만들지 않는다. 모든 모델에서 `uncertainty.status=not_calibrated`와 `quality.ood_status=not_assessed`를 보존한다.

ConPLex와 Boltz-2까지 연결했다. 독립 평가, 확률 보정, endpoint별 conformal calibration은 남아 있다. 다음 후보와 선정 근거는 [설계 문서](docs/DTI-first-pipeline.md)에 있다.

## 검증

```powershell
uv pip install --python .venv\Scripts\python.exe --cache-dir .uv-cache pytest pyyaml
.venv\Scripts\python.exe -m pytest -q
```

테스트 파일은 `runs/tests/`에 격리된다. MCP가 설치되어 있으면 MCP 통신 테스트도 실행한다. 합성 checkpoint 테스트는 원래 DeepPurpose architecture를 사용하며 모든 가중치를 고정해 로드와 출력 경로를 검증한다. 모델의 과학적 정확도를 검증하는 테스트가 아니다.

공식 가중치 확보 후 실제 추론을 별도로 검증한다.

```powershell
$env:DTI_RUN_LIVE = "1"
$env:DTI_RUN_CONPLEX_LIVE = "1"
.venv\Scripts\python.exe -m pytest -q --junitxml=runs/verification-expanded-models.xml
Remove-Item Env:DTI_RUN_LIVE
Remove-Item Env:DTI_RUN_CONPLEX_LIVE
```

이 테스트도 실행 재현성만 확인한다. 생물학적 성능·확률 보정·conformal coverage 평가와는 구별한다.

Boltz-2 GPU 테스트는 `DTI_RUN_BOLTZ_LIVE=1`로 따로 활성화한다. 바로 실행 가능한 새 모델 입력은 `examples/conplex.json`, `examples/boltz2.json`에 있다.
