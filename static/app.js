const uploadForm = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const analyzeBtn = document.getElementById("analyze-btn");
const uploadError = document.getElementById("upload-error");
const resultSection = document.getElementById("result-section");
const generateBtn = document.getElementById("generate-btn");
const numbersOutput = document.getElementById("numbers-output");

// 목적: 서버에 요청을 보내고 JSON 결과를 돌려주되, 실패하면 원인을 알 수 있는 한글 메시지로 바꾼다.
// 이유: 브라우저 기본 오류("Failed to fetch", "Unexpected token '<'")만으로는 무엇을 해야 할지 알 수 없었다.
// 방법: 전송 실패, JSON이 아닌 응답, 서버가 보낸 오류를 차례로 구분해 각각 다른 안내를 던진다.
async function requestJson(url, options, fallbackMessage) {
  let res;
  try {
    res = await fetch(url, options);
  } catch {
    throw new Error(
      "요청을 보내지 못했습니다. 프로그램(서버)이 켜져 있는지 확인하세요. " +
        "파일을 선택한 뒤에 그 파일을 수정·저장했다면, 페이지를 새로고침하고 파일을 다시 선택하세요."
    );
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

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  uploadError.hidden = true;
  uploadError.textContent = "";

  const file = fileInput.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("file", file);

  analyzeBtn.disabled = true;
  analyzeBtn.textContent = "분석 중...";

  try {
    const data = await requestJson(
      "/api/analyze",
      { method: "POST", body: formData },
      "분석에 실패했습니다."
    );

    renderResult(data);
    resultSection.hidden = false;
    generateBtn.disabled = false;
  } catch (err) {
    uploadError.textContent = err.message;
    uploadError.hidden = false;
    resultSection.hidden = true;
    generateBtn.disabled = true;
  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = "분석하기";
  }
});

generateBtn.addEventListener("click", async () => {
  generateBtn.disabled = true;
  generateBtn.textContent = "생성 중...";
  try {
    const data = await requestJson("/api/generate", { method: "POST" }, "번호 생성에 실패했습니다.");
    renderNumbers(data.numbers);
  } catch (err) {
    alert(err.message);
  } finally {
    generateBtn.disabled = false;
    generateBtn.textContent = "번호 생성하기";
  }
});

function renderResult(data) {
  const { analysis, backtest, skipped_rows: skippedRows } = data;

  document.getElementById("stat-range").textContent =
    `${analysis.first_round}회차 ~ ${analysis.last_round}회차 (총 ${analysis.total_rounds}회)`;

  const s = analysis.sum_stats;
  document.getElementById("stat-sum").textContent =
    `최소 ${s.min} / 최대 ${s.max} / 평균 ${s.avg} / 중앙값 ${s.median}`;

  document.getElementById("stat-odd").textContent = formatDistribution(
    analysis.odd_count_distribution,
    "홀수"
  );

  document.getElementById("stat-high").textContent = formatDistribution(
    analysis.high_count_distribution,
    "고구간(23~45)"
  );

  const c = analysis.consecutive_pair_ratio;
  document.getElementById("stat-consecutive").textContent =
    `연속번호 포함 ${c.with_consecutive}회 / 미포함 ${c.without_consecutive}회 (${c.percentage}%)`;

  document.getElementById("stat-backtest").textContent =
    `평균 일치 개수 ${backtest.average_matches}개 (이론값 ${backtest.theoretical_average_matches}개)`;

  document.getElementById("backtest-note").textContent = backtest.note;

  if (skippedRows && skippedRows.length > 0) {
    document.getElementById("skipped-info").textContent =
      `건너뛴 행 ${skippedRows.length}개 (예: ${skippedRows[0].row}행 - ${skippedRows[0].reason})`;
  } else {
    document.getElementById("skipped-info").textContent = "";
  }
}

function formatDistribution(dist, label) {
  const parts = Object.entries(dist).map(([count, freq]) => `${label} ${count}개: ${freq}회`);
  return parts.join(" / ");
}

function renderNumbers(numbers) {
  numbersOutput.innerHTML = "";
  numbers.forEach((n) => {
    const ball = document.createElement("div");
    ball.className = "ball";
    ball.textContent = n;
    numbersOutput.appendChild(ball);
  });
  numbersOutput.hidden = false;
}
