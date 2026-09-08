const state = { data: null, market: "ALL", installPrompt: null };
const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[char]);
}

function formatTime(value) {
  if (!value) return "尚未更新";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "尚未更新" : new Intl.DateTimeFormat("zh-TW", {
    month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false
  }).format(date);
}

function setMarketCard(id, market) {
  const card = $(id);
  card.classList.toggle("open", Boolean(market?.is_open));
  card.querySelector(".market-state span").textContent = market?.label || "未知";
  card.querySelector("small").textContent = market?.local_time
    ? `當地 ${formatTime(market.local_time).split(" ").pop()}` : "等待資料";
}

function candidateTemplate(row, index) {
  const isSignal = row.kind === "正式推薦";
  const score = Math.max(0, Number(row.score) || 0);
  const scoreWidth = Math.min(100, score);
  const reason = (row.reasons || []).slice(0, 2).join("・") || row.catalyst || "等待更多訊號確認";
  const price = row.price == null ? "—" : Number(row.price).toLocaleString("zh-TW", { maximumFractionDigits: 2 });
  return `<button class="candidate-card" data-index="${index}">
    <div class="candidate-top"><span class="symbol">${escapeHtml(row.symbol)}</span><span class="tag ${isSignal ? "signal" : "dynamic"}">${escapeHtml(row.kind)}</span></div>
    <div class="candidate-score"><div><span>綜合分數</span><strong>${escapeHtml(score)}</strong></div><span>${escapeHtml(row.market)}・${escapeHtml(row.tier || "WATCH")}</span></div>
    <div class="score-bar"><i style="width:${scoreWidth}%"></i></div>
    <p class="candidate-reason">${escapeHtml(reason)}</p>
    <div class="candidate-meta"><span>價格 <b>${escapeHtml(price)}</b></span><span>量比 <b>${escapeHtml(row.volume_ratio ?? "—")}</b></span></div>
  </button>`;
}

function render() {
  const data = state.data || {};
  const all = Array.isArray(data.candidates) ? data.candidates : [];
  const candidates = all.filter(row => state.market === "ALL" || row.market === state.market);
  setMarketCard("#twMarket", data.markets?.TW);
  setMarketCard("#usMarket", data.markets?.US);
  $("#candidateCount").textContent = all.length;
  $("#signalCount").textContent = all.filter(row => row.kind === "正式推薦").length;
  $("#dynamicCount").textContent = all.filter(row => row.kind === "浮動優先").length;
  $("#twCursor").textContent = data.cursors?.TW ?? "—";
  $("#usCursor").textContent = data.cursors?.US ?? "—";
  $("#lastUpdated").textContent = `資料更新：${formatTime(data.generated_at)}`;
  $("#systemStatus").textContent = data.last_dynamic_update
    ? `浮動名單更新 ${formatTime(data.last_dynamic_update)}` : "排程已連線，等待浮動名單";
  $("#notice").textContent = data.notice || "資料僅供研究，不構成投資建議。";
  $("#candidateGrid").innerHTML = candidates.map((row, index) => candidateTemplate(row, index)).join("");
  $("#emptyState").hidden = candidates.length > 0;
  $("#candidateGrid").hidden = candidates.length === 0;
  document.querySelectorAll(".candidate-card").forEach(button => {
    button.addEventListener("click", () => openDetail(candidates[Number(button.dataset.index)]));
  });
}

function openDetail(row) {
  const reasons = (row.reasons || []).map(reason => `<li>${escapeHtml(reason)}</li>`).join("") || "<li>等待更多資料確認</li>";
  $("#dialogContent").innerHTML = `<p class="eyebrow">${escapeHtml(row.kind)}</p><h3 class="dialog-symbol">${escapeHtml(row.symbol)}</h3><p class="dialog-sub">${escapeHtml(row.market)}・${escapeHtml(row.tier || "WATCH")}</p>
    <div class="dialog-grid"><div><span>綜合分數</span><strong>${escapeHtml(row.score ?? "—")}</strong></div><div><span>參考價格</span><strong>${escapeHtml(row.price ?? "—")}</strong></div><div><span>5日相對強度</span><strong>${escapeHtml(row.relative_strength_5d ?? "—")}%</strong></div><div><span>成交量比</span><strong>${escapeHtml(row.volume_ratio ?? "—")}</strong></div></div>
    <strong>入選原因</strong><ul class="reason-list">${reasons}</ul>${row.catalyst ? `<strong>主要催化</strong><p class="dialog-sub">${escapeHtml(row.catalyst)}</p>` : ""}`;
  $("#detailDialog").showModal();
}

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  window.setTimeout(() => element.classList.remove("show"), 2200);
}

async function loadData(showFeedback = false) {
  $("#refreshButton").classList.add("loading");
  try {
    const response = await fetch(`data.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("data unavailable");
    state.data = await response.json();
    render();
    if (showFeedback) toast("已更新最新掃描資料");
  } catch (error) {
    if (!state.data) {
      state.data = { candidates: [], markets: {}, cursors: {} };
      render();
      $("#systemStatus").textContent = "暫時無法讀取資料，稍後會自動重試";
    }
    if (showFeedback) toast("目前無法更新，請稍後再試");
  } finally {
    $("#refreshButton").classList.remove("loading");
  }
}

document.querySelectorAll("[data-market]").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll("[data-market]").forEach(item => item.classList.remove("active"));
  button.classList.add("active"); state.market = button.dataset.market; render();
}));
$("#refreshButton").addEventListener("click", () => loadData(true));
$(".dialog-close").addEventListener("click", () => $("#detailDialog").close());
$("#detailDialog").addEventListener("click", event => { if (event.target === $("#detailDialog")) $("#detailDialog").close(); });
window.addEventListener("beforeinstallprompt", event => { event.preventDefault(); state.installPrompt = event; $("#installButton").hidden = false; });
$("#installButton").addEventListener("click", async () => { if (state.installPrompt) { state.installPrompt.prompt(); await state.installPrompt.userChoice; state.installPrompt = null; $("#installButton").hidden = true; } else { toast("iPhone 請點分享，再選「加入主畫面」"); } });
if (/iphone|ipad|ipod/i.test(navigator.userAgent) && !window.navigator.standalone) $("#installButton").hidden = false;
if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("service-worker.js"));
loadData();
window.setInterval(() => loadData(), 60000);
