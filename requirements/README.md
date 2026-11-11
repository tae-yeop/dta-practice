# 의존성 파일 안내

모든 설치 명령은 **프로젝트 루트**에서 실행한다. 모델별 가상환경을 구분해 설치하며, 파일 이동으로 패키지 버전이나 의존성 구성은 변경하지 않았다.

| 파일 | 용도 | 설치 환경 |
| --- | --- | --- |
| [runtime.txt](runtime.txt) | 공통 도구·DeepPurpose CNN/MPNN 추론의 최소 의존성 | `.venv`, Python 3.10 |
| [web.txt](web.txt) | 로컬 웹 서버 | 기존 `.venv`에 추가 |
| [mcp.txt](mcp.txt) | 에이전트용 MCP 서버 | 기존 `.venv`에 추가 |
| [models/conplex.txt](models/conplex.txt) | ConPLex·ProtBert 추론 | `.venv-conplex`, Python 3.10 |
| [models/boltz2.txt](models/boltz2.txt) | Boltz-2 구조·affinity 추론 | `.venv-boltz2`, Python 3.12 |
| [locks/runtime-tested.lock](locks/runtime-tested.lock) | 검증한 공통 환경의 전체 패키지 스냅샷 | `.venv` |
| [locks/boltz2-tested.lock](locks/boltz2-tested.lock) | 검증한 Boltz-2 환경의 전체 패키지 스냅샷 | `.venv-boltz2` |

기본 설치는 [프로젝트 설치 안내](../README.md#설치와-모델-준비)를 따른다. DeepPurpose는 `runtime.txt` 설치 후 `--no-deps`로 별도 설치한다. 웹과 MCP도 필요할 때 각각 추가한다.

```powershell
uv pip install --python .venv\Scripts\python.exe --cache-dir .uv-cache -r requirements/runtime.txt
uv pip install --python .venv\Scripts\python.exe --cache-dir .uv-cache --no-deps DeepPurpose==0.1.5
uv pip install --python .venv\Scripts\python.exe --cache-dir .uv-cache -r requirements/web.txt
uv pip install --python .venv\Scripts\python.exe --cache-dir .uv-cache -r requirements/mcp.txt
```

[ConPLex 설치 안내](../docs/conplex.md)와 [Boltz-2 설치 안내](../docs/boltz2.md)는 전용 환경 생성부터 가중치 준비까지 설명한다. Boltz-2는 먼저 CUDA 12.1 인덱스에서 해당 PyTorch 빌드를 설치해야 한다. 세 환경의 의존성을 한 환경에 합쳐 설치하지 않는다.

`locks/`의 파일은 기존 환경에서 확인한 전체 버전 목록이며 플랫폼·Python 버전·PyTorch 빌드에 영향을 받는다. 테스트 도구 등 최소 추론에 필요하지 않은 패키지도 포함한다. 일반적인 의존성 해결기가 생성한 범용 lockfile이나 해시 검증 파일은 아니다. 복원 시 원래 환경과 설치 안내를 확인한다. ConPLex의 전체 환경 스냅샷은 현재 제공하지 않는다.

이 파일들은 Python 패키지만 설치한다. 모델 가중치는 명시적인 setup 명령으로 별도 준비하고, 예측 실행은 오프라인으로 수행한다.
