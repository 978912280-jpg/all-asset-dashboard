/* 全维度资产统计 —— 前端渲染 */
(function () {
  "use strict";

  var state = {
    data: null,
    group: "all",
    donut: null,
    trend: null,
    groupColors: { traditional: "#1d4ed8", crypto: "#b45309", cash: "#0f766e" },
  };

  function $(id) { return document.getElementById(id); }

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
    renderSplit();
    renderTable();
    renderCalendar();
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
      $("update-time").textContent = "数据更新时间：" + m.generated_at.replace("T", " ");
    }
    if (m.version) {
      $("meta-version").textContent = "v" + m.version;
      $("footer-version").textContent = "v" + m.version;
    }
    if (m.subtitle) $("subtitle").textContent = m.subtitle;
    var fx = (m.fx || {}).usdcny;
    if (fx) {
      $("trend-desc").textContent = "每日快照 · USD/CNY " + fx.toFixed(4) + " · " +
        ((m.sources || {}).crypto_dashboard ? "加密快照" : "");
    }
  }

  // ---------- KPI ----------
  function renderKpi() {
    var s = state.data.summary || {};
    var day = s.day_change_cny;
    var tradPnl = s.traditional_pnl_cny;
    var cryptoPnl = s.crypto_pnl_cny;
    var hasTradCost = !!(s.traditional_cost_cny && s.traditional_cost_cny > 0);
    var fxRate = (((state.data || {}).meta || {}).fx || {}).usdcny || 0;
    var cards = [
      {
        label: "总资产 (CNY)",
        value: "¥" + num(s.total_cny),
        small: false,
        delta: (day === null || day === undefined ? "" :
          '<span class="' + cls(day) + '">' +
          (state.replay ? "当日浮动收益 " : "今日浮动收益 ") +
          (day >= 0 ? "+" : "") + num(day) +
          "（" + pct(s.day_change_pct) + "）</span>"),
      },
      {
        label: '<i class="dot trad"></i>传统股票 & 基金',
        value: "¥" + num(s.traditional_cny),
        small: true,
        delta: (!hasTradCost
          ? '<span class="muted">盈亏待填成本价</span>'
          : (tradPnl === null || tradPnl === undefined
            ? '<span class="muted">盈亏—</span>'
            : '<span class="' + cls(tradPnl) + '">总盈亏 ' + (tradPnl >= 0 ? "+" : "−") +
              "¥" + num(Math.abs(tradPnl)) + "（" + pct(s.traditional_pnl_pct) + "）</span>")),
      },
      {
        label: '<i class="dot crypto"></i>加密货币',
        value: "¥" + num(s.crypto_cny),
        small: true,
        delta: (cryptoPnl === null || cryptoPnl === undefined ? '<span class="muted">盈亏—</span>' :
          '<span class="' + cls(cryptoPnl) + '">总盈亏 ' + (cryptoPnl >= 0 ? "+" : "") +
          num(cryptoPnl) + "（" + pct(s.crypto_pnl_pct) + "）</span>"),
      },
      {
        label: '<i class="dot cash"></i>现金',
        value: "¥" + num(s.cash_cny || 0),
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
        escapeHtml((s.cost_pending_ids || []).join("、")) + "。填成本价后才会计算浮动盈亏与收益率。");
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
  function renderSplit() {
    var groups = state.data.groups || [];
    var colors = state.groupColors;

    // 图例
    $("split-legend").innerHTML = groups.map(function (g) {
      var color = colors[g.key] || "#374151";
      var items = (state.data.items || []).filter(function (i) { return i.group === g.key; });
      // 按资产类别汇总
      var byClass = {};
      items.forEach(function (i) {
        var k = i.asset_class || "其他";
        byClass[k] = (byClass[k] || 0) + (i.value_cny || 0);
      });
      var clsKeys = Object.keys(byClass);
      var subRows = (clsKeys.length < 2 ? [] : clsKeys).map(function (k) {
        var v = byClass[k];
        var p = (v / (g.cny || 1)) * 100;
        return '<div class="legend-sub"><span>' + escapeHtml(k) + "</span><span>" +
          "¥" + num(v) + " · " + p.toFixed(1) + "%</span></div>";
      }).join("");
      return '<div class="legend-row">' +
        '<div class="legend-top">' +
        '<span class="name"><i class="dot" style="background:' + color + '"></i>' +
        escapeHtml(g.name) + "</span>" +
        '<span class="legend-num">¥' + num(g.cny) + " · " + num(g.weight) + "%</span>" +
        "</div>" +
        '<div class="bar"><i style="width:' + Math.max(0, Math.min(100, g.weight || 0)) +
        "%;background:" + color + '"></i></div>' +
        subRows +
        "</div>";
    }).join("");

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

    // 低于 3% 的小块合并成一块，标签分行列出各自占比，只用一根引线
    var sumAll = slices.reduce(function (a, x) { return a + x.value; }, 0) || 1;
    var bigSlices = [], smallSlices = [];
    slices.forEach(function (x) {
      if (x.value / sumAll * 100 < 3) smallSlices.push(x); else bigSlices.push(x);
    });
    if (smallSlices.length > 1) {
      var smallVal = smallSlices.reduce(function (a, x) { return a + x.value; }, 0);
      var lines = smallSlices.map(function (x) {
        return x.label + " " + (x.value / sumAll * 100).toFixed(1) + "%";
      });
      bigSlices.push({
        label: "小额合计 " + (smallVal / sumAll * 100).toFixed(1) + "%",
        full: "低于 3% 的标的合计",
        value: smallVal,
        color: "#9aa5b1",
        detail: lines,
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
          text: "{a|总资产}\n{b|¥" + num(total) + "}",
          textAlign: "center",
          rich: {
            a: { fontSize: compact ? 9 : 10, fill: "#6b7280", lineHeight: compact ? 15 : 16 },
            b: { fontSize: compact ? 12 : 14, fontWeight: "bold", fill: "#1f2329", lineHeight: compact ? 17 : 19 },
          },
        },
      }],
      tooltip: {
        trigger: "item",
        formatter: function (p) {
          return (p.data.full || p.data.name) + "<br/>¥" + num(p.value) + "（" + p.percent.toFixed(2) + "%）";
        },
      },
      legend: { show: false },
      series: [{
        name: "资产占比",
        type: "pie",
        radius: compact ? ["34%", "54%"] : ["38%", "56%"],
        center: ["50%", "50%"],
        avoidLabelOverlap: true,
        minAngle: 1.5,
        labelLayout: function (params) {
          if (mergedIdx !== null && params.dataIndex === mergedIdx) {
            return { x: compact ? 84 : 112, y: compact ? 4 : 8, align: "left", verticalAlign: "top", moveOverlap: "none" };
          }
          return { moveOverlap: "shiftY" };
        },
        itemStyle: { borderColor: "#fff", borderWidth: 1 },
        label: {
          show: true,
          position: "outside",
          formatter: function (p) {
            if (p.data.detail) return p.data.label + "\n" + p.data.detail.join("\n");
            return p.data.label + "\n" + p.percent.toFixed(1) + "%";
          },
          fontSize: compact ? 8.5 : 9,
          color: "#374151",
          lineHeight: compact ? 11 : 12,
        },
        labelLine: {
          show: true,
          length: compact ? 6 : 8,
          length2: compact ? 8 : 12,
          smooth: true,
          lineStyle: { width: 1, color: "#9ca3af" },
        },
        emphasis: { label: { fontWeight: "bold", color: "#1f2329" }, scaleSize: 3 },
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
    items.sort(function (a, b) { return (b.value_cny || 0) - (a.value_cny || 0); });
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
      var costTxt = (i.group === "crypto" || i.group === "cash") ? '<span class="muted">—</span>'
        : (!i.cost_price ? '<span class="muted">待填</span>'
          : (i.currency === "USD" ? "$" : "¥") + num(i.cost_price, i.cost_price < 10 ? 4 : 2));
      var pnlTxt;
      // 浮动盈亏列统一按「当日浮动收益」口径：份额 × 当日涨跌（按标的币种折算成 CNY）
      var dc = i.day_change_cny;
      if (i.group === "cash") {
        pnlTxt = '<span class="muted">—</span>';
      } else if (dc === null || dc === undefined) {
        pnlTxt = '<span class="muted">—</span>';
      } else {
        var sub = i.day_basis === "new"
          ? '<div class="sub muted">当日买入</div>'
          : '<div class="sub ' + cls(i.change_pct) + '">' + pct(i.change_pct) + "</div>";
        pnlTxt = '<span class="' + cls(dc) + '">' + (dc >= 0 ? "+" : "") + num(dc) + sub + "</span>";
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
        '<td class="num">' + (i.value_cny === null ? "—" : num(i.value_cny)) + "</td>" +
        '<td class="num">' + pnlTxt + "</td>" +
        '<td class="num">' + num(scopeWeight(i)) + "%</td>" +
        "</tr>";
    }).join("");

    // 合计行：市值与当日浮动收益按当前筛选求和
    var sumVal = items.reduce(function (a, i) { return a + (i.value_cny || 0); }, 0);
    var sumPnl = items.reduce(function (a, i) { return a + (i.day_change_cny || 0); }, 0);
    var sumW = items.reduce(function (a, i) { return a + scopeWeight(i); }, 0);
    var sumWTxt = Math.abs(sumW - 100) < 0.05 ? "100.00%" : num(sumW, 2) + "%";
    $("table-foot").innerHTML = "<tr>" +
      '<td class="name-cell">合计</td><td></td><td></td><td></td><td></td>' +
      '<td class="num">' + num(sumVal) + "</td>" +
      '<td class="num ' + cls(sumPnl) + '">' + (sumPnl >= 0 ? "+" : "") + num(sumPnl) + "</td>" +
      '<td class="num">' + sumWTxt + "</td></tr>";
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
  function renderCalendar() {
    calState();
    if (!state.calPeriod) state.calPeriod = "day";
    if (state.calPeriod !== "day") { renderPeriodGrid(); return; }
    var y = state.calY, m = state.calM;
    var hist = state.data.history || [];
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
      if (v !== null) cls += v >= 0 ? " pos" : " neg";
      if (ds === today) cls += " today";
      if (ds > today && v === null) cls += " future";
      if (rec) cls += " has";
      if (ds === state.calSel) cls += " sel";
      var vStr = v !== null ? (v >= 0 ? "+" : "−") + num(Math.abs(v), 0) : "—";
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
        start_total: (fs.total_cny || 0) - (fs.day_change_cny || 0),
        end_total: ls.total_cny || 0,
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
      var vstr = rec === null ? "—" : (rec.value >= 0 ? "+" : "−") + num(Math.abs(rec.value), 0);
      var blocked = rec === null ? "" :
        ' data-open="' + num(rec.start_total) + '" data-end="' + num(rec.end_total) +
        '" data-pnl="' + rec.value + '"';
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
      ["期初资产", "¥" + num(rec.start_total)],
      ["期末资产", "¥" + num(rec.end_total)],
      ["有数据天数", rec.count + " 天"],
      ["累计浮动收益", '<span class="' + cls2 + '">' + (rec.value >= 0 ? "+" : "−") +
        "¥" + num(Math.abs(rec.value)) + "</span>"],
      ["日均浮动收益", (rec.value / rec.count >= 0 ? "+" : "−") + "¥" + num(Math.abs(rec.value / rec.count))],
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
        '">' + (pv >= 0 ? "+" : "−") + "¥" + num(Math.abs(pv)) + "</span></div>" +
        '<div class="tip-row"><span>期初资产</span><span>¥' + cell.getAttribute("data-open") + "</span></div>" +
        '<div class="tip-row"><span>期末资产</span><span>¥' + cell.getAttribute("data-end") + "</span></div>";
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
      (chg >= 0 ? "+" : "−") + "¥" + num(Math.abs(chg)) +
      (rec.day_change_pct !== null && rec.day_change_pct !== undefined ? "（" + pct(rec.day_change_pct) + "）" : "");
    var cash = rec.cash_cny;
    var rows = [
      ["总资产", "¥" + num(rec.total_cny)],
      ["传统股票 & 基金", "¥" + num(rec.traditional_cny)],
      ["加密货币账户合计", "¥" + num(rec.crypto_cny)],
      ["其中 现金（稳定币）", cash === null || cash === undefined ? "—" : "¥" + num(cash)],
      ["当日浮动收益", '<span class="' + chgCls + '">' + chgTxt + "</span>"],
      ["USD→CNY 汇率", rec.fx_usdcny ? num(rec.fx_usdcny, 4) : "—"],
      ["加密账户 USDT 总额", rec.crypto_usdt ? num(rec.crypto_usdt, 2) : "—"],
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
  function renderTrend() {
    var h = state.data.history || [];
    if (!window.echarts) {
      $("trend-chart").innerHTML = '<p class="empty-tip">图表库未加载，趋势暂不可用</p>';
      return;
    }
    if (!state.trend) state.trend = echarts.init($("trend-chart"));
    var dates = h.map(function (x) { return x.date; });
    var total = h.map(function (x) { return Math.round(x.total_cny || 0); });
    var trad = h.map(function (x) { return Math.round(x.traditional_cny || 0); });
    var crypto = h.map(function (x) { return Math.round(x.crypto_cny || 0); });

    state.trend.setOption({
      grid: { left: 12, right: 18, top: 34, bottom: 26, containLabel: true },
      tooltip: {
        trigger: "axis",
        valueFormatter: function (v) { return "¥" + num(v, 0); },
      },
      legend: { top: 0, itemWidth: 14, itemHeight: 9, textStyle: { fontSize: 11 } },
      xAxis: {
        type: "category",
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: "#e5e7eb" } },
        axisLabel: { color: "#6b7280", fontSize: 11, formatter: function (v) { return v.slice(5); } },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: {
          color: "#6b7280", fontSize: 11,
          formatter: function (v) { return v >= 10000 ? (v / 10000).toFixed(0) + "万" : v; },
        },
        splitLine: { lineStyle: { color: "#f1f3f5" } },
      },
      series: [
        {
          name: "总资产", type: "line", data: total, smooth: true,
          symbol: "circle", symbolSize: 5,
          lineStyle: { width: 2.4, color: "#14532d" },
          itemStyle: { color: "#14532d" },
          areaStyle: {
            color: {
              type: "linear", x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(20,83,45,.16)" },
                { offset: 1, color: "rgba(20,83,45,0)" },
              ],
            },
          },
        },
        {
          name: "传统股票&基金", type: "line", data: trad, smooth: true,
          symbol: "none", lineStyle: { width: 1.6, color: "#1d4ed8" },
          itemStyle: { color: "#1d4ed8" },
        },
        {
          name: "加密货币", type: "line", data: crypto, smooth: true,
          symbol: "none", lineStyle: { width: 1.6, color: "#b45309", type: "dashed" },
          itemStyle: { color: "#b45309" },
        },
      ],
    }, true);
    state.trend.resize();

    $("trend-tip").textContent = h.length === 1
      ? "已有 1 个每日快照（" + h[0].date + "）。后台每日构建后会累积成趋势曲线。"
      : "共 " + h.length + " 个每日快照（" + h[0].date + " ~ " + h[h.length - 1].date + "），每日构建自动累积。";
  }

  // ---------- 数据来源 ----------
  function renderSources() {
    var m = state.data.meta || {};
    var s = m.sources || {};
    var cryptoMeta = state.data.crypto_meta || {};
    var rows = [
      "<li>传统标的价格：<strong>" + escapeHtml(s.traditional_price || "—") + "</strong>；全球资产仪表台数据地址 <code>" +
      escapeHtml(s.traditional_price_url || "—") + "</code></li>",
      "<li>加密货币资产：<strong>加密货币资产仪表台</strong>（" + escapeHtml(cryptoMeta.snapshot_date || "—") +
      " 快照，现货 " + num(cryptoMeta.spot_usdt) + " + 理财 " + num(cryptoMeta.earn_usdt) +
      " = " + num(cryptoMeta.total_usdt) + " USDT）</li>",
      "<li>汇率：USD/USDT → CNY = <strong>" + num((m.fx || {}).usdcny, 4) + "</strong>（" +
      escapeHtml((m.fx || {}).source || "—") + "）</li>",
      "<li>份额与成本维护：<code>data/holdings.json</code> 中的 <code>shares</code> 与 <code>cost_price</code>，市值/盈亏/占比/趋势全部由 <code>scripts/build.py</code> 自动计算</li>",
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
    bindTabs();
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
