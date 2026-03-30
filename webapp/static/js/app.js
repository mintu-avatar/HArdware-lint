/* ===================================================================
   Hardware-Lint — Frontend Logic
   =================================================================== */
(function () {
  "use strict";

  // ---- State --------------------------------------------------------
  let allFindings = [];
  let allRules = [];
  let summary = null;
  let selectedFiles = [];           // File objects queued for upload

  // ---- DOM refs -----------------------------------------------------
  const $  = (s, p) => (p || document).querySelector(s);
  const $$ = (s, p) => [...(p || document).querySelectorAll(s)];

  const uploadOverlay  = $("#uploadOverlay");
  const dropzone       = $("#dropzone");
  const fileInput      = $("#fileInput");
  const fileListEl     = $("#fileList");
  const btnScan        = $("#btnScan");
  const btnClearFiles  = $("#btnClearFiles");
  const uploadProgress = $("#uploadProgress");
  const progressFill   = $("#progressFill");
  const progressText   = $("#progressText");
  const emptyState     = $("#emptyState");
  const dashContent    = $("#dashboardContent");
  const toast          = $("#toast");

  // ---- Init ---------------------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    loadExistingSession();
    loadRules();
    wireNav();
    wireUpload();
    wireFilters();
    wireSourceModal();
  });

  // ==================================================================
  // Navigation
  // ==================================================================
  function wireNav() {
    $$(".nav-btn").forEach(btn => {
      btn.addEventListener("click", () => switchView(btn.dataset.view));
    });
    $("#btnNewAnalysis").addEventListener("click", openUpload);
    $("#btnStartFirst").addEventListener("click", openUpload);
    $("#uploadClose").addEventListener("click", closeUpload);
    uploadOverlay.addEventListener("click", e => {
      if (e.target === uploadOverlay) closeUpload();
    });
  }

  function switchView(name) {
    $$(".nav-btn").forEach(b => b.classList.toggle("active", b.dataset.view === name));
    $$(".view").forEach(v => v.classList.toggle("active", v.id === "view" + capitalise(name)));
  }

  function capitalise(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  // ==================================================================
  // Upload
  // ==================================================================
  function wireUpload() {
    // Drag events
    dropzone.addEventListener("dragover", e => { e.preventDefault(); dropzone.classList.add("drag-over"); });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag-over"));
    dropzone.addEventListener("drop", e => {
      e.preventDefault();
      dropzone.classList.remove("drag-over");
      addFiles(e.dataTransfer.files);
    });
    dropzone.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", () => {
      addFiles(fileInput.files);
      fileInput.value = "";
    });

    btnClearFiles.addEventListener("click", () => {
      selectedFiles = [];
      renderFileList();
    });

    btnScan.addEventListener("click", runScan);
  }

  function openUpload() { uploadOverlay.classList.add("open"); }
  function closeUpload() { uploadOverlay.classList.remove("open"); }

  function addFiles(fileListObj) {
    for (const f of fileListObj) {
      const ext = f.name.substring(f.name.lastIndexOf(".")).toLowerCase();
      if ([".v", ".sv", ".vh", ".svh", ".vams", ".va"].includes(ext)) {
        // Avoid duplicates
        if (!selectedFiles.some(sf => sf.name === f.name && sf.size === f.size)) {
          selectedFiles.push(f);
        }
      }
    }
    renderFileList();
  }

  function renderFileList() {
    fileListEl.innerHTML = "";
    selectedFiles.forEach((f, i) => {
      const div = document.createElement("div");
      div.className = "file-item";
      div.innerHTML = `
        <span class="file-item-name">${esc(f.name)}</span>
        <span class="file-item-size">${formatSize(f.size)}</span>
        <button class="file-item-remove" data-idx="${i}">&times;</button>`;
      fileListEl.appendChild(div);
    });
    // Remove handler
    $$(".file-item-remove", fileListEl).forEach(btn => {
      btn.addEventListener("click", e => {
        selectedFiles.splice(+e.target.dataset.idx, 1);
        renderFileList();
      });
    });
    btnScan.disabled = selectedFiles.length === 0;
  }

  async function runScan() {
    if (selectedFiles.length === 0) return;

    btnScan.disabled = true;
    uploadProgress.classList.add("active");
    progressFill.style.width = "20%";
    progressText.textContent = "Uploading files...";

    const fd = new FormData();
    selectedFiles.forEach(f => fd.append("files", f));

    try {
      progressFill.style.width = "50%";
      progressText.textContent = "Running analysis...";

      const res = await fetch("/api/upload", { method: "POST", body: fd });
      const data = await res.json();

      if (data.error) {
        showToast("Error: " + data.error);
        return;
      }

      progressFill.style.width = "100%";
      progressText.textContent = `Done — ${data.new_findings} findings`;

      allFindings = data.findings;
      summary = data.summary;

      renderDashboard();
      renderIssues();
      populateFilters();

      selectedFiles = [];
      renderFileList();

      setTimeout(() => {
        closeUpload();
        uploadProgress.classList.remove("active");
        switchView("dashboard");
      }, 600);

    } catch (err) {
      showToast("Network error — is the server running?");
    } finally {
      btnScan.disabled = false;
    }
  }

  // ==================================================================
  // Load existing session & rules
  // ==================================================================
  async function loadExistingSession() {
    try {
      const res = await fetch("/api/results");
      const data = await res.json();
      if (data.summary && data.summary.total > 0) {
        allFindings = data.findings;
        summary = data.summary;
        renderDashboard();
        renderIssues();
        populateFilters();
      }
    } catch (_) { /* ignore */ }
  }

  async function loadRules() {
    try {
      const res = await fetch("/api/rules");
      const data = await res.json();
      allRules = data.rules;
      $("#rulesBadge").textContent = data.total + " rules";
      renderRules();
    } catch (_) { /* ignore */ }
  }

  // ==================================================================
  // Dashboard
  // ==================================================================
  function renderDashboard() {
    if (!summary || summary.total === 0) {
      emptyState.style.display = "";
      dashContent.style.display = "none";
      return;
    }
    emptyState.style.display = "none";
    dashContent.style.display = "";

    // Quality gate
    const qg = $("#qgStatus");
    qg.textContent = summary.quality_gate;
    qg.className = "qg-status " + (summary.quality_gate === "PASSED" ? "passed" : "failed");

    // Metric cards
    $("#mcErrors").textContent   = summary.errors;
    $("#mcWarnings").textContent = summary.warnings;
    $("#mcInfos").textContent    = summary.infos;
    $("#mcFiles").textContent    = summary.files_scanned;
    $("#mcRules").textContent    = summary.rules_active;

    // Ring chart
    renderRing(summary.errors, summary.warnings, summary.infos);

    // Category table
    renderCatTable(summary.categories);

    // File table
    renderFileTable(summary.per_file);
  }

  function renderRing(errors, warnings, infos) {
    const total = errors + warnings + infos;
    const svg   = $("#ringChart");
    // Remove old segments
    $$(".ring-seg", svg).forEach(el => el.remove());

    const circumference = 2 * Math.PI * 50;   // r=50
    const slices = [
      { val: errors,   color: "var(--error)" },
      { val: warnings, color: "var(--warning)" },
      { val: infos,    color: "var(--info)" },
    ];

    let offset = 0;
    slices.forEach(s => {
      if (s.val === 0) return;
      const pct = s.val / (total || 1);
      const dash = pct * circumference;
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("class", "ring-seg");
      circle.setAttribute("cx", "60");
      circle.setAttribute("cy", "60");
      circle.setAttribute("r", "50");
      circle.setAttribute("stroke", s.color);
      circle.setAttribute("stroke-dasharray", `${dash} ${circumference - dash}`);
      circle.setAttribute("stroke-dashoffset", `${-offset}`);
      svg.appendChild(circle);
      offset += dash;
    });

    $(".ring-total").textContent = total;
    $(".ring-label").textContent = total === 1 ? "issue" : "issues";

    // Legend
    const legend = $("#ringLegend");
    legend.innerHTML = `
      <div class="legend-item"><span class="legend-dot" style="background:var(--error)"></span>Error ${errors}</div>
      <div class="legend-item"><span class="legend-dot" style="background:var(--warning)"></span>Warning ${warnings}</div>
      <div class="legend-item"><span class="legend-dot" style="background:var(--info)"></span>Info ${infos}</div>`;
  }

  function renderCatTable(cats) {
    const tbody = $("#catTable tbody");
    tbody.innerHTML = "";
    const sorted = Object.entries(cats).sort((a, b) => b[1].total - a[1].total);
    sorted.forEach(([name, c]) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="cat-name" data-cat="${esc(name)}">${esc(name)}</td>
        <td class="num ${c.ERROR ? 'num-error' : ''}">${c.ERROR || "-"}</td>
        <td class="num ${c.WARNING ? 'num-warning' : ''}">${c.WARNING || "-"}</td>
        <td class="num ${c.INFO ? 'num-info' : ''}">${c.INFO || "-"}</td>
        <td class="num num-total">${c.total}</td>`;
      tbody.appendChild(tr);
    });
    // Click on category → switch to issues with filter
    $$(".cat-name", tbody).forEach(td => {
      td.addEventListener("click", () => {
        $("#filterCategory").value = td.dataset.cat;
        switchView("issues");
        applyFilters();
      });
    });
  }

  function renderFileTable(perFile) {
    const tbody = $("#fileTable tbody");
    tbody.innerHTML = "";
    if (!perFile) return;
    const sorted = Object.entries(perFile).sort((a, b) => b[1].total - a[1].total);
    sorted.forEach(([fname, c]) => {
      const tr = document.createElement("tr");
      const rating = fileRating(c.ERROR, c.WARNING);
      tr.innerHTML = `
        <td><span class="file-link" data-file="${esc(fname)}">${esc(fname)}</span></td>
        <td class="num ${c.ERROR ? 'num-error' : ''}">${c.ERROR || "-"}</td>
        <td class="num ${c.WARNING ? 'num-warning' : ''}">${c.WARNING || "-"}</td>
        <td class="num ${c.INFO ? 'num-info' : ''}">${c.INFO || "-"}</td>
        <td class="num" style="font-weight:700">${c.total}</td>
        <td class="num"><span class="rating-badge rating-${rating}">${rating}</span></td>`;
      tbody.appendChild(tr);
    });
    $$(".file-link", tbody).forEach(el => {
      el.addEventListener("click", () => openSourceViewer(el.dataset.file));
    });
  }

  function fileRating(errors, warnings) {
    if (errors === 0 && warnings === 0) return "A";
    if (errors === 0 && warnings <= 3)  return "B";
    if (errors <= 2)  return "C";
    if (errors <= 5)  return "D";
    return "E";
  }

  // ==================================================================
  // Issues list
  // ==================================================================
  function renderIssues() {
    applyFilters();
  }

  function wireFilters() {
    ["filterSeverity", "filterCategory", "filterFile", "filterSearch"].forEach(id => {
      const el = document.getElementById(id);
      el.addEventListener("input", applyFilters);
      el.addEventListener("change", applyFilters);
    });
  }

  function populateFilters() {
    // Category
    const catSel = $("#filterCategory");
    const currentCat = catSel.value;
    const cats = [...new Set(allFindings.map(f => f.category))].sort();
    catSel.innerHTML = '<option value="">All</option>' +
      cats.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
    catSel.value = currentCat;

    // File
    const fileSel = $("#filterFile");
    const currentFile = fileSel.value;
    const files = [...new Set(allFindings.map(f => f.file))].sort();
    fileSel.innerHTML = '<option value="">All</option>' +
      files.map(f => `<option value="${esc(f)}">${esc(f)}</option>`).join("");
    fileSel.value = currentFile;
  }

  function applyFilters() {
    const sev  = $("#filterSeverity").value;
    const cat  = $("#filterCategory").value;
    const file = $("#filterFile").value;
    const q    = $("#filterSearch").value.toLowerCase().trim();

    let filtered = allFindings;
    if (sev)  filtered = filtered.filter(f => f.severity === sev);
    if (cat)  filtered = filtered.filter(f => f.category === cat);
    if (file) filtered = filtered.filter(f => f.file === file);
    if (q)    filtered = filtered.filter(f =>
      f.rule_id.toLowerCase().includes(q) ||
      f.description.toLowerCase().includes(q) ||
      f.snippet.toLowerCase().includes(q) ||
      f.category.toLowerCase().includes(q)
    );

    $("#issueCount").textContent = filtered.length + " issue" + (filtered.length !== 1 ? "s" : "");
    renderIssueCards(filtered);
  }

  function renderIssueCards(findings) {
    const container = $("#issuesList");
    container.innerHTML = "";

    if (findings.length === 0) {
      container.innerHTML = '<p style="text-align:center;color:var(--text-muted);padding:40px">No issues match the current filters.</p>';
      return;
    }

    // Limit rendered cards for perf (lazy-ish)
    const MAX = 500;
    const subset = findings.slice(0, MAX);

    subset.forEach(f => {
      const card = document.createElement("div");
      card.className = `issue-card sev-${f.severity}`;
      card.innerHTML = `
        <div class="issue-header">
          <span class="sev-badge sev-${f.severity}">${f.severity}</span>
          <span class="issue-rule">${esc(f.rule_id)}</span>
          <span class="issue-cat">${esc(f.category)}</span>
          <span class="issue-location" data-file="${esc(f.file)}" data-line="${f.line}">${esc(f.file)}:${f.line}</span>
        </div>
        <div class="issue-desc">${esc(f.description)}</div>
        <div class="issue-detail">
          ${f.snippet ? `<div class="issue-snippet">${esc(f.snippet)}</div>` : ""}
          ${f.suggestion ? `<div class="issue-suggestion">${esc(f.suggestion)}</div>` : ""}
        </div>`;
      // Toggle expanded
      card.addEventListener("click", e => {
        if (e.target.classList.contains("issue-location")) return;
        card.classList.toggle("expanded");
      });
      // Source viewer on location click
      const loc = $(".issue-location", card);
      if (loc) {
        loc.addEventListener("click", () => {
          openSourceViewer(loc.dataset.file, +loc.dataset.line);
        });
      }
      container.appendChild(card);
    });

    if (findings.length > MAX) {
      const more = document.createElement("p");
      more.style.cssText = "text-align:center;color:var(--text-muted);padding:20px";
      more.textContent = `Showing ${MAX} of ${findings.length} issues. Refine your filters to see more.`;
      container.appendChild(more);
    }
  }

  // ==================================================================
  // Rules browser
  // ==================================================================
  function renderRules(filter) {
    const grid = $("#rulesGrid");
    grid.innerHTML = "";
    let rules = allRules;
    if (filter) {
      const q = filter.toLowerCase();
      rules = rules.filter(r =>
        r.rule_id.toLowerCase().includes(q) ||
        r.category.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q)
      );
    }
    $("#rulesCount").textContent = rules.length + " rule" + (rules.length !== 1 ? "s" : "");

    rules.forEach(r => {
      const card = document.createElement("div");
      card.className = `rule-card sev-${r.severity}`;
      card.innerHTML = `
        <div class="rule-top">
          <span class="sev-badge sev-${r.severity}">${r.severity}</span>
          <span class="rule-id">${esc(r.rule_id)}</span>
          <span class="rule-cat">${esc(r.category)}</span>
        </div>
        <div class="rule-desc">${esc(r.description)}</div>`;
      grid.appendChild(card);
    });
  }

  // Rules search wiring
  document.addEventListener("DOMContentLoaded", () => {
    const search = $("#rulesSearch");
    if (search) search.addEventListener("input", () => renderRules(search.value));
  });

  // ==================================================================
  // Source viewer modal
  // ==================================================================
  function wireSourceModal() {
    $("#sourceModalClose").addEventListener("click", closeSourceModal);
    $("#sourceModal").addEventListener("click", e => {
      if (e.target === $("#sourceModal")) closeSourceModal();
    });
  }

  async function openSourceViewer(filename, highlightLine) {
    try {
      const res = await fetch("/api/source/" + encodeURIComponent(filename));
      const data = await res.json();
      if (data.error) { showToast(data.error); return; }

      $("#sourceModalTitle").textContent = filename;
      const container = $("#sourceCode");
      container.innerHTML = "";

      const lines = data.source.split("\n");

      // Collect all issue lines for this file
      const issueLines = new Set(
        allFindings.filter(f => f.file === filename).map(f => f.line)
      );

      lines.forEach((line, i) => {
        const div = document.createElement("div");
        const lineNum = i + 1;
        div.className = "source-line" +
          (issueLines.has(lineNum) ? " highlighted" : "");
        div.innerHTML =
          `<span class="line-num">${lineNum}</span><span class="line-code">${esc(line)}</span>`;
        div.dataset.line = lineNum;
        container.appendChild(div);
      });

      $("#sourceModal").classList.add("open");

      // Scroll to highlighted line
      if (highlightLine) {
        setTimeout(() => {
          const target = container.querySelector(`[data-line="${highlightLine}"]`);
          if (target) target.scrollIntoView({ block: "center", behavior: "smooth" });
        }, 100);
      }
    } catch (err) {
      showToast("Could not load source file");
    }
  }

  function closeSourceModal() {
    $("#sourceModal").classList.remove("open");
  }

  // ==================================================================
  // Helpers
  // ==================================================================
  function esc(s) {
    if (typeof s !== "string") return s;
    const div = document.createElement("div");
    div.appendChild(document.createTextNode(s));
    return div.innerHTML;
  }

  function formatSize(b) {
    if (b < 1024) return b + " B";
    if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
    return (b / (1024 * 1024)).toFixed(1) + " MB";
  }

  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add("visible");
    setTimeout(() => toast.classList.remove("visible"), 3000);
  }
})();
