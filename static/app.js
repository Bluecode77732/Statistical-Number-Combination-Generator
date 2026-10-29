const STATE_LABELS = {
  pending: "대기",
  running: "진행 중",
  done: "완료",
  warning: "주의",
  failed: "실패",
  skipped: "건너뜀",
};
const POLL_MS = 1000;

const rerunBtn = document.getElementById("rerun-btn");
let pollTimer = null;

// 목적: 서버에 요청을 보내고 JSON 결과를 돌려주되, 실패하면 원인을 알 수 있는 한글 메시지로 바꾼다.
// 이유: 브라우저 기본 오류("Failed to fetch", "Unexpected token '<'")만으로는 무엇을 해야 할지 알 수 없었다.
// 방법: 전송 실패, JSON이 아닌 응답, 서버가 보낸 오류를 차례로 구분해 각각 다른 안내를 던진다.
async function requestJson(url, options, fallbackMessage) {
  let res;
  try {
    res = await fetch(url, options);
  } catch {
    throw new Error("요청을 보내지 못했습니다. 프로그램(서버)이 켜져 있는지 확인하세요.");
  }

  let data;
  try {
    data = await res.json();
  } catch {
    throw new Error(
      `서버가 올바른 응답을 주지 않았습니다 (HTTP ${res.status}). ` +
        "프로그램을 실행했을 때 안내된 주소로 접속했는지 확인하세요."
    );
  }

  if (!res.ok) {
    throw new Error(data.detail || fallbackMessage);
  }
  return data;
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function pad(n) {
  return String(n).padStart(2, "0");
}

function table(id, header, rows) {
  const t = typeof id === "string" ? document.getElementById(id) : id;
  t.replaceChildren(
    el("thead", {}, el("tr", {}, header.map((h) => el("th", {}, h)))),
    el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => el("td", {}, c)))))
  );
  return t;
}

function newTable(header, rows) {
  return el("div", { class: "table-wrap" }, table(el("table"), header, rows));
}

function info(id, pairs) {
  document.getElementById(id).replaceChildren(
    ...pairs.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)])
  );
}

// 목적: 시작 절차를 시작(또는 이미 도는 절차에 합류)하고 진행 상태를 주기적으로 갱신한다.
// 이유: 첫 실행은 공식 데이터 수집에 몇 분이 걸려, 사용자가 무엇이 진행 중인지 볼 수 있어야 한다.
// 방법: /api/run으로 시작한 뒤 /api/status를 1초마다 읽고, 끝나면 /api/result를 한 번 받아 그린다.
async function start(force) {
  rerunBtn.disabled = true;
  try {
    let status = await requestJson("/api/status", {}, "상태를 읽지 못했습니다.");
    if (force || status.state === "idle") {
      status = await requestJson("/api/run", { method: "POST" }, "실행을 시작하지 못했습니다.");
    }
    renderStatus(status);
    if (status.state === "running") {
      poll();
    } else {
      await loadResult();
    }
  } catch (err) {
    document.getElementById("status-message").textContent = err.message;
    rerunBtn.disabled = false;
  }
}

function poll() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    try {
      const status = await requestJson("/api/status", {}, "상태를 읽지 못했습니다.");
      renderStatus(status);
      if (status.state === "running") poll();
      else await loadResult();
    } catch (err) {
      document.getElementById("status-message").textContent = err.message;
      rerunBtn.disabled = false;
    }
  }, POLL_MS);
}

function renderStatus(status) {
  document.getElementById("steps").replaceChildren(
    ...status.steps.map((s) =>
      el("li", {}, [
        el("span", { class: `step-state state-${s.state}` }, STATE_LABELS[s.state] || s.state),
        el("span", {}, s.label),
        el("span", { class: "step-msg" }, s.message ? `— ${s.message}` : ""),
      ])
    )
  );
  const msg = status.state === "running" ? status.message : status.state === "failed" ? status.message : "";
  document.getElementById("status-message").textContent = msg || "";
  rerunBtn.disabled = status.state === "running";
}

async function loadResult() {
  const data = await requestJson("/api/result", {}, "결과를 읽지 못했습니다.");
  renderStatus(data.status);
  const r = data.result || {};
  if (r.error) {
    document.getElementById("status-message").textContent = "예상하지 못한 오류로 중단했습니다.";
    document.getElementById("status-message").classList.add("error");
  }
  if (r.sync) renderData(r.sync, r.validation);
  if (r.candidates) renderCandidates(r.candidates, r.backtest);
  if (r.backtest) renderBacktest(r.backtest);
  if (r.candidates) renderModel(r.candidates);
  if (r.analysis) renderAnalysis(r.analysis);
}

function renderCandidates(c, bt) {
  document.getElementById("candidate-section").hidden = false;
  document.getElementById("target-round").textContent = `${c.target_round}회차용`;
  document.getElementById("candidate-line").textContent = `후보 숫자: ${c.numbers.map(pad).join(", ")}`;
  document.getElementById("candidate-balls").replaceChildren(
    ...c.numbers.map((n) => el("div", { class: "ball" }, pad(n)))
  );
  const method = document.getElementById("candidate-method");
  method.textContent = c.fallback_reason
    ? `선정 방식: ${c.method_label} — ${c.fallback_reason}`
    : `선정 방식: ${c.method_label} (전체 데이터로 학습한 모델의 점수 상위 10개, 동점은 무작위)`;

  const verdict = document.getElementById("candidate-verdict");
  const lr = bt && bt.ran ? bt.summaries.find((s) => s.key === "logistic") : null;
  verdict.textContent = lr
    ? `백테스트(${bt.start_round}~${bt.end_round}회, ${bt.rounds}회): 이 모델의 평균 일치 ${lr.mean}개, ` +
      `무작위 이론값 ${bt.theory.mean}개 — ${lr.verdict}.`
    : "백테스트 결과가 없어 모델 성능을 확인하지 못했습니다.";
}

function renderData(s, v) {
  document.getElementById("data-section").hidden = false;
  const labels = {
    created: "공식 데이터로 새로 만듦",
    updated: "업데이트함",
    up_to_date: "이미 최신",
    offline: "업데이트 실패 — 기존 데이터 사용",
    failed: "실패",
  };
  const pairs = [
    ["상태", labels[s.status] || s.status],
    ["데이터 범위", s.latest_round ? `${s.first_round}회 (${s.first_date || "-"}) ~ ${s.latest_round}회 (${s.latest_date || "-"})` : "-"],
    ["이번에 추가", s.added.length ? `${s.added.length}개 회차 (${s.added[0]}~${s.added[s.added.length - 1]}회)` : "없음"],
    ["공식 값으로 수정", s.corrected.length ? `${s.corrected.length}개 회차` : "없음"],
    ["엑셀 파일", s.store_path],
    ["백업", s.backup_path || "변경이 없어 만들지 않음"],
  ];
  if (v) pairs.push(["검증", v.missing.length || v.duplicates.length ? `빠진 회차 ${v.missing.length}개, 중복 ${v.duplicates.length}개` : `${v.rounds}개 회차 이상 없음`]);
  // 업데이트 실패(offline)는 저장할 것이 없었던 경우라, 실제로 저장하려다 실패한 때만 알린다.
  if ((s.status === "created" || s.status === "updated") && !s.saved) {
    pairs.push(["저장", "엑셀에 반영하지 못함 (아래 메시지 참고)"]);
  }
  info("data-info", pairs);

  const extra = document.getElementById("data-extra");
  extra.replaceChildren();
  if (s.corrected.length) {
    extra.append(el("h3", {}, "수정한 회차"), newTable(["회차", "기존 값", "공식 값"], s.corrected.map((c) => [c.round, c.before, c.after])));
  }
  if (s.messages.length) {
    extra.append(el("h3", {}, "알림"), el("ul", { class: "messages" }, s.messages.map((m) => el("li", {}, m))));
  }
}

function renderBacktest(bt) {
  document.getElementById("backtest-section").hidden = false;
  if (!bt.ran) {
    info("backtest-info", [["결과", bt.message]]);
    return;
  }
  const pairs = [
    ["시험 구간", `${bt.start_round}~${bt.end_round}회 (${bt.rounds}회)`],
    ["데이터 범위", `${bt.data_range[0]}~${bt.data_range[1]}회`],
    ["소요 시간", `${bt.seconds}초`],
    ["결과 파일", bt.saved_path || bt.save_error || "-"],
  ];
  if (bt.model_errors.length) pairs.push(["모델 오류", bt.model_errors.slice(0, 3).join(" / ")]);
  info("backtest-info", pairs);

  table(
    "backtest-summary",
    ["모델", "시험 회차", "평균 일치", "95% 범위", "판정"],
    [
      ...bt.summaries.map((s) => [s.label, s.rounds, s.mean, `${s.ci_low} ~ ${s.ci_high}`, s.verdict]),
      ["무작위 이론값", bt.rounds, bt.theory.mean, "-", "10 × 6 / 45"],
    ]
  );
  table(
    "backtest-dist",
    ["구분", "0개", "1개", "2개", "3개", "4개", "5개", "6개"],
    [
      ...bt.summaries.map((s) => [s.label, ...s.distribution]),
      ["무작위 이론 기대", ...bt.theory.expected_distribution],
    ]
  );

  const lr = bt.summaries.find((s) => s.key === "logistic");
  document.getElementById("overfit-note").textContent =
    lr && bt.in_sample_mean !== null
      ? `과적합 확인: 전체 데이터로 학습한 모델을 같은 회차들에 다시 적용하면 평균 ${bt.in_sample_mean}개, ` +
        `회차마다 이전 데이터로만 학습한 실제 백테스트는 ${lr.mean}개입니다. ` +
        "앞의 값이 더 높을수록 모델이 이미 본 데이터를 외운 만큼이며, 실제 성능은 뒤의 값입니다."
      : "";

  const actual = new Map(bt.actuals.map((a) => [a.round, a]));
  const byRound = new Map();
  for (const p of bt.predictions) {
    if (!byRound.has(p.round)) byRound.set(p.round, {});
    byRound.get(p.round)[p.model] = p.candidates;
  }
  const rows = [...byRound.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([round, m]) => {
      const a = actual.get(round);
      const set = new Set(a.numbers);
      const hit = (c) => (c ? c.filter((n) => set.has(n)).length : "-");
      return [
        round,
        a.numbers.map(pad).join(" "),
        m.logistic ? m.logistic.map(pad).join(" ") : "-",
        hit(m.logistic),
        m.random.map(pad).join(" "),
        hit(m.random),
      ];
    });
  table("backtest-rows", ["회차", "실제 당첨번호", "로지스틱 회귀 후보", "일치", "무작위 후보", "일치"], rows);
}

function renderModel(c) {
  const section = document.getElementById("model-section");
  if (!c.weights || !c.weights.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  table("model-weights", ["특징", "가중치"], c.weights.map((w) => [w.feature, w.weight]));
}

const ANALYSIS_RENDERERS = {
  frequency: (r) => [
    el("p", { class: "hint" }, `회차당 기대 출현 수: ${r.expected}회`),
    newTable(["번호", "출현", "기대값과 차이", "보너스"], r.rows.map((x) => [x.number, x.count, x.diff, x.bonus_count])),
  ],
  odd_even: (r) => [newTable(["홀:짝", "회차 수", "비율(%)", "이론 비율(%)"], r.rows.map((x) => [`${x.odd}:${x.even}`, x.rounds, x.ratio, x.theory_ratio]))],
  sections: (r) => [
    newTable(
      ["구간", "전체 출현", "회차당 평균", "기대 평균", "0개", "1개", "2개", "3개", "4개", "5개", "6개"],
      r.rows.map((x) => [x.section, x.total, x.mean_per_round, x.expected_per_round, ...x.distribution])
    ),
  ],
  consecutive: (r) => [
    el("p", { class: "hint" }, `연속번호가 하나라도 있는 회차: ${r.with_consecutive}회 (${r.ratio}%)`),
    newTable(["연속 쌍", "회차 수"], r.distribution.map((x) => [x.pairs, x.rounds])),
  ],
  sums: (r) => [
    el("p", { class: "hint" }, `최소 ${r.min} · 최대 ${r.max} · 평균 ${r.mean} · 중앙값 ${r.median} · 표준편차 ${r.stdev} (이론 평균 ${r.theory_mean}, 이론 표준편차 ${r.theory_stdev})`),
    newTable(["합계 구간", "회차 수"], r.bins.map((x) => [x.range, x.rounds])),
  ],
  gaps: (r) => [
    el("p", { class: "hint" }, `평균 간격 ${r.mean_gap} · 회차별 최대 간격의 평균 ${r.mean_max_gap}`),
    newTable(["간격", "횟수"], r.distribution.map((x) => [x.gap, x.count])),
  ],
  last_digit: (r) => [
    newTable(["끝자리", "출현", "기대값"], r.digits.map((x) => [x.digit, x.count, x.expected])),
    el("h3", {}, "회차별 서로 다른 끝자리 수"),
    newTable(["종류", "회차 수"], r.distinct_distribution.map((x) => [x.kinds, x.rounds])),
  ],
  repeats: (r) => [
    el("p", { class: "hint" }, `평균 ${r.mean}개 겹침 (이론 평균 ${r.theory_mean}개, ${r.pairs}쌍 비교)`),
    newTable(["겹친 개수", "회차 수"], r.distribution.map((x) => [x.overlap, x.rounds])),
  ],
  structure: (r) => [
    el("p", { class: "hint" }, `전체 ${r.rounds}회 중 서로 다른 구조 ${r.kinds}종, 한 번만 나온 구조 ${r.single_occurrence}종`),
    newTable(["구조", "회차 수"], r.top.map((x) => [x.structure, x.rounds])),
  ],
};

function renderAnalysis(items) {
  document.getElementById("analysis-section").hidden = false;
  document.getElementById("analysis-list").replaceChildren(
    ...items.map((a, i) => {
      const body = a.error
        ? [el("p", { class: "error" }, a.error)]
        : (ANALYSIS_RENDERERS[a.key] || ((r) => [el("pre", {}, JSON.stringify(r, null, 2))]))(a.result);
      return el("details", { class: "analysis-item" }, [
        el("summary", {}, `${i + 1}. ${a.title}`),
        el("p", { class: "hint" }, `계산 방법: ${a.method}`),
        ...body,
      ]);
    })
  );
}

rerunBtn.addEventListener("click", () => start(true));
start(false);
