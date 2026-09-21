/* 文档分块向量化平台 — 前端逻辑 */

const API = "/api";

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------

function showToast(msg, type = "") {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast show " + type;
  setTimeout(() => t.className = "toast", 3000);
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1048576).toFixed(1) + " MB";
}

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body && !(body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  } else if (body) {
    opts.body = body;
  }
  const res = await fetch(API + path, opts);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

// ---------------------------------------------------------------------------
// 健康检查
// ---------------------------------------------------------------------------

async function checkHealth() {
  const dot = document.getElementById("backendStatus");
  const text = document.getElementById("backendStatusText");
  try {
    await api("GET", "/health");
    dot.className = "status-dot ok";
    text.textContent = "后端已连接";
  } catch {
    dot.className = "status-dot error";
    text.textContent = "后端未连接";
  }
}

// ---------------------------------------------------------------------------
// Tab 切换
// ---------------------------------------------------------------------------

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
  });
});

// ---------------------------------------------------------------------------
// 配置管理
// ---------------------------------------------------------------------------

function serializeConfig() {
  const f = document.getElementById("configForm");
  const get = (name) => {
    const el = f.querySelector(`[name="${name}"]`);
    if (!el) return undefined;
    if (el.type === "number") return parseInt(el.value) || 0;
    if (el.tagName === "SELECT" && (el.value === "true" || el.value === "false")) return el.value === "true";
    return el.value;
  };
  return {
    chunk_size: get("chunk_size"),
    mini_chunk_size: get("mini_chunk_size"),
    enable_large_chunks: get("enable_large_chunks"),
    large_chunk_ratio: get("large_chunk_ratio"),
    enable_contextual_rag: get("enable_contextual_rag"),
    use_llm: get("use_llm"),
    enable_enrichment: get("enable_enrichment"),
    embedding_backend: get("embedding_backend"),
    embedding_model: get("embedding_model") || null,
    embedding_batch_size: get("embedding_batch_size"),
    embedding_device: get("embedding_device"),
    normalize_embeddings: get("normalize_embeddings"),
    openai_api_key: get("openai_api_key") || "",
    // 图片处理参数
    enable_image_processing: get("enable_image_processing"),
    image_processor_backend: get("image_processor_backend"),
    image_processor_model: get("image_processor_model") || null,
    image_processor_api_key: get("image_processor_api_key") || "",
    image_processor_base_url: get("image_processor_base_url") || "",
    ocr_languages: get("ocr_languages") || "ch_sim,en",
    ocr_device: get("ocr_device") || "cpu",
    image_min_width: get("image_min_width"),
    image_min_height: get("image_min_height"),
    qdrant_mode: get("qdrant_mode"),
    qdrant_path: get("qdrant_path"),
    qdrant_host: get("qdrant_host"),
    qdrant_port: get("qdrant_port"),
    qdrant_grpc_port: get("qdrant_grpc_port"),
    qdrant_collection_name: get("qdrant_collection_name"),
    qdrant_distance: get("qdrant_distance"),
    qdrant_vector_size: get("qdrant_vector_size"),
    qdrant_api_key: get("qdrant_api_key") || "",
    qdrant_https: get("qdrant_https"),
    log_pattern_collection_name: get("log_pattern_collection_name") || "log_patterns_collection",
  };
}

function applyConfig(cfg) {
  const f = document.getElementById("configForm");
  for (const [key, val] of Object.entries(cfg)) {
    const el = f.querySelector(`[name="${key}"]`);
    if (!el) continue;
    if (el.tagName === "SELECT" && typeof val === "boolean") {
      el.value = String(val);
    } else {
      el.value = val ?? "";
    }
  }
  toggleQdrantFields();
  toggleEmbeddingFields();
  toggleImageProcessingFields();
}

document.getElementById("configForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("configSaveMsg");
  try {
    await api("POST", "/config", serializeConfig());
    msg.textContent = "配置已保存";
    msg.className = "form-message";
    showToast("配置保存成功", "success");
  } catch (err) {
    msg.textContent = err.message;
    msg.className = "form-message error";
    showToast("保存失败: " + err.message, "error");
  }
  setTimeout(() => msg.textContent = "", 3000);
});

// Qdrant 字段显示/隐藏
function toggleQdrantFields() {
  const mode = document.getElementById("qdrant_mode").value;
  document.querySelectorAll(".remote-field").forEach(el => {
    el.style.display = mode === "remote" ? "" : "none";
  });
  document.getElementById("group_qdrant_path").style.display = mode === "local" ? "" : "none";
}

document.getElementById("qdrant_mode").addEventListener("change", toggleQdrantFields);

// Embedding 字段显示/隐藏
function toggleEmbeddingFields() {
  const backend = document.getElementById("embedding_backend").value;
  document.getElementById("group_device").style.display = backend === "local" ? "" : "none";
  document.getElementById("group_normalize").style.display = backend === "local" ? "" : "none";
}

document.getElementById("embedding_backend").addEventListener("change", toggleEmbeddingFields);

// 图片处理字段显示/隐藏
function toggleImageProcessingFields() {
  const enabled = document.getElementById("enable_image_processing").value === "true";
  const backend = document.getElementById("image_processor_backend").value;

  document.querySelectorAll(".ip-local-field").forEach(el => {
    el.style.display = enabled && backend === "local" ? "" : "none";
  });
  document.querySelectorAll(".ip-remote-field").forEach(el => {
    el.style.display = enabled && backend === "remote" ? "" : "none";
  });
  document.getElementById("image_processor_backend").disabled = !enabled;
}

document.getElementById("enable_image_processing").addEventListener("change", toggleImageProcessingFields);
document.getElementById("image_processor_backend").addEventListener("change", toggleImageProcessingFields);

async function loadConfig() {
  try {
    const cfg = await api("GET", "/config");
    applyConfig(cfg);
  } catch {
    showToast("加载配置失败", "error");
  }
}

// ---------------------------------------------------------------------------
// 文件上传
// ---------------------------------------------------------------------------

const uploadedFiles = []; // {file_id, filename, size, type}

const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");

dropZone.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) uploadFiles(fileInput.files);
  fileInput.value = "";
});

async function uploadFiles(files) {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);

  try {
    const res = await api("POST", "/upload/batch", fd);
    const uploaded = res.files || [];
    const errs = res.errors || [];

    for (const f of uploaded) uploadedFiles.push(f);
    renderFileTable();

    if (errs.length) {
      for (const e of errs) {
        showToast(`${e.filename}: ${e.error}`, "error");
      }
    }

    if (uploaded.length) {
      showToast(`上传成功 ${uploaded.length} 个文件`, "success");
    } else if (!errs.length) {
      showToast("没有文件被上传", "warning");
    }
  } catch (err) {
    showToast("上传失败: " + err.message, "error");
  }
}

function renderFileTable() {
  const tbody = document.getElementById("fileTableBody");
  const hint = document.getElementById("emptyFileHint");
  const clearBtn = document.getElementById("clearAllBtn");
  const processBtn = document.getElementById("processBtn");

  tbody.innerHTML = "";
  if (uploadedFiles.length === 0) {
    hint.style.display = "";
    clearBtn.disabled = true;
    processBtn.disabled = true;
    return;
  }

  hint.style.display = "none";
  clearBtn.disabled = false;
  processBtn.disabled = false;

  uploadedFiles.forEach((f, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" class="file-check" data-idx="${i}" checked></td>
      <td>${f.filename}</td>
      <td>${formatSize(f.size)}</td>
      <td>${f.type.toUpperCase()}</td>
      <td>-</td>
      <td><button class="btn btn-danger btn-sm" data-del="${i}">删除</button></td>
    `;
    tbody.appendChild(tr);
  });

  // 删除按钮
  tbody.querySelectorAll("[data-del]").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.del);
      const fid = uploadedFiles[idx].file_id;
      api("DELETE", "/documents/" + fid).catch(() => {});
      uploadedFiles.splice(idx, 1);
      renderFileTable();
    });
  });

  // 全选
  document.getElementById("selectAll").onchange = (e) => {
    tbody.querySelectorAll(".file-check").forEach(cb => cb.checked = e.target.checked);
  };
}

document.getElementById("clearAllBtn").addEventListener("click", () => {
  for (const f of uploadedFiles) {
    api("DELETE", "/documents/" + f.file_id).catch(() => {});
  }
  uploadedFiles.length = 0;
  renderFileTable();
});

// ---------------------------------------------------------------------------
// 处理（向量化）
// ---------------------------------------------------------------------------

document.getElementById("processBtn").addEventListener("click", async () => {
  const checked = document.querySelectorAll(".file-check:checked");
  if (checked.length === 0) {
    showToast("请至少选择一个文件", "error");
    return;
  }

  const fileIds = [];
  checked.forEach(cb => {
    const idx = parseInt(cb.dataset.idx);
    if (uploadedFiles[idx]) fileIds.push(uploadedFiles[idx].file_id);
  });

  const enableEmbedding = document.getElementById("enableEmbedding").checked;
  const enableVectorStore = document.getElementById("enableVectorStore").checked;

  try {
    const res = await api("POST", "/process", {
      file_ids: fileIds,
      enable_embedding: enableEmbedding,
      enable_vector_store: enableVectorStore,
    });
    showToast(`任务已创建: ${res.file_count} 个文件`, "success");
    // 切换到任务 tab
    document.querySelector('[data-tab="tasks"]').click();
    startTaskPolling();
  } catch (err) {
    showToast("创建任务失败: " + err.message, "error");
    if (err.message.includes("未找到有效的文件")) {
      await loadDocuments();
      showToast("文件列表已与服务端同步，请重新勾选", "warning");
    }
  }
});

// ---------------------------------------------------------------------------
// 任务状态
// ---------------------------------------------------------------------------

let taskPollTimer = null;

function startTaskPolling() {
  if (taskPollTimer) return;
  loadTasks(true);
  taskPollTimer = setInterval(() => loadTasks(true), 3000);
}

function stopTaskPolling() {
  if (taskPollTimer) { clearInterval(taskPollTimer); taskPollTimer = null; }
}

async function loadTasks(silent = false) {
  const refreshBtn = document.getElementById("refreshTasksBtn");
  if (refreshBtn) {
    refreshBtn.disabled = true;
    refreshBtn.textContent = "刷新中...";
  }

  try {
    const data = await api("GET", "/tasks");
    renderTasks(data.tasks);
    // 如果所有任务都已完成，停止轮询
    const tasks = data.tasks || [];
    const allDone = tasks.every(t => t.status === "completed" || t.status === "failed" || t.status === "partial");
    if (allDone && tasks.length > 0) stopTaskPolling();
  } catch (err) {
    if (!silent) showToast("刷新任务失败: " + err.message, "error");
  } finally {
    if (refreshBtn) {
      refreshBtn.disabled = false;
      refreshBtn.textContent = "刷新";
    }
  }
}

document.getElementById("refreshTasksBtn").addEventListener("click", loadTasks);

// 重复上一次任务（文件已删除的自动跳过，跳过数在 toast 中提示）
document.getElementById("repeatLastTaskBtn").addEventListener("click", async () => {
  try {
    const res = await api("POST", "/tasks/repeat");
    let msg = `已创建任务: ${res.file_count} 个文件`;
    if (res.skipped) msg += `（跳过已删除 ${res.skipped} 个）`;
    showToast(msg, "success");
    startTaskPolling();
  } catch (err) {
    showToast("重复任务失败: " + err.message, "error");
  }
});

function renderTasks(tasks) {
  const container = document.getElementById("taskList");
  const hint = document.getElementById("emptyTaskHint");

  if (!tasks || tasks.length === 0) {
    container.innerHTML = "";
    if (hint) {
      container.appendChild(hint);
      hint.style.display = "";
    }
    return;
  }

  if (hint) hint.style.display = "none";
  container.innerHTML = "";

  tasks.forEach(task => {
    const card = document.createElement("div");
    card.className = "task-card";

    const statusLabel = { pending: "等待中", processing: "处理中", completed: "已完成", failed: "失败", partial: "部分完成" };

    let filesHtml = "";
    if (task.files) {
      filesHtml = task.files.map(f => {
        const fs = { pending: "等待中", processing: "处理中", completed: "完成", failed: "失败" };
        let stats = "";
        if (f.status === "completed") {
          stats = `Chunks: ${f.chunk_count} | Mini: ${f.mini_chunk_count} | Large: ${f.large_chunk_count}`;
        }
        return `<div class="task-file-row">
          <span class="task-file-name">${f.filename}</span>
          <span class="task-status ${f.status}">${fs[f.status] || f.status}</span>
          ${stats ? `<span class="task-file-stats">${stats}</span>` : ""}
          ${f.error ? `<span class="task-file-error">${f.error}</span>` : ""}
        </div>`;
      }).join("");
    }

    card.innerHTML = `
      <div class="task-header">
        <span class="task-id">${task.task_id.substring(0, 8)}</span>
        <span class="task-status ${task.status}">${statusLabel[task.status] || task.status}</span>
        <button class="btn btn-sm btn-danger" data-del-task="${task.task_id}">删除</button>
      </div>
      <div class="task-time">${task.created_at || ""}</div>
      <div class="task-files">${filesHtml}</div>
    `;
    container.appendChild(card);
  });

  // 删除任务（执行中的后端会拒绝并返回 400）
  container.querySelectorAll("[data-del-task]").forEach(btn => {
    btn.addEventListener("click", async () => {
      try {
        await api("DELETE", "/tasks/" + btn.dataset.delTask);
        showToast("任务已删除", "success");
        loadTasks();
      } catch (err) {
        showToast("删除任务失败: " + err.message, "error");
      }
    });
  });
}

// ---------------------------------------------------------------------------
// 向量查询
// ---------------------------------------------------------------------------

document.getElementById("queryBtn").addEventListener("click", doQuery);
document.getElementById("queryInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doQuery();
});

async function doQuery() {
  const query = document.getElementById("queryInput").value.trim();
  if (!query) { showToast("请输入查询文本", "error"); return; }

  const topK = parseInt(document.getElementById("queryTopK").value) || 5;
  const filterStr = document.getElementById("queryFilter").value.trim();
  let filters = null;
  if (filterStr && filterStr.includes("=")) {
    const [k, v] = filterStr.split("=", 2);
    filters = { [k.trim()]: v.trim() };
  }

  const resultsDiv = document.getElementById("queryResults");
  resultsDiv.innerHTML = '<div class="empty-hint">查询中...</div>';

  try {
    const data = await api("POST", "/query", { query, top_k: topK, filters });
    if (!data.results || data.results.length === 0) {
      resultsDiv.innerHTML = '<div class="empty-hint">未找到匹配结果</div>';
      return;
    }

    resultsDiv.innerHTML = "";
    data.results.forEach(r => {
      const card = document.createElement("div");
      card.className = "result-card";
      const levelLabel = r.chunk_level || (r.is_large_chunk ? "large" : "standard");
      const levelText = {
        large: "Large Chunk",
        standard: "Standard Chunk",
        mini: "Mini Chunk",
        image: "Image Chunk",
        tabular: "Tabular Chunk"
      }[levelLabel] || levelLabel;
      card.innerHTML = `
        <div class="result-header">
          <span class="result-title">${r.title || "未知文档"}</span>
          <span class="result-score">Score: ${r.score}</span>
        </div>
        <div class="result-meta">
          ${levelText} | 文档: ${r.document_id} | Chunk: ${r.chunk_id}
        </div>
        <div class="result-content">${escapeHtml(r.content)}</div>
      `;
      resultsDiv.appendChild(card);
    });
  } catch (err) {
    resultsDiv.innerHTML = `<div class="empty-hint" style="color:var(--danger)">查询失败: ${err.message}</div>`;
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// ---------------------------------------------------------------------------
// 日志模式导入
// ---------------------------------------------------------------------------

const lpFileInput = document.getElementById("lpFileInput");
const lpDropZone = document.getElementById("lpDropZone");
let lpSelectedFile = null;

lpDropZone.addEventListener("click", () => lpFileInput.click());
lpDropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  lpDropZone.classList.add("dragover");
});
lpDropZone.addEventListener("dragleave", () => lpDropZone.classList.remove("dragover"));
lpDropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  lpDropZone.classList.remove("dragover");
  if (e.dataTransfer.files.length > 0) {
    lpSelectedFile = e.dataTransfer.files[0];
    lpDropZone.querySelector("p").textContent = `已选择: ${lpSelectedFile.name}`;
  }
});
lpFileInput.addEventListener("change", () => {
  if (lpFileInput.files.length > 0) {
    lpSelectedFile = lpFileInput.files[0];
    lpDropZone.querySelector("p").textContent = `已选择: ${lpSelectedFile.name}`;
  }
});

// 导入模式切换
document.querySelectorAll('input[name="lpMode"]').forEach(radio => {
  radio.addEventListener("change", () => {
    const mode = document.querySelector('input[name="lpMode"]:checked').value;
    document.getElementById("lpFileArea").style.display = mode === "file" ? "" : "none";
    document.getElementById("lpTextArea").style.display = mode === "text" ? "" : "none";
  });
});

document.getElementById("lpImportBtn").addEventListener("click", async () => {
  const btn = document.getElementById("lpImportBtn");
  const msg = document.getElementById("lpImportMsg");
  const resultDiv = document.getElementById("lpResult");
  const collection = document.getElementById("lpCollection").value.trim();
  const mode = document.querySelector('input[name="lpMode"]:checked').value;

  btn.disabled = true;
  btn.textContent = "导入中...";
  msg.textContent = "";
  resultDiv.innerHTML = "";

  try {
    let data;
    if (mode === "file") {
      if (!lpSelectedFile) {
        throw new Error("请先选择日志模式文件");
      }
      const formData = new FormData();
      formData.append("file", lpSelectedFile);
      if (collection) formData.append("collection_name", collection);
      const res = await fetch(API + "/log_patterns/import", {
        method: "POST",
        body: formData,
      });
      data = await res.json();
      if (!res.ok && res.status !== 207) {
        throw new Error(data.error || "导入失败");
      }
    } else {
      const text = document.getElementById("lpJsonText").value.trim();
      if (!text) {
        throw new Error("请粘贴日志模式 JSON");
      }
      let patterns;
      try {
        const parsed = JSON.parse(text);
        patterns = Array.isArray(parsed) ? parsed : parsed.patterns;
        if (!Array.isArray(patterns)) {
          throw new Error("JSON 应为数组或 {\"patterns\": [...]} 结构");
        }
      } catch (e) {
        throw new Error("JSON 解析失败: " + e.message);
      }
      data = await api("POST", "/log_patterns/import_json", {
        patterns,
        collection_name: collection || undefined,
      });
    }

    const statusText = data.status === "imported" ? "导入成功" : data.status;
    msg.textContent = statusText;
    msg.className = "form-message" + (data.invalid_patterns ? " error" : "");

    resultDiv.innerHTML = `
      <div class="result-card">
        <div class="result-meta">
          模式: ${data.valid_patterns}/${data.patterns} 有效 |
          standard chunks: ${data.standard_chunks} |
          mini chunks: ${data.mini_chunks} |
          collection: ${data.collection}
          ${data.total_points !== undefined ? " | 总点数: " + data.total_points : ""}
        </div>
        <pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>
      </div>
    `;
    showToast(statusText + `: ${data.valid_patterns} 条模式`, data.invalid_patterns ? "error" : "success");
  } catch (err) {
    msg.textContent = err.message;
    msg.className = "form-message error";
    showToast("导入失败: " + err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "导入日志模式";
  }
});

// ---------------------------------------------------------------------------
// 初始化
// ---------------------------------------------------------------------------

// 与服务端文档注册表同步（重启/多标签页变动后保持列表一致）
async function loadDocuments() {
  try {
    const res = await api("GET", "/documents");
    uploadedFiles.length = 0;
    for (const d of res.documents || []) uploadedFiles.push(d);
    renderFileTable();
  } catch (err) {
    showToast("同步文件列表失败: " + err.message, "error");
  }
}

(async function init() {
  checkHealth();
  setInterval(checkHealth, 30000);
  await loadConfig();
  await loadDocuments();
  loadTasks();
})();
