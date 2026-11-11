/* 全维度资产统计 —— 前端渲染 */
(function () {
  "use strict";

  var state = {
    data: null,
    group: "all",
    donut: null,
    trend: null,
    groupColors: { traditional: "#1d4ed8", crypto: "#b45309" },
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
        state.data = data;
        renderMeta();
        renderKpi();
        renderPending();
        renderSplit();
        renderTable();
        renderTrend();
        renderSources();
      })
      .catch(function (e) {
        $("table-body").innerHTML =
          '<tr><td colspan="10" class="muted" style="text-align:center;padding:24px">' +
          "数据加载失败：" + escapeHtml(e.message) +
          "（请确认 data/dashboard.json 已生成）</td></tr>";
      });
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
    var cards = [
      {
        label: "总资产 (CNY)",
        value: "¥" + num(s.total_cny),
        small: false,
        delta: (day === null || day === undefined ? "" :
          '<span class="' + cls(day) + '">今日浮动收益 ' + (day >= 0 ? "+" : "") + num(day) +
          "（" + pct(s.day_change_pct) + "）</span>"),
      },
      {
        label: '<i class="dot trad"></i>传统股票 & 基金',
        value: "¥" + num(s.traditional_cny),
        small: true,
        delta: "占比 " + num(s.traditional_weight) + "% · " +
          (!hasTradCost
            ? '<span class="muted">盈亏待填成本价</span>'
            : (tradPnl === null || tradPnl === undefined
              ? '<span class="muted">盈亏—</span>'
              : '<span class="' + cls(tradPnl) + '">总盈亏 ' + (tradPnl >= 0 ? "+" : "−") +
                "¥" + num(Math.abs(tradPnl)) + "（" + pct(s.traditional_pnl_pct) + "）</span>")) +
          (hasTradCost ? '<div class="kpi-sub">成本 ¥' + num(s.traditional_cost_cny) + "</div>" : ""),
      },
      {
        label: '<i class="dot crypto"></i>加密货币',
        value: "¥" + num(s.crypto_cny),
        small: true,
        delta: "占比 " + num(s.crypto_weight) + "% · " +
          (cryptoPnl === null || cryptoPnl === undefined ? '<span class="muted">盈亏—</span>' :
            '<span class="' + cls(cryptoPnl) + '">总盈亏 ' + (cryptoPnl >= 0 ? "+" : "") +
            num(cryptoPnl) + "（" + pct(s.crypto_pnl_pct) + "）</span>"),
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
      var subRows = Object.keys(byClass).map(function (k) {
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
      $("donut-chart").innerHTML = '<p class="empty-tip">图表库未加载，占比数据见左侧图例</p>';
      return;
    }
    var total = (state.data.summary || {}).total_cny || 0;
    if (!state.donut) state.donut = echarts.init($("donut-chart"));

    state.donut.setOption({
      tooltip: {
        trigger: "item",
        formatter: function (p) {
          return p.name + "<br/>¥" + num(p.value) + "（" + p.percent.toFixed(2) + "%）";
        },
      },
      legend: { show: false },
      series: [{
        name: "资产占比",
        type: "pie",
        radius: ["52%", "78%"],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: "#fff", borderWidth: 2 },
        label: {
          show: true,
          position: "center",
          formatter: function () { return "总资产\n¥" + num(total); },
          fontSize: 11,
          lineHeight: 18,
          color: "#6b7280",
        },
        emphasis: { label: { show: true, fontSize: 13, fontWeight: "bold", color: "#1f2329" } },
        data: groups.map(function (g) {
          return {
            name: g.name,
            value: Math.round(g.cny || 0),
            itemStyle: { color: colors[g.key] },
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

    if (!items.length) {
      $("table-body").innerHTML = "";
      $("empty-tip").hidden = false;
      return;
    }
    $("empty-tip").hidden = true;

    $("table-body").innerHTML = items.map(function (i) {
      var color = state.groupColors[i.group] || "#374151";
      var priceTxt = i.price === null || i.price === undefined ? "—" :
        (i.currency === "USD" ? "$" : i.currency === "USDT" ? "" : "¥") + num(i.price, i.price < 10 ? 4 : 2);
      var sharesTxt = num(i.shares, i.shares < 1 ? 6 : 4);
      var costTxt = i.group === "crypto" ? '<span class="muted">—</span>'
        : (!i.cost_price ? '<span class="muted">待填</span>'
          : (i.currency === "USD" ? "$" : "¥") + num(i.cost_price, i.cost_price < 10 ? 4 : 2));
      var pnlTxt;
      if (i.group === "crypto") {
        pnlTxt = '<span class="muted">—</span>';
      } else if (i.pnl_cny === null || i.pnl_cny === undefined) {
        pnlTxt = '<span class="muted">—</span>';
      } else {
        pnlTxt = '<span class="' + cls(i.pnl_cny) + '">' + (i.pnl_cny >= 0 ? "+" : "") + num(i.pnl_cny) +
          '<div class="sub ' + cls(i.pnl_pct) + '">' + pct(i.pnl_pct) + "</div></span>";
      }
      return "<tr>" +
        '<td class="name-cell"><div class="nm">' + escapeHtml(i.name) +
        (i.pending ? '<span class="tag pending">待填份额</span>' : "") +
        (i.note ? '<div class="sub">' + escapeHtml(i.note) + "</div>" : "") +
        "</div></td>" +
        '<td><span class="tag" style="border-color:' + color + '33;color:' + color +
        '">' + escapeHtml(i.asset_class) + "</span></td>" +
        '<td class="num">' + sharesTxt + "</td>" +
        '<td class="num">' + costTxt + "</td>" +
        '<td class="num">' + priceTxt + "</td>" +
        '<td class="num">' + (i.value_cny === null ? "—" : num(i.value_cny)) + "</td>" +
        '<td class="num">' + pnlTxt + "</td>" +
        '<td class="num"><div class="weight-cell">' + num(i.weight) + "%" +
        '<span class="mini-bar"><i style="width:' + Math.min(100, i.weight || 0) +
        "%;background:" + color + '"></i></span></div></td>' +
        '<td class="num ' + cls(i.change_pct) + '">' + pct(i.change_pct) + "</td>" +
        '<td class="src-cell">' + escapeHtml(i.price_source) + "</td>" +
        "</tr>";
    }).join("");
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

  function init() {
    bindTabs();
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
