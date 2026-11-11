A. Sequence/SMILES Pairwise Prediction

- 입력: Drug SMILES + Protein sequence → 출력: DTI/DTA 예측

| 모델 / GitHub | 가중치 | 학습 데이터셋 | 주요 특징 |
| --- | --- | --- | --- |
| StructureFree-DTA | 추론 가능 Davis 체크포인트 | Davis, KIBA, BindingDB를 각각 사용한 실험 | ESM-2 8M + ChemBERTa + Residual Inception + MLP. 3D 불필요 |
| DeepPurpose | 추론 가능 다수 체크포인트 | Davis, KIBA, BindingDB, BindingDB-IC50 | CNN, Transformer, Fingerprint, MPNN 등 여러 인코더의 표준 베이스라인 |
| DeepDTA | 조건부,  원본은 학습 코드 중심 | Davis, KIBA | SMILES CNN + 단백질 서열 CNN. 고전적인 DTA 비교 기준 |

B. Molecular Graph-based Prediction

- 입력: Drug molecular graph + Protein representation → 출력: DTI/DTA/MoA

| 모델 / GitHub | 가중치 | 학습 데이터셋 | 주요 특징 |
| --- | --- | --- | --- |
| DeepPurpose MPNN | 추론 가능 | Davis, KIBA, BindingDB | 약물 그래프 MPNN + 단백질 CNN. 가장 쉽게 실행 가능한 그래프 DTA 베이스라인 |
| EviDTI | 조건부 Zenodo 모델 파일 | DrugBank, Davis, KIBA | 약물 2D·3D 특징과 단백질 서열을 결합. Evidential learning으로 불확실성 추정 |
| GraphDTA | 재학습 필요 | Davis, KIBA | GCN, GAT, GIN 등 그래프 아키텍처 비교를 위한 표준 모델 |
| DrugBAN | 재학습 필요 | BindingDB, BioSNAP, Human | Bilinear attention + Domain adaptation. Drug/Protein 사이의 국소 상호작용 학습 |
| DTIAM | 조건부 BerMol만 확인 | Yamanishi_08, Hetionet, Davis, KIBA, Activation, Inhibition | DTI·DTA·활성화/억제 예측을 통합한 멀티태스크 프레임워크 |

C. Joint Embedding & Retrieval

- 입력: Drug + Target → 공동 임베딩 공간 → 결합 점수·후보 검색 순위

| 모델 / GitHub | 가중치 | 학습 데이터셋 | 주요 특징 |
| --- | --- | --- | --- |
| ConPLex | 추론 가능 | BindingDB 상호작용 데이터, ProtBert 표현 | Protein LM + 약물 Fingerprint를 공동 공간으로 투영해 DTI 추론 |
| DrugCLIP | 추론 가능 | 단백질 포켓–리간드 구조 쌍, 증강 포켓 데이터 | 3D 포켓–화합물 대조학습. 대규모 virtual screening |
| BindCLIP | 추론 가능 | DrugCLIP과 동일한 학습·검증 분할 + 추가 결합 포즈·negative molecule | 대조학습과 생성형 학습 결합. 2026 KDD 발표 |
| dtSFM | 조건부 | 공개 설명상 drug–target 공동 표현 학습 | MoLFormer와 ESM-2 기반 공동 임베딩. Research Preview 이용 조건 |

D. Structure-aware, Pose-free Prediction

- 입력: Drug 2D graph + Protein 3D → 출력: DTI/DTA, 별도 도킹 포즈 생성 없음

| 모델 / GitHub | 가중치 | 학습 데이터셋 | 주요 특징 |
| --- | --- | --- | --- |
| CASTER-DTA | 추론 가능 | BindingDB 체크포인트 공개. 연구에서는 Davis, KIBA, Metz 등도 활용 | 약물 2D 그래프 + 단백질 3D 그래프. 구조의 기하학적 특징을 활용하지만 도킹 포즈는 만들지 않음 |
| SCOPE-DTI | 조건부 | ChEMBL 기반으로 구축한 SCOPE-DTI 데이터 및 단백질 구조 정보 | 1D 서열 모드와 3D 구조 모드 비교 가능. DTI 분류 및 새로운 타깃 일반화 연구 |

E. Binding Pose Prediction

입력: Protein 3D + Ligand → 출력: 3D binding pose 및 모델별 점수

| 모델 / GitHub | 가중치 | 학습 데이터셋 | 주요 특징 |
| --- | --- | --- | --- |
| GNINA | 추론 가능 내장 CNN | CrossDocked/CrossDocked2020 및 PDBbind 관련 복합체·도킹 데이터. CNN 모델별 구성 상이 | 전통 도킹 탐색 + CNN rescoring. 표준적인 구조 기반 베이스라인 |
| DiffDock-L | 추론 가능 | PDBbind 중심, Binding MOAD 관련 학습·확장 데이터 | SE(3)-equivariant diffusion으로 회전·이동·torsion을 생성 |
| DynamicBind | 추론 가능 | PDB 유래 단백질–리간드 결합 구조 데이터. 학습용 자료 별도 배포 | 리간드 결합에 따른 단백질 구조 변화까지 고려 |
| FlowDock | 추론 가능 | PDBbind, Binding MOAD, PDB 기반 구조 데이터. DockGen은 일반화 평가에도 사용 | Geometric Flow Matching. 포즈와 affinity 관련 예측 |
| TankBind | 조건부 | PDBbind 2020 기반 | Trigonometry-aware 네트워크로 단백질–리간드 거리 관계 및 포즈 예측 |

F. Complex Co-folding

입력: Protein sequence + Ligand → 출력: 예측된 단백질–리간드 복합체 구조

| 모델 / GitHub | 가중치 | 학습 데이터셋 | 주요 특징 |
| --- | --- | --- | --- |
| Boltz-2 | 추론 가능 | PDB 복합체 구조, 구조 학습용 증강·증류 자료. Affinity 모듈은 BindingDB·ChEMBL·PubChem 등 활성 데이터 활용 | 복합체 구조와 결합 가능성·affinity 관련 값을 함께 예측 |
| Protenix-v1 | 추론 가능 | wwPDB 기반 생체분자 구조, MSA·템플릿 및 증류 자료. 체크포인트별 학습 시점 상이 | AlphaFold3 계열 복합체 구조 예측 |
| Chai-1 | 추론 가능 | PDB 기반 생체분자 복합체 및 구조 학습 자료 | 단백질·리간드·DNA·RNA 등을 통합하는 구조 예측 모델 |
| NeuralPLexer | 추론 가능 | PDB 유래 단백질–리간드 복합체 및 상태별 구조 학습 자료 | 단백질의 결합 상태 변화를 고려한 생성형 복합체 예측 |

G. Complex-based Affinity Scoring

입력: Protein–Ligand complex / 결합 포즈 → 출력: 친화도 관련 점수 및 상호작용 특징

| 모델 / GitHub | 가중치 | 학습 데이터셋 | 주요 특징 |
| --- | --- | --- | --- |
| PIGNet2 | 추론 가능 | PDBbind v2020 scoring/docking/cross/random 학습 구성 | 물리적으로 해석 가능한 에너지 성분 기반 점수화 |
| RTMScore | 추론 가능 | PDBbind v2020 General Set | Graph Transformer 기반 거리·상호작용 점수화 및 원자/잔기 기여도 분석 |
| GNINA CNN Scoring | 추론 가능 | GNINA CNN별 학습 자료 상이. CrossDocked 계열 포함 | 도킹 포즈의 CNNscore 및 CNNaffinity 출력 |
| Boltz-2 Affinity | 추론 가능 | BindingDB·ChEMBL·PubChem 등의 실험 활성 자료 | Binder probability와 연속적인 affinity 예측 |

H. Biological Network-based Prediction

입력: Drug–Protein–Disease 네트워크 → 출력: 알려지지 않은 DTI 및 생물학적 연관성

이 계열은 A~G와 달리 공식 코드와 완성된 추론 체크포인트가 함께 공개된 사례가 상대적으로 적습니다.

| 모델 / GitHub | 가중치 | 학습 데이터셋 | 주요 특징 |
| --- | --- | --- | --- |
| Pharmacology Graph | 조건부 | ChEMBL 36 | ESM-2 단백질 임베딩·약물 그래프·이종 GNN을 결합해 Drug–Protein 및 Drug–Indication 관계 예측 |
| ProKG | 조건부 | 21개 생물의학 데이터 소스를 통합한 BioLink 그래프, DrugBank 및 kinase 관련 다운스트림 데이터 | Cold-start 및 불확실성 연구, 그래프 인코더 사전학습 |
| PIGLET | 재학습 필요 | 약물–단백질·포켓 및 생물학적 네트워크 정보 | 단백질 포켓의 유사성을 이용해 새로운 타깃 관계 탐색 |
| NeoDTI | 재학습 필요 | 알려진 약물–타깃, 약물–약물, 단백질–단백질 등 이종 생물학적 연결 데이터 | 고전적인 이종 네트워크 DTI 기준선 |

I. Physics-based Free Energy

입력: 준비된 단백질–리간드 구조 → 출력: 상대 또는 절대 결합 자유에너지 추정

I는 딥러닝 모델이 아니므로 학습 데이터셋과 사전학습 weight가 없습니다. 대신 물리 모델, 힘장과 분자동역학 시뮬레이션을 사용합니다.

| 오픈소스 / GitHub | 학습 가중치 | 핵심 기능 |
| --- | --- | --- |
| OpenFE | 불필요 | Alchemical free energy 계산 워크플로, 특히 상대 결합 자유에너지(RBFE) |
| OpenMM | 불필요 | GPU 기반 분자동역학 시뮬레이션 엔진 |
| Perses | 불필요 | Alchemical 변환 및 상대 자유에너지 연구용 도구 |


담당 Agent	파이프라인	주요 입력	핵심 작업 및 다음 단계에 전달할 출력
Evidence & Preparation Agent	공통 전처리	Drug SMILES, Protein ID/서열	정규화된 SMILES, 단백질 서열, 준비된 3D 구조, 포켓, 실험 데이터 출처
Pairwise DTI Agent	A·B	SMILES, Protein sequence	여러 서열·그래프 모델의 DTI/DTA/MoA 예측 결과
Embedding Retrieval Agent	C1·C2	SMILES, Protein sequence 또는 3D pocket	Drug/Protein embeddings, 유사도, Top-K 후보
Structure-aware Agent	D	Drug graph, Protein 3D	구조 정보를 이용한 DTI/DTA 예측
Docking Agent	E1·E2	Receptor 3D, Ligand, Pocket	poses.sdf, 도킹 점수, 포즈 순위·신뢰도
Co-folding Agent	F	Protein sequence, Ligand SMILES, 선택적 MSA	예측 복합체 CIF/PDB, 구조 confidence, 지원 시 Boltz-2 affinity 결과
Affinity Scoring Agent	G	준비된 Protein–Ligand complex 또는 docked pose	PIGNet2/RTMScore 등 점수, 상호작용 특징, 포즈별 순위
Biological Evidence Agent	H + 문헌·실험 조사	Drug/Target ID, 관련 assay 및 그래프	기존 실험 측정값, 네트워크 연결, 출처 및 증거 수준
Physics Refinement Agent	I	적절히 준비된 복합체, 비교할 리간드 쌍	ΔΔG 또는 ΔG 추정, 계산 불확실성, 수렴 진단
Validation & Adjudication	공통 검증	전체 Agent 결과·QC 기록	결과 충돌 분석, 근거 통합, 재계산 요청, 최종 판단