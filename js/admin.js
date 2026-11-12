/* 份额维护后台逻辑 */
(function () {
  "use strict";

  var state = {
    holdings: null,
    dashboard: null,
    serverMode: false,
    importRows: null,
    dirty: false,
  };

  function $(id) { return document.getElementById(id); }

  function num(x, d) {
    if (x === null || x === undefined || isNaN(x)) return "—";
    return Number(x).toLocaleString("zh-CN", {
      minimumFractionDigits: d === undefined ? 2 : d,
      maximumFractionDigits: d === undefined ? 2 : d,
    });
  }

  function esc(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function toast(msg) {
    var el = document.getElementById("toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "toast";
      el.className = "toast";
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.classList.remove("show"); }, 2600);
  }

  // ---------- 载入 ----------
  function loadAll() {
    return fetch("api/holdings?t=" + Date.now())
      .then(function (r) {
        if (!r.ok) throw new Error("no api");
        return r.json();
      })
      .then(function (h) {
        state.holdings = h;
        ensureCash();
        state.serverMode = true;
      })
      .catch(function () {
        state.serverMode = false;
        return fetch("data/holdings.json?t=" + Date.now())
          .then(function (r) { return r.json(); })
          .then(function (h) { state.holdings = h; ensureCash(); });
      })
      .then(function () {
        return fetch("data/dashboard.json?t=" + Date.now())
          .then(function (r) { return r.json(); })
          .catch(function () { return null; });
      })
      .then(function (d) { state.dashboard = d; })
      .then(function () {
        $("mode-badge").textContent = state.serverMode
          ? "本地后台模式：可直接保存并重建"
          : "静态模式：用下方 GitHub Token 直连更新";
        var cm = state.dashboard && state.dashboard.crypto_meta;
        var today = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
        if (cm && cm.snapshot_date) {
          var stale = cm.snapshot_date !== today;
          $("fresh-badge").textContent = "加密快照 " + cm.snapshot_date +
            (stale ? "（每日约 07:00 汇总，点上方「立即抓取最新价格」可更新）" : "（已是最新）");
        }
        var bm = (state.dashboard && state.dashboard.meta) || {};
        if (bm.generated_at && $("fresh-badge")) {
          $("fresh-badge").textContent += " · 最近构建：" +
            (bm.build_source === "manual" ? "手动" : "自动") + " " +
            String(bm.generated_at).slice(5, 16).replace("T", " ") +
            (bm.crypto_price_mode === "live" ? "（币价实时）" : "（币价快照）");
        }
        $("save-note").innerHTML = state.serverMode
          ? "当前运行在本地后台（<code>scripts/server.py</code>）：保存后自动写入 <code>data/holdings.json</code> 并立即重建 <code>data/dashboard.json</code>。"
          : "当前为 GitHub Pages 静态页面：填入下方 GitHub Token 后点「保存并计算」，直接提交 <code>data/holdings.json</code> 并触发 Actions 重建。";
        renderTable();
        renderCash();
        syncGhUi();
        restoreDraftIfAny();
      });
  }

  function restoreDraftIfAny() {
    var raw = null;
    try { raw = localStorage.getItem(DRAFT_KEY); } catch (e) { return; }
    if (!raw) return;
    var d = null;
    try { d = JSON.parse(raw); } catch (e) { return; }
    if (!d || !d.data || !d.data.traditional) return;
    var same = JSON.stringify(d.data.traditional) === JSON.stringify(state.holdings.traditional);
    if (same) { clearDraft(); return; }
    state.pendingDraft = d.data;
    draftBanner(d.ts);
  }

  // ---------- 草稿（防刷新丢失） ----------
  var DRAFT_KEY = "aad_holdings_draft_v1";
  function persistDraft() {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({ ts: Date.now(), data: state.holdings }));
    } catch (e) { /* 隐私模式可能不可用，忽略 */ }
  }
  function clearDraft() { try { localStorage.removeItem(DRAFT_KEY); } catch (e) {} }
  function markDirty() { state.dirty = true; persistDraft(); updateSaveHint(); }
  function updateSaveHint() {
    var btn = $("btn-save");
    if (!btn) return;
    if (state.dirty) { btn.classList.add("dirty"); btn.setAttribute("title", "有未保存的修改"); }
    else { btn.classList.remove("dirty"); btn.removeAttribute("title"); }
  }
  function draftBanner(ts) {
    var el = $("draft-banner");
    if (!el) return;
    $("draft-time").textContent = new Date(ts).toLocaleString("zh-CN", { hour12: false });
    el.hidden = false;
  }

  function priceMap() {
    var map = {};
    if (state.dashboard && state.dashboard.items) {
      state.dashboard.items.forEach(function (i) { map[i.id] = i; });
    }
    return map;
  }

  // ---------- 表格 ----------
  function fxRate() {
    var fx = state.dashboard && state.dashboard.meta && state.dashboard.meta.fx;
    return (fx && fx.usdcny) ? Number(fx.usdcny) : 7.1;
  }

  function renderTable() {
    var prices = priceMap();
    var fx = fxRate();
    var rows = state.holdings.traditional || [];
    updatePendingPill();

    $("holdings-body").innerHTML = rows.map(function (r, idx) {
      var p = prices[r.id] || {};
      var shares = Number(r.shares) || 0;
      var costPrice = Number(r.cost_price) || 0;
      var cur = r.currency === "USD" ? fx : 1;
      var costCny = shares && costPrice ? shares * costPrice * cur : null;
      var valueCny = p.value_cny === undefined ? null : p.value_cny;
      var pnl = (costCny !== null && valueCny !== null) ? valueCny - costCny : null;
      var pnlCls = pnl === null ? "muted" : (pnl >= 0 ? "pos" : "neg");
      var pnlTxt = pnl === null ? '<span class="muted">—</span>'
        : '<span class="' + pnlCls + '">' + (pnl >= 0 ? "+" : "") + num(pnl) +
          '<div class="sub ' + pnlCls + '">' + (costCny ? (pnl / costCny * 100).toFixed(2) + "%" : "—") + "</div></span>";
      return "<tr>" +
        '<td class="name-cell"><div class="nm">' + esc(r.name) + "</div>" +
        (r.note ? '<div class="sub">' + esc(r.note) + "</div>" : "") + "</td>" +
        "<td><code>" + esc(r.symbol) + "</code></td>" +
        "<td>" + esc(r.asset_class || "—") + "</td>" +
        "<td>" + esc(r.currency) + "</td>" +
        '<td class="num"><input type="number" step="0.000001" min="0" data-idx="' + idx +
        '" data-field="shares" value="' + shares + '" aria-label="持有份额"></td>' +
        '<td class="num"><input type="number" step="0.0001" min="0" data-idx="' + idx +
        '" data-field="cost_price" value="' + costPrice + '" aria-label="成本价"></td>' +
        '<td class="num">' + (p.price === null || p.price === undefined ? "—" : num(p.price, p.price < 10 ? 4 : 2)) + "</td>" +
        '<td class="num">' + (valueCny === null ? "—" : num(valueCny)) + "</td>" +
        '<td class="num">' + pnlTxt + "</td>" +
        '<td><button class="row-del" data-del="' + idx + '" type="button">删除</button></td>' +
        "</tr>";
    }).join("");

    $("holdings-body").oninput = function (e) {
      var input = e.target;
      if (input.tagName !== "INPUT") return;
      var idx = Number(input.getAttribute("data-idx"));
      var field = input.getAttribute("data-field") || "shares";
      var v = Number(input.value);
      if (isNaN(v) || v < 0) return;
      state.holdings.traditional[idx][field] = v;
      markDirty();
      if (field === "shares") updatePendingPill();
    };

    $("holdings-body").onclick = function (e) {
      var btn = e.target.closest("[data-del]");
      if (!btn) return;
      var idx = Number(btn.getAttribute("data-del"));
      var item = state.holdings.traditional[idx];
      if (!confirm("确定删除标的「" + (item.name || item.symbol) + "」？")) return;
      state.holdings.traditional.splice(idx, 1);
      markDirty();
      renderTable();
    };
  }


  function ensureCash() {
    if (!state.holdings.cash_accounts || !state.holdings.cash_accounts.length) {
      state.holdings.cash_accounts = [{
        id: "alipay", name: "支付宝现金", currency: "CNY", amount_cny: 0,
      }];
    }
  }

  function renderCash() {
    var ca = (state.holdings.cash_accounts || [])[0] || {};
    var v = Number(ca.amount_cny) || 0;
    var inp = $("alipay-amount");
    if (inp && document.activeElement !== inp) inp.value = v ? String(v) : "";
    var pill = $("alipay-pill");
    if (pill) pill.textContent = v > 0 ? "当前 ¥" + num(v, 2) : "未填写则不计入现金";
  }

  function bindCash() {
    var inp = $("alipay-amount");
    if (!inp) return;
    inp.addEventListener("input", function () {
      ensureCash();
      var v = Number(inp.value);
      state.holdings.cash_accounts[0].amount_cny = isNaN(v) ? 0 : Math.max(0, v);
      markDirty();
      renderCash();
    });
  }

  function updatePendingPill() {
    var rows = state.holdings.traditional || [];
    var pending = rows.filter(function (r) { return !(Number(r.shares) > 0); }).length;
    var costPending = rows.filter(function (r) {
      return Number(r.shares) > 0 && !(Number(r.cost_price) > 0);
    }).length;
    var parts = [];
    if (pending) parts.push(pending + " 个待填份额");
    if (costPending) parts.push(costPending + " 个待填成本价");
    $("pending-pill").textContent = parts.length ? parts.join(" · ") : "份额与成本价已完整";
    $("pending-pill").className = "pill" + (parts.length ? " warn" : "");
  }

  // ---------- 新增 ----------
  function bindAdd() {
    $("add-form").addEventListener("submit", function (e) {
      e.preventDefault();
      var f = e.target;
      var name = f.name.value.trim();
      var symbol = f.symbol.value.trim();
      if (!name || !symbol) return;
      var exists = (state.holdings.traditional || []).some(function (r) {
        return String(r.symbol).toUpperCase() === symbol.toUpperCase();
      });
      if (exists) {
        toast("该代码已存在，直接修改其份额即可");
        return;
      }
      state.holdings.traditional.push({
        id: symbol.toUpperCase(),
        name: name,
        symbol: symbol.toUpperCase(),
        currency: f.currency.value,
        asset_class: f.asset_class.value.trim() || "其他",
        shares: Number(f.shares.value) || 0,
        cost_price: Number(f.cost_price.value) || 0,
        added_at: new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10),
        note: "",
      });
      markDirty();
      f.reset();
      f.asset_class.value = "美股基金";
      renderTable();
      toast("已添加 " + name + "，记得保存");
    });
  }

  // ---------- 上传解析 ----------
  function findHeaderRow(rows) {
    for (var i = 0; i < Math.min(rows.length, 10); i++) {
      var row = rows[i] || [];
      var text = row.map(function (c) { return String(c || ""); }).join("|");
      if (/持有数量|持有份额|份额|数量|持仓/.test(text) &&
          /项目|名称|代码|标的/.test(text)) {
        return i;
      }
    }
    return -1;
  }

  function pickCol(header, patterns) {
    for (var i = 0; i < header.length; i++) {
      var h = String(header[i] || "");
      for (var j = 0; j < patterns.length; j++) {
        if (h.indexOf(patterns[j]) !== -1) return i;
      }
    }
    return -1;
  }

  function toNum(v) {
    var n = parseFloat(String(v === undefined || v === null ? "" : v)
      .replace(/[,\s￥$%]/g, ""));
    return isNaN(n) ? null : n;
  }

  function parseSheet(rows) {
    var hi = findHeaderRow(rows);
    if (hi < 0) return null;
    var header = rows[hi];
    var nameCol = pickCol(header, ["项目名称", "名称", "标的", "项目"]);
    var codeCol = pickCol(header, ["代码", "symbol", "代码/代码"]);
    var sharesCol = pickCol(header, ["持有数量", "持有份额", "份额", "数量", "持仓"]);
    // 成本：优先「成本价/买入均价」，其次用「累计投入成本 / 成本总价 ÷ 份额」推导
    var costCol = pickCol(header, ["成本价", "买入均价"]);
    var totalCostCol = -1;
    if (costCol < 0) {
      totalCostCol = pickCol(header, ["累计投入成本", "成本总价", "投入成本", "持仓成本"]);
    }
    if (sharesCol < 0) return null;

    var out = [];
    for (var i = hi + 1; i < rows.length; i++) {
      var row = rows[i] || [];
      var name = nameCol >= 0 ? String(row[nameCol] || "").trim() : "";
      var code = codeCol >= 0 ? String(row[codeCol] || "").trim().toUpperCase() : "";
      var shares = toNum(row[sharesCol]);
      if (!name && !code) continue;
      var cost = costCol >= 0 ? toNum(row[costCol]) : null;
      if (cost === null && totalCostCol >= 0 && shares) {
        var total = toNum(row[totalCostCol]);
        if (total !== null && total > 0) cost = total / shares;
      }
      out.push({ name: name, code: code, shares: shares, cost: cost });
    }
    return out;
  }

  function matchRow(r) {
    var list = state.holdings.traditional || [];
    for (var i = 0; i < list.length; i++) {
      if (r.code && String(list[i].symbol).toUpperCase() === r.code) return list[i];
      if (r.code && String(list[i].id).toUpperCase() === r.code) return list[i];
    }
    for (var k = 0; k < list.length; k++) {
      if (r.name && list[k].name && (list[k].name.indexOf(r.name) !== -1 || r.name.indexOf(list[k].name) !== -1)) {
        return list[k];
      }
    }
    return null;
  }

  function handleFile(file) {
    if (!file) return;
    if (!window.XLSX) {
      toast("表格解析库未加载，请用 CSV 或稍后重试");
      return;
    }
    var reader = new FileReader();
    reader.onload = function (e) {
      try {
        var wb = XLSX.read(e.target.result, { type: "array" });
        var sheet = wb.Sheets[wb.SheetNames[0]];
        var rows = XLSX.utils.sheet_to_json(sheet, { header: 1, raw: true, defval: "" });
        var parsed = parseSheet(rows);
        if (!parsed || !parsed.length) {
          toast("没找到「持有数量」相关列，请检查表头");
          return;
        }
        state.importRows = parsed.map(function (r) {
          var hit = matchRow(r);
          return { row: r, hit: hit };
        });
        renderImport();
      } catch (err) {
        toast("解析失败：" + err.message);
      }
    };
    reader.readAsArrayBuffer(file);
  }

  function renderImport() {
    var box = $("import-result");
    box.hidden = false;
    var matched = state.importRows.filter(function (x) { return x.hit && x.row.shares !== null; });
    var unmatched = state.importRows.filter(function (x) { return !x.hit; });

    box.innerHTML =
      "<h3>解析结果：" + state.importRows.length + " 行，可匹配 " + matched.length + " 个标的</h3>" +
      '<table class="import-table"><thead><tr><th>表格行</th><th>匹配标的</th><th>代码</th><th class="num">新份额</th><th class="num">成本价</th><th>状态</th></tr></thead><tbody>' +
      state.importRows.map(function (x) {
        var st = !x.hit ? '<span class="import-msg warn">未匹配</span>'
          : x.row.shares === null ? '<span class="import-msg warn">无份额值</span>'
            : '<span class="import-msg ok">将更新</span>';
        return "<tr><td>" + esc(x.row.name || "—") + "</td><td>" +
          esc(x.hit ? x.hit.name : "—") + "</td><td>" + esc(x.row.code || "—") + "</td>" +
          '<td class="num">' + (x.row.shares === null ? "—" : num(x.row.shares, 4)) + "</td>" +
          '<td class="num">' + (x.row.cost === null || x.row.cost === undefined ? "—" : num(x.row.cost, 4)) + "</td>" +
          "<td>" + st + "</td></tr>";
      }).join("") + "</tbody></table>" +
      '<div class="import-actions">' +
      '<button class="btn primary" id="btn-apply-import" type="button">应用 ' + matched.length + " 项</button>" +
      '<button class="btn" id="btn-cancel-import" type="button">取消</button>' +
      (unmatched.length ? '<span class="import-msg warn">' + unmatched.length + " 行未匹配，可在下方新增标的或手动填写</span>" : "") +
      "</div>";

    $("btn-cancel-import").onclick = function () { box.hidden = true; state.importRows = null; };
    $("btn-apply-import").onclick = function () {
      matched.forEach(function (x) {
        x.hit.shares = x.row.shares;
        if (x.row.cost !== null && x.row.cost !== undefined && x.row.cost >= 0) {
          x.hit.cost_price = x.row.cost;
        }
      });
      markDirty();
      renderTable();
      box.hidden = true;
      state.importRows = null;
      toast("已应用 " + matched.length + " 个标的的份额，记得保存");
    };
  }

  // ---------- 保存 ----------
  function payload() {
    var h = JSON.parse(JSON.stringify(state.holdings));
    return h;
  }

  // ---------- GitHub 直连更新 ----------
  var GH_KEY = "asset_dash_gh";
  var gh = { token: "", repo: "978912280-jpg/all-asset-dashboard", branch: "main" };

  function ghMsg(text, kind) {
    var el = $("gh-msg");
    if (!el) return;
    el.textContent = text;
    el.className = "import-msg" + (kind ? " " + kind : "");
  }

  function ghLoad() {
    $("gh-repo").value = gh.repo;
    $("gh-branch").value = gh.branch;
    try {
      var saved = JSON.parse(localStorage.getItem(GH_KEY) || "{}");
      if (saved.repo) gh.repo = saved.repo;
      if (saved.branch) gh.branch = saved.branch;
      if (saved.token) {
        gh.token = saved.token;
        $("gh-token").value = saved.token;
        $("gh-remember").checked = true;
      }
      $("gh-repo").value = gh.repo;
      $("gh-branch").value = gh.branch;
    } catch (e) { /* localStorage 不可用时忽略 */ }
    syncGhUi();
  }

  function readGhForm() {
    gh.repo = ($("gh-repo").value || "").trim() || gh.repo;
    gh.branch = ($("gh-branch").value || "").trim() || "main";
    gh.token = ($("gh-token").value || "").trim();
    try {
      if ($("gh-remember").checked && gh.token) {
        localStorage.setItem(GH_KEY, JSON.stringify({ token: gh.token, repo: gh.repo, branch: gh.branch }));
      } else {
        localStorage.removeItem(GH_KEY);
      }
    } catch (e) { /* 隐私模式下忽略 */ }
    syncGhUi();
  }

  function syncGhUi() {
    var pill = $("gh-pill");
    if (!pill) return;
    var on = !!gh.token;
    pill.textContent = on ? "已配置 · 可直接更新" : "未配置";
    pill.className = "pill" + (on ? "" : " warn");
    if (on) {
      $("mode-badge").textContent = "GitHub 直连模式：保存后自动提交并触发构建";
    }
  }

  function ghFetch(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({
      "Accept": "application/vnd.github+json",
      "Authorization": "Bearer " + gh.token,
      "X-GitHub-Api-Version": "2022-11-28",
    }, opts.headers || {});
    return fetch("https://api.github.com" + path, opts).then(function (r) {
      return r.text().then(function (t) {
        var body = null;
        try { body = t ? JSON.parse(t) : null; } catch (e) { body = { message: t }; }
        return { ok: r.ok, status: r.status, body: body };
      });
    });
  }

  function ghB64(str) {
    var bytes = new TextEncoder().encode(str);
    var bin = "";
    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
  }

  function ghPutHoldings(data) {
    var apiPath = "/repos/" + gh.repo + "/contents/data/holdings.json";
    var content = ghB64(JSON.stringify(data, null, 2) + "\n");
    return ghFetch(apiPath + "?ref=" + encodeURIComponent(gh.branch)).then(function (res) {
      var sha = (res.ok && res.body && res.body.sha) ? res.body.sha : null;
      var body = {
        message: "chore(holdings): 网页更新份额 " +
          new Date().toLocaleString("zh-CN", { hour12: false }),
        content: content,
        branch: gh.branch,
      };
      if (sha) body.sha = sha;
      return ghFetch(apiPath, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    });
  }

  function ghDispatch() {
    return ghFetch("/repos/" + gh.repo + "/actions/workflows/daily.yml/dispatches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: gh.branch, inputs: { source: "manual" } }),
    });
  }

  function setSaveBusy(busy, label) {
    $("btn-save").disabled = busy;
    $("btn-save").textContent = busy ? (label || "保存中…") : "保存并计算";
  }

  function refreshDashboard() {
    return fetch("data/dashboard.json?t=" + Date.now())
      .then(function (r) { return r.json(); })
      .then(function (d) { state.dashboard = d; renderTable(); });
  }

  function pollBuild(sinceMs, ui) {
    ui = ui || {};
    var btnId = ui.btn || "btn-save";
    var prefix = ui.prefix || "构建中…";
    var restore = ui.restore || "保存并计算";
    function setBtn(disabled, text) {
      var el = $(btnId);
      if (!el) return;
      el.disabled = disabled;
      el.textContent = text;
    }
    function done(msg, level, toastMsg) {
      ghMsg(msg, level || "");
      setBtn(false, restore);
      if (toastMsg) toast(toastMsg);
    }
    var started = sinceMs || Date.now();
    var timer = setInterval(function () {
      var elapsed = Math.round((Date.now() - started) / 1000);
      setBtn(true, prefix + " " + elapsed + "s");
      ghFetch("/repos/" + gh.repo + "/actions/runs?per_page=3").then(function (res) {
        if (!res.ok) {
          if (res.status === 401 || res.status === 403) {
            clearInterval(timer);
            done("⚠ 无法读取 Actions 状态（HTTP " + res.status +
              "）：Token 缺少 Actions: Read。数据已提交，约 1 分钟后刷新页面即可。", "warn");
          }
          return;
        }
        var runs = (res.body && res.body.workflow_runs) || [];
        var run = null;
        for (var i = 0; i < runs.length; i++) {
          if (new Date(runs[i].created_at).getTime() >= started - 10000) { run = runs[i]; break; }
        }
        if (!run) {
          if (elapsed > 150) {
            clearInterval(timer);
            done("尚未检测到本次构建（可能仍在排队）。约 1 分钟后刷新页面即可看到结果。", "");
          }
          return;
        }
        if (run.status !== "completed") {
          ghMsg("✅ 已提交，构建进行中（" + run.status + "）… " + elapsed + "s", "ok");
          return;
        }
        clearInterval(timer);
        if (run.conclusion === "success") {
          ghMsg("✅ 构建完成，正在刷新页面数据…", "ok");
          refreshDashboard().then(function () {
            setBtn(false, restore);
            toast("已更新：份额已写入，价格与市值已重算");
          });
        } else {
          done("⚠ 构建结束但未成功（" + run.conclusion + "）：数据已提交，请到 Actions 查看日志。", "warn");
        }
      }).catch(function () { /* 单次轮询失败忽略，下轮继续 */ });
    }, 4000);
  }

  function ghSave() {
    readGhForm();
    if (!gh.token) {
      ghMsg("请先填入 GitHub Token（需 Contents 与 Actions 读写权限）", "warn");
      return false;
    }
    if (!/^[\w.-]+\/[\w.-]+$/.test(gh.repo)) {
      ghMsg("仓库格式应为 owner/repo", "warn");
      return false;
    }
    setSaveBusy(true, "提交中…");
    var dispatchAt = Date.now();
    ghMsg("正在提交 data/holdings.json …", "");

    ghPutHoldings(payload())
      .then(function (res) {
        if (res.status === 409) return ghPutHoldings(payload()); // sha 冲突时重取一次
        if (!res.ok) {
          throw new Error("提交失败（HTTP " + res.status + "）：" +
            ((res.body && res.body.message) || "请检查 Token 权限"));
        }
        return res;
      })
      .then(function () {
        state.dirty = false;
        clearDraft(); updateSaveHint();
        ghMsg("✅ 已写入 " + gh.repo + "（" + gh.branch + "），正在触发构建…", "ok");
        setSaveBusy(true, "已提交，触发构建…");
        return ghDispatch();
      })
      .then(function (res) {
        if (res.status === 204) {
          ghMsg("✅ 已触发 Actions 构建，正在等待（约 1 分钟）…", "ok");
          setSaveBusy(true, "构建中…");
          pollBuild(dispatchAt, { btn: "btn-save", prefix: "构建中…", restore: "保存并计算" });
        } else if (res.status === 403 || res.status === 404) {
          ghMsg("⚠ 份额已提交，但触发构建失败（HTTP " + res.status +
            "）：Token 缺少 Actions: Read and write 权限。可等每日定时构建生效。", "warn");
          setSaveBusy(false);
        } else {
          throw new Error("触发构建失败（HTTP " + res.status + "）");
        }
      })
      .catch(function (e) {
        ghMsg("保存失败：" + e.message, "warn");
        toast("保存失败：" + e.message);
        setSaveBusy(false);
      });
    return true;
  }

  function ghTest() {
    readGhForm();
    if (!gh.token) { ghMsg("请先填入 Token", "warn"); return; }
    ghMsg("正在验证连接…", "");
    ghFetch("/repos/" + gh.repo)
      .then(function (res) {
        if (!res.ok) {
          throw new Error("HTTP " + res.status + " · " +
            ((res.body && res.body.message) || "请检查仓库名 / Token 权限"));
        }
        return ghFetch("/repos/" + gh.repo + "/actions/workflows").then(function (w) {
          ghMsg("已连接 " + (res.body.full_name || gh.repo) +
            "（默认分支 " + (res.body.default_branch || "") + "）· " +
            (w.ok ? "Actions 可读写" : "⚠ Actions 无权限，提交后需等定时构建"), w.ok ? "ok" : "warn");
        });
      })
      .catch(function (e) { ghMsg("连接失败：" + e.message, "warn"); });
  }

  function save() {
    var data = payload();
    if (state.serverMode) {
      $("btn-save").disabled = true;
      $("btn-save").textContent = "保存中…";
      fetch("api/holdings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      })
        .then(function (r) {
          return r.json().then(function (j) { return { ok: r.ok, body: j }; });
        })
        .then(function (res) {
          if (!res.ok || !res.body.ok) throw new Error(res.body.error || "保存失败");
          state.dirty = false;
          clearDraft();
          toast("已保存并重建：" + (res.body.message || "OK"));
          return fetch("data/dashboard.json?t=" + Date.now())
            .then(function (r) { return r.json(); })
            .then(function (d) { state.dashboard = d; renderTable(); });
        })
        .catch(function (e) { toast("保存失败：" + e.message); })
        .then(function () {
          $("btn-save").disabled = false;
          $("btn-save").textContent = "保存并计算";
        });
    } else if (gh.token || (($("gh-token").value || "").trim())) {
      ghSave();
    } else {
      download();
      toast("未填 Token：已下载 holdings.json，请上传覆盖仓库 data/holdings.json");
    }
  }

  function download() {
    var data = payload();
    var text = JSON.stringify(data, null, 2) + "\n";
    var blob = new Blob([text], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "holdings.json";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  function bindDraftUi() {
    var banner = $("draft-banner");
    if (banner) {
      $("draft-restore").onclick = function () {
        if (state.pendingDraft && state.pendingDraft.traditional) {
          state.holdings = state.pendingDraft;
          renderTable();
          markDirty();
          banner.hidden = true;
          toast("已恢复未保存的修改，请点「保存并计算」写入");
        }
      };
      $("draft-discard").onclick = function () {
        state.pendingDraft = null;
        clearDraft();
        banner.hidden = true;
        toast("已丢弃未保存的修改");
      };
    }
    window.addEventListener("beforeunload", function (e) {
      if (!state.dirty) return;
      e.preventDefault();
      e.returnValue = "";
    });
  }

  function bindButtons() {
    $("btn-save").onclick = save;
    $("btn-gh-test").onclick = ghTest;
    $("btn-gh-clear").onclick = function () {
      $("gh-token").value = "";
      gh.token = "";
      try { localStorage.removeItem(GH_KEY); } catch (e) { /* ignore */ }
      $("gh-remember").checked = false;
      ghMsg("已清除本机保存的 Token", "");
      syncGhUi();
      $("mode-badge").textContent = state.serverMode
        ? "本地后台模式：可直接保存并重建"
        : "静态模式：保存后需下载 holdings.json 上传仓库";
    };
    $("gh-token").addEventListener("change", readGhForm);
    bindDraftUi();
    $("btn-download").onclick = function () { download(); };
    $("btn-copy").onclick = function () {
      var text = JSON.stringify(payload(), null, 2);
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(function () { toast("已复制到剪贴板"); },
          function () { toast("复制失败，请用下载"); });
      } else {
        toast("当前浏览器不支持剪贴板");
      }
    };
    $("btn-rebuild").onclick = function () {
      if (state.dirty) {
        toast("有未保存的修改：抓价不会保存它们，请先点「保存并计算」");
        return;
      }
      if (!state.serverMode) {
        readGhForm();
        if (!gh.token) {
          toast("需先填写下方 GitHub Token（Actions 读写权限），或在 GitHub Actions 手动 Run workflow");
          return;
        }
        ghMsg("正在抓取最新价格：传统标的实时价 + 加密货币最新快照…", "");
        $("btn-rebuild").disabled = true;
        var t0 = Date.now();
        ghDispatch().then(function (res) {
          $("btn-rebuild").disabled = false;
          if (!res.ok) {
            ghMsg("触发失败（HTTP " + res.status + "）：请确认 Token 有 Actions 读写权限", "warn");
            return;
          }
          ghMsg("已触发构建，约 1 分钟完成，完成后页面会自动刷新…", "ok");
          pollBuild(t0, { btn: "btn-rebuild", prefix: "抓取中…", restore: "立即抓取最新价格" });
        }).catch(function (e) {
          $("btn-rebuild").disabled = false;
          ghMsg("触发失败：" + e.message, "warn");
        });
        return;
      }
      fetch("api/rebuild", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (!j.ok) throw new Error(j.error || "重建失败");
          toast("已重建：" + (j.message || ""));
          return fetch("data/dashboard.json?t=" + Date.now())
            .then(function (r) { return r.json(); })
            .then(function (d) { state.dashboard = d; renderTable(); });
        })
        .catch(function (e) { toast("重建失败：" + e.message); });
    };
  }

  function bindUpload() {
    var zone = $("drop-zone");
    var input = $("file-input");
    $("pick-file").onclick = function () { input.click(); };
    input.onchange = function () { handleFile(input.files[0]); input.value = ""; };
    ["dragenter", "dragover"].forEach(function (ev) {
      zone.addEventListener(ev, function (e) {
        e.preventDefault();
        zone.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      zone.addEventListener(ev, function (e) {
        e.preventDefault();
        zone.classList.remove("dragover");
      });
    });
    zone.addEventListener("drop", function (e) {
      var f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) handleFile(f);
    });
  }

  function init() {
    bindUpload();
    bindAdd();
    bindCash();
    bindButtons();
    ghLoad();
    loadAll().catch(function (e) { toast("加载失败：" + e.message); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
