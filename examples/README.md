# 실행 가능한 SMILES·Protein 예시

웹의 **예시 입력 불러오기**에서 항목을 고르면 SMILES와 Protein sequence가 바로 채워진다. 입력을 확인한 뒤 **예측 실행**을 누른다. 약물 9종, 단백질 5종으로 구성한 12쌍이다. 원본 데이터와 출처는 [catalog.json](catalog.json)에 저장되어 오프라인으로 사용할 수 있다.

| 예시 ID | 약물 | 표적 / UniProt | 서열 길이 |
| --- | --- | --- | --- |
| aspirin-cox1 | Aspirin | 사람 COX-1 / P23219 | 599 aa |
| aspirin-cox2 | Aspirin | 사람 COX-2 / P35354 | 604 aa |
| ibuprofen-cox1 | Ibuprofen | 사람 COX-1 / P23219 | 599 aa |
| ibuprofen-cox2 | Ibuprofen | 사람 COX-2 / P35354 | 604 aa |
| diclofenac-cox1 | Diclofenac | 사람 COX-1 / P23219 | 599 aa |
| diclofenac-cox2 | Diclofenac | 사람 COX-2 / P35354 | 604 aa |
| celecoxib-cox2 | Celecoxib | 사람 COX-2 / P35354 | 604 aa |
| acetazolamide-ca2 | Acetazolamide | 사람 CA2 / P00918 | 260 aa |
| methazolamide-ca2 | Methazolamide | 사람 CA2 / P00918 | 260 aa |
| trimethoprim-ecoli-dhfr | Trimethoprim | 대장균 K-12 DHFR / P0ABQ4 | 159 aa |
| caffeine-a2a | Caffeine | 사람 A2A receptor / P29274 | 412 aa |
| theophylline-a2a | Theophylline | 사람 A2A receptor / P29274 | 412 aa |

2026-11-11에 PubChem의 SMILES·InChIKey와 UniProt의 전체 canonical 서열을 조회했다. 모든 입력은 CNN의 100자 SMILES / 1,000 aa 제한에 맞으며, 두 모델로 실제 추론이 완료됨을 확인했다. 분자의 동일성은 RDKit으로 계산한 InChIKey와 PubChem 기록을 대조했다. Ibuprofen은 입체가 지정되지 않은 PubChem 항목이며, 특정 enantiomer의 표기를 제거한 입력이 아니다. Diclofenac은 중성 분자 형태다.

각 항목의 `evidence_url`은 상호작용 근거이며, `note`에 해석 범위를 기록했다. 구조 논문의 실험 construct와 여기의 전체 canonical 서열은 다를 수 있다. 이 목록은 사용법과 실행을 확인하기 위한 예시다. 실험 affinity 정답은 포함하지 않으며, BindingDB 학습 데이터와의 중복 여부도 확인하지 않았다. 독립 성능 평가·음성 대조·conformal calibration 데이터로 취급하지 않는다.

CLI에서도 그대로 사용할 수 있다.

```powershell
.venv\Scripts\python.exe -m dti_tool run --source agent --input examples/requests/acetazolamide-ca2.json --output runs/example-result.json
```

각 `requests/<예시 ID>.json`에는 SMILES, 전체 서열, CPU 설정이 들어 있다. 기본 모델은 CNN이며, 비교를 요청하려면 JSON에 `"models": ["CNN_CNN_BindingDB", "MPNN_CNN_BindingDB"]`를 추가한다. 모델별 점수를 평균하거나 nM·DTI 확률로 변환하지 않는다.

새 모델을 바로 실행하려면 [conplex.json](conplex.json) 또는 [boltz2.json](boltz2.json)을 사용한다. 두 파일은 Trimethoprim–DHFR 입력과 모델별 자동 장치 설정을 담고 있다. 두 새 모델도 이 입력에서 실제 추론을 확인했다. Boltz-2는 단일 서열 모드이며 MSA를 원격으로 생성하지 않는다. [모델별 사용법과 해석](../docs/expanded-models.md)을 참고한다.

분자 출처는 [PubChem](https://pubchem.ncbi.nlm.nih.gov/), 단백질 출처는 [UniProt](https://www.uniprot.org/)이다. 각 분자·서열의 직접 링크와 조회 날짜는 카탈로그에 보존했다. UniProt 데이터의 출처와 [CC BY 4.0 이용 조건](https://www.uniprot.org/help/license)을 따른다.
