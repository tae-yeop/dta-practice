"use strict";

const flow = {stage: "input", pairKey: "", profile: null, request: null, timer: null, view: "protein", run: null, edited: false, revision: 0};
const stageCopy = {
  input: ["입력 프로파일", "분자 구조와 표적 서열을 확인하세요."],
  models: ["모델 선택", "예측하려는 값과 입력 조건을 보고 실행 순서를 확인하세요."],
  execution: ["실행 추적", "모델별 진행 상황과 실제 호출 기록을 확인하세요."],
  results: ["결과 해석", "각 모델의 예측값과 측정 대상, 해석 범위를 확인하세요."],
};
const recentSummaries = new Map();
let latestRuns = [], summaryBusy = false;

function runListButton(run, compact) {
  const summary = recentSummaries.get(run.run_id);
  const button = element("button", undefined, compact ? "recent-run" : "history-item");
  button.type = "button"; button.setAttribute("aria-pressed", String(run.run_id === state.selected));
  button.append(element("strong", summary?.name || (sourceNames[run.source] || run.source) + " 실행"),
    element("small", summary?.models ? "모델 " + summary.models + "개" : sourceNames[run.source] || run.source),
    element("time", date(run.created_at)), element("span", statusNames[run.status] || run.status, "pill " + run.status));
  button.addEventListener("click", () => selectRun(run.run_id, true));
  return button;
}

function paintRunLists() {
  for (const [id, rows] of [["recent-runs", latestRuns.slice(0, 3)], ["history", latestRuns]]) {
    const root = $(id), active = root.contains(document.activeElement) ? [...root.children].indexOf(document.activeElement) : -1;
    root.replaceChildren(...rows.map(run => runListButton(run, id === "recent-runs")));
    if (!rows.length) root.append(element("p", "저장된 실행이 없습니다.", "muted"));
    if (active >= 0) root.children[active]?.focus({preventScroll: true});
  }
}

async function loadRunSummaries() {
  if (summaryBusy || !exampleLibrary.size) return;
  summaryBusy = true;
  try {
    for (const [index, run] of latestRuns.entries()) {
      if (index >= 3 && !$("history-sidebar").open) break;
      if (recentSummaries.has(run.run_id)) continue;
      try {
        const record = await api("/api/runs/" + run.run_id);
        recentSummaries.set(run.run_id, {name: runLabel(record), models: requestedModelNames(record).length});
      } catch { continue; }
    }
    paintRunLists();
  } finally { summaryBusy = false; }
}

function updateStageNav() {
  const completed = {input: flow.profile?.status === "success", models: Boolean(flow.run),
    execution: Boolean(flow.run?.result), results: false};
  for (const [idx, button] of [...document.querySelectorAll("#stage-nav button")].entries()) {
    const stage = button.dataset.stage, current = stage === flow.stage;
    if (current) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
    button.classList.toggle("step-done", completed[stage]);
    const marker = button.querySelector(".step-number");
    marker.textContent = completed[stage] && !current ? "✓" : String(idx + 1);
    marker.setAttribute("aria-hidden", "true");
    button.setAttribute("aria-label", (idx + 1) + "단계 " + stageCopy[stage][0] + (completed[stage] ? " · 단계 완료" : ""));
  }
}

function goToStage(stage, focus = true) {
  flow.stage = stage;
  for (const pane of document.querySelectorAll("[data-pane]")) pane.hidden = pane.dataset.pane !== stage;
  updateStageNav();
  [$("stage-title").textContent, $("stage-description").textContent] = stageCopy[stage];
  if (flow.run && ["execution", "results"].includes(stage)) $("stage-description").textContent = runLabel(flow.run) + " · " + date(flow.run.created_at);
  if (stage === "models") renderPlan();
  if (focus) {
    $("stage-title").focus({preventScroll: true});
    window.scrollTo(0, 0);
  }
}

function draftPair() {
  return {smiles: $("smiles").value, protein_sequence: $("protein").value};
}

function renderSpecimen() {
  const body = $("preview-body"), profile = flow.profile;
  body.replaceChildren();
  $("view-protein").setAttribute("aria-pressed", String(flow.view === "protein"));
  $("view-drug").setAttribute("aria-pressed", String(flow.view === "compound"));
  $("preview-profile").disabled = !profile;
  if (!profile) {
    body.append(element("p", flow.request ? "입력 정보를 확인하고 있습니다…" : "화합물과 서열을 입력하거나 예시를 선택하세요.", "specimen-empty"));
    return;
  }
  const showProtein = flow.view === "protein";
  const entity = showProtein ? profile.protein : profile.compound;
  const match = profile.catalog?.[showProtein ? "protein" : "compound"]?.matches?.[0];
  const ref = profile.protein?.reference_structures?.records?.[0];
  const label = showProtein ? match?.name || "입력 단백질" : match?.name || "입력 화합물";
  const picture = element("div", undefined, "specimen-image");
  const img = element("img");
  if (showProtein && ref) {
    img.src = "/static/structures/" + encodeURIComponent(ref.pdb_id) + ".png";
    img.alt = label + " 실험 구조 · " + ref.pdb_id + " 사슬 " + ref.chain;
  } else if (!showProtein && entity?.structures?.depiction_png) {
    img.src = "data:image/png;base64," + entity.structures.depiction_png;
    img.alt = label + " 2D 구조식";
  }
  if (img.hasAttribute("src")) {
    img.addEventListener("error", () => picture.replaceChildren(element("p", "구조 이미지를 열 수 없습니다.")), {once: true});
    picture.append(img);
  } else picture.append(element("p", entity ? "연결된 구조 미리보기가 없습니다." : "입력 형식을 확인하세요."));
  const meta = element("div", undefined, "specimen-meta");
  meta.append(element("strong", label));
  if (entity) meta.append(element("span", showProtein
    ? [match?.organism, match?.accession, entity.length + " aa"].filter(Boolean).join(" · ")
    : [entity.formula, entity.molecular_weight_da.toFixed(2) + " Da"].join(" · ")));
  if (showProtein && ref) {
    const source = element("a", "PDB " + ref.pdb_id + " · " + ref.resolution_angstrom + " Å", "specimen-source");
    source.href = ref.source_url; source.target = "_blank"; source.rel = "noopener noreferrer"; picture.append(source);
  }
  body.append(picture, meta);
  $("preview-profile").textContent = entity ? "구조·프로파일 상세" : "입력 오류 상세";
}

function updateProfileStatus(message, isError = false) {
  $("input-feedback").textContent = message;
  $("input-feedback").classList.toggle("error", isError);
}

function loadDraftProfile() {
  clearTimeout(flow.timer);
  const pair = draftPair(), key = JSON.stringify(pair);
  if (!pair.smiles.trim() || !pair.protein_sequence.trim()) return Promise.resolve(null);
  if (key === flow.pairKey && flow.profile) return Promise.resolve(flow.profile);
  if (flow.request?.key === key) return flow.request.promise;
  flow.request?.controller.abort();
  const controller = new AbortController();
  const request = {key, controller};
  flow.request = request;
  renderSpecimen();
  request.promise = api("/api/profile", {method: "POST", headers: {"Content-Type": "application/json"},
    body: key, signal: controller.signal}).then(profile => {
    if (flow.request !== request) return null;
    flow.pairKey = key; flow.profile = profile;
    const invalid = profile.status !== "success";
    const matches = Object.values(profile.models || {});
    updateProfileStatus(invalid ? fixes[profile.error?.code]?.[0] || profile.error?.message || "입력을 확인하세요."
      : "입력 가능 모델 " + matches.filter(item => item.eligible).length + " / " + matches.length + "개", invalid);
    return profile;
  }).catch(error => {
    if (!controller.signal.aborted) updateProfileStatus("프로파일 조회 실패 · " + error.message, true);
    return null;
  }).finally(() => {
    if (flow.request !== request) return;
    flow.request = null; renderSpecimen(); renderPlan(); updateStageNav();
  });
  return request.promise;
}

function clearRunView() {
  flow.revision++;
  flow.run = null; state.selected = null; state.signature = "";
  note("");
  $("result-status").textContent = "입력 대기"; $("result-status").className = "pill";
  $("result-content").replaceChildren(element("p", "모델 실행을 마치면 예측값과 해석을 확인할 수 있습니다.", "stage-empty"));
  $("run-meta").textContent = ""; $("event-count").textContent = "0개 이벤트";
  $("events").replaceChildren(element("p", "실행을 시작하면 이곳에 로그가 표시됩니다.", "empty-log"));
  document.querySelector(".trace-route").replaceChildren();
  for (const id of ["download-result", "download-events"]) { $(id).hidden = true; $(id).removeAttribute("href"); }
  renderExecution(); updateStageNav();
}

function changedPair(immediate = false, keepRun = false) {
  flow.edited = true;
  clearTimeout(flow.timer); flow.request?.controller.abort(); flow.request = null;
  flow.profile = null; flow.pairKey = "";
  if (!keepRun) clearRunView();
  updateProfileStatus(""); renderSpecimen(); renderPlan();
  const pair = draftPair();
  if (pair.smiles.trim() && pair.protein_sequence.trim()) {
    if (immediate) loadDraftProfile();
    else flow.timer = setTimeout(loadDraftProfile, 550);
  }
}

function renderPlan() {
  const list = $("plan-summary");
  list.replaceChildren();
  const example = exampleLibrary.get($("example-select").value);
  const residues = $("protein").value.replace(/\s/g, "").length;
  list.append(element("p", example?.label || (residues ? "직접 입력 · " + residues + " aa" : "입력 대기"), "plan-pair"));
  const order = [...chosenModels].filter(id => modelCatalog.has(id));
  if (!order.length) list.append(element("p", "실행할 모델을 선택하세요.", "muted"));
  for (const [index, id] of order.entries()) {
    const row = element("div", undefined, "plan-row"), info = element("div");
    const check = flow.profile?.models?.[id];
    const device = $("device-selection").value === "auto" ? modelCatalog.get(id).default_device : $("device-selection").value;
    info.append(element("strong", modelMethods[id]?.name || id), element("small", "실행 장치 · " + (device === "cuda" ? "GPU (CUDA)" : device?.toUpperCase() || "미확인")));
    row.append(element("span", String(index + 1), "plan-number"), info);
    if (check) row.append(element("span", {pass:"입력 가능",warn:"입력 주의",fail:"입력 미지원"}[check.status], "check-state " + check.status));
    list.append(row);
  }
  if (order.length > 1) list.append(element("p", "선택한 순서대로 한 모델씩 실행합니다.", "plan-device"));
}

function renderExecution() {
  const panel = $("execution-summary"), run = flow.run;
  panel.replaceChildren(); $("next-results").disabled = !run?.result;
  if (!run) {
    panel.append(element("p", "현재 입력으로 시작한 실행이 없습니다.", "stage-empty"));
    return;
  }
  const models = requestedModelNames(run);
  const results = run.result?.results || (run.result && models.length === 1 ? [run.result] : []);
  panel.append(element("h2", "모델별 실행 상태"));
  for (const [idx, name] of models.entries()) {
    const last = run.events.filter(e => e.component === "model" && e.details?.model === name).at(-1);
    const result = results.find(r => r.requested_model === name) || (models.length === 1 ? results[0] : null);
    const status = result?.status || ({started:"running", completed:"success", failed:"error"}[last?.event.split(".")[1]]) ||
      (run.result ? "unexecuted" : models.length === 1 && run.events.some(e => e.event === "tool.started") ? "running" : "queued");
    const row = element("div", undefined, "execution-row");
    row.append(element("span", String(idx + 1), "plan-number"), element("strong", modelMethods[name]?.name || name),
      element("span", statusNames[status] || "미실행", "pill " + status));
    panel.append(row);
  }
}

function openProfileSnapshot(profile, complexUrl, tabIndex = 0) {
  openModal("입력 프로파일", []);
  const url = URL.createObjectURL(new Blob([JSON.stringify(profile, null, 2)], {type:"application/json"}));
  const link = profileLink("전체 프로파일 JSON 저장", url, "input-profile.json");
  $("info-modal").addEventListener("close", () => URL.revokeObjectURL(url), {once:true});
  renderInputProfile(profile, link, complexUrl);
  if (tabIndex) $("profile-tab-" + tabIndex)?.click();
}

function initWorkflow() {
  for (const button of document.querySelectorAll("#stage-nav button")) {
    button.addEventListener("click", () => goToStage(button.dataset.stage));
  }
  $("view-drug").addEventListener("click", () => { flow.view = "compound"; renderSpecimen(); });
  $("view-protein").addEventListener("click", () => { flow.view = "protein"; renderSpecimen(); });
  $("preview-profile").addEventListener("click", () => {
    if (flow.profile) openProfileSnapshot(flow.profile, null, flow.view === "protein" && flow.profile.compound && flow.profile.protein ? 1 : 0);
  });
  $("next-models").addEventListener("click", async () => {
    const pair = draftPair();
    if (!pair.smiles.trim() || !pair.protein_sequence.trim()) {
      updateProfileStatus("화합물 SMILES와 단백질 서열을 모두 입력하세요.", true);
      $(pair.smiles.trim() ? "protein" : "smiles").focus(); return;
    }
    const profile = await loadDraftProfile();
    if (profile?.status === "success" && flow.stage === "input") goToStage("models");
  });
  $("next-results").addEventListener("click", () => goToStage("results"));
  $("roadmap").addEventListener("click", () => {
    const map = element("ol", undefined, "design-map");
    for (const [name, status, detail, bridge] of [
      ["추론 전 입력 검사", "프로파일 사용 가능", "분자·서열, 실험 구조, 모델별 입력 조건과 연결된 학습 근거를 확인합니다.",
        "모델 선택 → 실행 추적 · 사용자가 고른 모델을 순서대로 실행합니다. 자동 라우팅은 설계 단계입니다."],
      ["출력 정리", "일부 구현", "결과 해석에서 모델별 원시 점수와 예측 대상·척도를 확인합니다. 공통 척도 변환은 설계 단계입니다."],
      ["신뢰도·불일치 검증", "설계 단계", "모델별 오차와 학습 분포 이탈을 평가하고, 예측이 엇갈리면 추가 검증 여부를 판단합니다."],
      ["융합·보정·기권", "설계 단계", "비교 가능한 결과를 통합하고 검증된 예측 구간이나 기권 사유를 보고합니다."],
    ]) {
      const row = element("li"); row.append(element("strong", name), element("span", status, "pill"), element("p", detail));
      if (bridge) row.append(element("p", bridge, "design-bridge"));
      map.append(row);
    }
    openModal("전체 분석 설계", [map]);
  });
  $("history-close").addEventListener("click", () => $("history-sidebar").close());
  $("all-runs").addEventListener("click", () => $("toggle-history").click());
  clearRunView(); renderSpecimen(); goToStage("input", false);
}
