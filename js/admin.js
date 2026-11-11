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
        state.serverMode = true;
      })
      .catch(function () {
        state.serverMode = false;
        return fetch("data/holdings.json?t=" + Date.now())
          .then(function (r) { return r.json(); })
          .then(function (h) { state.holdings = h; });
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
          : "静态模式：保存后需下载 holdings.json 上传仓库";
        $("save-note").innerHTML = state.serverMode
          ? "当前运行在本地后台（<code>scripts/server.py</code>）：保存后自动写入 <code>data/holdings.json</code> 并立即重建 <code>data/dashboard.json</code>。"
          : "当前为 GitHub Pages 静态页面：保存后下载 <code>holdings.json</code>，覆盖仓库 <code>data/holdings.json</code>；Actions 每日构建或手动 Run workflow 后生效。";
        renderTable();
        syncGhUi();
      });
  }

  function priceMap() {
    var map = {};
    if (state.dashboard && state.dashboard.items) {
      state.dashboard.items.forEach(function (i) { map[i.id] = i; });
    }
    return map;
  }

  // ---------- 表格 ----------
  function renderTable() {
    var prices = priceMap();
    var rows = state.holdings.traditional || [];
    var pending = rows.filter(function (r) { return !(Number(r.shares) > 0); }).length;

    $("pending-pill").textContent = pending ? pending + " 个标的待填写份额" : "份额已全部填写";
    $("pending-pill").className = "pill" + (pending ? " warn" : "");

    $("holdings-body").innerHTML = rows.map(function (r, idx) {
      var p = prices[r.id] || {};
      return "<tr>" +
        '<td class="name-cell"><div class="nm">' + esc(r.name) + "</div>" +
        (r.note ? '<div class="sub">' + esc(r.note) + "</div>" : "") + "</td>" +
        "<td><code>" + esc(r.symbol) + "</code></td>" +
        "<td>" + esc(r.asset_class || "—") + "</td>" +
        "<td>" + esc(r.currency) + "</td>" +
        '<td class="num"><input type="number" step="0.000001" min="0" data-idx="' + idx +
        '" value="' + (r.shares || 0) + '" aria-label="持有份额"></td>' +
        '<td class="num">' + (p.price === null || p.price === undefined ? "—" : num(p.price, p.price < 10 ? 4 : 2)) + "</td>" +
        '<td class="num">' + (p.value_cny === undefined ? "—" : num(p.value_cny)) + "</td>" +
        '<td><button class="row-del" data-del="' + idx + '" type="button">删除</button></td>' +
        "</tr>";
    }).join("");

    $("holdings-body").oninput = function (e) {
      var input = e.target;
      if (input.tagName !== "INPUT") return;
      var idx = Number(input.getAttribute("data-idx"));
      var v = Number(input.value);
      if (isNaN(v) || v < 0) return;
      state.holdings.traditional[idx].shares = v;
      state.dirty = true;
      updatePendingPill();
    };

    $("holdings-body").onclick = function (e) {
      var btn = e.target.closest("[data-del]");
      if (!btn) return;
      var idx = Number(btn.getAttribute("data-del"));
      var item = state.holdings.traditional[idx];
      if (!confirm("确定删除标的「" + (item.name || item.symbol) + "」？")) return;
      state.holdings.traditional.splice(idx, 1);
      state.dirty = true;
      renderTable();
    };
  }

  function updatePendingPill() {
    var rows = state.holdings.traditional || [];
    var pending = rows.filter(function (r) { return !(Number(r.shares) > 0); }).length;
    $("pending-pill").textContent = pending ? pending + " 个标的待填写份额" : "份额已全部填写";
    $("pending-pill").className = "pill" + (pending ? " warn" : "");
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
        note: "",
      });
      state.dirty = true;
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

  function parseSheet(rows) {
    var hi = findHeaderRow(rows);
    if (hi < 0) return null;
    var header = rows[hi];
    var nameCol = pickCol(header, ["项目名称", "名称", "标的", "项目"]);
    var codeCol = pickCol(header, ["代码", "symbol", "代码/代码"]);
    var sharesCol = pickCol(header, ["持有数量", "持有份额", "份额", "数量", "持仓"]);
    if (sharesCol < 0) return null;

    var out = [];
    for (var i = hi + 1; i < rows.length; i++) {
      var row = rows[i] || [];
      var name = nameCol >= 0 ? String(row[nameCol] || "").trim() : "";
      var code = codeCol >= 0 ? String(row[codeCol] || "").trim().toUpperCase() : "";
      var sharesRaw = row[sharesCol];
      var shares = parseFloat(String(sharesRaw === undefined ? "" : sharesRaw).replace(/[,\s￥$]/g, ""));
      if (!name && !code) continue;
      out.push({ name: name, code: code, shares: isNaN(shares) ? null : shares });
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
      '<table class="import-table"><thead><tr><th>表格行</th><th>匹配标的</th><th>代码</th><th class="num">新份额</th><th>状态</th></tr></thead><tbody>' +
      state.importRows.map(function (x) {
        var st = !x.hit ? '<span class="import-msg warn">未匹配</span>'
          : x.row.shares === null ? '<span class="import-msg warn">无份额值</span>'
            : '<span class="import-msg ok">将更新</span>';
        return "<tr><td>" + esc(x.row.name || "—") + "</td><td>" +
          esc(x.hit ? x.hit.name : "—") + "</td><td>" + esc(x.row.code || "—") + "</td>" +
          '<td class="num">' + (x.row.shares === null ? "—" : num(x.row.shares, 4)) + "</td><td>" + st + "</td></tr>";
      }).join("") + "</tbody></table>" +
      '<div class="import-actions">' +
      '<button class="btn primary" id="btn-apply-import" type="button">应用 ' + matched.length + " 项</button>" +
      '<button class="btn" id="btn-cancel-import" type="button">取消</button>' +
      (unmatched.length ? '<span class="import-msg warn">' + unmatched.length + " 行未匹配，可在下方新增标的或手动填写</span>" : "") +
      "</div>";

    $("btn-cancel-import").onclick = function () { box.hidden = true; state.importRows = null; };
    $("btn-apply-import").onclick = function () {
      matched.forEach(function (x) { x.hit.shares = x.row.shares; });
      state.dirty = true;
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
      body: JSON.stringify({ ref: gh.branch }),
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

  function pollBuild() {
    var tries = 0;
    var timer = setInterval(function () {
      tries++;
      ghFetch("/repos/" + gh.repo + "/actions/runs?per_page=1").then(function (res) {
        var runs = res.ok && res.body && res.body.workflow_runs;
        if (!runs || !runs.length) return;
        var run = runs[0];
        if (run.status === "completed") {
          clearInterval(timer);
          if (run.conclusion === "success") {
            ghMsg("✅ 构建完成，已重新抓价并计算，正在刷新数据…", "ok");
            refreshDashboard().then(function () {
              setSaveBusy(false);
              toast("已更新：页面数据已刷新");
            });
          } else {
            ghMsg("⚠ 构建结束但未成功（" + run.conclusion + "），请到 Actions 查看日志。", "warn");
            setSaveBusy(false);
          }
        } else if (tries >= 20) {
          clearInterval(timer);
          ghMsg("构建仍在进行（" + run.status + "），约 1 分钟后刷新页面即可看到。", "");
          setSaveBusy(false);
        }
      }).catch(function () { /* 忽略单次轮询失败 */ });
    }, 6000);
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
        ghMsg("✅ 已提交到 " + gh.repo + "（" + gh.branch + "），正在触发构建…", "ok");
        return ghDispatch();
      })
      .then(function (res) {
        if (res.status === 204) {
          ghMsg("✅ 已触发 Actions 构建，约 1–2 分钟后生效，正在等待…", "ok");
          pollBuild();
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
      if (!state.serverMode) { toast("静态模式无法重建，请在 GitHub Actions 手动 Run workflow"); return; }
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
