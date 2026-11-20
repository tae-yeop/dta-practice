"use strict";

// A single local WebGL context can be reused across tabs and modal openings.
let moleculeLibrary, moleculeViewer, moleculeCanvas;
function loadMoleculeLibrary() {
  if (!moleculeLibrary) moleculeLibrary = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/static/vendor/3dmol-2.5.5/3Dmol-min.js";
    script.onload = () => resolve(window.$3Dmol);
    script.onerror = () => { moleculeLibrary = null; reject(new Error("3D 뷰어 로드 실패")); };
    document.head.append(script);
  });
  return moleculeLibrary;
}

function profileButton(label, action) {
  const button = element("button", label, "profile-control");
  button.type = "button"; button.addEventListener("click", action);
  return button;
}

function profileLink(label, href, download) {
  const link = element("a", label, "download");
  link.href = href;
  if (download) link.download = download;
  else { link.target = "_blank"; link.rel = "noopener noreferrer"; }
  return link;
}

function profileFacts(entries) {
  const facts = element("dl", undefined, "profile-facts");
  for (const [label, value] of entries) {
    if (value == null) continue;
    const row = element("div");
    row.append(element("dt", label), element("dd", String(value)));
    facts.append(row);
  }
  return facts;
}

function depiction(png) {
  const img = element("img");
  img.className = "compound-depiction"; img.alt = "입력 SMILES에서 그린 화합물의 2D 구조식";
  img.src = "data:image/png;base64," + png;
  return img;
}

function structureFigure(spec) {
  const figure = element("figure", undefined, "structure-figure");
  const stage = element("div", undefined, "structure-stage");
  const caption = element("figcaption", spec.caption);
  figure.append(stage, caption);
  const controls = element("div", undefined, "structure-controls");
  let drawToken = 0;
  function draw2d() {
    ++drawToken;
    stage.replaceChildren(depiction(spec.png));
    stage.removeAttribute("role"); stage.removeAttribute("aria-label");
    caption.textContent = "입력 SMILES의 2D 구조식";
    controls.replaceChildren(profileButton("3D 형태 보기", draw3d));
  }
  async function draw3d() {
    const token = ++drawToken;
    stage.replaceChildren(element("span", "좌표를 불러오는 중…"));
    caption.textContent = spec.caption;
    const reset = profileButton("시점 초기화", () => {
      moleculeViewer.setView(initialView); moleculeViewer.render();
    });
    let initialView;
    controls.replaceChildren();
    if (spec.png) controls.append(profileButton("2D 구조식", draw2d));
    try {
      const [lib, coordinates] = await Promise.all([loadMoleculeLibrary(),
        spec.text || fetch(spec.url).then(r => {
          if (!r.ok) throw new Error("좌표 파일을 읽을 수 없습니다.");
          return r.text();
        })]);
      if (token !== drawToken || !stage.isConnected || !$("info-modal").open) return;
      if (!moleculeCanvas) moleculeCanvas = element("div", undefined, "molecule-canvas");
      stage.replaceChildren(moleculeCanvas);
      if (!moleculeViewer) {
        const probe = document.createElement("canvas");
        const gl = probe.getContext("webgl2") || probe.getContext("webgl");
        if (!gl) throw new Error("브라우저에서 WebGL을 사용할 수 없습니다. 아래 링크에서 좌표를 저장할 수 있습니다.");
        gl.getExtension("WEBGL_lose_context")?.loseContext();
        moleculeViewer = lib.createViewer(moleculeCanvas, {backgroundColor: "#f5f9f8", antialias: true});
      }
      const viewer = moleculeViewer;
      viewer.clear(); viewer.resize();
      const model = viewer.addModel(coordinates, spec.text ? "sdf" : "cif");
      const selection = spec.chain ? {chain: spec.chain, hetflag: false} : {};
      if (!model.selectedAtoms(selection).length) throw new Error("표시할 원자 좌표가 없습니다.");
      if (spec.text) viewer.setStyle({}, {stick: {radius: 0.16}, sphere: {scale: 0.25}});
      else {
        viewer.setStyle({}, {});
        viewer.setStyle(selection, {cartoon: {color: "spectrum"}});
        if (spec.complex) viewer.setStyle({chain: "L"}, {stick: {radius: 0.28, colorscheme: "orangeCarbon"}, sphere: {scale: 0.32}});
      }
      viewer.setView([0, 0, 0, 0, 0, 0, 0, 1]); viewer.zoomTo(selection); viewer.render();
      initialView = viewer.getView();
      stage.setAttribute("aria-label", spec.caption + " · 드래그하여 회전");
      stage.setAttribute("role", "img");
      controls.append(profileButton("회전", () => { viewer.rotate(30, "y"); viewer.render(); }), reset);
    } catch (error) {
      if (token !== drawToken || !stage.isConnected) return;
      stage.replaceChildren(spec.png ? depiction(spec.png) : element("p", "3D 미리보기를 열 수 없습니다."));
      caption.textContent = spec.png ? "3D 표시를 사용할 수 없어 2D 구조식을 표시합니다." : (error.message || "아래 링크에서 좌표를 저장할 수 있습니다.");
      controls.replaceChildren(profileButton("다시 열기", draw3d));
    }
  }
  figure.append(controls);
  if (spec.url || spec.text) requestAnimationFrame(draw3d);
  else if (spec.png) { stage.append(depiction(spec.png)); caption.textContent = spec.caption; }
  return figure;
}

function compoundPanel(compound, drug) {
  const panel = element("div", undefined, "profile-columns");
  const details = element("div");
  details.append(element("h3", drug?.name || "입력 화합물"));
  const structures = compound.structures;
  const conformer = structures?.conformer;
  if (structures?.depiction_png || conformer?.sdf) {
    const caption = conformer?.sdf ? "분리된 화합물 · RDKit으로 계산한 3D 형태 한 가지" :
      (conformer?.status === "skipped" ? "2D 구조식 · 3D 미리보기 크기 한도 초과" : "2D 구조식 · 3D 좌표 생성 실패");
    panel.append(structureFigure({text: conformer?.sdf, png: structures.depiction_png, caption}));
  } else if (structures) {
    panel.append(element("p", "이 입력에서 표시할 구조를 생성하지 못했습니다. " +
      (conformer?.reason === "preview_atom_limit" ? "3D 미리보기는 128원자까지 계산합니다." : ""), "field-hint"));
  }
  const rounded = value => Number.isFinite(value) ? Number(value.toFixed(2)) : null;
  details.append(profileFacts([
    ["분자식", compound.formula], ["분자량", rounded(compound.molecular_weight_da) + " Da"],
    ["수소 제외 원자", compound.heavy_atoms], ["형식 전하", compound.formal_charge],
    ["계산 지용성 (logP)", rounded(compound.logp)], ["극성 표면적 (TPSA)", rounded(compound.tpsa_angstrom2) + " Å²"],
    ["수소 결합 공여체 / 수용체", compound.hbond_donors + " / " + compound.hbond_acceptors],
    ["회전 가능 결합 / 고리", compound.rotatable_bonds + " / " + compound.rings],
    ["입체화학 요소", (compound.stereochemistry || []).length + "개"],
    ["분자 골격", compound.murcko_scaffold || "고리 골격 없음"], ["표준화 SMILES", compound.identity_smiles], ["InChIKey", compound.inchikey],
    ["IUPAC 명칭", drug?.iupac_name],
  ]));
  if (drug?.cid) details.append(profileLink("PubChem · CID " + drug.cid, drug.source_url));
  if (conformer?.sdf) details.append(profileLink("3D 좌표 SDF 저장",
    "data:chemical/x-mdl-sdfile;charset=utf-8," + encodeURIComponent(conformer.sdf), "ligand.sdf"));
  if (compound.stereochemistry?.some(s => s.specified !== "Specified")) {
    details.append(element("p", "입력에서 정하지 않은 입체화학은 생성된 3D 형태에서 한 가지 배치로 보일 수 있습니다.", "field-hint"));
  }
  panel.append(details);
  return panel;
}

function proteinPanel(protein, target) {
  const panel = element("div", undefined, "profile-columns"), details = element("div");
  const ref = protein.reference_structures?.records?.[0];
  if (ref) {
    const url = "/api/structures/" + encodeURIComponent(ref.pdb_id) + ".cif";
    panel.append(structureFigure({url, chain: ref.chain, caption: "실험 참조 구조 · " + ref.pdb_id + " · 사슬 " + ref.chain}));
    details.append(element("h3", target?.name || "입력 단백질"), profileFacts([
      ["생물종", target?.organism], ["전체 서열", protein.length + " aa"], ["실험 방법", ref.method],
      ["구조 해상도", ref.resolution_angstrom + " Å"], ["입력 서열 커버리지", Math.round(ref.coverage * 100) + "%"],
      ["관측 구간 (UniProt)", ref.observed_regions.map(r => r.unp_start + "–" + r.unp_end).join(", ")],
    ]), element("p", ref.title, "structure-title"), profileLink("PDB · " + ref.pdb_id, ref.source_url),
    profileLink("전체 좌표 CIF 저장", url, ref.pdb_id + ".cif"));
    if (ref.nonpolymer_components?.length) {
      details.append(element("h4", "구조에 기록된 비고분자 성분 · 물 제외"));
      for (const component of ref.nonpolymer_components) {
        const link = profileLink(component.ccd, "https://www.rcsb.org/ligand/" + encodeURIComponent(component.ccd));
        link.title = component.name; link.setAttribute("aria-label", component.ccd + " · " + component.name);
        details.append(link);
      }
    }
  } else {
    details.append(element("h3", target?.name || "입력 단백질"),
      profileFacts([["전체 서열", protein.length + " aa"], ["생물종", target?.organism]]),
      element("p", protein.reference_structures?.status === "failed" ? "실험 구조 목록을 읽을 수 없습니다." :
        "이 프로파일에 저장된 실험 구조 좌표가 없습니다."));
  }
  if (target?.source_url) details.append(profileLink("UniProt · " + target.accession, "https://www.uniprot.org/uniprotkb/" + encodeURIComponent(target.accession)));
  details.append(element("h4", "아미노산 조성"), element("p", Object.entries(protein.residue_counts).map(([aa, count]) => aa + " " + count).join(" · "), "residue-counts"));
  panel.append(details);
  return panel;
}

function complexPanel(url) {
  const panel = element("div");
  panel.append(structureFigure({url, complex: true, caption: "Boltz-2 예측 복합체 · 단백질과 입력 리간드의 결합 자세"}),
    profileLink("예측 좌표 CIF 저장", url, "boltz2-complex.cif"));
  return panel;
}

function showRunComplex(runId) {
  openModal("예측 복합체", []);
  $("info-modal").classList.add("profile-modal");
  $("modal-body").append(complexPanel("/api/runs/" + runId + "/complex.cif"));
}

function evidencePanel(profile) {
  const panel = element("div");
  const pairs = profile.catalog?.pair?.matches || [];
  for (const pair of pairs) {
    panel.append(element("h3", "카탈로그 상호작용 근거"), element("p", pair.note));
    if (pair.evidence_url) panel.append(profileLink("상호작용 출처", pair.evidence_url));
  }
  const labels = {protein_family_domains_isoforms: "단백질 주석", structures_pockets_ligands: "추가 구조·포켓 주석",
    experimental_assays_exact_pair: "입력 쌍의 실험 측정", experimental_assays_similar_pairs: "유사 쌍의 실험 측정"};
  const states = {not_queried: "자료 미연결", unpublished: "비공개", failed: "조회 실패", no_match: "일치 없음"};
  const facts = [];
  for (const [key, report] of Object.entries(profile.enrichment || {})) {
    facts.push([labels[key] || key, states[report.status] || (report.records?.length || 0) + "건"]);
    for (const record of report.records || []) {
      panel.append(element("h4", (labels[key] || key) + " · " + record.reference_id),
        profileFacts(Object.entries(record).filter(([k]) => !["pair_id","sequence_sha256","reference_id"].includes(k))
          .map(([k, v]) => [k, typeof v === "object" ? JSON.stringify(v) : v])), element("p", report.source, "field-hint"));
    }
  }
  panel.append(element("h3", "추가 근거 자료"), profileFacts(facts), ...profileModelNodes(profile));
  return panel;
}

function renderInputProfile(profile, download, complexUrl) {
  const body = $("modal-body");
  body.replaceChildren(); $("info-modal").classList.add("profile-modal");
  for (const error of profile.errors || (profile.error ? [profile.error] : [])) {
    body.append(element("p", (error.field === "smiles" ? "화합물 · " : error.field === "protein_sequence" ? "단백질 · " : "") +
      (fixes[error.code]?.[0] || error.message)));
  }
  const drug = profile.catalog?.compound?.matches?.[0], target = profile.catalog?.protein?.matches?.[0];
  const views = [];
  if (profile.compound) views.push(["화합물", () => compoundPanel(profile.compound, drug)]);
  if (profile.protein) views.push(["단백질 구조", () => proteinPanel(profile.protein, target)]);
  if (complexUrl) views.push(["예측 복합체", () => complexPanel(complexUrl)]);
  if (Object.keys(profile.models || {}).length) views.push(["모델·근거", () => evidencePanel(profile)]);
  if (views.length) {
    const bar = element("div", undefined, "profile-tabs"), content = element("div", undefined, "profile-content");
    bar.setAttribute("role", "tablist"); bar.setAttribute("aria-label", "입력 프로파일 항목");
    content.id = "profile-content"; content.setAttribute("role", "tabpanel");
    function select(index) {
      for (const [i, button] of [...bar.children].entries()) {
        button.setAttribute("aria-selected", String(i === index)); button.tabIndex = i === index ? 0 : -1;
      }
      content.setAttribute("aria-labelledby", "profile-tab-" + index);
      content.replaceChildren(views[index][1]());
    }
    views.forEach(([label], i) => {
      const tab = profileButton(label, () => select(i)); tab.id = "profile-tab-" + i;
      tab.setAttribute("role", "tab"); tab.setAttribute("aria-controls", content.id);
      tab.addEventListener("keydown", event => {
        const next = {ArrowRight: (i + 1) % views.length, ArrowLeft: (i + views.length - 1) % views.length,
          Home: 0, End: views.length - 1}[event.key];
        if (next != null) { event.preventDefault(); select(next); bar.children[next].focus(); }
      });
      bar.append(tab);
    });
    body.append(bar, content); select(0);
  }
  if (profile.schema_version === "1.0" && profile.original) {
    body.append(profileButton("이전 입력으로 최신 프로파일 열기", () => showProfile("/api/profile", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(profile.original)}, complexUrl)));
  }
  body.append(download);
}
