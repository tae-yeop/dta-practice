# 입력 프로파일 v1.1

워크벤치의 **입력 프로파일**은 편집 중인 입력을 검사한다. 첫 화면에서 화합물의 2D 구조식과 단백질 실험 구조의 미리보기를 전환할 수 있다. 단백질 미리보기 이미지는 저장소에 포함된 mmCIF의 지정 사슬을 3Dmol.js로 렌더링한 것이다. **구조·프로파일 상세**는 현재 입력을, 결과 화면의 **저장된 입력 프로파일**은 예측을 시작할 때 기록한 값을 연다. 둘 다 모달에서 전체 JSON을 저장할 수 있다.

**화합물** 탭은 입력 SMILES의 2D 구조식과 분리된 리간드의 3D 형태 한 가지를 보여준다. RDKit ETKDGv3로 수소를 추가한 후 고정 시드 42에서 좌표를 계산한다. 3D 좌표는 SDF로 저장할 수 있다. 미지정 입체중심은 생성된 좌표에서 한 가지 배치로 나타날 수 있다. 3D 미리보기는 수소 추가 전 128원자까지 계산하며, 계산 실패·크기 초과 시 프로파일에 사유를 남긴다. 2D 그림은 400원자까지 생성한다.

**단백질 구조** 탭은 입력 전체 서열이 로컬 카탈로그와 정확히 일치할 때, 그 accession에 대응하는 실험 구조를 연다. 예시 표적 다섯 종의 mmCIF와 PDBe 매핑을 저장소에 포함했다. 관측 범위는 UniProt 번호 기준이며 화면은 지정한 사슬을 보여준다. 원본 CIF에는 전체 엔트리가 담겨 있다. 화면의 비고분자 목록은 해당 엔트리에 등록된 성분이다. [좌표 출처와 사슬 매핑](../examples/structures/index.json)

**예측 복합체**는 Boltz-2가 해당 실행에서 저장한 CIF를 사용한다. 결과의 **복합체 3D 보기**를 누르면 같은 좌표계에서 단백질과 리간드를 회전해 볼 수 있다. 최신 프로파일이 함께 저장된 실행에서는 프로파일 안에서도 열 수 있다. 1.0 스냅샷에는 당시 관측치가 표시되며, 입력을 다시 분석해 최신 프로파일을 열 수 있다. 뷰어는 로컬에 포함된 3Dmol.js 2.5.5를 사용한다.

```powershell
.venv\Scripts\python.exe -m dti_tool profile --input examples/requests/acetazolamide-ca2.json --output runs/profile.json
```

Python에서는 `from dti_tool import profile_input`으로 가져와 `profile_input(smiles, protein_sequence)`를 호출한다. MCP의 `profile_input`과 HTTP의 `POST /api/profile`도 같은 두 필드를 받는다. CLI는 기존 예측 요청 파일을 읽을 때 모델 선택과 장치 필드를 건너뛴다. 독립 호출은 예측 실행 이력을 생성하지 않는다.

| 필드 | 후속 모듈에서 읽는 값 |
| --- | --- |
| `original`, `compound`, `protein` | 원본과 정규화한 입력, 입체화학·전하를 보존한 구조 식별자, 잔기 수와 조성, 서열 해시. 분자에는 분자식, 원자·결합·고리, 전하, 분자량, logP, TPSA, 수소 결합, 골격과 입체화학 정보가 있다. |
| `pair_id` | 원자 매핑 번호를 제거한 canonical isomeric SMILES와 전체 정규화 서열을 순서대로 묶은 SHA-256. CNN 문자 조건은 사용자가 입력한 SMILES 표기에 적용한다. |
| `compound.structures`, `protein.reference_structures` | 2D PNG(base64), 3D 생성 상태·방법·SDF, 실험 구조의 PDB ID·사슬·분해능·관측 범위·비고분자 성분·출처와 로컬 좌표 경로·SHA-256. |
| `catalog` | 로컬 카탈로그의 정확한 구조, 전체 서열, 예시 쌍을 개별 조회한 결과와 원래 출처. `no_match`의 범위는 기록된 카탈로그 버전이다. |
| `models[id]` | 출력 종류, 입력 적격 여부, 규칙별 관측치와 한도, 표현상의 주의점. `warn`인 모델도 입력을 받을 수 있다. 체크포인트 준비 상태와 CPU·GPU 가용성은 별도 `status`에서 확인한다. |
| `training`, `applicability` | 각 모델에 속한 체크포인트·학습 단계별 중복, 실제 학습 항목 ID와 최근접 관측치. 검증된 OOD 판정 기준이 없어 `ood_status`는 `not_assessed`다. |
| `enrichment` | 단백질 주석, 구조·포켓·결합 리간드, 정확한 쌍과 유사 쌍의 실험 기록을 각각 조회한 상태와 출처. 로컬 자료가 없으면 `not_queried`다. |

`status`는 프로파일 생성 결과다. 네 모델이 모두 입력 한도를 초과해도 각 실패 원인을 반환한다. 분자나 서열 자체가 잘못되면 `status=error`와 필드별 오류를 반환하고, 읽을 수 있는 쪽의 관측치는 보존한다. 예측 실행에서는 `result.input_profile`이 해당 실행 폴더의 파일을 가리킨다. 기존 실행 이력은 그대로 읽을 수 있다.

## 로컬 근거 자료 연결

`DTI_PROFILE_REFERENCES`에 근거 자료가 있는 디렉터리를 지정한다. 프로파일러는 이 위치의 UTF-8 JSON을 읽는다. 학습 목록은 `<model>/<stage>.json`에 둔다. 각 모델의 `training` 키에서 지원하는 단계와 해당 공식 체크포인트 SHA-256을 확인할 수 있다. ConPLex는 지도학습과 단백질 인코더 사전학습을, Boltz-2는 친화도와 구조 학습을 따로 조회한다. 이 해시는 감사 대상인 등록 체크포인트의 식별자다. 실제 실행 가중치는 예측 결과의 모델 provenance에서 확인한다.

| 학습 목록 필드 | 규약 |
| --- | --- |
| `schema_version`, `model`, `stage`, `checkpoint_sha256` | 버전 `1.0`과 해당 프로파일에 표시된 모델·단계·해시가 일치해야 한다. |
| `source`, `version` | 해당 체크포인트의 실제 학습 항목을 뒷받침하는 출처와 자료 버전. |
| `unit`, `coverage` | `compound`, `protein`, `pair` 중 하나와 `partial` 또는 `complete`. 완전성은 자료 공급자가 명시한다. |
| `entries` | 고유한 `id`와 해당 단위의 `smiles` 또는 `protein_sequence`를 가진 레코드 배열. 쌍은 두 필드가 모두 필요하다. |

정확한 중복은 구조와 전체 서열로 확인한다. 전체 **쌍** 목록에서만 양쪽이 각각 알려진 새 조합, 새 분자, 새 단백질, 둘 다 새로운 경우를 구별한다. 부분 목록의 미관측은 `unknown`으로 남긴다. 최근접 분자는 키랄성을 포함한 Morgan 지문의 Tanimoto, 최근접 단백질은 국소 정렬 점수로 선택한다. 단백질은 일치도와 양쪽 서열의 정렬 커버리지를 함께 제공한다. 쌍 목록에서는 각 최근접 레코드에 같은 행의 상대편 관측치도 들어 있다. 동점이면 파일에서 먼저 나온 행을 사용한다. 이 방식은 로컬 목록을 순회하므로 조회 비용은 참조 항목 수에 따라 증가한다.

추가 근거는 `evidence/<kind>.json`에 둔다. 파일에는 `schema_version` 값 `1.0`, `kind`, `source`, `version`, `records`를 넣는다. 각 레코드에는 출처에서 다시 찾을 수 있는 `reference_id`와 아래 조회 키가 필요하다. 도메인 좌표·단위·측정 부등호·실험 조건 등 공급자가 기록한 필드는 그대로 전달한다.

| kind | 조회 키 | 연결할 근거 |
| --- | --- | --- |
| `protein_family_domains_isoforms` | `sequence_sha256` | 전체 서열에 대응하는 accession, isoform, family, domain 구간 |
| `structures_pockets_ligands` | `sequence_sha256` | 구조 ID, 체인·서열 범위, 포켓과 관측 리간드 |
| `experimental_assays_exact_pair` | `pair_id` | 해당 쌍의 assay ID, endpoint, 측정값·단위·조건 |
| `experimental_assays_similar_pairs` | 조회 대상의 `pair_id` | 근거가 된 이웃 쌍의 ID와 유사성 근거, 그 쌍의 실험 기록 |

조회한 근거에는 자료 버전과 파일 SHA-256을 남긴다. 출처가 비공개임을 확인한 경우 메타데이터에 `availability: "unpublished"`를 명시할 수 있다. 이 경우 레코드 목록을 생략한다. 조회 실패는 `failed`, 추가 근거 자료에서 일치 항목이 없으면 `no_match`, 자료를 연결하지 않았으면 `not_queried`다.
