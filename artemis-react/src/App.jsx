import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import heroImage from "../../hero.png";
import introVideo from "../../assets/37546101229-1-192-enhanced.mp4";
import kzAvatar from "./assets/KZ.png";
import moonFlagImage from "./assets/moon-flag.svg";
import qgAvatar from "./assets/QG.png";
import zekaiAvatar from "./assets/Zekai.png";

const modes = ["recall", "balanced", "strict"];
const STORAGE_KEY = "artemis:lastRows";
const API_BASE = (import.meta.env.VITE_API_BASE || "http://127.0.0.1:8765").replace(/\/$/, "");
const REQUEST_TIMEOUT_MS = 180000;
const FULL_BATCH_SIZE = 8;
const JUDGE_BATCH_SIZE = 16;
const typeLabels = {
  cul: "文化",
  eco: "经济",
  edu: "教育",
  org: "组织",
  pol: "政策",
  soc: "社会",
  tech: "技术",
  term: "术语",
};
const llmModes = [
  { value: "full", label: "full" },
  { value: "judge", label: "judge" },
  { value: "off", label: "off" },
];
const developers = [
  { name: "Kai Zhang", avatar: kzAvatar },
  { name: "Qiushi Gu", avatar: qgAvatar },
  { name: "Zekai Wu", avatar: zekaiAvatar },
];
const quoteItems = [
  "“We choose to go to the Moon.”",
  "John F. Kennedy · Rice University · 1962",
  "“That’s one small step for man, one giant leap for mankind.”",
  "Neil Armstrong · Apollo 11 · 1969",
  "“The Earth is the cradle of humanity, but mankind cannot stay in the cradle forever.”",
  "Konstantin Tsiolkovsky",
  "“循此苦旅，终抵群星。”",
  "Artemis Mission Log",
  "“一歩ずつ、星の海へ。”",
  "Japanese Mission Proverb",
];
const panelMotion = {
  hidden: { opacity: 0, y: 18 },
  show: { opacity: 1, y: 0 },
};

function formatTimeInZone(date, timeZone) {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone,
  }).format(date);
}

function formatMarsTime(date) {
  const unixMillis = date.getTime();
  const jdUtc = unixMillis / 86400000 + 2440587.5;
  const msd = (jdUtc - 2405522.0028779) / 1.0274912517;
  const mtcHours = (((msd % 1) + 1) % 1) * 24;
  const hours = Math.floor(mtcHours);
  const minutes = Math.floor((mtcHours - hours) * 60);
  const seconds = Math.floor((((mtcHours - hours) * 60) - minutes) * 60);
  return [hours, minutes, seconds].map((x) => String(x).padStart(2, "0")).join(":");
}

function formatMoonTime(date) {
  return formatTimeInZone(date, "UTC");
}

async function runPythonExtraction(payload, options, signal) {
  const response = await fetch(`${API_BASE}/api/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payload, ...options }),
    signal,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) {
    throw new Error(data.error || "Python API 没有返回有效结果。");
  }
  return data;
}

function getPayloadItems(payload) {
  if (Array.isArray(payload)) {
    return { items: payload, key: null };
  }
  if (!payload || typeof payload !== "object") {
    return { items: [], key: null };
  }
  const key = ["data", "items", "sentences", "records", "segments"].find((name) => Array.isArray(payload[name]));
  return { items: key ? payload[key] : [], key };
}

function buildChunkPayload(payload, key, items) {
  if (Array.isArray(payload)) {
    return items;
  }
  return { ...payload, [key]: items };
}

function chunkList(items, size) {
  const chunks = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function dedupeRows(rows) {
  const seen = new Set();
  return rows.filter((row) => {
    const key = `${String(row.term_src || "").trim().toLowerCase()}::${String(row.term_tgt || "").trim().toLowerCase()}`;
    if (!row.term_src || seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

async function checkApiHealth(signal) {
  try {
    const response = await fetch(`${API_BASE}/api/health`, { signal });
    return response.ok;
  } catch {
    return false;
  }
}

async function downloadRows(rows) {
  const response = await fetch(`${API_BASE}/api/export-xlsx`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows }),
  });
  if (!response.ok) {
    throw new Error("Excel 导出失败，请确认 Python API 正在运行。");
  }
  const blob = new Blob([await response.arrayBuffer()], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `artemis_terms_${Date.now()}.xlsx`;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function App() {
  const [showIntro, setShowIntro] = useState(true);
  const [mode, setMode] = useState("balanced");
  const [llmMode, setLlmMode] = useState("full");
  const [allowEmptyTarget, setAllowEmptyTarget] = useState(false);
  const [includeNamedEntities, setIncludeNamedEntities] = useState(false);
  const [jsonText, setJsonText] = useState("");
  const [rows, setRows] = useState([]);
  const [extractionDone, setExtractionDone] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 0, percent: 0 });
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [runtime, setRuntime] = useState("Python V3.1");
  const [now, setNow] = useState(() => new Date());
  const [apiOnline, setApiOnline] = useState(null);
  const [fileName, setFileName] = useState("");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [openHelp, setOpenHelp] = useState({ mode: false, ai: false });
  const abortRef = useRef(null);
  const progressTimerRef = useRef(null);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const check = async () => setApiOnline(await checkApiHealth(controller.signal));
    check();
    const timer = window.setInterval(check, 12000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "[]");
      if (Array.isArray(saved) && saved.length) {
        setRows(saved);
        setExtractionDone(true);
        setRuntime("Python V3.1 / 已恢复上次结果");
      }
    } catch {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  const stats = useMemo(() => {
    const typeCount = rows.reduce((acc, row) => {
      acc[row.type] = (acc[row.type] || 0) + 1;
      return acc;
    }, {});
    return {
      total: rows.length,
      uniqueType: Object.keys(typeCount).length,
      topType: Object.entries(typeCount).sort((a, b) => b[1] - a[1])[0]?.[0] || "-",
    };
  }, [rows]);

  const payloadMeta = useMemo(() => {
    if (!jsonText.trim()) {
      return { status: "empty", label: "Waiting", pairs: "-", chars: 0 };
    }
    try {
      const payload = JSON.parse(jsonText);
      const list = Array.isArray(payload)
        ? payload
        : payload?.data || payload?.items || payload?.sentences || payload?.records || payload?.segments || [];
      return {
        status: "valid",
        label: "Valid JSON",
        pairs: Array.isArray(list) ? list.length : "-",
        chars: jsonText.length,
      };
    } catch {
      return { status: "invalid", label: "Invalid JSON", pairs: "-", chars: jsonText.length };
    }
  }, [jsonText]);

  const availableTypes = useMemo(
    () => Object.keys(rows.reduce((acc, row) => ({ ...acc, [row.type || "term"]: true }), {})).sort(),
    [rows],
  );

  const filteredRows = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return rows.filter((row) => {
      const rowType = row.type || "term";
      const typeMatches = typeFilter === "all" || rowType === typeFilter;
      if (!typeMatches) return false;
      if (!normalizedQuery) return true;
      return [row.term_src, row.term_tgt, row.src_text, row.tgt_text, row.note, rowType]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalizedQuery));
    });
  }, [query, rows, typeFilter]);

  const stopProgressTimer = () => {
    if (progressTimerRef.current) {
      window.clearInterval(progressTimerRef.current);
      progressTimerRef.current = null;
    }
  };

  const cancelExtraction = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    stopProgressTimer();
    setRunning(false);
    setRuntime("Python V3.1");
    setExtractionDone(false);
    setProgress({ current: 0, total: 0, percent: 0 });
  };

  useEffect(
    () => () => {
      abortRef.current?.abort();
      stopProgressTimer();
    },
    [],
  );

  const runExtraction = async () => {
    cancelExtraction();
    setError("");
    let payload;
    try {
      payload = JSON.parse(jsonText);
    } catch (e) {
      setError("JSON 解析失败，请检查格式。");
      return;
    }

    setRunning(true);
    setRows([]);
    setExtractionDone(false);
    setRuntime("连接 Python V3.1...");
    setProgress({ current: 0, total: 0, percent: 6 });

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const ok = await checkApiHealth(controller.signal);
      setApiOnline(ok);
      if (!ok) {
        throw new Error("Python API 没有启动。");
      }

      const { items, key } = getPayloadItems(payload);
      const batchSize = llmMode === "full" ? FULL_BATCH_SIZE : llmMode === "judge" ? JUDGE_BATCH_SIZE : items.length || 1;
      const chunks = key || Array.isArray(payload) ? chunkList(items, batchSize) : [items];
      const totalPairs = items.length || 1;
      const collectedRows = [];
      let effectiveLlmMode = llmMode;
      let processedPairs = 0;

      setProgress({ current: 0, total: totalPairs, percent: 1 });

      for (const [chunkIndex, chunkItems] of chunks.entries()) {
        if (controller.signal.aborted) {
          throw new DOMException("Aborted", "AbortError");
        }

        const chunkPayload = key || Array.isArray(payload)
          ? buildChunkPayload(payload, key, chunkItems)
          : payload;
        const label = chunks.length > 1 ? `批次 ${chunkIndex + 1}/${chunks.length}` : "单批";
        setRuntime(`Python V3.1 / ${llmMode} 正在调用 AI... ${label}`);

        const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
        try {
          const result = await runPythonExtraction(chunkPayload, {
            mode,
            llmMode,
            allowEmptyTarget,
            includeNamedEntities,
          }, controller.signal);
          effectiveLlmMode = result.effectiveLlmMode;
          collectedRows.push(...(result.rows || []));
          processedPairs += chunkItems.length || result.totalPairs || 0;
          const mergedRows = dedupeRows(collectedRows);
          setRows(mergedRows);
          window.localStorage.setItem(STORAGE_KEY, JSON.stringify(mergedRows));
          setProgress({
            current: Math.min(processedPairs, totalPairs),
            total: totalPairs,
            percent: Math.min(99, Math.round((processedPairs / totalPairs) * 100)),
          });
        } finally {
          window.clearTimeout(timeout);
        }
      }

      const finalRows = dedupeRows(collectedRows);
      setRows(finalRows);
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(finalRows));
      setRuntime(`Python V3.1 / ${effectiveLlmMode}`);
      setExtractionDone(true);
      setProgress({ current: totalPairs, total: totalPairs, percent: 100 });
    } catch (e) {
      const hint =
        e.name === "AbortError"
          ? "当前批次已取消或超过 3 分钟。full 模式会逐句调用 AI，建议先用 judge，或把批次大小调小后重新部署。"
          : `${e.message || "未知错误"} 请确认项目根目录里的 python artemis_api.py 正在运行。`;
      setError(`运行失败：${hint}`);
      setProgress({ current: 0, total: 0, percent: 0 });
    } finally {
      stopProgressTimer();
      abortRef.current = null;
      setRunning(false);
    }
  };

  const onFileChange = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const content = await file.text();
    setFileName(file.name);
    setJsonText(content);
  };

  const exportRows = async () => {
    setError("");
    setExporting(true);
    try {
      await downloadRows(rows);
    } catch (e) {
      setError(e.message || "Excel 导出失败。");
    } finally {
      setExporting(false);
    }
  };

  if (showIntro) {
    return (
      <main className="intro-screen">
        <div className="intro-media" aria-hidden="true">
          <video
            src={introVideo}
            autoPlay
            muted
            loop
            playsInline
            preload="auto"
          />
          <span className="intro-plume plume-a" />
          <span className="intro-plume plume-b" />
          <span className="intro-plume plume-c" />
        </div>
        <div className="intro-shade" aria-hidden="true" />
        <motion.section
          className="intro-copy"
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.72, ease: "easeOut" }}
        >
          <p>ARTEMIS PROGRAM</p>
          <h1>TERMINOLOGY<br />MISSION CONTROL</h1>
          <span>LOCAL PYTHON V3.1 · REACT CONSOLE</span>
        </motion.section>
        <motion.button
          className="intro-enter"
          type="button"
          onClick={() => setShowIntro(false)}
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.62, delay: 0.14, ease: "easeOut" }}
          whileHover={{ y: -2, scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
        >
          进入系统
        </motion.button>
      </main>
    );
  }

  return (
    <div className="page">
      <motion.header
        className="top-nav"
        initial={{ opacity: 0, y: -16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
      >
        <div className="nav-brand">ARTEMIS</div>
        <div className="mission-clocks" aria-label="Mission clocks">
          <div><span>Beijing</span><strong>{formatTimeInZone(now, "Asia/Shanghai")}</strong></div>
          <div><span>Tokyo</span><strong>{formatTimeInZone(now, "Asia/Tokyo")}</strong></div>
          <div><span>New York</span><strong>{formatTimeInZone(now, "America/New_York")}</strong></div>
          <div><span>Mars</span><strong>{formatMarsTime(now)}</strong></div>
          <div><span>Moon</span><strong>{formatMoonTime(now)}</strong></div>
        </div>
      </motion.header>
      <motion.section
        className="quote-strip"
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.52, delay: 0.06, ease: "easeOut" }}
      >
        <div className="quote-track">
          {[...quoteItems, ...quoteItems].map((item, idx) => (
            <span key={`${item}-${idx}`}>{item}</span>
          ))}
        </div>
      </motion.section>
      <motion.main
        className="shell"
        initial="hidden"
        animate="show"
        transition={{ staggerChildren: 0.08, delayChildren: 0.04 }}
      >
        <motion.aside className="sidebar glass" variants={panelMotion} transition={{ duration: 0.52, ease: "easeOut" }}>
          <div className="brand-block">
            <div>
              <div className="eyebrow">TERMINOLOGY CONSOLE</div>
              <div className="brand">ARTEMIS 术语抽取系统</div>
            </div>
            <span className="status-pill">LOCAL</span>
          </div>
          <a className="align-entry" href="/align.html">
            <span>SUBTITLE ALIGNMENT</span>
            <strong>字幕时间轴对齐</strong>
          </a>
          <div className={apiOnline ? "api-card online" : "api-card"}>
            <span>{apiOnline === null ? "CHECKING API" : apiOnline ? "PYTHON API ONLINE" : "PYTHON API OFFLINE"}</span>
            <strong>{apiOnline ? `${API_BASE} 已连接` : "确认 Python API 已部署或本机运行"}</strong>
          </div>
          <div className="row">
            <div className="row-head">
              <label>抽取模式</label>
              <button
                className="help-trigger"
                type="button"
                aria-expanded={openHelp.mode}
                onClick={() => setOpenHelp((current) => ({ ...current, mode: !current.mode }))}
              >
                说明
              </button>
            </div>
            {openHelp.mode && (
              <div className="inline-help">
                <strong>模式越靠右越严格。</strong>
                <span>Recall 适合初筛，尽量多抓候选；Balanced 适合日常检查；Strict 适合最终导出前收紧结果。</span>
              </div>
            )}
            <div className="chips">
              {modes.map((m) => (
                <motion.button
                  key={m}
                  className={mode === m ? "chip active" : "chip"}
                  onClick={() => setMode(m)}
                  whileHover={{ y: -2, scale: 1.03 }}
                  whileTap={{ scale: 0.96 }}
                >
                  {m}
                </motion.button>
              ))}
            </div>
          </div>
          <div className="row">
            <div className="row-head">
              <label>AI 模式</label>
              <button
                className="help-trigger"
                type="button"
                aria-expanded={openHelp.ai}
                onClick={() => setOpenHelp((current) => ({ ...current, ai: !current.ai }))}
              >
                说明
              </button>
            </div>
            {openHelp.ai && (
              <div className="inline-help">
                <strong>控制是否调用大模型裁判。</strong>
                <span>Full 会完整参与判断；Judge 只做裁判复核；Off 完全本地规则运行，适合没有 API Key 或快速测试。</span>
              </div>
            )}
            <div className="chips">
              {llmModes.map((item) => (
                <motion.button
                  key={item.value}
                  className={llmMode === item.value ? "chip active" : "chip"}
                  onClick={() => setLlmMode(item.value)}
                  whileHover={{ y: -2, scale: 1.03 }}
                  whileTap={{ scale: 0.96 }}
                >
                  {item.label}
                </motion.button>
              ))}
            </div>
          </div>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={allowEmptyTarget}
              onChange={(event) => setAllowEmptyTarget(event.target.checked)}
            />
            <span>允许空目标语</span>
          </label>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={includeNamedEntities}
              onChange={(event) => setIncludeNamedEntities(event.target.checked)}
            />
            <span>保留地点/人名实体</span>
          </label>
          <div className="row">
            <label>导入 JSON</label>
            <input type="file" accept=".json,application/json" onChange={onFileChange} />
            <div className={`payload-card ${payloadMeta.status}`}>
              <div>
                <span>{payloadMeta.label}</span>
                <strong>{fileName || "手动粘贴 / 尚未选择文件"}</strong>
              </div>
              <div>
                <span>Pairs</span>
                <strong>{payloadMeta.pairs}</strong>
              </div>
              <div>
                <span>Chars</span>
                <strong>{payloadMeta.chars.toLocaleString()}</strong>
              </div>
            </div>
          </div>
          <div className="row">
            <label>原始内容</label>
            <textarea
              value={jsonText}
              onChange={(e) => setJsonText(e.target.value)}
              placeholder="粘贴句对 JSON..."
              rows={10}
            />
          </div>
          <div className="actions">
            <motion.button
              className="btn primary"
              onClick={runExtraction}
              disabled={running || !jsonText.trim()}
              whileHover={{ y: -2, scale: 1.02 }}
              whileTap={{ scale: 0.97 }}
            >
              {running ? "Extracting..." : "AI 术语提取"}
            </motion.button>
            {running && (
              <motion.button
                className="btn"
                onClick={cancelExtraction}
                whileHover={{ y: -2, scale: 1.02 }}
                whileTap={{ scale: 0.97 }}
              >
                取消
              </motion.button>
            )}
            <motion.button
              className="btn"
              onClick={exportRows}
              disabled={!rows.length || exporting}
              whileHover={{ y: -2, scale: 1.02 }}
              whileTap={{ scale: 0.97 }}
            >
              {exporting ? "导出中..." : "导出 Excel"}
            </motion.button>
          </div>
          <div className="progress-voyage">
            <span className="planet earth" aria-label="Earth">🌍</span>
            <div className="progress">
              <div className="bar" style={{ width: `${progress.percent}%` }} />
              <span className="rocket" style={{ left: `${progress.percent}%` }} aria-hidden="true">🚀</span>
            </div>
            <span className="planet moon" aria-label="Moon">🌕</span>
          </div>
          <small>
            {runtime} · {progress.current}/{progress.total} ({progress.percent}%)
          </small>
          {!!error && <p className="error">{error}</p>}
          <div className="developer-card" aria-label="Developers">
            <div className="developer-head">
              <span>CREW MANIFEST</span>
              <strong>开发人员</strong>
            </div>
            <div className="developer-list">
              {developers.map((developer) => (
                <span className="developer-chip" key={developer.name}>
                  <img src={developer.avatar} alt="" aria-hidden="true" />
                  {developer.name}
                </span>
              ))}
            </div>
          </div>
        </motion.aside>

        <motion.section className="stage" variants={panelMotion} transition={{ duration: 0.58, ease: "easeOut" }}>
          <motion.section className="hero-panel" variants={panelMotion} transition={{ duration: 0.64, ease: "easeOut" }}>
            <img src={heroImage} alt="Artemis hero" className="hero-image" />
            <div className="speed-lines" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <div className="hero-overlay">
              <div className="hero-copy">
                <p className="micro">MOON TO MARS</p>
                <h1>ARTEMIS 术语抽取系统</h1>
                <p>上传中日句对 JSON，智能提取可复用术语并导出表格。</p>
              </div>
            </div>
          </motion.section>

          <motion.section
            className={`upload-panel results-panel ${extractionDone ? "completed" : ""} ${rows.length ? "has-rows" : "no-rows"}`}
            variants={panelMotion}
            transition={{ duration: 0.54, ease: "easeOut" }}
          >
            <div className="result-orbit" aria-hidden="true" />
            <div className="section-head">
              <div>
                <p className="eyebrow">RESULTS BAY</p>
                <h2>术语抽取结果</h2>
              </div>
              <span className={running ? "run-badge running" : "run-badge"}>{running ? "RUNNING" : "READY"}</span>
            </div>
            <div className={extractionDone ? "landing-status landed" : "landing-status"}>
              <div className="lunar-mark">
                <img src={moonFlagImage} alt="" className="moon-flag-image" />
              </div>
              <div>
                <span>{extractionDone ? "RUN COMPLETE" : "AWAITING TOUCHDOWN"}</span>
                <strong>
                  {extractionDone
                    ? rows.length
                      ? "术语舱已着陆，结果可以导出"
                      : "本次抽取完成，当前设置下未命中术语"
                    : "完成抽取后，结果将在此处着陆"}
                </strong>
              </div>
            </div>
            <div className="result-summary">
              <div>
                <span>Input</span>
                <strong>{payloadMeta.label}</strong>
              </div>
              <div>
                <span>Engine</span>
                <strong>{runtime}</strong>
              </div>
            </div>
            <div className="mission-readout" aria-label="Result mission readout">
              <div>
                <span>Orbit</span>
                <strong>{progress.percent}%</strong>
              </div>
              <div>
                <span>Touchdown</span>
                <strong>{extractionDone ? "locked" : "standby"}</strong>
              </div>
              <div>
                <span>Review</span>
                <strong>{filteredRows.length ? "active" : "idle"}</strong>
              </div>
            </div>
            <div className="stats">
              <div className="stat">
                <span>Total Terms</span>
                <strong>{stats.total}</strong>
              </div>
              <div className="stat">
                <span>Categories</span>
                <strong>{stats.uniqueType}</strong>
              </div>
              <div className="stat">
                <span>Top Type</span>
                <strong>{typeLabels[stats.topType] || stats.topType}</strong>
              </div>
            </div>
            <div className="result-tools">
              <label className="search-box">
                <span>Search</span>
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="术语、译文、原句..."
                />
              </label>
              <label className="select-box">
                <span>Type</span>
                <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
                  <option value="all">全部类型</option>
                  {availableTypes.map((item) => (
                    <option value={item} key={item}>{typeLabels[item] || item}</option>
                  ))}
                </select>
              </label>
              <div className="visible-count">
                <span>Visible</span>
                <strong>{filteredRows.length}/{rows.length}</strong>
              </div>
            </div>
            {!!rows.length && (
              <button className="text-action" onClick={() => {
                setRows([]);
                setExtractionDone(false);
                window.localStorage.removeItem(STORAGE_KEY);
                setQuery("");
                setTypeFilter("all");
              }}>
                清空结果
              </button>
            )}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>句号</th>
                    <th>源术语</th>
                    <th>目标</th>
                    <th>类型</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRows.length ? (
                    filteredRows.slice(0, 120).map((row, idx) => (
                      <tr key={`${row.sent_id}-${row.term_src}-${idx}`}>
                        <td>{row.sent_id}</td>
                        <td title={row.src_text}>{row.term_src}</td>
                        <td title={row.tgt_text}>{row.term_tgt || "-"}</td>
                        <td><span className="type-tag">{typeLabels[row.type] || row.type}</span></td>
                      </tr>
                    ))
                  ) : (
                    <tr className="empty-row">
                      <td colSpan="4">{rows.length ? "没有匹配当前筛选的术语" : "等待抽取结果"}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </motion.section>
        </motion.section>
      </motion.main>
    </div>
  );
}
