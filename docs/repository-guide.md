# 저장소 구조와 작업 관리

## 루트 점검 (2026-11-14)

| 경로 | 역할 | 관리 방식 |
| --- | --- | --- |
| `AGENTS.md`, `README.md`, `.gitignore`, `pytest.ini` | 에이전트 지침·사용법·Git 제외·테스트 설정 | Git 추적 |
| `dti_tool/` | 모델 실행·입력 검증·결과와 실행 기록 | Git 추적, 추론 변경 시 전체 pytest 실행 |
| `dti_web/` | 로컬 API와 웹 UI | Git 추적, UI 변경 시 문법·브라우저·웹 테스트 확인 |
| `skills/` | 에이전트 호출·결과 해석 지침 | Git 추적, 모델 실행 코드는 넣지 않음 |
| `scripts/` | 웹·MCP 시작과 명시적 모델 설치 | Git 추적 |
| `requirements/` | 공통·모델별 의존성 및 검증 환경 스냅샷 | Git 추적, 환경을 합치지 않음 |
| `examples/` | 입력 예시·공개 출처·MCP 설정 예시 | Git 추적, 실험 정답 또는 독립 평가로 취급하지 않음 |
| `tests/` | 검증 코드 | Git 추적 |
| `docs/` | 설계·모델 의미·체크포인트 출처·검증 기록 | Git 추적 |
| `.venv*`, `.model-cache/` | 로컬 실행 환경과 모델 가중치 | 보존, Git 제외 |
| `runs/` | 입력·실제 예측·로그·화면 캡처·테스트 산출물 | 보존, Git 제외; 입력이 포함되므로 일괄 업로드하지 않음 |
| `.uv-cache/`, `.taste-skill/`, `__pycache__/` | 설치·디자인 검사·Python 캐시 | Git 제외, 필요 시 재생성 가능 |
| `.pytest_cache/` | 과거 기본 위치의 테스트 캐시 | 현재 설정은 `runs/pytest-cache`; Git 제외 |

브라우저 검사 명령의 리다이렉션으로 생긴 루트의 0바이트 파일 `[e.className`을 제거했다. 기존 `.pytest_cache/`는 Windows 접근 권한 때문에 내용을 확인할 수 없어 삭제하지 않았다. 모델 캐시와 실행 이력은 재설치 비용과 실제 결과 보존을 고려해 삭제하지 않았다. 기존 설계 문서는 구현 기록에서 참조하므로 유지했다.

## 커밋 단위

- UI 표시·상호작용은 `feat(web): …` 또는 `fix(web): …`로 묶는다.
- 추론·어댑터 변경은 UI와 분리하고 `feat(tool): …` 또는 `fix(tool): …`로 기록한다.
- 의존성·저장소 구조는 `chore: …` 또는 `refactor: …`, 사용법·점검 기록은 `docs: …`로 기록한다.
- 관련 파일을 명시해 stage하고 `git diff --cached`를 확인한다. 환경·가중치·실행 산출물은 커밋하지 않는다.
- 기존 이력을 보존하고 일반 push를 사용한다. 원격 이력이 있으면 fetch·검토 후 통합하며 강제 push하지 않는다.

```powershell
git status --short
git diff --check
node --check dti_web/static/app.js
.venv\Scripts\python.exe -m pytest -q
git add -- <관련 파일>
git diff --cached
git commit -m "<작업 범위와 변경 내용>"
git push origin main
```

새 clone에는 로컬 환경·가중치·과거 실행이 포함되지 않는다. `README.md`의 설치와 명시적 모델 준비 절차를 수행한다. 예측 중 자동 다운로드나 임의 가중치 대체는 허용하지 않는다.
