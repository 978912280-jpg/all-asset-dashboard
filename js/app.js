/* 全维度资产统计 —— 前端渲染 */
(function () {
  "use strict";

  var state = {
    data: null,
    group: "all",
    sortKey: "value_cny",
    sortDir: "desc",
    donut: null,
    trend: null,
    groupColors: { traditional: "#1d4ed8", crypto: "#b45309", cash: "#0f766e" },
    currency: "CNY",
  };

  function $(id) { return document.getElementById(id); }

  // ---------- 主题 ----------
  var THEME_KEY = "aad-theme";
  var THEME_MODES = ["auto", "light", "dark"];
  var THEME_LABEL = { auto: "跟随系统", light: "浅色", dark: "深色" };
  function isDark() { return document.documentElement.getAttribute("data-theme") === "dark"; }
  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name);
    v = (v || "").trim();
    return v || fallback;
  }
  function themeMode() {
    try { return localStorage.getItem(THEME_KEY) || "auto"; } catch (e) { return "auto"; }
  }
  function tipSkin() {
    return {
      backgroundColor: isDark() ? "#131c2b" : "#ffffff",
      borderColor: isDark() ? "#263244" : "#e5e7eb",
      borderWidth: 1,
      textStyle: { color: cssVar("--text", "#1f2329"), fontSize: 12 },
      extraCssText: "box-shadow:0 8px 24px rgba(0,0,0," + (isDark() ? ".5" : ".12") + ");border-radius:10px;",
    };
  }

  function repaintCharts() {
    if (state.donut) renderSplit();
    if (state.trend) renderTrend();
  }
  function syncThemeButton() {
    var btn = $("btn-theme"), lab = $("theme-label");
    if (!btn) return;
    var m = themeMode();
    if (lab) lab.textContent = THEME_LABEL[m] || "跟随系统";
    btn.setAttribute("title", "当前：" + (THEME_LABEL[m] || "跟随系统") + "（点击切换）");
    btn.style.color = isDark() ? cssVar("--accent", "#f5b301") : "";
  }
  function bindTheme() {
    syncThemeButton();
    var btn = $("btn-theme");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var m = themeMode();
      var next = THEME_MODES[(THEME_MODES.indexOf(m) + 1) % THEME_MODES.length];
      try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
      if (window.__applyTheme) window.__applyTheme();
      syncThemeButton();
      repaintCharts();
      toastTip("主题：" + (THEME_LABEL[next] || next));
    });
    try {
      var mq = window.matchMedia("(prefers-color-scheme: dark)");
      var onChange = function () {
        if (themeMode() !== "auto") return;
        if (window.__applyTheme) window.__applyTheme();
        syncThemeButton();
        repaintCharts();
      };
      if (mq.addEventListener) mq.addEventListener("change", onChange);
      else if (mq.addListener) mq.addListener(onChange);
    } catch (e) {}
  }

  function num(x, digits) {
    if (x === null || x === undefined || isNaN(x)) return "—";
    return Number(x).toLocaleString("zh-CN", {
      minimumFractionDigits: digits === undefined ? 2 : digits,
      maximumFractionDigits: digits === undefined ? 2 : digits,
    });
  }

  function pct(x, digits) {
    if (x === null || x === undefined || isNaN(x)) return "—";
    var v = Number(x);
    return (v >= 0 ? "+" : "") + v.toFixed(digits === undefined ? 2 : digits) + "%";
  }

  // ---------- 货币单位 ----------
  var CUR_KEY = "aad-currency";
  function curCode() { return state.currency === "USD" ? "USD" : "CNY"; }
  function fxRate() {
    var m = (state.data && state.data.meta) || {};
    var f = (m.fx || {}).usdcny;
    return f ? Number(f) : 1;
  }
  // 数据里的金额都是 CNY，切到美元时按当日汇率折算
  function convCny(v) {
    if (v === null || v === undefined || isNaN(v)) return null;
    return curCode() === "USD" ? Number(v) / fxRate() : Number(v);
  }
  function curSym() { return curCode() === "USD" ? "$" : "¥"; }
  // 美元计价的价格按当前币种展示（USD 原值，CNY 乘汇率）
  function usdToCur(v) {
    var n = Number(v || 0);
    return curCode() === "USD" ? n : n * fxRate();
  }
  function money(cny, digits) {
    var v = convCny(cny);
    if (v === null) return "—";
    return curSym() + num(v, digits);
  }
  function signedMoney(cny, digits) {
    var v = convCny(cny);
    if (v === null) return "—";
    return (v >= 0 ? "+" : "−") + curSym() + num(Math.abs(v), digits);
  }

  // 中国市场习惯：红涨绿跌
  function cls(x) {
    if (x === null || x === undefined || isNaN(x)) return "muted";
    return Number(x) >= 0 ? "pos" : "neg";
  }

  function escapeHtml(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ---------- 数据加载 ----------
  function load() {
    // 加时间戳破缓存，避免 GitHub Pages / 浏览器读到旧数据
    fetch("data/dashboard.json?t=" + Date.now())
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        state.base = data;
        state.data = data;
        renderAll();
      })
      .catch(function (e) {
        $("table-body").innerHTML =
          '<tr><td colspan="8" class="muted" style="text-align:center;padding:24px">' +
          "数据加载失败：" + escapeHtml(e.message) +
          "（请确认 data/dashboard.json 已生成）</td></tr>";
      });
  }

  function renderAll() {
    renderMeta();
    renderKpi();
    renderPending();
    renderAnalysis();
    renderSplit();
    renderTable();
    renderFlow();
    renderRealized();
    renderCalendar();
    renderPnlAnalysis();
    renderTrend();
    renderSources();
  }

  // ---------- 历史快照整页复现 ----------
  function toastTip(text) {
    var el = document.createElement("div");
    el.className = "toast-tip";
    el.textContent = text;
    document.body.appendChild(el);
    setTimeout(function () { el.classList.add("show"); }, 30);
    setTimeout(function () {
      el.classList.remove("show");
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 250);
    }, 2600);
  }

  function loadSnapshots() {
    if (state.snapCache) return Promise.resolve(state.snapCache);
    return fetch("data/snapshots.json?t=" + Date.now())
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (list) { state.snapCache = list || []; return state.snapCache; });
  }

  function applyReplay(detail) {
    var base = state.base;
    var ds = detail.date;
    var view = JSON.parse(JSON.stringify(base));
    view.summary = detail.summary;
    view.items = detail.items;
    view.groups = detail.groups || view.groups || [];
    view.history = (base.history || []).filter(function (h) { return h.date <= ds; });
    view.meta = JSON.parse(JSON.stringify(base.meta || {}));
    view.meta.snapshot_replay = ds;
    view.pnl_breakdown = detail.pnl_breakdown || null;
    view.analysis = null;
    state.replay = ds;
    state.data = view;
    state.calSel = ds;
    var d = new Date(ds + "T00:00:00+08:00");
    state.calY = d.getFullYear();
    state.calM = d.getMonth();
    renderAll();
    var banner = $("snap-banner");
    if (banner) { $("sb-date").textContent = ds; banner.hidden = false; }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function enterReplay(ds) {
    if (!state.base) return;
    loadSnapshots().then(function (list) {
      var detail = null;
      for (var k = 0; k < list.length; k++) { if (list[k].date === ds) detail = list[k]; }
      if (!detail || !detail.items || !detail.summary) {
        toastTip(ds + " 只记录了总资产，明细未落库，暂不能整页复现");
        return;
      }
      applyReplay(detail);
    }).catch(function () { toastTip("快照数据读取失败，请稍后重试"); });
  }

  function exitReplay() {
    if (!state.base) return;
    state.replay = null;
    state.data = state.base;
    state.calSel = null;
    var t = cstToday().split("-");
    state.calY = +t[0];
    state.calM = +t[1] - 1;
    renderAll();
    var banner = $("snap-banner");
    if (banner) banner.hidden = true;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function renderMeta() {
    var m = state.data.meta || {};
    if (m.generated_at) {
      $("update-time").textContent = "数据更新时间：" +
        m.generated_at.replace("T", " ").replace("+08:00", "（GMT+8）");
    }
    if (m.version) {
      var vtxt = "v" + m.version + (m.version_date ? "（" + m.version_date + "）" : "");
      $("meta-version").textContent = vtxt;
      $("footer-version").textContent = vtxt;
    }
    if (m.subtitle) $("subtitle").textContent = m.subtitle;
    var fx = (m.fx || {}).usdcny;
    if (fx) {
      $("trend-desc").textContent = "每日快照 · USD/CNY " + fx.toFixed(4) + " · " +
        ((m.sources || {}).crypto_dashboard ? "加密快照" : "");
    }
  }

  function syncCurrencyButton() {
    if ($("cur-label")) $("cur-label").textContent = curCode() === "USD" ? "美元" : "人民币";
    if ($("cur-ico")) $("cur-ico").textContent = curSym();
    if ($("cur-ico-head")) $("cur-ico-head").textContent = curSym();
    if ($("th-value")) $("th-value").textContent = "市值 (" + curCode() + ")";
    if ($("sort-value")) $("sort-value").textContent = curCode() === "USD" ? "市值 ($)" : "市值";
  }

  function bindCurrency() {
    try {
      var saved = localStorage.getItem(CUR_KEY);
      if (saved === "USD" || saved === "CNY") state.currency = saved;
    } catch (e) { /* 忽略隐私模式 */ }
    syncCurrencyButton();
    function flip() {
      state.currency = curCode() === "USD" ? "CNY" : "USD";
      try { localStorage.setItem(CUR_KEY, state.currency); } catch (e) { /* 忽略 */ }
      syncCurrencyButton();
      if (state.data) renderAll();
    }
    ["btn-currency", "btn-currency-head"].forEach(function (id) {
      var b = $(id);
      if (b) b.addEventListener("click", flip);
    });
  }

  function moneyLine(prefix, val, pctVal) {
    if (val === null || val === undefined) return '<span class="kpi-line muted">' + prefix + '—</span>';
    // 数值与百分号必须同一行；前缀可单独换行（竖屏窄卡）
    return '<span class="kpi-line ' + cls(val) + '">' + prefix +
      '<span class="kpi-val">' + signedMoney(val) +
      (pctVal === null || pctVal === undefined ? "" : "（" + pct(pctVal) + "）") + "</span></span>";
  }

  // ---------- KPI ----------
  function renderKpi() {
    var s = state.data.summary || {};
    var day = s.day_change_cny;
    var tradPnl = s.traditional_pnl_cny;
    var cryptoPnl = s.crypto_pnl_cny;
    var totalPnl = s.total_pnl_cny;
    var hasTradCost = !!(s.traditional_cost_cny && s.traditional_cost_cny > 0);
    var fxRate = (((state.data || {}).meta || {}).fx || {}).usdcny || 0;
    var cards = [
      {
        label: "总资产 (" + curCode() + ")",
        value: money(s.total_cny),
        small: false,
        delta: moneyLine(state.replay ? "当日浮动收益 " : "今日浮动收益 ", day, s.day_change_pct) +
          (totalPnl === null || totalPnl === undefined ? "" :
            "<br>" + moneyLine("总盈亏 ", totalPnl, s.total_pnl_pct)),
      },
      {
        label: '<i class="dot trad"></i>传统股票 & 基金',
        value: money(s.traditional_cny),
        small: true,
        delta: moneyLine("今日浮动收益 ", s.traditional_day_change_cny, s.traditional_day_change_pct) +
          "<br>" + (!hasTradCost
            ? '<span class="muted">总盈亏待填成本价</span>'
            : moneyLine("总盈亏 ", tradPnl, s.traditional_pnl_pct)),
      },
      {
        label: '<i class="dot crypto"></i>加密货币',
        value: money(s.crypto_cny),
        small: true,
        delta: moneyLine(state.replay ? "当日浮动收益 " : "今日浮动收益 ", s.crypto_day_change_cny, s.crypto_day_change_pct) +
          "<br>" + moneyLine("总盈亏 ", cryptoPnl, s.crypto_pnl_pct),
      },
      {
        label: '<i class="dot cash"></i>现金',
        value: money(s.cash_cny || 0),
        small: true,
        delta: '<span class="muted">稳定币 ≈ $' + num((s.stable_cash_cny || 0) / (fxRate || 1), 2) + " USDT</span>" +
          ((s.fiat_cash_cny ? '<br><span class="muted">支付宝现金 ¥' + num(s.fiat_cash_cny, 2) + "</span>" : "")),
      },
    ];
    $("kpi-grid").innerHTML = cards.map(function (c) {
      return '<div class="kpi">' +
        '<div class="kpi-label">' + c.label + "</div>" +
        '<div class="kpi-value' + (c.small ? " small" : "") + (c.cls ? " " + c.cls : "") + '">' + c.value + "</div>" +
        '<div class="kpi-delta">' + c.delta + "</div>" +
        "</div>";
    }).join("");
  }

  function renderPending() {
    var s = state.data.summary || {};
    var msgs = [];
    if (s.pending_count) {
      msgs.push("<strong>" + s.pending_count + " 个标的份额未填写：</strong>" +
        escapeHtml((s.pending_ids || []).join("、")) + "。填份额后市值与占比自动计算。");
    }
    if (s.cost_pending_count) {
      msgs.push("<strong>" + s.cost_pending_count + " 个标的成本价未填写：</strong>" +
        escapeHtml((s.cost_pending_ids || []).join("、")) + "。填成本价后才会计算未实现盈亏与收益率。");
    }
    var m = state.data.meta || {};
    if (m.shares_age_days && m.shares_age_days >= 7) {
      msgs.push("<strong>份额已 " + m.shares_age_days + " 天未更新</strong>（最后更新 " +
        escapeHtml(String(m.holdings_updated_at || "").slice(0, 10)) +
        "）。市值、盈亏与占比都按现有份额计算，若期间买卖或定投过，数字会偏离真实持仓。");
    }
    if (!msgs.length) { $("pending-alert").hidden = true; return; }
    $("pending-alert").hidden = false;
    $("pending-text").innerHTML = msgs.join("<br>");
  }

  // ---------- 占比 ----------
  function renderBars() {
    var host = $("split-bars");
    if (!host) return;
    var groups = state.data.groups || [];
    var items = state.data.items || [];
    var colors = state.groupColors || {};

    function money0(v) { return money(v); }

    function darken(hex, t) {
      var r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
      function mix(c) { return Math.round(c * (1 - t)).toString(16).padStart(2, "0"); }
      return "#" + mix(r) + mix(g) + mix(b);
    }

    function shade(hex, t) {
      var r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
      function mix(c) { return Math.round(c + (255 - c) * t).toString(16).padStart(2, "0"); }
      return "#" + mix(r) + mix(g) + mix(b);
    }

    function cryptoBar(g) {
      var color = colors[g.key] || "#b45309";
      var btc = items.filter(function (i) { return i.group === g.key && i.id === "BTC"; })[0] || {};
      var sol = items.filter(function (i) { return i.group === g.key && i.id === "SOL"; })[0] || {};
      var bv = btc.value_cny || 0, sv = sol.value_cny || 0;
      var other = Math.max(0, (g.cny || 0) - bv - sv);
      return '<div class="bar-item">' +
        '<div class="bar-line"><span class="name"><i class="dot" style="background:' + color + '"></i>' +
        escapeHtml(g.name) + '</span><span class="bar-num">' + money0(g.cny) + " · " + num(g.weight) + "%</span></div>" +
        '<div class="bar"><i style="width:' + Math.max(0, Math.min(100, g.weight || 0)) + "%;background:" + color + '"></i></div>' +
        '<div class="bar-sub"><span>BTC ' + money0(bv) + '</span><span>SOL ' + money0(sv) +
        '</span><span>小额币种合计 ' + money0(other) + "</span></div>" +
        "</div>";
    }

    host.innerHTML = groups.map(function (g) {
      if (g.key === "crypto") return cryptoBar(g);
      var color = colors[g.key] || "#374151";
      return '<div class="bar-item">' +
        '<div class="bar-line"><span class="name"><i class="dot" style="background:' + color + '"></i>' +
        escapeHtml(g.name) + '</span><span class="bar-num">' + money0(g.cny) + " · " + num(g.weight) + "%</span></div>" +
        '<div class="bar"><i style="width:' + Math.max(0, Math.min(100, g.weight || 0)) + "%;background:" + color + '"></i></div>' +
        '<div class="bar-sub"><span>' + (g.key === "cash" ? "稳定币 + 支付宝余额" : (g.key === "traditional" ? "美股基金 + 国内基金" : "分四类记账")) + "</span></div>" +
        "</div>";
    }).join("");
  }

  function anaToken(v, kind) {
    v = Number(v) || 0;
    var signCls = kind === "abs" ? "neg" : (v > 0 ? "pos" : (v < 0 ? "neg" : ""));
    var txt;
    if (kind === "pct") txt = (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "%";
    else if (kind === "signed") txt = signedMoney(v, 0);
    else if (kind === "neg") txt = "−" + curSym() + num(convCny(Math.abs(v)), 0);
    else if (kind === "abs") txt = curSym() + num(convCny(Math.abs(v)), 0);
    else txt = curSym() + num(convCny(v), 0);
    return '<span class="ana-num ' + signCls + '">' + txt + "</span>";
  }

  function anaFill(text, values) {
    var map = values || {};
    return String(text || "").replace(/\{([a-z0-9_]+)\}/g, function (m, key) {
      var item = map[key];
      if (!item) return m;
      return anaToken(item.v, item.kind || "money");
    });
  }

  function renderAnalysis() {
    var box = $("analysis-head");
    if (!box) return;
    var a = (state.data && state.data.analysis) || null;
    var list = $("analysis-list");
    var foot = $("analysis-foot");
    var tag = $("analysis-tag");
    if (!a) {
      box.className = "analysis-head muted";
      box.textContent = "当日分析待生成：下次构建（手动或每日自动）后会自动出现在这里。";
      list.innerHTML = "";
      if (foot) foot.textContent = "";
      if (tag) tag.textContent = "待生成";
      return;
    }
    var vals = a.values || {};
    box.className = "analysis-head " + (a.tone === "neg" ? "neg" : "pos");
    box.innerHTML = anaFill(a.headline || "", vals);
    list.innerHTML = (a.bullets || []).map(function (b) {
      return '<li><span class="a-label">' + escapeHtml(b.label || "") + "</span>" +
        '<span class="a-text">' + anaFill(b.text || "", vals) + "</span></li>";
    }).join("");
    if (tag) tag.textContent = a.date || "自动生成";
    if (foot) {
      var t = (a.generated_at || "").slice(11, 16);
      var by = a.ai && a.ai.used ? "规则口径 + AI 润色（" + (a.ai.model || "模型") + "）" : "规则引擎生成";
      foot.textContent = by + (t ? " · " + t : "") + (state.replay ? " · 历史快照无独立分析" : "");
    }
  }

  function renderSplit() {
    var groups = state.data.groups || [];
    var colors = state.groupColors;

    renderBars();

    if (!window.echarts) {
      $("donut-chart").innerHTML = '<p class="empty-tip">图表库未加载，占比数据见右侧图例</p>';
      return;
    }
    var s = state.data.summary || {};
    var items = state.data.items || [];
    var total = s.total_cny || 0;
    if (!state.donut) state.donut = echarts.init($("donut-chart"));

    function shade(hex, t) {
      var r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
      function mix(c) { return Math.round(c + (255 - c) * t).toString(16).padStart(2, "0"); }
      return "#" + mix(r) + mix(g) + mix(b);
    }
    function sumBy(list) { return list.reduce(function (a, i) { return a + (i.value_cny || 0); }, 0); }

    // 环保持不变，只在环内用相近色切分：加密固定三块 BTC / SOL / 其他
    var slices = [];
    var tradItems = items.filter(function (i) { return i.group === "traditional" && (i.value_cny || 0) > 0; });
    tradItems.sort(function (a, b) { return b.value_cny - a.value_cny; });
    var tradT = [0, 0.15, 0.28, 0.4, 0.52, 0.62];
    tradItems.forEach(function (i, idx) {
      slices.push({
        label: i.id, full: i.name || i.id, value: i.value_cny,
        color: shade(colors.traditional, tradT[idx] || 0.7),
      });
    });

    var cryptoItems = items.filter(function (i) { return i.group === "crypto"; });
    var btcItems = cryptoItems.filter(function (i) { return i.id === "BTC"; });
    var solItems = cryptoItems.filter(function (i) { return i.id === "SOL"; });
    var restItems = cryptoItems.filter(function (i) { return i.id !== "BTC" && i.id !== "SOL"; });
    if (btcItems.length) slices.push({ label: "BTC", full: "BTC", value: sumBy(btcItems), color: colors.crypto });
    if (solItems.length) slices.push({ label: "SOL", full: "SOL", value: sumBy(solItems), color: shade(colors.crypto, 0.22) });
    if (restItems.length) {
      slices.push({
        label: "其他币种", full: "其他加密货币：" + restItems.map(function (i) { return i.id; }).join("、"),
        value: sumBy(restItems), color: shade(colors.crypto, 0.45),
      });
    }

    var cashItems = items.filter(function (i) { return i.group === "cash" && (i.value_cny || 0) > 0; });
    var stableItems = cashItems.filter(function (i) { return (i.asset_class || "").indexOf("稳定币") >= 0; });
    var fiatItems = cashItems.filter(function (i) { return (i.asset_class || "").indexOf("余额") >= 0; });
    if (stableItems.length) slices.push({ label: "稳定币", full: "现金（稳定币）", value: sumBy(stableItems), color: colors.cash });
    if (fiatItems.length) {
      slices.push({
        label: "支付宝", full: fiatItems.map(function (i) { return i.name; }).join(" / "),
        value: sumBy(fiatItems), color: shade(colors.cash, 0.5),
      });
    }
    slices = slices.filter(function (x) { return x.value > 0; });
    var compact = window.matchMedia("(max-width: 860px)").matches;

    // 低于 1% 的小块合并成一块，标签分行列出各自占比，只用一根引线
    var sumAll = slices.reduce(function (a, x) { return a + x.value; }, 0) || 1;
    var bigSlices = [], smallSlices = [];
    slices.forEach(function (x) {
      if (x.value / sumAll * 100 < 1) smallSlices.push(x); else bigSlices.push(x);
    });
    if (smallSlices.length > 1) {
      var smallVal = smallSlices.reduce(function (a, x) { return a + x.value; }, 0);
      var lines = smallSlices.map(function (x) {
        return x.label + " " + (x.value / sumAll * 100).toFixed(1) + "%";
      });
      bigSlices.push({
        label: "小额合计",
        full: "低于 1% 的标的合计：" + lines.join(" / "),
        value: smallVal,
        color: "#9aa5b1",
      });
    } else {
      bigSlices = bigSlices.concat(smallSlices);
    }
    slices = bigSlices;
    var mergedIdx = null;
    for (var mi = 0; mi < slices.length; mi++) { if (slices[mi].detail) mergedIdx = mi; }

    state.donut.setOption({
      graphic: [{
        type: "text",
        left: "center",
        top: "middle",
        z: 10,
        silent: true,
        style: {
          text: "{a|总资产}\n{b|" + curSym() + num(convCny(total)) + "}",
          textAlign: "center",
          rich: {
            a: { fontSize: compact ? 9 : 10, fill: cssVar("--muted", "#6b7280"), lineHeight: compact ? 15 : 16 },
            b: { fontSize: compact ? 12 : 14, fontWeight: "bold", fill: cssVar("--text", "#1f2329"), lineHeight: compact ? 17 : 19 },
          },
        },
      }],
      tooltip: Object.assign(tipSkin(), {
        trigger: "item",
        formatter: function (p) {
          return (p.data.full || p.data.name) + "<br/>" + curSym() + num(convCny(p.value)) +
            "（" + p.percent.toFixed(2) + "%）";
        },
      }),
      legend: { show: false },
      series: [{
        name: "资产占比",
        type: "pie",
        radius: compact ? ["36%", "58%"] : ["40%", "62%"],
        center: ["50%", "50%"],
        avoidLabelOverlap: true,
        minAngle: 8,
        labelLayout: function () {
          return { moveOverlap: "shiftY", hideOverlap: false };
        },
        itemStyle: { borderColor: cssVar("--card", "#fff"), borderWidth: 1 },
        label: {
          show: true,
          position: "outside",
          formatter: function (p) {
            if (p.data.label === "小额合计") {
              return "小额合计  " + p.percent.toFixed(1) + "%";
            }
            return p.data.label + "  " + p.percent.toFixed(1) + "%";
          },
          fontSize: compact ? 8.5 : 9,
          color: cssVar("--text", "#374151"),
          lineHeight: compact ? 11 : 12,
        },
        labelLine: {
          show: true,
          length: compact ? 3 : 5,
          length2: compact ? 5 : 8,
          smooth: true,
          lineStyle: { width: 1, color: cssVar("--muted", "#9ca3af") },
        },
        emphasis: { label: { fontWeight: "bold", color: cssVar("--text", "#1f2329") }, scaleSize: 3 },
        data: slices.map(function (x) {
          return {
            name: x.label, full: x.full, label: x.label, detail: x.detail,
            value: Math.round(x.value), itemStyle: { color: x.color },
          };
        }),
      }],
    }, true);
    state.donut.resize();
  }

  // ---------- 明细表 ----------
  function renderTable() {
    var items = (state.data.items || []).filter(function (i) {
      return state.group === "all" || i.group === state.group;
    });
    var sortKey = state.sortKey || "value_cny";
    var dir = state.sortDir === "asc" ? 1 : -1;
    items.sort(function (a, b) {
      // 现金没有「净收益」口径（成本=市值恒为 0），按净收益排序时视为空值排到最后
      var av = (sortKey === "pnl_cny" && a.group === "cash") ? null : a[sortKey];
      var bv = (sortKey === "pnl_cny" && b.group === "cash") ? null : b[sortKey];
      var an = (av === null || av === undefined || isNaN(av)) ? null : Number(av);
      var bn = (bv === null || bv === undefined || isNaN(bv)) ? null : Number(bv);
      if (an === null && bn === null) return 0;
      if (an === null) return 1;      // 空值始终排最后
      if (bn === null) return -1;
      if (an === bn) return dir * ((b.value_cny || 0) - (a.value_cny || 0));
      return (an - bn) * dir;
    });
    // 分组筛选时，占比按当前分组内合计换算成 100%
    var scopeSum = items.reduce(function (a, i) { return a + (i.value_cny || 0); }, 0);
    var scopeLocal = state.group !== "all" && scopeSum > 0;
    function scopeWeight(i) {
      if (!scopeLocal) return i.weight || 0;
      return (i.value_cny || 0) / scopeSum * 100;
    }

    if (!items.length) {
      $("table-body").innerHTML = "";
      $("empty-tip").hidden = false;
      return;
    }
    $("empty-tip").hidden = true;
    if ($("group-hint")) {
      $("group-hint").textContent = scopeLocal
        ? "当前为分组内占比，本组合计 100%。" : "";
    }

    $("table-body").innerHTML = items.map(function (i) {
      var color = state.groupColors[i.group] || "#374151";
      var priceTxt = i.price === null || i.price === undefined ? "—" :
        (i.currency === "USD" || i.currency === "USDT" ? "$" : "¥") + num(i.price, i.price < 10 ? 4 : 2);
      var sharesTxt = (i.shares === null || i.shares === undefined)
        ? '<span class="muted">—</span>' : num(i.shares, i.shares < 1 ? 6 : 4);
      var costTxt;
      if (i.group === "cash") {
        costTxt = '<span class="muted">—</span>';
      } else if (i.group === "crypto") {
        // 加密货币成本来自「净入金校准 + Bitget 成交」账本，没有则显示 —
        costTxt = (i.cost_price === null || i.cost_price === undefined)
          ? '<span class="muted">—</span>'
          : "$" + num(i.cost_price, i.cost_price < 10 ? 4 : 2);
      } else {
        costTxt = !i.cost_price ? '<span class="muted">待填</span>'
          : (i.currency === "USD" ? "$" : "¥") + num(i.cost_price, i.cost_price < 10 ? 4 : 2);
      }
      var pnlTxt;
      // 净收益列 = 市值 − 成本（相对成本价的累计盈亏），并给出收益率
      var pv = i.pnl_cny;
      if (i.group === "cash" || i.cost_pending) {
        pnlTxt = '<span class="muted">—</span>';
      } else if (pv === null || pv === undefined) {
        pnlTxt = '<span class="muted">—</span>';
      } else {
        var sub = (i.pnl_pct === null || i.pnl_pct === undefined)
          ? '<div class="sub muted">—</div>'
          : '<div class="sub ' + cls(i.pnl_pct) + '">' + pct(i.pnl_pct) + "</div>";
        pnlTxt = '<span class="' + cls(pv) + '"><span class="amt">' + signedMoney(pv) +
          "</span>" + sub + "</span>";
      }
      return "<tr>" +
        '<td class="name-cell"><div class="nm">' + escapeHtml(i.name) +
        (i.pending ? '<span class="tag pending">待填份额</span>' : "") +
        "</div></td>" +
        '<td><span class="tag" style="border-color:' + color + '33;color:' + color +
        '">' + escapeHtml(i.asset_class) + "</span></td>" +
        '<td class="num">' + sharesTxt + "</td>" +
        '<td class="num">' + costTxt + "</td>" +
        '<td class="num">' + priceTxt + "</td>" +
        '<td class="num">' + (i.value_cny === null ? "—" : money(i.value_cny)) + "</td>" +
        '<td class="num">' + pnlTxt + "</td>" +
        '<td class="num">' + num(scopeWeight(i)) + "%</td>" +
        "</tr>";
    }).join("");

    // 合计行：市值与净收益按当前筛选求和（现金的净收益恒为 0，不计入）
    var sumVal = items.reduce(function (a, i) { return a + (i.value_cny || 0); }, 0);
    var sumPnl = items.reduce(function (a, i) {
      return a + ((i.group === "cash" || i.cost_pending) ? 0 : (i.pnl_cny || 0));
    }, 0);
    var sumW = items.reduce(function (a, i) { return a + scopeWeight(i); }, 0);
    var sumWTxt = Math.abs(sumW - 100) < 0.05 ? "100.00%" : num(sumW, 2) + "%";
    $("table-foot").innerHTML = "<tr>" +
      '<td class="name-cell">合计</td><td></td><td></td><td></td><td></td>' +
      '<td class="num total-gold">' + money(sumVal) + "</td>" +
      '<td class="num total-gold ' + cls(sumPnl) + '"><span class="amt">' + signedMoney(sumPnl) + "</span></td>" +
      '<td class="num total-gold">' + sumWTxt + "</td></tr>";
  }

  function bindSort() {
    var box = $("sort-box"), dirBtn = $("sort-dir");
    if (!box || !dirBtn) return;
    box.addEventListener("click", function (e) {
      var keyBtn = e.target.closest("[data-sort]");
      if (keyBtn) {
        state.sortKey = keyBtn.getAttribute("data-sort");
        var btns = box.querySelectorAll(".sort-btn");
        for (var i = 0; i < btns.length; i++) btns[i].classList.toggle("active", btns[i] === keyBtn);
        renderTable();
        return;
      }
      if (e.target.closest("#sort-dir")) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
        dirBtn.setAttribute("data-dir", state.sortDir);
        dirBtn.textContent = state.sortDir === "asc" ? "升序 ↑" : "降序 ↓";
        renderTable();
      }
    });
  }

  // ---------- 访问密码锁（拨号盘） ----------
  var PIN_HASH = "sg6ibi";   // 访问密码的散列值（adpin::<6位密码>）

  function pinHash(str) {
    var x = 5381;
    for (var i = 0; i < str.length; i++) { x = ((x << 5) + x) ^ str.charCodeAt(i); }
    return (x >>> 0).toString(36);
  }
  function bindPinLock() {
    var lock = $("pin-lock"), pad = $("pin-pad"), dots = $("pin-dots"), tip = $("pin-tip");
    if (!lock || !pad) return;
    // 每次进入网站都需重新验证，不做任何本地记忆
    lock.hidden = false;
    document.body.classList.add("locked");
    var buf = "";
    function paint() {
      for (var i = 0; i < dots.children.length; i++) {
        dots.children[i].classList.toggle("on", i < buf.length);
      }
    }
    function reset(msg) {
      buf = "";
      paint();
      dots.classList.remove("err", "ok");
      if (msg) tip.textContent = msg;
    }
    pad.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-k]");
      if (!btn || btn === pad) return;
      var k = btn.getAttribute("data-k");
      if (dots.classList.contains("ok")) return;
      if (k === "clear") { reset("请输入 6 位访问密码"); return; }
      if (k === "del") { buf = buf.slice(0, -1); paint(); return; }
      if (buf.length >= 6) return;
      buf += k;
      paint();
      if (buf.length === 6) {
        if (pinHash("adpin::" + buf) === PIN_HASH) {
          dots.classList.add("ok");
          tip.textContent = "验证通过";
          setTimeout(function () {
            lock.hidden = true;
            document.body.classList.remove("locked");
            window.dispatchEvent(new Event("resize"));
            if (state.trend) setTimeout(function () { state.trend.resize(); }, 100);
          }, 420);
        } else {
          dots.classList.add("err");
          lock.classList.add("pin-shake");
          tip.textContent = "密码不正确，请重新输入";
          setTimeout(function () {
            lock.classList.remove("pin-shake");
            reset("请输入 6 位访问密码");
          }, 620);
        }
      }
    });
  }

  // ---------- 首页「立即抓取最新价格」 ----------
  function bindRefreshPrice() {
    var btn = $("btn-refresh-price");
    if (!btn) return;
    btn.onclick = function () {
      if (btn.disabled) return;
      var token = "";
      try {
        token = (JSON.parse(localStorage.getItem("asset_dash_gh") || "{}").token || "");
      } catch (e) { token = ""; }
      if (!token) {
        toastTip("先在「份额维护后台」填入 GitHub Token，再回来点这个按钮");
        return;
      }
      var old = btn.textContent;
      btn.disabled = true;
      btn.textContent = "抓取中…";
      var t0 = Date.now();
      var base = ((state.data.meta || {}).generated_at || "");
      fetch("https://api.github.com/repos/978912280-jpg/all-asset-dashboard/actions/workflows/daily.yml/dispatches", {
        method: "POST",
        headers: {
          Authorization: "Bearer " + token,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: "main", inputs: { source: "manual" } }),
      }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        toastTip("已触发抓取最新价格，约 1 分钟完成，页面会自动刷新");
        poll();
      }).catch(function (e) {
        btn.disabled = false;
        btn.textContent = old;
        toastTip("触发失败：" + e.message);
      });
      function poll() {
        if (Date.now() - t0 > 240000) {
          btn.disabled = false;
          btn.textContent = old;
          toastTip("抓取超时，请稍后手动刷新页面");
          return;
        }
        setTimeout(function () {
          fetch("data/dashboard.json?t=" + Date.now())
            .then(function (r) { return r.json(); })
            .then(function (d) {
              var g = ((d.meta || {}).generated_at || "");
              if (g && g !== base) { location.reload(); } else { poll(); }
            })
            .catch(poll);
        }, 8000);
      }
    };
  }

  function bindPanel() {
    var rail = $("rail");
    if (!rail) return;
    var main = document.querySelector("main.container");
    var views = Array.prototype.slice.call(document.querySelectorAll(".view-page"));

    function show(key) {
      var isHome = key === "home" || !key;
      if (main) main.hidden = !isHome;
      views.forEach(function (v) {
        v.hidden = v.getAttribute("data-view") !== key || isHome;
      });
      Array.prototype.forEach.call(rail.children, function (b) {
        b.classList.toggle("active", b.getAttribute("data-view") === (isHome ? "home" : key));
      });
      document.body.classList.toggle("view-mode", !isHome);
      window.scrollTo({ top: 0, behavior: "instant" });
      state.view = isHome ? "home" : key;
      setTimeout(function () {
        if (key === "trend" && state.trend) { state.trend.resize(); }
        if (key === "flow") renderFlow();
        if (key === "pnl") renderRealized();
      }, 50);
    }
    var toggle = $("menu-toggle"), mask = $("drawer-mask");
    function openMenu(open) {
      document.body.classList.toggle("menu-open", !!open);
      if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (mask) mask.hidden = !open;
    }
    if (toggle) toggle.addEventListener("click", function () { openMenu(!document.body.classList.contains("menu-open")); });
    if (mask) mask.addEventListener("click", function () { openMenu(false); });
    rail.addEventListener("click", function (e) {
      var b = e.target.closest("[data-view]");
      if (!b) return;
      show(b.getAttribute("data-view"));
      openMenu(false);
    });
    document.addEventListener("click", function (e) {
      var b = e.target.closest(".back-home");
      if (!b) return;
      show("home");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (document.body.classList.contains("menu-open")) { openMenu(false); return; }
      if (state.view && state.view !== "home") show("home");
    });
    state.showView = show;
  }

  function bindTabs() {
    $("group-tabs").addEventListener("click", function (e) {
      var btn = e.target.closest(".seg-btn");
      if (!btn) return;
      state.group = btn.getAttribute("data-group");
      Array.prototype.forEach.call($("group-tabs").children, function (b) {
        b.classList.toggle("active", b === btn);
      });
      renderTable();
    });
    var mnav = $("flow-month-nav");
    if (mnav) {
      mnav.addEventListener("click", function (e) {
        var b = e.target.closest("[data-mstep]");
        if (!b || b.disabled) return;
        var months = state.flowMonths || [];
        var idx = months.indexOf(state.flowMonth);
        var step = Number(b.getAttribute("data-mstep"));
        var next = idx + (step === -1 ? 1 : -1);   // ‹ 看更早的月份，› 回到更近的
        if (next < 0 || next >= months.length) return;
        state.flowMonth = months[next];
        renderFlow();
      });
    }
    var flowBox = $("flow-tabs");
    if (flowBox) {
      flowBox.addEventListener("click", function (e) {
        var btn = e.target.closest(".seg-btn");
        if (!btn) return;
        state.flowTab = btn.getAttribute("data-flow");
        Array.prototype.forEach.call(flowBox.children, function (b) {
          b.classList.toggle("active", b === btn);
        });
        renderFlow();
      });
    }
  }

  // ---------- 资金流水 ----------
  function flowMoney(usdt) {
    if (usdt === null || usdt === undefined) return "—";
    return money(Number(usdt) * fxRate());
  }

  function qtyText(v) {
    var n = Number(v || 0);
    if (!n) return "0";
    var d = Math.abs(n) >= 1000 ? 2 : (Math.abs(n) >= 1 ? 4 : 8);
    var s = n.toFixed(d);
    if (s.indexOf(".") >= 0) s = s.replace(/0+$/, "").replace(/\.$/, "");
    return s;
  }

  function shortDate(s) {
    return String(s || "").replace(/^\d{4}-/, "");
  }

  function renderFlow() {
    var ev = state.data && state.data.events;
    var body = $("flow-body");
    if (!body) return;
    var tab = state.flowTab || "trades";
    var head = $("flow-head"), foot = $("flow-foot"), empty = $("flow-empty");
    // 用卡片自身宽度判断（面板内约 700px，手机约 380px），避免面板里横向溢出
    var host = body.closest(".flow-card");
    var cw = host ? host.getBoundingClientRect().width : 0;
    var narrow = (cw ? cw : window.innerWidth) < 860;
    if (!ev) {
      head.innerHTML = ""; body.innerHTML = ""; foot.innerHTML = "";
      if (empty) { empty.hidden = false; empty.textContent = "当前快照不含流水数据（历史复现时不可用）。"; }
      return;
    }

    // 按月过滤（月份取最近 90 天里出现过的自然月）
    var evAll = ev;
    var months = [];
    (ev.trades || []).concat().forEach(function (x) { months.push((x.date_day || "").slice(0, 7)); });
    (ev.earn_daily || []).forEach(function (x) { months.push(x.day); });
    (ev.flows || []).forEach(function (x) { months.push(x.day); });
    (ev.transfers || []).forEach(function (x) { months.push(x.day); });
    months = months.filter(function (m) { return m; }).map(function (m) { return m.slice(0, 7); });
    months = months.filter(function (m, i) { return months.indexOf(m) === i; }).sort().reverse();
    if (!state.flowMonth || months.indexOf(state.flowMonth) < 0) state.flowMonth = months[0] || "";
    var mKey = state.flowMonth;
    function inMonth(x) {
      var d = x.date_day || x.day || x.date || "";
      return !mKey || String(d).slice(0, 7) === mKey;
    }
    ev = {
      trades: (evAll.trades || []).filter(inMonth),
      earn_daily: (evAll.earn_daily || []).filter(inMonth),
      flows: (evAll.flows || []).filter(inMonth),
      transfers: (evAll.transfers || []).filter(inMonth),
      net_deposit: evAll.net_deposit,
    };
    if ($("flow-month")) {
      $("flow-month").textContent = mKey || "—";
      var prevBtn = document.querySelector('[data-mstep="-1"]');
      var nextBtn = document.querySelector('[data-mstep="1"]');
      var idx = months.indexOf(mKey);
      if (prevBtn) prevBtn.disabled = idx < 0 || idx >= months.length - 1;
      if (nextBtn) nextBtn.disabled = idx <= 0;
      state.flowMonths = months;
    }

    function T(t, c) { return { t: t, c: c || "" }; }
    function S(subs) { return { sub: subs }; }        // 窄屏竖排合并列

    var cols = [], rows = [], footCells = [];

    if (tab === "trades") {
      cols = narrow
        ? [T("时间", "col-name"), T("币种 / 方向"), T("数量 / 价格", "num"), T("金额", "num")]
        : [T("时间", "col-name"), T("币种"), T("方向"), T("数量", "num"),
           T("成交价", "num"), T("金额", "num"), T("手续费", "num col-fee")];
      (ev.trades || []).forEach(function (t) {
        var sc = t.side === "买入" ? "neg" : "pos";
        rows.push(narrow
          ? [T(shortDate(t.date), "col-name"),
             S([[escapeHtml(t.coin), ""], [escapeHtml(t.side), sc]]),
             S([[qtyText(t.qty), ""], ["@" + Number(t.price || 0).toFixed(2), "muted"]]),
             T(flowMoney(t.quote_usdt), "num")]
          : [T(shortDate(t.date), "col-name"), T(escapeHtml(t.coin)),
             T(escapeHtml(t.side), sc), T(qtyText(t.qty), "num"),
             T(num(t.price, 2), "num"), T(flowMoney(t.quote_usdt), "num"),
             T(escapeHtml(t.fee || "—"), "num muted col-fee")]);
      });
      var buys = (ev.trades || []).filter(function (t) { return t.side === "买入"; });
      var sells = (ev.trades || []).filter(function (t) { return t.side === "卖出"; });
      var buyAmt = buys.reduce(function (a, t) { return a + (t.quote_usdt || 0); }, 0);
      var sellAmt = sells.reduce(function (a, t) { return a + (t.quote_usdt || 0); }, 0);
      footCells = narrow
        ? [{ t: "买 " + buys.length + " / 卖 " + sells.length, c: "", s: 2 },
           { t: flowMoney(buyAmt) + " · " + flowMoney(sellAmt), c: "num total-gold", s: 2 }]
        : [{ t: "买入 " + buys.length + " 笔 / 卖出 " + sells.length + " 笔", c: "", s: 5 },
           { t: flowMoney(buyAmt) + " 买 · " + flowMoney(sellAmt) + " 卖", c: "num total-gold", s: 1 },
           { t: "", c: "", s: 1 }];
      empty.hidden = !!(ev.trades || []).length;
      if (!(ev.trades || []).length) empty.textContent = "近 90 天没有成交记录。";
    } else if (tab === "earn") {
      cols = narrow
        ? [T("日期", "col-name"), T("币种"), T("当日收益", "num"), T("估值", "num")]
        : [T("日期", "col-name"), T("币种"), T("当日收益", "num"), T("估值", "num"), T("笔数", "num")];
      (ev.earn_daily || []).forEach(function (e) {
        rows.push(narrow
          ? [T(shortDate(e.day), "col-name"), T(escapeHtml(e.coin)),
             T("+" + qtyText(e.qty), "num pos"), T(flowMoney(e.value_usdt), "num")]
          : [T(shortDate(e.day), "col-name"), T(escapeHtml(e.coin)),
             T("+" + qtyText(e.qty), "num pos"), T(flowMoney(e.value_usdt), "num"),
             T(String(e.count || 1), "num muted")]);
      });
      var earnTotal = (ev.earn_daily || []).reduce(function (a, e) { return a + (e.value_usdt || 0); }, 0);
      var earnCount = (ev.earn_daily || []).reduce(function (a, e) { return a + (e.count || 0); }, 0);
      footCells = narrow
        ? [{ t: "累计 " + earnCount + " 笔", c: "", s: 2 },
           { t: flowMoney(earnTotal), c: "num total-gold", s: 2 }]
        : [{ t: "累计理财收益", c: "", s: 3 },
           { t: flowMoney(earnTotal), c: "num total-gold", s: 1 },
           { t: String(earnCount) + " 笔", c: "num muted", s: 1 }];
      empty.hidden = !!(ev.earn_daily || []).length;
      if (!(ev.earn_daily || []).length) empty.textContent = "近 90 天没有理财收益记录。";
    } else if (tab === "flows") {
      cols = narrow
        ? [T("日期", "col-name"), T("方向 / 币种"), T("数量", "num"), T("金额", "num")]
        : [T("日期", "col-name"), T("方向"), T("币种"), T("数量", "num"),
           T("金额", "num"), T("通道")];
      (ev.flows || []).forEach(function (f) {
        var dc = f.direction === "入金" ? "pos" : "neg";
        rows.push(narrow
          ? [T(shortDate(f.date), "col-name"),
             S([[escapeHtml(f.direction), dc], [escapeHtml(f.coin), ""]]),
             T(qtyText(f.qty), "num"), T(flowMoney(f.value_usdt), "num")]
          : [T(shortDate(f.date), "col-name"), T(escapeHtml(f.direction), dc),
             T(escapeHtml(f.coin)), T(qtyText(f.qty), "num"),
             T(flowMoney(f.value_usdt), "num"), T(escapeHtml(f.channel || "—"), "muted")]);
      });
      var nd = ev.net_deposit || {};
      var mIn = (ev.flows || []).filter(function (f) { return f.direction === "入金"; })
        .reduce(function (a, f) { return a + (f.value_usdt || 0); }, 0);
      var mOut = (ev.flows || []).filter(function (f) { return f.direction === "出金"; })
        .reduce(function (a, f) { return a + (f.value_usdt || 0); }, 0);
      var netTotal = nd.computed_total_usdt != null ? nd.computed_total_usdt : nd.computed_usdt;
      footCells = narrow
        ? [{ t: "当月入 " + flowMoney(mIn) + " / 出 " + flowMoney(mOut), c: "", s: 2 },
           { t: "净入金 " + flowMoney(netTotal), c: "num total-gold", s: 2 }]
        : [{ t: "当月累计入金 " + flowMoney(mIn) + " · 出金 " + flowMoney(mOut), c: "", s: 2 },
           { t: "净入金 " + flowMoney(netTotal), c: "num total-gold", s: 2 },
           { t: "其中美股 " + flowMoney(nd.stock_part_usdt), c: "num muted", s: 2 }];
      empty.hidden = !!(ev.flows || []).length;
      if (!(ev.flows || []).length) empty.textContent = "近 90 天没有链上充提记录。";
    } else {
      var isStock = tab === "stock";
      var list = (ev.transfers || []).filter(function (t) {
        var k = String(t.kind || "");
        return isStock ? k.indexOf("美股") >= 0 : k.indexOf("美股") < 0;
      });
      cols = narrow
        ? [T("日期", "col-name"), T("币种 / 类型"), T("数量", "num"), T("估值", "num")]
        : [T("日期", "col-name"), T("币种"), T("类型"), T("数量", "num"), T("估值", "num")];
      list.forEach(function (t) {
        rows.push(narrow
          ? [T(shortDate(t.date), "col-name"),
             S([[escapeHtml(t.coin), ""], [escapeHtml(t.kind), "muted"]]),
             T(qtyText(t.qty), "num"), T(flowMoney(t.value_usdt), "num")]
          : [T(shortDate(t.date), "col-name"), T(escapeHtml(t.coin)),
             T(escapeHtml(t.kind)), T(qtyText(t.qty), "num"),
             T(flowMoney(t.value_usdt), "num")]);
      });
      var trTotal = list.reduce(function (a, t) { return a + (t.value_usdt || 0); }, 0);
      var label = isStock ? "美股账户划转合计（不计入净入金）" : "内部划转合计（不计入净入金）";
      footCells = narrow
        ? [{ t: (isStock ? "美股划转 " : "划转 ") + list.length + " 笔", c: "", s: 2 },
           { t: flowMoney(trTotal), c: "num total-gold", s: 2 }]
        : [{ t: label + " · " + list.length + " 笔", c: "", s: 4 },
           { t: flowMoney(trTotal), c: "num total-gold", s: 1 }];
      empty.hidden = !!list.length;
      if (!list.length) empty.textContent = isStock ? "近 90 天没有划往美股账户的记录。" : "近 90 天没有内部划转记录。";
    }

    function td(c) {
      if (c.sub) {
        return '<td class="' + (c.c || "") + '">' +
          c.sub.map(function (x) {
            return "<span" + (x[1] ? ' class="' + x[1] + '"' : "") + ">" + x[0] + "</span>";
          }).join("<br>") + "</td>";
      }
      return "<td" + (c.c ? ' class="' + c.c + '"' : "") +
        (c.s > 1 ? ' colspan="' + c.s + '"' : "") + ">" + c.t + "</td>";
    }

    head.innerHTML = "<tr>" + cols.map(function (c) {
      return '<th class="' + (c.c || "") + '">' + c.t + "</th>";
    }).join("") + "</tr>";
    body.innerHTML = rows.map(function (cells) {
      return "<tr>" + cells.map(td).join("") + "</tr>";
    }).join("");
    var footHtml = "<tr>" + footCells.map(td).join("") + "</tr>";
    if (tab === "flows") {
      var ndx = ev.net_deposit || {};
      if (ndx.computed_total_usdt != null) {
        footHtml += '<tr><td colspan="' + cols.length + '" class="num muted foot-split">' +
          "净入金含已划入美股账户部分；加密账户口径 " + flowMoney(ndx.computed_usdt) +
          "（收益率按此计算），美股账户批量约为 " + flowMoney(ndx.stock_part_usdt) + "</td></tr>";
      }
    }
    foot.innerHTML = footHtml;

    var desc = {
      trades: "Bitget 成交明细 · 按时间倒序",
      earn: "理财派息 / 锁仓收益 / 活动奖励 · 按日汇总",
      flows: "链上充值 = 外部入金，链上提现 = 外部出金",
      transfers: "账户间划转 / 划入美股账户 · 不计入净入金",
    };
    $("flow-desc").textContent = desc[tab] || "";
  }

  function renderRealized() {
    var s = (state.data && state.data.summary) || {};
    var d = (state.data && state.data.realized_detail) || {};
    var cryptoRealized = Number(s.crypto_realized_cny || 0);
    var tradRealized = Number(s.traditional_realized_cny || 0);
    var cRows = d.crypto || [];
    var tRows = d.traditional || [];

    var kpis = [
      { label: "加密累计已实现", value: signedMoney(cryptoRealized), cls: cls(cryptoRealized) },
      { label: "加密累计卖出笔数", value: cRows.length + " 笔", cls: "muted" },
      { label: "传统累计已实现", value: signedMoney(tradRealized), cls: cls(tradRealized) },
      { label: "传统累计卖出笔数", value: tRows.length + " 笔", cls: "muted" },
    ];
    $("realized-kpis").innerHTML = kpis.map(function (k) {
      return '<div class="rk-item"><p class="rk-label">' + k.label + '</p><p class="rk-value ' +
        k.cls + '">' + k.value + "</p></div>";
    }).join("");

    var cb = $("ra-crypto-body");
    if (cb) {
      cb.innerHTML = cRows.length
        ? cRows.map(function (r) {
            return "<tr><td class=\"col-name\">" + escapeHtml(r.date || "—") + "</td>" +
              "<td>" + escapeHtml(r.coin || "") + "</td>" +
              '<td class="num">' + num(r.shares, 6) + "</td>" +
              '<td class="num">' + curSym() + num(usdToCur(r.price), 2) + "</td>" +
              '<td class="num">' + curSym() + num(usdToCur(r.cost_price), 2) + "</td>" +
              '<td class="num ' + cls(r.pnl_cny) + '">' + signedMoney(r.pnl_cny, 2) + "</td></tr>";
          }).join("")
        : '<tr><td colspan="6" class="pa-empty">校准日以来还没有卖出记录</td></tr>';
    }

    var tb = $("ra-trad-body");
    if (tb) {
      tb.innerHTML = tRows.length
        ? tRows.map(function (r) {
            return "<tr><td class=\"col-name\">" + escapeHtml(r.date || "—") + "</td>" +
              "<td>" + escapeHtml(r.id || "") + "</td>" +
              '<td class="num">' + num(r.shares, 6) + "</td>" +
              '<td class="num">' + curSym() + num(convCny(r.price_cny !== undefined ? r.price_cny : usdToCur(r.price)), 2) + "</td>" +
              '<td class="num">' + curSym() + num(convCny(r.cost_price_cny !== undefined ? r.cost_price_cny : usdToCur(r.cost_price)), 2) + "</td>" +
              '<td class="num ' + cls(r.pnl_cny) + '">' + signedMoney(r.pnl_cny, 2) + "</td></tr>";
          }).join("")
        : '<tr><td colspan="6" class="pa-empty">还没有记录：在后台「传统交易台账」登记卖出即可累计</td></tr>';
    }
  }

  // ---------- 盈亏日历 ----------
  function cstToday() {
    var d = new Date(Date.now() + 8 * 3600 * 1000);
    return d.toISOString().slice(0, 10);
  }
  function calState() {
    if (!state.calY) {
      var latest = (state.data.history || []).slice(-1)[0];
      var ds = (latest && latest.date) || cstToday();
      state.calY = +ds.slice(0, 4);
      state.calM = +ds.slice(5, 7) - 1;
    }
  }
  // ---------- 盈亏分析 ----------
  function renderPnlAnalysis() {
    var box = $("pnl-analysis");
    if (!box) return;
    var pb = state.data.pnl_breakdown;
    if (!pb || !pb.groups) {
      box.innerHTML = '<p class="pa-empty">该日快照未记录盈亏分析明细</p>';
      if ($("pa-desc")) $("pa-desc").hidden = true;
      return;
    }
    if ($("pa-desc")) {
      $("pa-desc").hidden = false;
      $("pa-desc").textContent = "上一快照：" + (pb.prev_date || "—") +
        " · 汇率 " + num(pb.fx_usdcny, 4) +
        " · 当日浮动收益 = 上一快照份额 ×（现价 − 上一快照价）× 汇率；未实现盈亏 = 现价市值 − 成本";
    }
    var html = pb.groups.filter(function (g) { return g.key !== "cash"; }).map(function (g) {
      var rows = (g.items || []).map(function (i) {
        var diff = (i.price !== null && i.price !== undefined && i.prev_price !== null && i.prev_price !== undefined)
          ? i.price - i.prev_price : null;
        var prevTxt = (i.prev_price === null || i.prev_price === undefined ? "—" :
          num(i.prev_price, 4) + (i.prev_date ? ' <span class="pa-dim">(' + i.prev_date + ")</span>" : ""));
        var sym = (i.currency === "USD" || i.currency === "USDT") ? "$" : "¥";
        var priceTxt = (i.price === null || i.price === undefined ? "—" : sym + num(i.price, 4));
        var prevSymTxt = (i.prev_price === null || i.prev_price === undefined ? "—" :
          sym + num(i.prev_price, 4) + (i.prev_date ? ' <span class="pa-dim">(' + i.prev_date + ")</span>" : ""));
        return "<tr>" +
          "<td>" + escapeHtml(i.name || i.id) + "</td>" +
          "<td>" + (i.shares === null || i.shares === undefined ? "—" : num(i.shares, 6)) + "</td>" +
          "<td>" + (i.cost_price === null || i.cost_price === undefined || i.cost_price === 0 && i.group === "cash" ? "—" :
            sym + num(i.cost_price, i.cost_price < 10 ? 4 : 2)) + "</td>" +
          "<td>" + priceTxt + "</td>" +
          "<td>" + prevSymTxt + "</td>" +
          "<td>" + (diff === null ? "—" :
            '<span class="' + cls(diff) + '">' + (diff >= 0 ? "+" : "−") + sym + num(Math.abs(diff), 4) + "</span>") + "</td>" +
          "<td>" + (i.value_cny === null || i.value_cny === undefined ? "—" : money(i.value_cny, 2)) + "</td>" +
          "<td>" + (i.cost_cny === null || i.cost_cny === undefined ? "—" : money(i.cost_cny, 2)) + "</td>" +
          "<td>" + (i.day_change_cny === null || i.day_change_cny === undefined ? "—" :
            '<span class="' + cls(i.day_change_cny) + '">' + signedMoney(i.day_change_cny, 2) + "</span>") + "</td>" +
          "<td>" + (i.pnl_cny === null || i.pnl_cny === undefined ? "—" :
            '<span class="' + cls(i.pnl_cny) + '">' + signedMoney(i.pnl_cny, 2) + "</span>") + "</td>" +
          "</tr>";
      }).join("");
      return '<div class="pa-group">' +
        '<div class="pa-head"><span class="pa-name">' + escapeHtml(g.name) + "</span>" +
        (function () {
          var un = Number(g.pnl_cny || 0), re = Number(g.realized_cny || 0), tot = un + re;
          var den = Number(g.cost_cny || 0);
          var p = den ? Math.round(tot / den * 10000) / 100 : null;
          return '<span class="pa-metric">总盈亏 ' +
            (g.pnl_cny === null || g.pnl_cny === undefined ? "—" :
              '<b class="' + cls(tot) + '">' + signedMoney(tot, 2) + "</b>" +
              (p === null ? "" : "（" + pct(p) + "）")) +
            '</span><span class="pa-metric pa-dim">未实现 ' + signedMoney(un, 2) +
            " · 已实现 " + signedMoney(re, 2) + "</span>";
        })() +
        '<span class="pa-metric">当日浮动收益 ' +
        (g.day_cny === null || g.day_cny === undefined ? "—" :
          '<b class="' + cls(g.day_cny) + '">' + signedMoney(g.day_cny, 2) + "</b>" +
          (g.day_pct === null || g.day_pct === undefined ? "" : "（" + pct(g.day_pct) + "）")) +
        '</span>' +
        '<span class="pa-metric pa-dim">成本 ' + money(g.cost_cny || 0, 2) + "</span></div>" +
        '<table class="pa-table"><thead><tr>' +
        "<th>标的</th><th>份额</th><th>成本价</th><th>现价</th><th>上一快照价</th><th>价差</th>" +
        "<th>市值</th><th>成本</th><th>当日浮动收益</th><th>未实现盈亏</th></tr></thead><tbody>" +
        (rows || '<tr><td colspan="10" class="pa-empty">无持仓</td></tr>') +
        "</tbody></table></div>";
    }).join("");
    var sumPnl = totalPnlOf(pb);
    var s2 = (state.data && state.data.summary) || {};
    var realC = Number(s2.crypto_realized_cny || 0) + Number(s2.traditional_realized_cny || 0);
    var grand = sumPnl + realC;
    html += '<div class="pa-total">未实现盈亏 <b class="' + cls(sumPnl) + '">' + signedMoney(sumPnl, 2) +
      "</b> ＋ 已实现盈亏 <b class=\"" + cls(realC) + "\">" + signedMoney(realC, 2) +
      "</b> ＝ 总盈亏 <b class=\"" + cls(grand) + "\">" + signedMoney(grand, 2) +
      "</b> · 当日浮动收益 <b class=\"" + cls(totalDayOf(pb)) + "\">" +
      signedMoney(totalDayOf(pb), 2) + "</b></div>";
    box.innerHTML = html;
  }

  function totalPnlOf(pb) {
    return (pb.groups || []).filter(function (g) { return g.key !== "cash"; })
      .reduce(function (a, g) { return a + (g.pnl_cny || 0); }, 0);
  }
  function totalDayOf(pb) {
    return (pb.groups || []).filter(function (g) { return g.key !== "cash"; })
      .reduce(function (a, g) { return a + (g.day_cny || 0); }, 0);
  }

  function renderCalendar() {
    calState();
    if (!state.calPeriod) state.calPeriod = "day";
    if (state.calPeriod !== "day") { renderPeriodGrid(); return; }
    var y = state.calY, m = state.calM;
    var hist = (state.replay ? ((state.base || {}).history || []) : (state.data.history || []));
    var today = cstToday();
    var first = new Date(y, m, 1);
    var lastDay = new Date(y, m + 1, 0).getDate();
    var startDow = (first.getDay() + 6) % 7;
    var prefix = y + "-" + String(m + 1).padStart(2, "0");
    var dows = ["一", "二", "三", "四", "五", "六", "日"];
    var html = '<div class="cal-nav"><button type="button" id="cal-prev" aria-label="上个月">‹</button>' +
      "<span>" + y + "-" + String(m + 1).padStart(2, "0") + "</span>" +
      '<button type="button" id="cal-next" aria-label="下个月">›</button></div>';
    html += '<div class="cal-grid">' + dows.map(function (d) { return '<div class="cal-dow">' + d + "</div>"; }).join("");
    for (var day = 1; day <= lastDay; day++) {
      var ds = prefix + "-" + String(day).padStart(2, "0");
      var rec = null;
      for (var k = 0; k < hist.length; k++) { if (hist[k].date === ds) { rec = hist[k]; break; } }
      var v = rec && rec.day_change_cny !== null && rec.day_change_cny !== undefined ? rec.day_change_cny : null;
      var cls = "cal-cell";
      // 复现态下，晚于快照日期的格子属于「尚未发生」，按未来态灰显，不加今天高亮
      var cutoff = state.replay || today;
      if (v !== null) cls += v >= 0 ? " pos" : " neg";
      if (ds === today && !state.replay) cls += " today";
      if (ds > cutoff && v === null) cls += " future";
      if (rec) cls += " has";
      if (ds === state.calSel) cls += " sel";
      var vStr = v !== null ? (v >= 0 ? "+" : "−") + curSym() + num(Math.abs(convCny(v)), 0) : "—";
      var colStyle = day === 1 ? ' style="grid-column-start:' + (startDow + 1) + '"' : "";
      var dataAttr = rec ? ' data-date="' + ds + '"' : "";
      var titleAttr = rec ? ' title="点击查看 ' + ds + " 的当日快照\"" : "";
      html += '<div class="' + cls + '"' + colStyle + dataAttr + titleAttr + '><div class="d">' + day +
        '</div><div class="v">' + vStr + "</div></div>";
    }
    html += "</div>";
    $("pnl-calendar").innerHTML = html;

    $("cal-prev").onclick = function () {
      state.calM--; if (state.calM < 0) { state.calM = 11; state.calY--; } renderCalendar();
    };
    $("cal-next").onclick = function () {
      state.calM++; if (state.calM > 11) { state.calM = 0; state.calY++; } renderCalendar();
    };
    bindCalTip();
    $("pnl-calendar").onclick = function (e) {
      var cell = e.target.closest("[data-date]");
      if (!cell) return;
      var ds = cell.getAttribute("data-date");
      if (state.replay === ds) { exitReplay(); return; }
      enterReplay(ds);
    };
  }

  // ISO 周号
  function isoWeek(d) {
    var t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    var dayNum = t.getUTCDay() || 7;
    t.setUTCDate(t.getUTCDate() + 4 - dayNum);
    var ys = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
    return { year: t.getUTCFullYear(), week: Math.ceil((((t - ys) / 86400000) + 1) / 7) };
  }
  function weekLabel(y, w) {
    var jan4 = new Date(Date.UTC(y, 0, 4));
    var mon = new Date(jan4);
    mon.setUTCDate(jan4.getUTCDate() - ((jan4.getUTCDay() || 7) - 1) + (w - 1) * 7);
    var sun = new Date(mon);
    sun.setUTCDate(mon.getUTCDate() + 6);
    var f = function (d) { return (d.getUTCMonth() + 1) + "." + d.getUTCDate(); };
    return f(mon) + "-" + f(sun);
  }
  // 按周期聚合当日浮动收益
  function aggPnl(period) {
    var hist = state.data.history || [];
    var g = {};
    var cnt = {};
    var first = {}, last = {};
    var firstSnap = {}, lastSnap = {};
    hist.forEach(function (h) {
      if (h.day_change_cny === null || h.day_change_cny === undefined) return;
      var d = new Date(h.date + "T00:00:00");
      var key;
      if (period === "week") { var w = isoWeek(d); key = w.year + "-W" + String(w.week).padStart(2, "0"); }
      else if (period === "month") { key = h.date.slice(0, 7); }
      else { key = String(d.getFullYear()); }
      g[key] = (g[key] || 0) + h.day_change_cny;
      cnt[key] = (cnt[key] || 0) + 1;
      if (!first[key] || h.date < first[key]) { first[key] = h.date; firstSnap[key] = h; }
      if (!last[key] || h.date > last[key]) { last[key] = h.date; lastSnap[key] = h; }
    });
    var out = {};
    Object.keys(g).forEach(function (k) {
      var fs = firstSnap[k] || {}, ls = lastSnap[k] || {};
      out[k] = {
        value: g[k], count: cnt[k], from: first[k], to: last[k],
        // 期初 = 周期首日收盘总资产；期末 = 周期末日收盘总资产（均为真实快照，不再用日变动反推）
        start_total: fs.total_cny || 0,
        end_total: ls.total_cny || 0,
        start_date: first[k],
        end_date: last[k],
      };
    });
    return out;
  }
  function renderPeriodGrid() {
    var period = state.calPeriod;
    var data = aggPnl(period);
    var y = state.calY, m = state.calM;
    var items = [], navLabel = "", cols = 2, showNav = false;
    if (period === "week") {
      navLabel = y + "-" + String(m + 1).padStart(2, "0");
      cols = 2; showNav = true;
      var monthStart = new Date(y, m, 1), monthEnd = new Date(y, m + 1, 0);
      var startDow = (monthStart.getDay() + 6) % 7;
      var cur = new Date(monthStart);
      cur.setDate(cur.getDate() - startDow);
      while (cur <= monthEnd) {
        var w2 = isoWeek(cur);
        var key2 = w2.year + "-W" + String(w2.week).padStart(2, "0");
        items.push([key2, weekLabel(w2.year, w2.week), data[key2] || null]);
        cur = new Date(cur); cur.setDate(cur.getDate() + 7);
      }
    } else if (period === "month") {
      navLabel = y + " 年"; cols = 4; showNav = true;
      for (var mm = 1; mm <= 12; mm++) {
        var k = y + "-" + String(mm).padStart(2, "0");
        items.push([k, mm + " 月", data[k] || null]);
      }
    } else {
      cols = 3;
      var years = Object.keys(data).map(function (x) { return +x; });
      var minY = years.length ? Math.min.apply(null, years) : y;
      var maxY = Math.max(y, new Date().getFullYear());
      for (var yy = minY; yy <= maxY; yy++) {
        items.push([String(yy), yy + " 年", data[String(yy)] || null]);
      }
    }
    var html = showNav ? '<div class="cal-nav"><button type="button" id="cal-prev">‹</button><span>' +
      navLabel + '</span><button type="button" id="cal-next">›</button></div>' : "";
    html += '<div class="pnl-blocks" style="grid-template-columns:repeat(' + cols + ',minmax(0,1fr))">';
    items.forEach(function (it) {
      var key = it[0], label = it[1], rec = it[2];
      var cls = "pnl-block " + (rec === null ? "zero" : (rec.value > 0 ? "pos" : (rec.value < 0 ? "neg" : "zero")));
      if (key === state.calKey) cls += " sel";
      var vstr = rec === null ? "—" : (rec.value >= 0 ? "+" : "−") + curSym() + num(Math.abs(convCny(rec.value)), 0);
      var blocked = rec === null ? "" :
        ' data-open="' + Number(rec.start_total || 0) + '" data-end="' + Number(rec.end_total || 0) +
        '" data-pnl="' + Number(rec.value || 0) + '"';
      html += '<div class="' + cls + '" data-key="' + key + '" data-label="' + label + '"' + blocked +
        '><div class="pb-label">' + label +
        '</div><div class="pb-val">' + vstr + "</div></div>";
    });
    html += "</div>";
    $("pnl-calendar").innerHTML = html;

    if (showNav) {
      $("cal-prev").onclick = function () {
        if (period === "month") { state.calY--; } else {
          state.calM--; if (state.calM < 0) { state.calM = 11; state.calY--; }
        }
        renderCalendar();
      };
      $("cal-next").onclick = function () {
        if (period === "month") { state.calY++; } else {
          state.calM++; if (state.calM > 11) { state.calM = 0; state.calY++; }
        }
        renderCalendar();
      };
    }
    $("pnl-calendar").onclick = function (e) {
      var cell = e.target.closest("[data-key]");
      if (!cell) return;
      var key = cell.getAttribute("data-key");
      var rec = data[key];
      if (!rec) return;
      state.calKey = (state.calKey === key) ? null : key;
      renderCalendar();
      if (state.calKey) openAggSnapshot(period, key, rec);
    };
  }
  function openAggSnapshot(period, key, rec) {
    var label = period === "week" ? "周" : (period === "month" ? "月" : "年");
    var cls2 = cls(rec.value);
    var rows = [
      ["周期", label + " " + key],
      ["数据区间", rec.from + " ~ " + rec.to],
      ["期初资产（" + (rec.start_date || "首日") + " 收盘）", money(rec.start_total)],
      ["期末资产（" + (rec.end_date || "末日") + " 收盘）", money(rec.end_total)],
      ["期末 − 期初", '<span class="' + cls(rec.end_total - rec.start_total) + '">' +
        signedMoney(rec.end_total - rec.start_total) + "</span>"],
      ["有数据天数", rec.count + " 天"],
      ["累计浮动收益", '<span class="' + cls2 + '">' + signedMoney(rec.value) + "</span>"],
      ["日均浮动收益", signedMoney(rec.value / rec.count)],
    ];
    var html = '<div class="snap-box"><div class="snap-head"><h3>' + label + "度汇总 · " + key + "</h3>" +
      '<button type="button" id="snap-close" aria-label="关闭">×</button></div>' +
      '<div class="snap-rows">' + rows.map(function (r) {
        return '<div class="snap-row"><span>' + r[0] + "</span><span>" + r[1] + "</span></div>";
      }).join("") + "</div>" +
      '<p class="snap-note">按每日快照的浮动收益求和；某天无快照则不计入。</p></div>';
    showSnapMask(html);
  }
  function bindCalTip() {
    var box = $("pnl-calendar");
    var tip = document.getElementById("cal-tip");
    if (!tip) {
      tip = document.createElement("div");
      tip.id = "cal-tip";
      tip.className = "cal-tip";
      tip.hidden = true;
      document.body.appendChild(tip);
    }
    function show(e) {
      var cell = e.target.closest(".pnl-block");
      if (!cell || !cell.getAttribute("data-open")) { tip.hidden = true; return; }
      var label = cell.getAttribute("data-label") || "";
      var pv = parseFloat(cell.getAttribute("data-pnl")) || 0;
      tip.innerHTML = '<div class="tip-label">' + label + "</div>" +
        '<div class="tip-row"><span>累计浮动收益</span><span class="' + (pv >= 0 ? "pos" : "neg") +
        '">' + signedMoney(pv) + "</span></div>" +
        '<div class="tip-row"><span>期初资产（首日）</span><span>' + money(parseFloat(cell.getAttribute("data-open"))) + "</span></div>" +
        '<div class="tip-row"><span>期末资产（末日）</span><span>' + money(parseFloat(cell.getAttribute("data-end"))) + "</span></div>" +
        '<div class="tip-row"><span>期末 − 期初</span><span class="' +
        ((parseFloat(cell.getAttribute("data-end")) - parseFloat(cell.getAttribute("data-open"))) >= 0 ? "pos" : "neg") +
        '">' + signedMoney(parseFloat(cell.getAttribute("data-end")) - parseFloat(cell.getAttribute("data-open"))) + "</span></div>";
      tip.hidden = false;
      var x = e.clientX + 12, y = e.clientY - 10;
      tip.style.left = Math.min(x, document.documentElement.clientWidth - tip.offsetWidth - 8) + "px";
      tip.style.top = Math.max(8, y - tip.offsetHeight) + "px";
    }
    function hide() { tip.hidden = true; }
    box.addEventListener("mousemove", show);
    box.addEventListener("mouseleave", hide);
    box.addEventListener("touchstart", function (e) {
      var cell = e.target.closest(".pnl-block");
      if (!cell) return;
      var r = cell.getBoundingClientRect();
      var fake = { target: cell, clientX: r.left + r.width / 2, clientY: r.top };
      show(fake);
      setTimeout(hide, 2200);
    }, { passive: true });
  }

  function showSnapMask(html) {
    var mask = document.createElement("div");
    mask.className = "snap-mask";
    mask.id = "snap-mask";
    mask.innerHTML = html;
    document.body.appendChild(mask);
    function close() {
      var el = $("snap-mask");
      if (el) el.parentNode.removeChild(el);
      state.calSel = null; state.calKey = null;
      renderCalendar();
    }
    mask.onclick = function (e) { if (e.target === mask) close(); };
    $("snap-close").onclick = close;
    document.addEventListener("keydown", function esc(ev) {
      if (ev.key === "Escape") { close(); document.removeEventListener("keydown", esc); }
    });
  }

  function openSnapshot(ds) {
    var hist = state.data.history || [];
    var rec = null;
    for (var k = 0; k < hist.length; k++) { if (hist[k].date === ds) { rec = hist[k]; break; } }
    if (!rec) return;
    var chg = rec.day_change_cny;
    var chgCls = chg === null || chg === undefined ? "" : cls(chg);
    var chgTxt = chg === null || chg === undefined ? "—" :
      signedMoney(chg) +
      (rec.day_change_pct !== null && rec.day_change_pct !== undefined ? "（" + pct(rec.day_change_pct) + "）" : "");
    var cash = rec.cash_cny;
    var rows = [
      ["总资产", money(rec.total_cny)],
      ["传统股票 & 基金", money(rec.traditional_cny)],
      ["加密货币账户合计", money(rec.crypto_cny)],
      ["其中 现金（稳定币）", cash === null || cash === undefined ? "—" : money(cash)],
      ["当日浮动收益", '<span class="' + chgCls + '">' + chgTxt + "</span>"],
      ["USD→CNY 汇率", rec.fx_usdcny ? num(rec.fx_usdcny, 4) : "—"],
      ["加密账户 USDT 总额", rec.crypto_usdt ? "$" + num(rec.crypto_usdt, 2) : "—"],
    ];
    var html = '<div class="snap-box"><div class="snap-head"><h3>' + ds + " 快照</h3>" +
      '<button type="button" id="snap-close" aria-label="关闭">×</button></div>' +
      '<div class="snap-rows">' + rows.map(function (r) {
        return '<div class="snap-row"><span>' + r[0] + "</span><span>" + r[1] + "</span></div>";
      }).join("") + "</div>" +
      '<p class="snap-note">快照为当日构建时落库的数据；份额、成本价与价格均按当日口径。</p></div>';
    var mask = document.createElement("div");
    mask.className = "snap-mask";
    mask.id = "snap-mask";
    mask.innerHTML = html;
    document.body.appendChild(mask);
    function close() {
      var el = $("snap-mask");
      if (el) el.parentNode.removeChild(el);
      state.calSel = null;
      renderCalendar();
    }
    mask.onclick = function (e) { if (e.target === mask) close(); };
    $("snap-close").onclick = close;
    document.addEventListener("keydown", function esc(ev) {
      if (ev.key === "Escape") { close(); document.removeEventListener("keydown", esc); }
    });
  }

  // ---------- 趋势 ----------
  function trGold() { return isDark() ? "#f5b301" : "#d4a017"; }
  var TR_GOLD = "#d4a017", TR_UP = "#16a34a", TR_DOWN = "#dc2626";
  function trUp() { return isDark() ? "#34d399" : "#16a34a"; }
  function trDown() { return isDark() ? "#f87171" : "#dc2626"; }
  function trTip(rec) {
    function cny(v) { return (v === null || v === undefined) ? '<span class="pa-dim">—</span>' : money(v); }
    function signed(v) {
      if (v === null || v === undefined) return '<span class="pa-dim">—</span>';
      return '<span class="' + (v >= 0 ? "pos" : "neg") + '">' + signedMoney(v) + "</span>";
    }
    return '<div class="tr-tip"><div class="tr-tip-h">' + rec.date + '</div>' +
      '<div>总资产&nbsp;&nbsp;' + cny(rec.total_cny) + "</div>" +
      '<div>总盈亏&nbsp;&nbsp;' + signed(rec.total_pnl_cny) + "</div>" +
      '<div>传统&nbsp;&nbsp;' + cny(rec.traditional_cny) + "（" + signed(rec.traditional_pnl_cny) + "）</div>" +
      '<div>加密（币类）&nbsp;&nbsp;' + cny(rec.crypto_coin_cny) + "（" + signed(rec.crypto_pnl_cny) + "）</div>" +
      '<div>现金&nbsp;&nbsp;' + cny(rec.cash_cny) + "</div>" +
      '<div>当日浮动&nbsp;&nbsp;' + signed(rec.day_change_cny) +
      (rec.day_change_pct === null || rec.day_change_pct === undefined ? "" : "（" + pct(rec.day_change_pct) + "）") +
      "</div></div>";
  }

  function renderTrend() {
    // 趋势图始终展示完整历史，切换历史快照复现时不回退
    var h = (state.base || state.data).history || [];
    if (!window.echarts) {
      $("trend-chart").innerHTML = '<p class="empty-tip">图表库未加载，趋势暂不可用</p>';
      return;
    }
    if (!state.trend) state.trend = echarts.init($("trend-chart"));
    var dates = h.map(function (x) { return x.date; });
    var byDate = {};
    h.forEach(function (x) { byDate[x.date] = x; });
    var total = h.map(function (x) {
      return (x.total_cny === null || x.total_cny === undefined) ? "-" : Math.round(convCny(x.total_cny));
    });
    var pnl = h.map(function (x) {
      return (x.total_pnl_cny === null || x.total_pnl_cny === undefined) ? null : Math.round(convCny(x.total_pnl_cny));
    });
    function pnlColor(v) { return v >= 0 ? trUp() : trDown(); }

    var pnlMin = null, pnlMax = null;
    pnl.forEach(function (v) {
      if (typeof v !== "number") return;
      pnlMin = pnlMin === null ? v : Math.min(pnlMin, v);
      pnlMax = pnlMax === null ? v : Math.max(pnlMax, v);
    });
    var margin = (pnlMax !== null && pnlMin !== null) ? Math.abs(pnlMax - pnlMin) * 0.06 : 0;
    if (pnlMin !== null) { pnlMin -= margin; pnlMax += margin; }

    // Catmull-Rom 平滑：把相邻两点拟合成 12 段折线，保留原始数据点作为锚点
    function smoothSegment(i, api) {
      if (i <= 0) return null;
      var p0 = pnl[i - 2], p1 = pnl[i - 1], p2 = pnl[i], p3 = pnl[i + 1];
      if (typeof p1 !== "number" || typeof p2 !== "number") return null;
      var hasP0 = typeof p0 === "number", hasP3 = typeof p3 === "number";
      var a = api.coord([i - 1, p1]), b = api.coord([i, p2]);
      var c0 = hasP0 ? p0 : p1 - (p2 - p1), c3 = hasP3 ? p3 : p2 + (p2 - p1);
      var steps = 12, pts = [];
      for (var k = 0; k <= steps; k++) {
        var t = k / steps;
        var v = 0.5 * ((2 * p1) + (-c0 + p2) * t +
          (2 * c0 - 5 * p1 + 4 * p2 - c3) * t * t +
          (-c0 + 3 * p1 - 3 * p2 + c3) * t * t * t);
        // 轻微限制过冲，避免曲线偏离真实数值太多
        if (pnlMin !== null) v = Math.max(pnlMin, Math.min(pnlMax, v));
        var y = api.coord([i, v])[1];
        pts.push({ x: a[0] + (b[0] - a[0]) * t, y: y, v: v });
      }
      return pts;
    }

    state.trend.setOption({
      grid: { left: 12, right: 56, top: 34, bottom: 26, containLabel: true },
      tooltip: Object.assign(tipSkin(), {
        trigger: "item",
        formatter: function (p) {
          var ds = (dates.indexOf(p.name) >= 0) ? p.name :
            (p.dataIndex !== undefined && dates[p.dataIndex]) || "";
          return trTip(byDate[ds] || { date: ds });
        },
      }),
      legend: { top: 0, itemWidth: 14, itemHeight: 9,
        textStyle: { fontSize: 11, color: cssVar("--muted", "#6b7280") },
        data: [{ name: "总资产", icon: "circle" }, { name: "总盈亏", icon: "circle" }] },
      xAxis: {
        type: "category",
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: cssVar("--line", "#e5e7eb") } },
        axisLabel: { color: cssVar("--muted", "#6b7280"), fontSize: 11, formatter: function (v) { return v.slice(5); } },
      },
      yAxis: [
        {
          type: "value", scale: true,
          axisLabel: {
            color: isDark() ? "#c9a227" : "#9a7b1f", fontSize: 11,
            formatter: function (v) {
              if (curCode() === "USD") {
                var a = Math.abs(v);
                return (v < 0 ? "−" : "") + "$" + (a >= 1000 ? (a / 1000).toFixed(1) + "k" : Math.round(a));
              }
              return v >= 10000 ? "¥" + (v / 10000).toFixed(1) + "万" : "¥" + Math.round(v);
            },
          },
          splitLine: { lineStyle: { color: isDark() ? "#16202e" : "#f1f3f5" } },
        },
        {
          type: "value", scale: true, position: "right",
          axisLabel: {
            color: cssVar("--muted", "#6b7280"), fontSize: 11,
            formatter: function (v) {
              var a = Math.abs(v);
              if (a < 1) return "0";
              return (v > 0 ? "+" : "−") + curSym() + (a >= 1000 ? (a / 1000).toFixed(1) + "k" : Math.round(a));
            },
          },
          splitLine: { show: false },
          splitNumber: 4,
        },
      ],
      series: [
        {
          name: "总资产", type: "line", yAxisIndex: 0, smooth: true,
          data: total.map(function (v, i) { return [dates[i], v]; }),
          symbol: "circle", symbolSize: 7,
          lineStyle: { width: 2.4, color: trGold() },
          itemStyle: { color: trGold(), borderColor: cssVar("--card", "#fff"), borderWidth: 1.5 },
          areaStyle: {
            color: {
              type: "linear", x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(212,160,23,.18)" },
                { offset: 1, color: "rgba(212,160,23,0)" },
              ],
            },
          },
        },
        // 总盈亏：自定义绘制，逐段按 0 值水平线着色（0 上方绿、0 下方红）
        {
          name: "总盈亏", type: "custom", yAxisIndex: 1, z: 3,
          itemStyle: { color: trUp() },
          data: pnl.map(function (v, i) { return [i, v]; }),
          encode: { x: 0, y: 1 },
          renderItem: function (params, api) {
            var i = params.dataIndex;
            var v1 = api.value(1, i);
            var out = [];
            if (typeof v1 !== "number") return { type: "group", children: out };
            var pts = smoothSegment(i, api);
            if (pts && pts.length > 1) {
              var run = [pts[0]];
              for (var k = 1; k < pts.length; k++) {
                run.push(pts[k]);
                var crossed = (pts[k - 1].v >= 0 && pts[k].v < 0) || (pts[k - 1].v < 0 && pts[k].v >= 0);
                if (crossed || k === pts.length - 1) {
                  out.push({ type: "polyline", shape: { points: run.map(function (q) { return [q.x, q.y]; }) },
                    style: { stroke: pnlColor((run[0].v + run[run.length - 1].v) / 2), fill: null, lineWidth: 2 } });
                  run = [pts[k]];
                }
              }
            }
            var p1 = api.coord([i, v1]);
            out.push({ type: "circle", shape: { cx: p1[0], cy: p1[1], r: 3.4 },
              style: { fill: pnlColor(v1), stroke: "#fff", lineWidth: 1.2 } });
            return { type: "group", children: out };
          },
        },
      ],
    }, true);
    state.trend.resize();

    $("trend-tip").textContent = h.length === 1
      ? "已有 1 个每日快照（" + h[0].date + "）。后台每日构建后会累积成趋势曲线。"
      : "共 " + h.length + " 个每日快照（" + h[0].date + " ~ " + h[h.length - 1].date + "），金线=总资产（左轴），红绿线=总盈亏（右轴，0 上方绿、0 下方红）。";
  }

  // ---------- 数据来源 ----------
  function renderSources() {
    var m = state.data.meta || {};
    var s = m.sources || {};
    var cm = state.data.crypto_meta || {};
    var rows = [
      "<li>传统标的价格：<strong>" + escapeHtml(s.traditional_price || "腾讯实时 / 东方财富基金 / Yahoo") +
      "</strong>，取自「全球资产仪表台」已抓取的行情 <code>" +
      escapeHtml(s.traditional_price_url || "—") + "</code>，缺失时本地回退抓取。</li>",
      "<li>加密资产：<strong>直连 Bitget 私有接口</strong>读取现货账户与理财（Earn）持仓，本快照 " +
      escapeHtml(cm.snapshot_date || "—") + " 合计 <strong>" + num(cm.total_usdt) + " USDT</strong>；" +
      "接口读不到的仓位（如 PoolX 锁仓）在「份额维护后台」手工登记进出，本仪表台不再依赖任何上游加密仪表台。</li>",
      "<li>加密成本：以 <code>data/crypto_cost.json</code> 的校准点为起点，" +
      "用 <code>data/bitget_ledger.json</code> 记录的成交（fills）逐笔回放买入/卖出，" +
      "按平均成本法自动维护成本价，无需手工填写。</li>",
      "<li>汇率：USD/USDT → CNY = <strong>" + num((m.fx || {}).usdcny, 4) + "</strong>（" +
      escapeHtml((m.fx || {}).source || "—") + "）。</li>",
      "<li>份额与成本人工维护：仅 <code>data/holdings.json</code> 中的 <code>shares</code> 与 <code>cost_price</code>（传统标的）；" +
      "市值、盈亏、占比、日历与趋势全部由 <code>scripts/build.py</code> 自动计算。</li>",
    ];
    $("source-list").innerHTML = rows.join("");
  }

  // ---------- 交互 ----------
  function bindDisclaimer() {
    $("toggle-disclaimer").addEventListener("click", function () {
      var el = $("disclaimer");
      el.hidden = !el.hidden;
      this.textContent = el.hidden ? "口径与说明" : "收起说明";
    });
  }

  function bindResize() {
    var t;
    window.addEventListener("resize", function () {
      clearTimeout(t);
      t = setTimeout(function () {
        if (state.donut) state.donut.resize();
        if (state.trend) state.trend.resize();
        renderFlow();
      }, 120);
    });
  }

  function bindCalTabs() {
    var box = $("cal-tabs");
    if (!box) return;
    box.addEventListener("click", function (e) {
      var btn = e.target.closest(".seg-btn");
      if (!btn) return;
      state.calPeriod = btn.getAttribute("data-period");
      state.calKey = null;
      Array.prototype.forEach.call(box.children, function (b) { b.classList.toggle("active", b === btn); });
      renderCalendar();
    });
  }

  function init() {
    if ($("btn-back-today")) $("btn-back-today").addEventListener("click", exitReplay);
    bindTheme();
    bindCurrency();
    bindTabs();
    bindPanel();
    bindRefreshPrice();
    bindSort();
    bindPinLock();
    bindCalTabs();
    bindDisclaimer();
    bindResize();
    load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
