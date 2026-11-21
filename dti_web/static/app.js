"use strict";

const $ = (id) => document.getElementById(id);
const state = {selected: null, submitted: null, busy: false, polling: false, signature: "", historySignature: ""};
const exampleLibrary = new Map();
const modelCatalog = new Map();
const defaultModels = ["CNN_CNN_BindingDB", "MPNN_CNN_BindingDB"];
let chosenModels = new Set(defaultModels);
let modelCatalogSignature = "";
const sourceNames = {web: "웹", agent: "에이전트", mcp: "MCP", cli: "CLI", python: "Python"};
const statusNames = {queued: "대기 중", running: "실행 중", success: "완료", partial: "일부 완료", error: "실패"};
const modelLabels = {CNN_CNN_BindingDB: "CNN · 서열 DTA", MPNN_CNN_BindingDB: "MPNN · 약물 그래프 DTA", ConPLex_v1_BindingDB: "ConPLex · DTI 점수", Boltz2: "Boltz-2 · 3D 구조·affinity"};
const modelMethods = {
  CNN_CNN_BindingDB: {
    id: "method-cnn", name: "CNN_CNN", category: "서열 패턴 학습",
    drug: "SMILES 문자열 → 1D CNN", protein: "아미노산 서열 → 1D CNN", structure: "사용하지 않음",
    output: "로그 친화도 점수 · 정확한 예측 대상 미확인",
    explanation: "약물과 단백질을 각각 1차원 CNN으로 읽어 짧은 구간의 패턴을 추출합니다. 두 특징 벡터를 합쳐 친화도 점수 하나를 예측합니다. 이름의 앞 CNN은 약물, 뒤 CNN은 단백질 인코더이며 BindingDB는 학습 데이터의 출처입니다.",
    limit: "실제 결합 포즈나 원자 사이의 3D 거리를 계산하지 않습니다. 현재 출력은 upstream_log_affinity로 보존하며, pKd·IC50·nM로 단정하거나 환산하지 않습니다.",
    source: "https://github.com/kexinhuang12345/DeepPurpose/blob/master/DeepPurpose/encoders.py",
  },
  MPNN_CNN_BindingDB: {
    id: "method-mpnn", name: "MPNN_CNN", category: "약물 2D 그래프 학습",
    drug: "원자·결합 그래프 → MPNN", protein: "아미노산 서열 → 1D CNN", structure: "사용하지 않음",
    output: "로그 친화도 점수 · 정확한 예측 대상 미확인",
    explanation: "SMILES를 원자가 점, 화학결합이 선인 2D 그래프로 자동 변환합니다. MPNN(메시지 전달 신경망)이 연결된 주변 원자·결합 정보를 반복해서 모아 분자 특징을 만들고, 단백질 CNN의 특징과 합쳐 친화도 점수를 예측합니다.",
    limit: "그래프는 약물의 2D 연결 구조를 뜻합니다. 단백질 3D 그래프나 복합체 포즈를 사용하지 않으며, 현재 체크포인트의 정확한 예측 대상과 변환식은 추가 확인이 필요합니다.",
    source: "https://github.com/kexinhuang12345/DeepPurpose/blob/master/DeepPurpose/encoders.py#L222",
  },
  ConPLex_v1_BindingDB: {
    id: "method-conplex", name: "ConPLex", category: "단백질 언어모델 · 대조학습",
    drug: "Morgan 분자 지문", protein: "ProtBert 언어모델", structure: "사용하지 않음",
    output: "코사인 유사도 · DTI 상호작용 점수",
    explanation: "약물은 부분구조를 기록한 Morgan fingerprint로, 단백질은 대량의 서열로 사전학습된 ProtBert의 특징 벡터로 표현합니다. 상호작용하는 약물·단백질의 표현이 공통 공간에서 가까워지도록 학습한 모델이며, 현재 구현은 두 벡터의 코사인 유사도를 출력합니다.",
    limit: "상호작용 점수는 IC50·Kd 같은 농도값이나 보정된 결합 확률이 아닙니다. 현재 Morgan 지문 설정은 입체화학을 구별하지 않으며 3D 결합 구조도 계산하지 않습니다.",
    source: "https://github.com/samsledje/ConPLex",
  },
  Boltz2: {
    id: "method-boltz2", name: "Boltz-2", category: "3D 복합체 구조 · affinity",
    drug: "원자·결합 정보", protein: "단백질 서열 정보", structure: "복합체 3D 좌표 생성",
    output: "log10(IC50/µM) · binder 확률 · 복합체 구조",
    explanation: "Pairformer로 분자 구성요소 사이의 관계를 처리하고, 확산 모델로 원자의 3D 좌표를 생성합니다. 현재 파이프라인은 단백질–약물 복합체 구조를 예측한 뒤 affinity와 binder 확률을 계산합니다. SMILES와 서열에서 시작하므로 PDB를 따로 준비할 필요가 없습니다.",
    limit: "현재 앱은 유사 서열을 정렬한 MSA 없이 단일 서열로 실행합니다. 구조 생성에 시간이 걸리며 IC50는 실험값이 아닌 모델 예측입니다. Binder 확률과 구조 confidence는 affinity 예측 구간과 별개입니다.",
    source: "https://github.com/jwohlwend/boltz/blob/main/docs/prediction.md",
  },
};
const fixes = {
  MODEL_NOT_READY: ["모델 가중치를 먼저 준비해 주세요.", "아래 ‘모델 준비 상태’의 명령으로 공식 체크포인트를 설치한 뒤 다시 실행할 수 있습니다."],
  MODEL_INTEGRITY_ERROR: ["모델 파일 검증에 실패했습니다.", "체크포인트 파일과 manifest의 해시를 확인해 주세요."],
  INVALID_SMILES: ["SMILES를 해석할 수 없습니다.", "분자 표기와 괄호, 고리 번호를 확인한 뒤 다시 실행해 주세요."],
  UNSUPPORTED_SEQUENCE: ["지원하지 않는 서열 형식입니다.", "FASTA 헤더를 제거하고 표준 아미노산 20종으로 된 단일 서열을 입력해 주세요."],
  UNSUPPORTED_SMILES_TOKEN: ["이 모델이 지원하지 않는 SMILES 표기입니다.", "입체화학 기호 등을 자동으로 제거하지 않습니다. 해당 표기를 지원하는 모델이 필요합니다."],
  INPUT_TOO_LONG: ["모델의 입력 크기를 초과했습니다.", "모델별 입력 제한을 확인해 주세요. 분자나 단백질을 자동으로 절단하지 않습니다."],
  GRAPH_ENCODING_FAILED: ["약물 그래프 변환에 실패했습니다.", "그래프 특징을 확인할 수 없어 이 모델의 예측을 중단했습니다."],
  UNSUPPORTED_MOLECULE: ["지원하지 않는 분자 형식입니다.", "염이나 여러 분자 조각, 와일드카드 원자는 현재 어댑터에서 지원하지 않습니다."],
  DEVICE_UNAVAILABLE: ["이 모델의 실행 환경에서 선택한 장치를 사용할 수 없습니다.", "실행 장치를 ‘자동’으로 바꾸어 다시 실행하세요. CNN·MPNN·ConPLex는 CPU, Boltz-2는 GPU를 사용합니다. GPU 강제 실행에는 각 모델 환경의 CUDA 지원이 필요합니다."],
  INFERENCE_TIMEOUT: ["모델 실행 시간 제한에 도달했습니다.", "모델별 로그에서 진행 상태와 입력 크기, 실행 장치를 확인해 주세요."],
  RUNTIME_NOT_READY: ["모델 실행 환경이 준비되지 않았습니다.", "아래 모델 준비 상태와 오류의 설치 안내를 확인해 주세요."],
  DEPENDENCY_MISSING: ["모델 실행에 필요한 환경이 없습니다.", "아래 모델 준비 상태와 해당 모델의 설치 안내를 확인해 주세요."],
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
// Native dialogs keep keyboard focus inside the explanation and restore it on close.
function openModal(title, nodes) {
  const dialog = $("info-modal");
  dialog.classList.remove("graph-modal", "profile-modal");
  $("modal-title").textContent = title;
  $("modal-body").replaceChildren(...nodes.map(node => node.cloneNode(true)));
  if (!dialog.open) dialog.showModal();
}
function modalAction(title, nodes, label = title) {
  const button = element("button", label, "modal-action");
  button.type = "button";
  button.setAttribute("aria-haspopup", "dialog");
  button.addEventListener("click", () => openModal(title, typeof nodes === "function" ? nodes() : nodes));
  return button;
}
function convertDisclosures(root = document) {
  for (const detail of root.querySelectorAll("details")) {
    const summary = detail.querySelector("summary");
    if (!summary) continue;
    const wrapper = element("div");
    for (const attr of detail.attributes) if (attr.name !== "open") wrapper.setAttribute(attr.name, attr.value);
    wrapper.classList.add("modal-disclosure");
    // Keep source content addressable for the example picker without displaying it inline.
    const content = element("div"); content.hidden = true;
    content.append(...[...detail.childNodes].filter(node => node !== summary));
    wrapper.append(modalAction(summary.textContent, () => [...content.childNodes]));
    wrapper.append(content);
    detail.replaceWith(wrapper);
  }
}
function scoreMeaning(prediction) {
  if (prediction.scale === "cosine_similarity") return {
    name: "벡터 간 유사도", endpoint: "약물–단백질 상호작용 점수",
    text: "약물과 단백질의 특징 벡터가 얼마나 비슷한 방향인지 나타냅니다. 코사인 유사도이며, 농도 단위나 결합 확률이 아닙니다.",
  };
  if (prediction.scale === "upstream_log_affinity") return {
    name: "로그 친화도 · 원시 점수", endpoint: "정확한 실험 지표 미확인",
    text: "원본 모델이 반환한 로그 척도의 친화도 점수입니다. upstream은 원본 모델에서 온 값이라는 뜻입니다. 이 체크포인트가 Kd·Ki·IC50 중 무엇을 예측하는지와 정확한 변환식이 확인되지 않아 nM 농도나 결합 확률로 환산할 수 없습니다.",
  };
  if (/ic50/i.test(`${prediction.scale} ${prediction.endpoint}`)) return {
    name: "IC50의 상용로그 · µM 기준", endpoint: "IC50 · 50% 억제 농도",
    text: "IC50는 측정 대상의 활성을 50% 억제하는 데 필요한 농도입니다. 이 출력은 µM 단위의 IC50에 log10을 취한 모델 예측값입니다. 예를 들어 −2는 0.01 µM(10 nM)에 해당합니다. 낮을수록 더 낮은 농도에서 억제한다는 의미이며, Kd와는 다른 지표입니다.",
  };
  return {name: prediction.scale || "척도 미확인", endpoint: prediction.endpoint || "예측 대상 미확인", text: "이 출력의 척도와 예측 대상은 원시 결과 JSON에서 확인하세요. 확인되지 않은 단위로 환산하지 않습니다."};
}
function methodLink(model, label) {
  const method = modelMethods[model];
  if (!method) return null;
  const link = element("a", label, "method-link");
  link.href = `#${method.id}`;
  link.addEventListener("click", (event) => {
    event.preventDefault();
    const detail = $(method.id);
    detail.querySelector("button").click();
  });
  return link;
}
function renderMethods() {
  const table = $("methods-table-body"), explanations = $("methods-explanations");
  table.replaceChildren(); explanations.replaceChildren();
  for (const [model, method] of Object.entries(modelMethods)) {
    const row = element("tr"), name = element("th"); name.scope = "row";
    name.append(methodLink(model, method.name), element("small", method.category));
    row.append(name);
    for (const value of [method.drug, method.protein, method.structure, method.output]) row.append(element("td", value));
    table.append(row);
    const detail = element("details", undefined, "method-explanation"); detail.id = method.id; detail.tabIndex = -1;
    detail.append(element("summary", `${method.name} · 방법 자세히`), element("p", method.explanation), element("p", method.limit, "method-limit"));
    const source = element("a", "공식 문서·구현 ↗", "method-link");
    source.href = method.source; source.target = "_blank"; source.rel = "noopener noreferrer";
    detail.append(source); explanations.append(detail);
    if (location.hash === `#${method.id}`) detail.open = true;
  }
}
function time(value) { return new Date(value).toLocaleTimeString("ko-KR", {hour12: false}); }
function eventVisual(name) {
  if (name === "route.selected") return {tone: "completed", icon: "M5 12l4 4L19 6", label: "모델 추천"};
  if (name.endsWith("failed")) return {tone: "failed", icon: "M6 6l12 12M18 6L6 18", label: "실패"};
  if (name.endsWith("partial")) return {tone: "partial", icon: "M12 8v5m0 3h.01M12 3L2 21h20Z", label: "일부 완료"};
  if (name.endsWith("completed")) return {tone: "completed", icon: "M5 12l4 4L19 6", label: "완료"};
  if (name.endsWith("started")) return {tone: "started", icon: "M8 5l11 7-11 7Z", label: "시작"};
  if (name === "skill.loaded") return {tone: "loaded", icon: "M4 4h6l2 2 2-2h6v15h-6l-2 2-2-2H4ZM12 6v15", label: "스킬 로드"};
  return {tone: "received", icon: "M12 3v12m-5-5 5 5 5-5M4 15v6h16v-6", label: "요청 접수"};
}
function eventIcon(visual) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [key, value] of Object.entries({viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", class: "event-icon"})) svg.setAttribute(key, value);
  const path = document.createElementNS(svg.namespaceURI, "path"); path.setAttribute("d", visual.icon); svg.append(path);
  return svg;
}
function renderTraceSummary(run) {
  const route = document.querySelector(".trace-route"); route.replaceChildren();
  document.querySelector(".trace-panel .section-heading").insertBefore(route, $("download-events"));
  route.classList.add("trace-progress"); route.setAttribute("aria-label", "실행 단계별 상태");
  const steps = [["요청", "request"], ...(run.use_skill ? [["스킬", "skill"]] : []), ["예측 도구", "tool"], ["결과", "run"]];
  if (run.events.some(e => e.component === "profiler")) steps.splice(steps.length - 2, 0, ["입력 검사", "profile"]);
  for (const [label, prefix] of steps) {
    const events = run.events.filter(event => event.event.startsWith(`${prefix}.`));
    const last = events.at(-1);
    const visual = last ? eventVisual(last.event) : {tone: "waiting", icon: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0", label: "대기"};
    const step = element("span", undefined, `trace-step tone-${visual.tone}`);
    step.append(eventIcon(visual), element("span", `${label} · ${visual.label}`)); route.append(step);
  }
  const graphButton = element("button", `${sourceNames[run.source] || run.source} → 호출 그래프`, "call-graph-button");
  graphButton.type = "button"; graphButton.setAttribute("aria-haspopup", "dialog");
  graphButton.addEventListener("click", () => showCallGraph(run)); route.append(graphButton);
}
let graphEvidence = new Map();
let graphEdges = [];
window.addEventListener("resize", () => drawCallEdges(graphEdges));
function runLabel(run) {
  const request = run.request || {};
  const smiles = typeof request.smiles === "string" ? request.smiles.trim() : "";
  const protein = typeof request.protein_sequence === "string" ? request.protein_sequence.replace(/\s/g, "").toUpperCase() : "";
  const example = [...exampleLibrary.values()].find(item => item.input.smiles === smiles && item.input.protein_sequence.replace(/\s/g, "").toUpperCase() === protein);
  return example ? example.label : `직접 입력${protein ? ` · ${protein.length} aa` : ""}`;
}
function requestedModelNames(run) {
  const request = run.request || {};
  const names = Array.isArray(request.models) ? request.models : [request.model ?? request.models ?? "CNN_CNN_BindingDB"];
  return names.filter(name => typeof name === "string");
}
function showCallGraph(run) {
  const graph = element("div", undefined, "call-graph");
  const viewport = element("div", undefined, "call-graph-viewport");
  viewport.tabIndex = 0; viewport.setAttribute("role", "region"); viewport.setAttribute("aria-label", "호출 관계 그래프 · 가로로 이동할 수 있습니다");
  const canvas = element("div", undefined, "call-graph-canvas");
  const evidence = new Map(), edges = [];
  const columns = Array.from({length: 5}, () => element("div", undefined, "call-column"));
  const waiting = {tone: "waiting", icon: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0", label: "미호출"};
  function node(id, column, title, role, events, extra = "", status) {
    const last = events.at(-1), visual = status || (last ? eventVisual(last.event) : waiting);
    const button = element("button", undefined, `call-node tone-${visual.tone}`);
    button.type = "button"; button.dataset.graphNode = id; button.setAttribute("aria-pressed", "false");
    button.append(element("small", role), element("strong", title));
    const stateLabel = element("span", undefined, "call-node-state"); stateLabel.append(eventIcon(visual), element("span", visual.label)); button.append(stateLabel);
    if (extra) button.append(element("small", extra));
    button.setAttribute("aria-label", `${title} · ${role} · ${visual.label} · 관련 로그 보기`);
    evidence.set(id, {title, role, events, extra}); columns[column].append(button);
  }
  const matching = prefix => run.events.filter(event => event.event.startsWith(`${prefix}.`));
  const requests = matching("request"), tools = matching("tool"), skill = matching("skill");
  node("source", 0, sourceNames[run.source] || run.source, "요청자", requests);
  node("workflow", 1, "로컬 워크플로", "실행 조율", run.events.filter(event => /^(request|workflow|run)\./.test(event.event)));
  edges.push(["source", "workflow", requests.length ? "요청" : "요청 경로", !requests.length]);
  if (skill.length) {
    node("skill", 1, "predict-dta", "참조 지침", skill);
    edges.push(["workflow", "skill", "문서 로드", true]);
  }
  node("tool", 2, "predict_dta", "실행 도구", tools);
  if (matching("route").length) {
    node("router", 2, "모델 라우터", "모델 선택", matching("route"));
    edges.push(["workflow", "router", "추천 계획 사용", false]);
  }
  if (matching("profile").length) {
    node("profile", 2, "입력 프로파일", "입력 검사", matching("profile"));
    edges.push(["workflow", "profile", "프로파일 생성", false]);
  }
  edges.push(["workflow", "tool", tools.length ? "호출" : "호출 전", !tools.length]);
  const requested = requestedModelNames(run);
  const names = [...new Set([...requested, ...matching("model").map(event => event.details?.model).filter(Boolean)])];
  for (const [index, name] of names.entries()) {
    const events = matching("model").filter(event => event.details?.model === name);
    node(`model-${index}`, 3, modelMethods[name]?.name || name, "모델 · 순차 실행", events, events.at(-1)?.details?.elapsed_seconds != null ? `${events.at(-1).details.elapsed_seconds.toFixed(2)}초` : "");
    edges.push(["tool", `model-${index}`, events.length ? "모델 호출" : "선택됨 · 미호출", !events.length]);
    edges.push([`model-${index}`, "result", "출력", !events.some(event => /\.(completed|failed)$/.test(event.event))]);
  }
  node("result", 4, "예측 결과", "결과", matching("run"), run.result?.summary ? `${run.result.summary.succeeded}개 성공 · ${run.result.summary.failed}개 실패` : "", run.result ? undefined : {...waiting, label: "결과 대기"});
  canvas.append(...columns); viewport.append(canvas);
  const legend = element("div", undefined, "graph-legend");
  legend.append(element("span", "호출", "legend-call"), element("span", "참조·대기", "legend-reference"), element("span", "모델은 순차 실행"));
  graph.append(element("p", `${runLabel(run)} · ${date(run.created_at)} · 모델 ${names.length}개 · ${statusNames[run.status] || run.status}`, "graph-meta"), viewport,
    legend, element("p", "노드를 선택하면 상세 로그를 볼 수 있습니다.", "graph-intro"), element("div", undefined, "graph-evidence"));
  graphEvidence = evidence;
  graphEdges = edges;
  openModal("호출 흐름", [graph]);
  $("info-modal").classList.add("graph-modal");
  requestAnimationFrame(() => drawCallEdges(edges));
  setTimeout(() => { if (graphEdges === edges) drawCallEdges(edges); }, 260);
}
function drawCallEdges(edges) {
  const canvas = document.querySelector("#modal-body .call-graph-canvas"); if (!canvas) return;
  canvas.querySelector("svg.call-edges")?.remove();
  const rect = canvas.getBoundingClientRect();
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "call-edges"); svg.setAttribute("aria-hidden", "true"); svg.setAttribute("viewBox", `0 0 ${rect.width} ${rect.height}`);
  for (const [from, to, label, dashed] of edges) {
    const a = canvas.querySelector(`[data-graph-node="${from}"]`).getBoundingClientRect();
    const b = canvas.querySelector(`[data-graph-node="${to}"]`).getBoundingClientRect();
    const vertical = from === "workflow" && to === "skill";
    const x1 = (vertical ? a.left + a.width / 2 : a.right) - rect.left, y1 = (vertical ? a.bottom : a.top + a.height / 2) - rect.top;
    const x2 = (vertical ? b.left + b.width / 2 : b.left) - rect.left, y2 = (vertical ? b.top : b.top + b.height / 2) - rect.top;
    const path = document.createElementNS(svg.namespaceURI, "path");
    path.setAttribute("d", vertical ? `M${x1},${y1}V${y2}` : `M${x1},${y1}H${(x1+x2)/2}V${y2}H${x2}`);
    path.setAttribute("class", dashed ? "planned-edge" : "recorded-edge");
    const title = document.createElementNS(svg.namespaceURI, "title"); title.textContent = label; path.append(title); svg.append(path);
    const arrow = document.createElementNS(svg.namespaceURI, "path");
    arrow.setAttribute("d", vertical ? `M${x2-3},${y2-5}l3 5 3-5` : `M${x2-5},${y2-3}l5 3-5 3`); svg.append(arrow);
  }
  canvas.prepend(svg);
}
function date(value) { return new Date(value).toLocaleString("ko-KR", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false}); }
async function api(path, options, onResponse) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  onResponse?.(response);
  return data;
}

const profileRules = {
  protein_residues: "서열 길이", smiles_characters: "SMILES 길이", unsupported_smiles_tokens: "지원하지 않는 문자",
  atoms: "원자 수", directed_bond_slots: "방향성 결합 슬롯", neighbors: "원자당 최대 이웃 수",
  heavy_atoms: "중원자 수", atoms_after_remove_hs: "수소 제거 후 원자 수", recommended_ligand_atoms: "권장 원자 수",
};
function profileModelNodes(profile) {
  const nodes = [];
  const models = Object.entries(profile.models || {});
  if (models.length) {
    const list = element("ul");
    for (const [id, model] of models) {
      const issues = [...model.checks, ...model.warnings];
      const detail = issues.map(check => {
        if (check.rule === "chirality_blind_fingerprint") return "분자 지문이 입체화학을 구별하지 않음";
        const value = Array.isArray(check.observed) ? (check.observed.join(" ") || "없음") : check.observed;
        return (profileRules[check.rule] || check.rule) + " " + value + (check.maximum != null ? " / 상한 " + check.maximum : "");
      });
      const row = element("li");
      row.append(element("strong", (modelLabels[id] || id) + " · " + ({pass: "통과", warn: "주의", fail: "입력 미지원"}[model.status])));
      if (detail.length) row.append(element("div", detail.join(" · ")));
      const stages = {supervised: "지도학습", protein_pretraining: "단백질 사전학습", structure_training: "구조 학습"};
      const overlap = {seen: "관측", not_seen: "미관측", unknown: "미확인"};
      for (const [stage, audit] of Object.entries(model.training)) {
        if (audit.lookup_status === "queried") {
          row.append(element("div", stages[stage] + " 목록 · 분자 " + overlap[audit.overlap.compound] +
            " · 단백질 " + overlap[audit.overlap.protein] + " · 쌍 " + overlap[audit.overlap.pair], "field-hint"));
        }
      }
      list.append(row);
    }
    nodes.push(element("h3", "모델별 입력 조건"), list);
    const stages = models.flatMap(([, model]) => Object.values(model.training));
    const checked = stages.filter(stage => stage.lookup_status === "queried").length;
    const failed = stages.filter(stage => stage.lookup_status === "failed").length;
    nodes.push(element("p", (checked ? "학습 목록 " + checked + "건 대조 완료." : "대조한 학습 목록 없음.") +
      (failed ? " 목록 조회 실패 " + failed + "건." : "") + " 학습 분포 이탈 여부는 미평가입니다.", "field-hint"));
  }
  return nodes;
}
async function showProfile(path, options, complexUrl) {
  openModal("입력 프로파일", [element("p", "입력을 확인하고 있습니다…")]);
  const pending = $("modal-body").firstElementChild;
  try {
    const profile = await api(path, options);
    if (!pending.isConnected || !$("info-modal").open) return;
    openProfileSnapshot(profile, complexUrl);
  } catch (error) {
    if (pending.isConnected) pending.textContent = "프로파일을 열 수 없습니다. " + error.message;
  }
}
function countInputs() {
  const smilesLength = $("smiles").value.trim().length;
  const proteinLength = $("protein").value.replace(/\s/g, "").length;
  const selected = [...chosenModels].map(name => modelCatalog.get(name)).filter(Boolean);
  const smilesLimits = selected.map(item => item.limits?.smiles_characters).filter(Number.isFinite);
  const proteinLimits = selected.map(item => item.limits?.protein_residues).filter(Number.isFinite);
  $("smiles-count").textContent = `${smilesLength.toLocaleString()}자`;
  $("protein-count").textContent = `${proteinLength.toLocaleString()} aa`;
  $("smiles-count").classList.toggle("over-limit", smilesLimits.some(limit => smilesLength > limit));
  $("protein-count").classList.toggle("over-limit", proteinLimits.some(limit => proteinLength > limit));
  $("smiles-hint").textContent = chosenModels.has("CNN_CNN_BindingDB")
    ? "단일 분자 · CNN은 최대 100자 및 일부 입체화학 표기 미지원 · 제한은 모델별로 검사"
    : "단일 분자 · 원본 SMILES를 유지하며 모델별 입력 제한을 검사합니다.";
  $("protein-hint").textContent = "FASTA 헤더 없이 입력 · 표준 아미노산 20종 · 모델별 길이 제한 적용";
  $("model-selection-count").textContent = `· ${selected.length}개 선택`;
  $("model-selection-hint").textContent = chosenModels.has("Boltz2")
    ? "Boltz-2를 포함해 선택한 모델만 순차 실행합니다. 구조 예측은 오래 걸릴 수 있습니다."
    : "선택한 모델만 순차 실행합니다. Boltz-2는 별도로 선택하세요.";
  describeDevice();
}
function describeDevice() {
  const selected = [...chosenModels].map(name => modelCatalog.get(name)).filter(Boolean);
  const defaults = selected.map(item => `${item.model.split("_")[0]}: ${item.default_device === "cuda" ? "GPU" : "CPU"}`).join(" · ");
  const device = $("device-selection").value;
  $("device-hint").textContent = device === "auto"
    ? `자동 실행 — ${defaults || "모델별 권장 장치"}`
    : device === "cuda"
      ? "선택한 모든 모델에 GPU를 강제합니다. GPU가 있어도 각 모델 실행 환경에 CUDA 지원이 필요합니다. 여러 모델 비교에는 ‘자동’을 권장합니다."
      : "선택한 모든 모델을 CPU로 실행합니다. Boltz-2 구조 예측은 매우 오래 걸릴 수 있습니다.";
}
function inputLimits(item) {
  const limits = item.limits || {};
  const parts = [];
  if (Number.isFinite(limits.smiles_characters)) parts.push(`SMILES ≤${limits.smiles_characters}자`);
  if (Number.isFinite(limits.atoms)) parts.push(`원자 ≤${limits.atoms}`);
  if (Number.isFinite(limits.heavy_atoms)) parts.push(`리간드 중원자 ≤${limits.heavy_atoms}`);
  if (Number.isFinite(limits.protein_residues)) parts.push(`단백질 ≤${limits.protein_residues.toLocaleString()} aa`);
  if (item.default_device) parts.push(`자동: ${item.default_device === "cuda" ? "GPU" : item.default_device.toUpperCase()}`);
  return parts.join(" · ");
}
function renderModelChoices() {
  const list = $("model-selection"); list.replaceChildren();
  for (const item of modelCatalog.values()) {
    const row = element("label", undefined, "model-option");
    const checkbox = element("input"); checkbox.type = "checkbox"; checkbox.name = "models"; checkbox.value = item.model;
    checkbox.checked = chosenModels.has(item.model); checkbox.defaultChecked = defaultModels.includes(item.model);
    checkbox.addEventListener("change", () => {
      if ($("route-purpose").value) resetRouting();
      if (checkbox.checked) chosenModels.add(item.model); else chosenModels.delete(item.model);
      clearRunView(); countInputs(); renderPlan();
    });
    const text = element("span", undefined, "model-option-text");
    const heading = element("span", undefined, "model-option-heading");
    const ready = item.checkpoint?.status === "ready";
    heading.append(element("strong", modelMethods[item.model]?.name || item.display_name || item.model),
      element("span", ready ? "준비됨" : "준비 필요", `model-availability ${ready ? "ready" : ""}`));
    text.append(heading, element("small", item.description || inputLimits(item)));
    if (!ready) text.append(element("small", item.checkpoint?.message || "모델 준비 상태를 확인하세요.", "model-unavailable"));
    row.append(checkbox, text); list.append(row);
  }
  if (!modelCatalog.size) list.append(element("p", "사용 가능한 모델 목록이 없습니다.", "field-hint"));
  countInputs(); renderPlan();
}
function note(message, error = false) {
  $("form-note").textContent = message;
  $("form-note").classList.toggle("error", error);
}
function setBusy(busy) {
  state.busy = busy;
  $("submit").disabled = busy;
  $("submit").replaceChildren(document.createTextNode(busy ? "예측 실행 중" : "예측 실행"), element("span", busy ? "…" : "↗"));
}
function setDownload(id, run, kind, enabled) {
  const link = $(id);
  link.hidden = !enabled;
  if (enabled) link.href = `/api/runs/${run.run_id}/download/${kind}`;
  else link.removeAttribute("href");
}
function renderModelResult(result, runId) {
  const box = element("section", undefined, "model-result");
  const heading = element("div", undefined, "model-result-heading");
  const model = result.requested_model || result.model?.model || "CNN_CNN_BindingDB";
  heading.append(element("strong", modelMethods[model]?.name || model),
    element("span", statusNames[result.status] || result.status, `pill ${result.status}`));
  box.append(heading);
  if (result.status === "error") {
    const code = result.error.code;
    const [title, resolution] = fixes[code] || ["예측을 완료하지 못했습니다.", "입력과 실행 환경을 확인한 뒤 다시 실행해 주세요."];
    const error = element("div", undefined, "error-result");
    error.append(element("code", code), element("h3", title), element("p", result.error.message), element("p", resolution, "resolution"));
    box.append(error);
    return box;
  }
  const prediction = result.prediction || {};
  const isInteractionScore = result.task === "DTI" || prediction.scale === "cosine_similarity" || result.requested_model === "ConPLex_v1_BindingDB";
  const rawValue = prediction.raw_value;
  box.append(element("p", isInteractionScore ? "약물–단백질 상호작용 점수" : "모델이 예측한 친화도 점수", "score-label"),
    element("div", typeof rawValue === "number" && Number.isFinite(rawValue) ? rawValue.toFixed(4) : "값 없음", "score"));
  const facts = element("dl", undefined, "result-facts");
  const seconds = result.execution?.elapsed_seconds;
  const meaning = scoreMeaning(prediction);
  const explanation = element("div", undefined, "score-explanation");
  explanation.append(element("strong", meaning.name), element("p", meaning.text),
    element("p", "예측 구간 미보정: 실제 오차를 검증해 만든 신뢰 범위를 아직 제공하지 않습니다. 점수는 실험 측정값이 아닙니다."), element("pre", JSON.stringify(prediction, null, 2)));
  const rows = [["점수 척도", meaning.name], ["예측 대상", meaning.endpoint],
    ["예측 구간", result.uncertainty?.status === "not_calibrated" ? "미보정 · 오차 범위 미제공" : result.uncertainty?.status || "미제공"],
    ["실행 장치", result.execution?.device || "미기록"],
    ["실행 시간", typeof seconds === "number" ? `${seconds.toFixed(2)} s` : "미기록"]];
  if (typeof prediction.higher_is_stronger === "boolean") rows.splice(2, 0, ["점수 방향", isInteractionScore
    ? "높을수록 상호작용 점수 큼"
    : prediction.higher_is_stronger ? "높을수록 강한 결합" : "낮을수록 강한 결합"]);
  const probability = prediction.binding_probability;
  if (typeof probability === "number" && Number.isFinite(probability)) rows.push(["모델의 binder 확률", `${(probability * 100).toFixed(2)}%`]);
  for (const [label, value] of rows) {
    const row = element("div"); row.append(element("dt", label), element("dd", value)); facts.append(row);
  }
  explanation.append(facts);
  if (modelMethods[model]) {
    const method = modelMethods[model];
    explanation.append(element("h3", "예측 방법"), element("p", method.explanation), element("p", method.limit));
  }
  if (isInteractionScore) explanation.append(element("p", "상호작용 점수이며 결합 확률이나 nM 값이 아닙니다.", "result-warning"));
  if (typeof probability === "number") explanation.append(element("p", "Binder 확률은 이 모델의 출력입니다. 이 프로젝트에서 독립적인 확률 보정을 검증하지 않았으며, affinity 예측 구간과 다릅니다.", "result-warning"));
  box.append(modalAction(`${modelMethods[model]?.name || model} · 점수 해석`, [explanation], "점수 해석"));
  box.append(element("span", `${result.execution?.device || "장치 미기록"} · ${typeof seconds === "number" ? `${seconds.toFixed(1)}초` : "시간 미기록"}`, "execution-inline"));
  const warnings = result.quality?.warnings || [];
  if (warnings.length) {
    const details = element("section", undefined, "result-details");
    details.append(element("h3", `해석·입력 주의점 (${warnings.length})`));
    const list = element("ul"); for (const warning of warnings) list.append(element("li", String(warning)));
    details.append(list); explanation.append(details);
  }
  const structure = result.quality?.structure_confidence || result.quality?.structural_confidence;
  if (structure) {
    const details = element("section", undefined, "result-details");
    details.append(element("h3", "구조 예측 품질"), element("p", "구조 confidence는 결합 확률이나 affinity의 예측 구간이 아닙니다."),
      element("pre", JSON.stringify(structure, null, 2)));
    explanation.append(details);
  }
  if (model === "Boltz2" && result.artifacts?.complex_cif) {
    const button = element("button", "복합체 3D 보기", "modal-action complex-action");
    button.type = "button"; button.setAttribute("aria-haspopup", "dialog");
    button.addEventListener("click", () => showRunComplex(runId));
    box.append(button);
  }
  return box;
}
function showRun(run) {
  if (flow.run?.run_id === run.run_id && (flow.run.events.length > run.events.length || (flow.run.result && !run.result))) return;
  const elapsed = Math.max(0, Math.floor((Date.now() - new Date(run.started_at || run.created_at).getTime()) / 1000));
  const duration = $("run-duration");
  if (duration) duration.textContent = `경과 ${Math.floor(elapsed / 60)}분 ${elapsed % 60}초 · 모델별 로그를 확인하세요.`;
  const signature = `${run.run_id}:${run.status}:${run.events.length}:${Boolean(run.result)}`;
  if (signature === state.signature) return;
  state.signature = signature; flow.run = run; renderExecution();
  if (["execution", "results"].includes(flow.stage)) goToStage(flow.stage, false);
  const badge = $("result-status");
  badge.textContent = statusNames[run.status] || run.status;
  badge.className = `pill ${run.status}`;
  $("run-meta").textContent = `${runLabel(run)} · ${date(run.created_at)} · ${sourceNames[run.source] || run.source}`;
  const body = $("result-content");
  body.replaceChildren();
  const result = run.result;
  if (!result) {
    const box = element("div", undefined, "pending-result");
    const clock = element("p", `경과 ${Math.floor(elapsed / 60)}분 ${elapsed % 60}초 · 모델별 로그를 확인하세요.`, "run-duration"); clock.id = "run-duration";
    box.append(element("h3", run.status === "queued" ? "실행을 기다리고 있습니다." : "선택한 모델을 실행하고 있습니다."), element("p", "구조·단백질 임베딩 계산은 수 분 이상 걸릴 수 있습니다. 결과가 준비되면 자동으로 표시됩니다."), clock);
    body.append(box);
  } else if (Array.isArray(result.results)) {
    body.append(element("p", `${result.summary.succeeded}개 성공 · ${result.summary.failed}개 실패`, "comparison-summary"));
    const grid = element("div", undefined, "result-grid");
    for (const item of result.results) grid.append(renderModelResult(item, run.run_id));
    body.append(grid, element("p", "각 점수는 해당 모델의 척도로 표시됩니다. 예측 구간은 미보정 상태입니다.", "result-warning"));
  } else if (result.status === "error") {
    const code = result.error.code;
    const [title, resolution] = fixes[code] || ["예측을 완료하지 못했습니다.", "입력과 실행 환경을 확인한 뒤 다시 실행해 주세요."];
    const box = element("div", undefined, "error-result");
    box.append(element("code", result.requested_model || "predict_dta"), element("code", code), element("h3", title), element("p", result.error.message), element("p", resolution, "resolution"));
    body.append(box);
  } else {
    body.append(renderModelResult(result, run.run_id), element("p", "모델 예측값 · 예측 구간 미보정", "result-warning"));
  }
  const inputs = element("details", undefined, "input-receipt");
  inputs.append(element("summary", "이 실행의 입력 확인"));
  const request = run.request || {};
  const requestedModels = requestedModelNames(run);
  inputs.append(element("pre", `Models\n${requestedModels.join(", ")}\n\nDevice\n${request.device || "cpu"}\n\nSMILES\n${request.smiles ?? ""}\n\nProtein sequence\n${request.protein_sequence ?? ""}`));
  body.append(inputs);
  if (run.events.some(event => event.component === "profiler")) {
    const saved = element("button", "저장된 입력 프로파일", "modal-action");
    saved.type = "button"; saved.setAttribute("aria-haspopup", "dialog");
    const hasComplex = (result?.results || [result]).some(item => item?.artifacts?.complex_cif);
    saved.addEventListener("click", () => showProfile("/api/runs/" + run.run_id + "/download/profile", undefined,
      hasComplex ? "/api/runs/" + run.run_id + "/complex.cif" : null));
    body.append(saved);
  }
  setDownload("download-result", run, "result", Boolean(result));
  if (run.events.some(e => e.event === "route.selected")) {
    body.append(profileLink("모델 선택 근거 JSON", "/api/runs/" + run.run_id + "/download/route", "routing.json"));
  }
  setDownload("download-events", run, "events", true);
  renderTraceSummary(run);
  $("event-count").textContent = `${run.events.length}개 · 최신순`;
  const list = $("events");
  list.replaceChildren();
  for (const event of [...run.events].reverse()) {
    const visual = eventVisual(event.event);
    const row = element("div", undefined, `event tone-${visual.tone} ${event.event.endsWith("failed") ? "error" : ""}`);
    const stamp = element("time", time(event.timestamp)); stamp.dateTime = event.timestamp;
    const modelName = modelMethods[event.details?.model]?.name || event.details?.model;
    const modelMessage = modelName && event.event.startsWith("model.")
      ? `${modelName} · ${visual.label}${event.event.endsWith("started") ? " — 예측을 계산하고 있습니다." : ""}` : event.message;
    const message = element("p", modelMessage);
    const errorCode = event.details?.error_code;
    if (event.event.endsWith("failed") && errorCode) {
      const help = fixes[errorCode];
      message.append(element("br"), element("strong", errorCode));
      if (help) message.append(element("br"), document.createTextNode(`${help[0]} ${help[1]}`));
      else if (event.details.error_message) message.append(element("br"), document.createTextNode(event.details.error_message));
    }
    const identity = element("span", undefined, "event-identity");
    const component = {model: "모델", profile: "입력 검사", tool: "도구", run: "실행", worker: "작업", workflow: "워크플로"}[event.event.split(".")[0]];
    identity.append(eventIcon(visual), element("span", component ? `${component} ${visual.label}` : visual.label, "event-name"));
    identity.title = event.event;
    row.append(stamp, identity, message, modalAction(`${event.event} · ${time(event.timestamp)}`, [element("p", event.message), element("pre", JSON.stringify(event, null, 2))], "상세"));
    list.append(row);
  }
}
function renderHistory(runs) {
  const signature = JSON.stringify(runs.map(r => [r.run_id, r.status])) + state.selected;
  if (signature === state.historySignature) return;
  state.historySignature = signature;
  latestRuns = runs; paintRunLists(); loadRunSummaries();
}
async function selectRun(runId, loadInput = false) {
  if ($("history-sidebar").open) $("history-sidebar").close();
  flow.revision++;
  state.selected = runId; state.signature = "";
  try {
    const run = await api(`/api/runs/${runId}`);
    if (state.selected !== runId) return;
    if (loadInput && run.request) {
      $("smiles").value = run.request.smiles || "";
      $("protein").value = run.request.protein_sequence || "";
      syncExampleWithInput();
      chosenModels = new Set(requestedModelNames(run));
      $("device-selection").value = ["auto", "cpu", "cuda"].includes(run.request.device) ? run.request.device : "cpu";
      renderModelChoices(); changedPair(true, true);
      countInputs(); note("선택한 실행의 입력입니다. 수정하여 다시 실행할 수 있습니다.");
    }
    showRun(run);
    goToStage(loadInput && run.result ? "results" : "execution");
  } catch (error) {
    if (state.selected === runId) { note(error.message, true); goToStage("models"); }
  }
}
async function refreshHealth() {
  try {
    const data = await api("/api/status");
    const models = Array.isArray(data.models) ? data.models : [];
    const signature = JSON.stringify(models.map(item => [item.model, item.display_name, item.description, item.limits, item.default_device, item.checkpoint?.status, item.checkpoint?.code, item.checkpoint?.message]));
    modelCatalog.clear(); for (const item of models) modelCatalog.set(item.model, item);
    if (signature !== modelCatalogSignature) { modelCatalogSignature = signature; renderModelChoices(); }
    const list = $("model-state"), setup = $("setup-command");
    list.replaceChildren(); setup.replaceChildren(); setup.hidden = true;
    for (const item of models) {
      const ready = item.checkpoint?.status === "ready";
      list.append(element("p", `${item.model}: ${ready ? "파일 검증 완료 · 실제 로딩은 실행 시 확인" : item.checkpoint?.message || "준비가 필요합니다."}`));
      if (!ready) {
        setup.hidden = false;
        setup.append(element("code", item.setup_command || `.venv\\Scripts\\python.exe -m dti_tool prepare-model --model ${item.model}`));
        if (item.source_url) {
          const link = element("a", `${item.model} 공식 출처`, "download");
          link.href = item.source_url; link.target = "_blank"; link.rel = "noopener noreferrer";
          setup.append(link);
        }
      }
    }
  } catch (error) { $("model-state").textContent = "서버에 연결하지 못했습니다. 서버 실행 상태를 확인해 주세요."; }
}
async function poll() {
  if (state.polling) return;
  state.polling = true;
  try {
    const {runs} = await api("/api/runs");
    $("connection").textContent = "로컬 연결됨"; $("connection").className = "connection online";
    renderHistory(runs);
    const selected = state.selected;
    if (selected && (flow.run?.run_id !== selected || !flow.run?.result)) {
      const run = await api(`/api/runs/${selected}`);
      if (state.selected === selected) showRun(run);
    }
    if (state.submitted) {
      const submitted = runs.find(run => run.run_id === state.submitted);
      if ((submitted && ["success", "partial", "error"].includes(submitted.status)) || (state.submitted === flow.run?.run_id && flow.run?.result)) {
        if (state.selected === state.submitted) {
          const status = (submitted || flow.run).status;
          note(status === "success" ? "결과와 로그를 저장했습니다." : status === "partial" ? "일부 모델이 완료되었습니다. 각 모델의 결과와 오류를 확인하세요." : "실행이 끝났습니다. 결과에서 오류 원인을 확인하세요.");
        }
        setBusy(false); state.submitted = null;
      }
    }
  } catch (error) {
    $("connection").textContent = "서버 연결 끊김"; $("connection").className = "connection";
    if (state.busy) note("서버 연결을 확인하고 있습니다. 연결되면 실행 결과를 다시 조회합니다.", true);
  } finally { state.polling = false; }
}
$("smiles").addEventListener("input", () => { countInputs(); syncExampleWithInput(); changedPair(); });
$("protein").addEventListener("input", () => { countInputs(); syncExampleWithInput(); changedPair(); });
$("device-selection").addEventListener("change", () => { describeDevice(); clearRunView(); renderPlan(); });
function syncExampleWithInput() {
  if (!exampleLibrary.size) return;
  const smiles = $("smiles").value.trim();
  const sequence = $("protein").value.replace(/\s/g, "").toUpperCase();
  const match = [...exampleLibrary.values()].find(example => example.input.smiles === smiles
    && example.input.protein_sequence.replace(/\s/g, "").toUpperCase() === sequence);
  $("example-select").value = match ? match.id : "";
  describeExample();
}
function describeExample() {
  const example = exampleLibrary.get($("example-select").value);
  if (!example) {
    $("example-description").textContent = "SMILES와 단백질 서열을 직접 입력하거나 목록에서 예시를 선택하세요.";
    $("example-evidence").replaceChildren(); $("example-details").hidden = true;
    return;
  }
  $("example-description").textContent = `${example.target.organism} · ${example.target.accession} · 전체 서열 ${example.target.sequence_length} aa`;
  const evidence = $("example-evidence"); evidence.replaceChildren();
  evidence.append(element("p", example.note), element("p", "알려진 상호작용의 실행 예시입니다. 실험 affinity 정답이나 독립 성능 평가 데이터가 아닙니다."));
  const links = element("p", undefined, "example-links");
  for (const [label, url] of [["분자 · PubChem", example.compound.source_url], ["서열 · UniProt", example.target.source_url], ["상호작용 근거", example.evidence_url]]) {
    const link = element("a", label); link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer"; links.append(link);
  }
  evidence.append(links); $("example-details").hidden = false;
}
async function loadExamples() {
  try {
    const data = await api("/api/examples");
    const select = $("example-select"); select.replaceChildren();
    const custom = element("option", "직접 입력 / 저장된 실행"); custom.value = ""; custom.defaultSelected = true; select.append(custom);
    for (const example of data.examples) {
      exampleLibrary.set(example.id, example);
      const option = element("option", example.label); option.value = example.id; select.append(option);
    }
    if (!exampleLibrary.size) throw new Error("예시 목록이 비어 있습니다.");
    select.disabled = false;
    $("example-total").textContent = `· ${exampleLibrary.size}개`;
    if (!flow.edited && !$("smiles").value && !$("protein").value && exampleLibrary.has("aspirin-cox2")) {
      select.value = "aspirin-cox2"; select.dispatchEvent(new Event("change"));
    } else syncExampleWithInput();
    loadRunSummaries();
  } catch (error) {
    $("example-select").replaceChildren(element("option", "예시 목록을 불러오지 못했습니다"));
    $("example-description").textContent = "페이지를 새로고침하거나 직접 입력해 주세요.";
  }
}
$("example-select").addEventListener("change", () => {
  const example = exampleLibrary.get($("example-select").value);
  describeExample();
  if (!example) { $("smiles").value = ""; $("protein").value = ""; countInputs(); changedPair(); return; }
  $("smiles").value = example.input.smiles;
  $("protein").value = example.input.protein_sequence;
  countInputs(); changedPair(true);
});
$("new-run").addEventListener("click", () => {
  if ($("history-sidebar").open) $("history-sidebar").close();
  $("prediction-form").reset(); chosenModels = new Set(defaultModels); renderModelChoices(); describeDevice(); describeExample(); changedPair(); goToStage("input"); $("smiles").focus();
});
$("refresh").addEventListener("click", refreshHealth);
$("toggle-history").addEventListener("click", () => {
  $("history-sidebar").showModal(); loadRunSummaries();
});
$("prediction-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (flow.stage === "input") { $("next-models").click(); return; }
  if (state.busy || ($("route-purpose").value && flow.route?.action !== "execute")) return;
  const smiles = $("smiles").value, protein_sequence = $("protein").value;
  if (!smiles.trim() || !protein_sequence.trim()) { goToStage("input"); updateProfileStatus("화합물과 단백질 서열을 모두 입력하세요.", true); return; }
  const models = [...chosenModels].filter(name => modelCatalog.has(name));
  if (!models.length) return note("실행할 모델을 하나 이상 선택해 주세요.", true);
  if (flow.profile?.status === "error") { goToStage("input"); return; }
  const revision = flow.revision;
  setBusy(true); note("로컬 실행을 요청하고 있습니다.");
  try {
    const selection = models.length === 1 ? {model: models[0]} : {models};
    const headers = {"Content-Type":"application/json"};
    if ($("route-purpose").value && flow.routeToken) headers["X-Route-Token"] = flow.routeToken;
    const run = await api("/api/runs", {method: "POST", headers, body: JSON.stringify({smiles, protein_sequence, device: $("device-selection").value, ...selection})});
    state.submitted = run.run_id;
    if (revision !== flow.revision) { await poll(); return; }
    await selectRun(run.run_id); await poll();
  } catch (error) { setBusy(false); note(error.message, true); }
});
$("modal-close").addEventListener("click", () => $("info-modal").close());
$("modal-body").addEventListener("click", event => {
  const graphNode = event.target.closest("[data-graph-node]");
  if (graphNode) {
    const data = graphEvidence.get(graphNode.dataset.graphNode);
    const pane = $("modal-body").querySelector(".graph-evidence");
    if (data && pane) {
      for (const node of $("modal-body").querySelectorAll(".call-node")) node.setAttribute("aria-pressed", String(node === graphNode));
      pane.replaceChildren(element("h3", `${data.title} · ${data.role}`), element("p", data.extra || "기록된 이벤트를 시간순으로 표시합니다."));
      if (!data.events.length) pane.append(element("p", "이 노드의 실행 이벤트가 아직 없습니다."));
      for (const item of data.events) pane.append(element("p", `${time(item.timestamp)} · ${item.event} · ${item.message}`), element("pre", JSON.stringify(item.details, null, 2)));
      pane.setAttribute("role", "region"); pane.setAttribute("aria-label", `${data.title}의 근거 로그`);
    }
  }
  const link = event.target.closest('a[href^="#method-"]');
  if (link) { event.preventDefault(); document.querySelector(`${link.getAttribute("href")} button`)?.click(); }
  if (event.target.closest("#refresh")) refreshHealth();
});
$("info-modal").addEventListener("click", event => {
  if (event.target !== $("info-modal")) return;
  const rect = event.target.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.target.close();
});
$("info-modal").addEventListener("close", () => { document.body.classList.remove("modal-open"); });
new MutationObserver(() => {
  convertDisclosures();
  document.body.classList.toggle("modal-open", $("info-modal").open);
}).observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ["open"]});
renderMethods(); convertDisclosures(); initWorkflow(); countInputs(); loadExamples(); refreshHealth(); poll();
const tools = element("nav", undefined, "workbench-tools");
tools.setAttribute("aria-label", "워크벤치 안내");
document.querySelector(".bottom-row").hidden = true;
for (const [selector, title] of [["#model-methods", "모델별 예측 방법"], [".readiness", "모델 준비 상태"]]) {
  const panel = document.querySelector(selector);
  panel.hidden = true;
  tools.append(modalAction(title, () => [...panel.childNodes]));
}
tools.append(modalAction("에이전트 사용 안내", () => [...document.querySelector(".agent-help > div[hidden]").childNodes]));
document.querySelector(".rail-resources").append(tools);
const inputHelp = element("div");
inputHelp.append(modalAction("입력 안내", () => {
  const nodes = [...document.querySelectorAll("#smiles-hint, #protein-hint, #model-selection-hint, #device-hint")].map(node => element("p", node.textContent));
  for (const item of modelCatalog.values()) nodes.push(element("p", `${modelMethods[item.model]?.name || item.model}: ${inputLimits(item)}`));
  return nodes;
}));
document.querySelector(".input-panel .section-heading").append(inputHelp);
document.querySelector('a[href="#model-methods"]').addEventListener("click", event => {
  event.preventDefault(); openModal("모델별 예측 방법", [...$("model-methods").childNodes]);
});
setInterval(poll, 1200);
setInterval(refreshHealth, 30000);
