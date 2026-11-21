"""Deterministic planning from a profile. Planning never starts inference."""

import math

from .models import MODELS

PURPOSES = ("measurements", "ranking", "interaction", "pose", "ic50_prediction")
ENDPOINTS = ("IC50", "Ki", "Kd", "EC50")


def route_schema():
    return {"name": "route_models", "description": "Plan from a pair's cached evidence, purpose and compute budget without running models.",
            "inputSchema": {"type": "object", "additionalProperties": False,
                "required": ["smiles", "protein_sequence", "purpose"], "properties": {
                    "smiles": {"type": "string"}, "protein_sequence": {"type": "string"},
                    "purpose": {"enum": list(PURPOSES)}, "endpoint": {"enum": list(ENDPOINTS)},
                    "budget_seconds": {"type": "integer", "minimum": 1}}}}


def route_error(message, code="INVALID_ARGUMENT"):
    return {"tool": "route_models", "status": "error", "error": {"code": code, "message": message}}


def execute_route(arguments, profile=None):
    from .profiler import execute_profile
    schema = route_schema()["inputSchema"]
    if (not isinstance(arguments, dict) or not set(schema["required"]) <= arguments.keys()
            or arguments.keys() - schema["properties"].keys()):
        return route_error("smiles, protein_sequence, purpose 및 선택 항목 endpoint, budget_seconds를 확인하세요.")
    if profile is None:
        profile = execute_profile({key: arguments[key] for key in ("smiles", "protein_sequence")})
    return route_models(profile, arguments["purpose"], arguments.get("budget_seconds"), arguments.get("endpoint"))


def _purpose_fit(spec, purpose):
    endpoints = {output.get("endpoint") for output in spec["outputs"]}
    if purpose == "ranking":
        return spec["task"] == "DTA" and spec["provider"] == "deeppurpose"
    return {"pose": "predicted_complex", "interaction": "interaction_score",
            "ic50_prediction": "IC50"}.get(purpose, "measured") in endpoints


def route_models(profile, purpose, budget_seconds=None, endpoint=None, readiness=None):
    if not isinstance(profile, dict) or profile.get("status") != "success" or not profile.get("pair_id"):
        return route_error("유효한 입력 프로파일이 필요합니다.")
    if purpose not in PURPOSES or (endpoint is not None and (purpose != "measurements" or endpoint not in ENDPOINTS)):
        return route_error("조회 목적과 실험 지표를 확인하세요.")
    if budget_seconds is not None and (type(budget_seconds) is not int or budget_seconds <= 0):
        return route_error("시간 예산은 양의 정수(초)로 입력하세요.")
    if readiness is None:
        from .__main__ import checkpoint_status
        readiness = {name: checkpoint_status(name)["checkpoint"]["status"] for name in MODELS}
    evidence = profile.get("public_evidence", {})
    assays = evidence.get("assays", {})
    measurements = [r for r in assays.get("records", []) if r.get("kind") == "quantitative"
                    and r.get("target_context") == "species_supported"
                    and not r.get("validity_comment") and r.get("relation") in ("=", "<", ">", "<=", ">=", "~")
                    and (endpoint is None or r.get("endpoint", "").lower() == endpoint.lower())]
    local = profile.get("enrichment", {}).get("experimental_assays_exact_pair", {})
    for r in local.get("records", []):
        if (r.get("pair_id") == profile["pair_id"] and isinstance(r.get("endpoint"), str)
                and (endpoint is None or r["endpoint"].lower() == endpoint.lower())
                and type(r.get("value")) in (int, float) and math.isfinite(r["value"]) and r.get("unit")
                and r.get("relation") in ("=", "<", ">", "<=", ">=", "~")):
            measurements.append({**r, "source": local.get("source")})
    poses = evidence.get("structures", {}).get("records", [])
    assessments = {}
    choices = []
    for name, spec in MODELS.items():
        obs = profile.get("models", {}).get(name, {})
        eligible = obs.get("eligible") is True
        fits = _purpose_fit(spec, purpose)
        affordable = budget_seconds is None or spec["timeout_seconds"] <= budget_seconds
        ready = readiness.get(name, "unknown")
        reasons = []
        if not eligible:
            reasons.append("입력 제약 미충족")
        if not fits:
            reasons.append("요청한 출력과 다른 모델")
        if ready != "ready":
            reasons.append("체크포인트 준비 미확인")
        if not affordable:
            reasons.append("모델 시간 상한이 예산을 초과")
        candidate = not reasons
        if candidate:
            choices.append(name)
            reasons.append("요청한 출력·입력 조건·예산 충족")
        warnings = [r["rule"] for r in obs.get("warnings", [])]
        training = {stage: {key: data.get(key) for key in
                    ("lookup_status", "pair_context", "nearest_compound", "nearest_protein", "source", "coverage")}
                    for stage, data in obs.get("training", {}).items()}
        supervised = training.get("supervised", {})
        context = supervised.get("pair_context")
        if not eligible:
            applicability = "unsupported_input"
        elif warnings or context in ("cold_compound", "cold_protein", "cold_both"):
            applicability = "review_input_or_domain"
        elif supervised.get("lookup_status") == "queried":
            applicability = "training_reference_available"
        else:
            applicability = "domain_unassessed"
        assessments[name] = {"input_eligible": eligible, "purpose_fit": fits, "within_budget": affordable,
            "checkpoint": ready, "timeout_seconds": spec["timeout_seconds"], "candidate": candidate,
            "reasons": reasons, "warnings": warnings, "outputs": spec["outputs"], "applicability": applicability,
            "training": training, "input_failures": [r for r in obs.get("checks", []) if r.get("status") == "fail"],
            "ood_status": obs.get("applicability", {}).get("ood_status", "not_assessed"),
            "reliability": "not_calibrated"}
    selected = []
    if purpose == "measurements":
        if measurements:
            action, reason = "report_evidence", "요청 지표의 측정값을 실험 조건별로 확인하세요."
        elif any(endpoint is None or (r.get("endpoint") or "").lower() == endpoint.lower() for r in assays.get("records", [])):
            action, reason = "review_assays", "관련 실험 기록이 있습니다. 지표·관계식 또는 실험 대상을 원자료에서 확인하세요."
        elif assays.get("status", "not_queried") == "not_queried":
            action, reason = "lookup_evidence", "이 입력의 PubChem 실험 기록을 먼저 조회하세요."
        else:
            action, reason = "insufficient_evidence", "현재 조회 범위에 요청한 실험 근거가 없습니다. 공개 DB 조회 상태를 확인하세요."
    elif purpose == "pose" and poses:
        action, reason = "review_structure", "동일 리간드와 표적 사슬의 접촉이 보고되었습니다. 실험 구성체와 좌표를 먼저 확인하세요."
    elif purpose == "pose" and evidence.get("structures", {}).get("status", "not_queried") == "not_queried":
        action, reason = "lookup_evidence", "구조 예측 전에 이 리간드와 표적 사슬의 실험 구조를 조회하세요."
    elif choices:
        selected = [min(choices, key=lambda n: (len(assessments[n]["warnings"]), MODELS[n]["timeout_seconds"]))]
        action = "execute"
        reason = {"ranking": "입력 주의 사항과 시간 상한을 기준으로 순위 탐색용 모델 하나를 선택했습니다. 원시 점수의 실험 지표는 미확인입니다.",
                  "interaction": "약물–표적 상호작용 점수를 요청했습니다.", "pose": "현재 근거에서 동일 리간드 자세를 확인할 수 없어 복합체 예측을 제안합니다.",
                  "ic50_prediction": "IC50 척도를 명시한 예측 모델을 선택했습니다."}[purpose]
    else:
        action, reason = "no_candidate", "입력·목적·예산·체크포인트 조건을 모두 만족하는 모델이 없습니다."
    return {"tool": "route_models", "status": "success", "pair_id": profile["pair_id"], "purpose": purpose,
            "endpoint": endpoint, "budget_seconds": budget_seconds, "action": action, "reason": reason,
            "selected_models": selected, "assessments": assessments, "measurements": measurements,
            "structure_matches": poses, "lookup_status": {key: val["status"] for key, val in evidence.items()},
            "lookup_times": {key: val.get("retrieved_at") for key, val in evidence.items()}}
