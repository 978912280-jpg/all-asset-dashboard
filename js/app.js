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

  function moneyLine(prefix, val, pctVal) {
    if (val === null || val === undefined) return '<span class="muted">' + prefix + '—</span>';
    return '<span class="' + cls(val) + '">' + prefix + (val >= 0 ? "+" : "−") +
      "¥" + num(Math.abs(val)) + (pctVal === null || pctVal === undefined ? "" :
        ' <span class="nowrap">（' + pct(pctVal) + "）</span>") + "</span>";
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
        label: "总资产 (CNY)",
        value: "¥" + num(s.total_cny),
        small: false,
        delta: moneyLine(state.replay ? "当日浮动收益 " : "今日浮动收益 ", day, s.day_change_pct) +
          (totalPnl === null || totalPnl === undefined ? "" :
            "<br>" + moneyLine("总盈亏 ", totalPnl, s.total_pnl_pct)),
      },
      {
        label: '<i class="dot trad"></i>传统股票 & 基金',
        value: "¥" + num(s.traditional_cny),
        small: true,
        delta: moneyLine("今日浮动收益 ", s.traditional_day_change_cny, s.traditional_day_change_pct) +
          "<br>" + (!hasTradCost
            ? '<span class="muted">总盈亏待填成本价</span>'
            : moneyLine("总盈亏 ", tradPnl, s.traditional_pnl_pct)),
      },
      {
        label: '<i class="dot crypto"></i>加密货币',
        value: "¥" + num(s.crypto_cny),
        small: true,
        delta: moneyLine(state.replay ? "当日浮动收益 " : "今日浮动收益 ", s.crypto_day_change_cny, s.crypto_day_change_pct) +
          "<br>" + moneyLine("总盈亏 ", cryptoPnl, s.crypto_pnl_pct),
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
        label: "小额合计 " + (smallVal / sumAll * 100).toFixed(1) + "%",
        full: "低于 1% 的标的合计",
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
    var sortKey = state.sortKey || "value_cny";
    var dir = state.sortDir === "asc" ? 1 : -1;
    items.sort(function (a, b) {
      // 现金没有「浮动收益」口径，按浮动收益排序时视为空值排到最后
      var av = (sortKey === "day_change_cny" && a.group === "cash") ? null : a[sortKey];
      var bv = (sortKey === "day_change_cny" && b.group === "cash") ? null : b[sortKey];
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
        pnlTxt = '<span class="' + cls(dc) + '">' + (dc >= 0 ? "+" : "−") + "¥" + num(Math.abs(dc)) + sub + "</span>";
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
        '<td class="num">' + (i.value_cny === null ? "—" : "¥" + num(i.value_cny)) + "</td>" +
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
      '<td class="num">¥' + num(sumVal) + "</td>" +
      '<td class="num ' + cls(sumPnl) + '">' + (sumPnl >= 0 ? "+" : "−") + "¥" + num(Math.abs(sumPnl)) + "</td>" +
      '<td class="num">' + sumWTxt + "</td></tr>";
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
        " · 当日浮动收益 = 上一快照份额 ×（现价 − 上一快照价）× 汇率；净盈亏 = 现价市值 − 成本";
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
          "<td>" + (i.value_cny === null || i.value_cny === undefined ? "—" : "¥" + num(i.value_cny, 2)) + "</td>" +
          "<td>" + (i.cost_cny === null || i.cost_cny === undefined ? "—" : "¥" + num(i.cost_cny, 2)) + "</td>" +
          "<td>" + (i.day_change_cny === null || i.day_change_cny === undefined ? "—" :
            '<span class="' + cls(i.day_change_cny) + '">' + (i.day_change_cny >= 0 ? "+" : "−") + "¥" + num(Math.abs(i.day_change_cny), 2) + "</span>") + "</td>" +
          "<td>" + (i.pnl_cny === null || i.pnl_cny === undefined ? "—" :
            '<span class="' + cls(i.pnl_cny) + '">' + (i.pnl_cny >= 0 ? "+" : "−") + "¥" + num(Math.abs(i.pnl_cny), 2) + "</span>") + "</td>" +
          "</tr>";
      }).join("");
      return '<div class="pa-group">' +
        '<div class="pa-head"><span class="pa-name">' + escapeHtml(g.name) + "</span>" +
        '<span class="pa-metric">净盈亏 ' +
        (g.pnl_cny === null || g.pnl_cny === undefined ? "—" :
          '<b class="' + cls(g.pnl_cny) + '">' + (g.pnl_cny >= 0 ? "+" : "−") + "¥" + num(Math.abs(g.pnl_cny), 2) + "</b>" +
          (g.pnl_pct === null || g.pnl_pct === undefined ? "" : "（" + pct(g.pnl_pct) + "）")) +
        '</span><span class="pa-metric">当日浮动收益 ' +
        (g.day_cny === null || g.day_cny === undefined ? "—" :
          '<b class="' + cls(g.day_cny) + '">' + (g.day_cny >= 0 ? "+" : "−") + "¥" + num(Math.abs(g.day_cny), 2) + "</b>" +
          (g.day_pct === null || g.day_pct === undefined ? "" : "（" + pct(g.day_pct) + "）")) +
        '</span>' +
        (g.realized_cny
          ? '<span class="pa-metric">已实现 ' + (g.realized_cny >= 0 ? "+" : "−") + "¥" +
            num(Math.abs(g.realized_cny), 2) + "</span>"
          : "") +
        '<span class="pa-metric pa-dim">成本 ¥' + num(g.cost_cny || 0, 2) + "</span></div>" +
        '<table class="pa-table"><thead><tr>' +
        "<th>标的</th><th>份额</th><th>成本价</th><th>现价</th><th>上一快照价</th><th>价差</th>" +
        "<th>市值</th><th>成本</th><th>当日浮动收益</th><th>净盈亏</th></tr></thead><tbody>" +
        (rows || '<tr><td colspan="10" class="pa-empty">无持仓</td></tr>') +
        "</tbody></table></div>";
    }).join("") + '<div class="pa-total">合计：净盈亏 <b class="' + cls(totalPnlOf(pb)) + '">' +
      (totalPnlOf(pb) >= 0 ? "+" : "−") + "¥" + num(Math.abs(totalPnlOf(pb)), 2) +
      "</b> · 当日浮动收益 <b class=\"" + cls(totalDayOf(pb)) + "\">" +
      (totalDayOf(pb) >= 0 ? "+" : "−") + "¥" + num(Math.abs(totalDayOf(pb)), 2) + "</b></div>";
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
      var vStr = v !== null ? (v >= 0 ? "+" : "−") + "¥" + num(Math.abs(v), 0) : "—";
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
      var vstr = rec === null ? "—" : (rec.value >= 0 ? "+" : "−") + "¥" + num(Math.abs(rec.value), 0);
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
  var TR_GOLD = "#d4a017", TR_UP = "#16a34a", TR_DOWN = "#dc2626";
  function trTip(rec) {
    function cny(v) { return (v === null || v === undefined) ? '<span class="pa-dim">—</span>' : "¥" + num(v); }
    function signed(v) {
      if (v === null || v === undefined) return '<span class="pa-dim">—</span>';
      return '<span class="' + (v >= 0 ? "pos" : "neg") + '">' + (v >= 0 ? "+" : "−") + "¥" + num(Math.abs(v)) + "</span>";
    }
    return '<div class="tr-tip"><div class="tr-tip-h">' + rec.date + '</div>' +
      '<div>总资产&nbsp;&nbsp;' + cny(rec.total_cny) + "</div>" +
      '<div>总盈亏&nbsp;&nbsp;' + signed(rec.total_pnl_cny) + "</div>" +
      '<div>传统&nbsp;&nbsp;' + cny(rec.traditional_cny) + "（" + signed(rec.traditional_pnl_cny) + "）</div>" +
      '<div>加密&nbsp;&nbsp;' + cny(rec.crypto_cny) + "（" + signed(rec.crypto_pnl_cny) + "）</div>" +
      '<div>现金&nbsp;&nbsp;' + cny(rec.cash_cny) + "</div>" +
      '<div>当日浮动&nbsp;&nbsp;' + signed(rec.day_change_cny) +
      (rec.day_change_pct === null || rec.day_change_pct === undefined ? "" : "（" + pct(rec.day_change_pct) + "）") +
      "</div></div>";
  }

  function renderTrend() {
    var h = state.data.history || [];
    if (!window.echarts) {
      $("trend-chart").innerHTML = '<p class="empty-tip">图表库未加载，趋势暂不可用</p>';
      return;
    }
    if (!state.trend) state.trend = echarts.init($("trend-chart"));
    var dates = h.map(function (x) { return x.date; });
    var byDate = {};
    h.forEach(function (x) { byDate[x.date] = x; });
    var total = h.map(function (x) {
      return (x.total_cny === null || x.total_cny === undefined) ? "-" : Math.round(x.total_cny);
    });
    var pnl = h.map(function (x) {
      return (x.total_pnl_cny === null || x.total_pnl_cny === undefined) ? null : Math.round(x.total_pnl_cny);
    });
    function pnlColor(v) { return v >= 0 ? TR_UP : TR_DOWN; }

    state.trend.setOption({
      grid: { left: 12, right: 56, top: 34, bottom: 26, containLabel: true },
      tooltip: {
        trigger: "item",
        formatter: function (p) {
          var ds = (dates.indexOf(p.name) >= 0) ? p.name :
            (p.dataIndex !== undefined && dates[p.dataIndex]) || "";
          return trTip(byDate[ds] || { date: ds });
        },
      },
      legend: { top: 0, itemWidth: 14, itemHeight: 9, textStyle: { fontSize: 11 },
        data: [{ name: "总资产", icon: "circle" }, { name: "总盈亏", icon: "circle" }] },
      xAxis: {
        type: "category",
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: "#e5e7eb" } },
        axisLabel: { color: "#6b7280", fontSize: 11, formatter: function (v) { return v.slice(5); } },
      },
      yAxis: [
        {
          type: "value", scale: true,
          axisLabel: {
            color: "#9a7b1f", fontSize: 11,
            formatter: function (v) {
              return v >= 10000 ? "¥" + (v / 10000).toFixed(1) + "万" : "¥" + Math.round(v);
            },
          },
          splitLine: { lineStyle: { color: "#f1f3f5" } },
        },
        {
          type: "value", scale: true, position: "right",
          axisLabel: {
            color: "#6b7280", fontSize: 11,
            formatter: function (v) {
              var a = Math.abs(v);
              if (a < 1) return "0";
              return (v > 0 ? "+" : "−") + "¥" + (a >= 1000 ? (a / 1000).toFixed(1) + "k" : Math.round(a));
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
          lineStyle: { width: 2.4, color: TR_GOLD },
          itemStyle: { color: TR_GOLD, borderColor: "#fff", borderWidth: 1.5 },
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
          itemStyle: { color: TR_UP },
          data: pnl.map(function (v, i) { return [i, v]; }),
          encode: { x: 0, y: 1 },
          renderItem: function (params, api) {
            var i = params.dataIndex;
            var v1 = api.value(1, i);
            var pi = i - 1;
            var v0 = pi >= 0 ? api.value(1, pi) : null;
            var out = [];
            if (v0 !== null && v0 !== "-" && typeof v0 === "number" && typeof v1 === "number") {
              var a = api.coord([pi, v0]);
              var b = api.coord([i, v1]);
              function poly(pts, color) {
                return { type: "polyline", shape: { points: pts },
                  style: { stroke: color, fill: null, lineWidth: 2 } };
              }
              if ((v0 >= 0 && v1 >= 0) || (v0 < 0 && v1 < 0)) {
                out.push(poly([a, b], pnlColor(v1)));
              } else {
                var t = v0 === v1 ? 0 : v0 / (v0 - v1);
                var cx = a[0] + (b[0] - a[0]) * t, cy = a[1] + (b[1] - a[1]) * t;
                out.push(poly([a, [cx, cy]], pnlColor(v0)));
                out.push(poly([[cx, cy], b], pnlColor(v1)));
              }
            }
            if (typeof v1 === "number") {
              var p1 = api.coord([i, v1]);
              out.push({ type: "circle", shape: { cx: p1[0], cy: p1[1], r: 3.4 },
                style: { fill: pnlColor(v1), stroke: "#fff", lineWidth: 1.2 } });
            }
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
