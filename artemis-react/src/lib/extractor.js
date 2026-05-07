const MODE_CONFIG = {
  recall: { minScore: 2.3, maxTermsPerSentence: 12 },
  balanced: { minScore: 2.8, maxTermsPerSentence: 8 },
  strict: { minScore: 3.4, maxTermsPerSentence: 6 },
};

const TYPE_HINTS = {
  pol: ["政策", "制度", "法律", "法规", "治理", "监管"],
  eco: ["经济", "市场", "产业", "资本", "投资", "劳动"],
  soc: ["社会", "人口", "教育", "医疗", "福利", "就业"],
  tech: ["技术", "AI", "算法", "模型", "系统", "数据", "LLM", "NLP"],
  cul: ["文化", "语言", "翻译", "历史", "价值观", "旅游"],
  edu: ["教育", "学校", "大学", "课程", "研究", "学习"],
  org: ["委员会", "协会", "机构", "组织", "研究所", "公司"],
};

const STOP_WORDS = new Set([
  "问题",
  "情况",
  "方面",
  "内容",
  "方式",
  "这个",
  "那个",
  "这些",
  "那些",
  "这里",
  "那里",
  "我们",
  "他们",
  "人们",
]);

const TERM_SUFFIX = /(化|性|型|制|论|法|系统|模型|算法|机制|体系|战略|治理|平台|经济|产业)$/;
const ACRONYM = /\b[A-Z]{2,12}\b/g;
const CJK_BLOCK = /[\u4e00-\u9fff\u3040-\u30ff]/;

function normalize(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function pickTextField(value) {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    if (typeof value.text === "string") return value.text;
    if (typeof value.content === "string") return value.content;
    if (typeof value.value === "string") return value.value;
  }
  return "";
}

function normalizeKey(term) {
  return normalize(term).toLowerCase().replace(/\s+/g, "");
}

function classifyType(term) {
  let winner = "term";
  let score = 0;
  for (const [type, hints] of Object.entries(TYPE_HINTS)) {
    const current = hints.reduce((acc, hint) => (term.includes(hint) ? acc + hint.length : acc), 0);
    if (current > score) {
      score = current;
      winner = type;
    }
  }
  return winner;
}

function scoreTerm(term, srcText) {
  let score = 0;
  if (term.length >= 2) score += 0.8;
  if (term.length >= 4) score += 0.6;
  if (TERM_SUFFIX.test(term)) score += 1.1;
  if (/[A-Z]{2,}/.test(term)) score += 1.2;
  if (CJK_BLOCK.test(term)) score += 0.8;
  if (srcText.includes(term)) score += 0.9;
  if (STOP_WORDS.has(term)) score -= 1.5;
  return score;
}

function chooseTarget(term, tgtText) {
  if (!tgtText) return "";
  if (tgtText.includes(term)) return term;
  const chars = term.split("").filter(Boolean);
  const overlap = chars.filter((c) => tgtText.includes(c)).length;
  if (overlap >= Math.max(2, Math.floor(chars.length * 0.5))) {
    return term;
  }
  return "";
}

function readPairs(raw) {
  const arr = Array.isArray(raw)
    ? raw
    : raw?.data || raw?.items || raw?.sentences || raw?.records || raw?.segments || [];
  if (!Array.isArray(arr)) return [];

  return arr
    .map((item, idx) => {
      const sentId = item?.sent_id || item?.id || item?.sentence_id || item?.seg_id || idx + 1;
      const srcRaw =
        item?.src_text ||
        item?.source_text ||
        item?.source ||
        item?.src ||
        item?.ja ||
        item?.jp ||
        item?.zh ||
        item?.text;
      const tgtRaw =
        item?.tgt_text ||
        item?.target_text ||
        item?.target ||
        item?.tgt ||
        item?.translation ||
        item?.zh_translation ||
        item?.mt ||
        item?.trans;
      const srcText = normalize(
        pickTextField(srcRaw),
      );
      const tgtText = normalize(
        pickTextField(tgtRaw),
      );
      if (!srcText) return null;
      return { sentId, srcText, tgtText };
    })
    .filter(Boolean);
}

function splitChunks(text) {
  return normalize(text)
    .split(/[。！？!?；;，,、：:\n\r\t()（）【】「」"'“”]/)
    .map((x) => normalize(x))
    .filter((x) => x && x.length >= 2);
}

function extractCandidates(pair) {
  const bag = new Map();
  const push = (term, source) => {
    const t = normalize(term);
    const key = normalizeKey(t);
    if (!t || t.length < 2 || STOP_WORDS.has(t)) return;
    const current = bag.get(key) || { term: t, source: new Set() };
    current.source.add(source);
    bag.set(key, current);
  };

  splitChunks(pair.srcText).forEach((chunk) => {
    if (chunk.length <= 24) push(chunk, "chunk");
    if (chunk.length > 4) {
      for (let i = 0; i < chunk.length; i += 1) {
        for (let n = 2; n <= 6; n += 1) {
          const part = chunk.slice(i, i + n);
          if (part.length === n) push(part, "ngram");
        }
      }
    }
  });

  const acronyms = pair.srcText.match(ACRONYM) || [];
  acronyms.forEach((a) => push(a, "acronym"));

  return Array.from(bag.values()).map((cand) => {
    const algoScore = scoreTerm(cand.term, pair.srcText);
    const termTgt = chooseTarget(cand.term, pair.tgtText);
    return {
      sent_id: pair.sentId,
      src_text: pair.srcText,
      tgt_text: pair.tgtText,
      term_src: cand.term,
      term_tgt: termTgt,
      type: classifyType(cand.term),
      note: "",
      algo_score: Number(algoScore.toFixed(2)),
      source: Array.from(cand.source).join(","),
    };
  });
}

export function runArtemisExtraction(jsonPayload, mode = "balanced", onProgress) {
  const pairs = readPairs(jsonPayload);
  const conf = MODE_CONFIG[mode] || MODE_CONFIG.balanced;
  const rows = [];
  const dedup = new Set();

  pairs.forEach((pair, index) => {
    const candidates = extractCandidates(pair)
      .filter((x) => x.algo_score >= conf.minScore)
      .sort((a, b) => b.algo_score - a.algo_score)
      .slice(0, conf.maxTermsPerSentence);

    candidates.forEach((c) => {
      const key = normalizeKey(c.term_src);
      if (dedup.has(key)) return;
      dedup.add(key);
      rows.push(c);
    });

    if (typeof onProgress === "function") {
      onProgress({
        current: index + 1,
        total: pairs.length,
        percent: pairs.length ? Math.round(((index + 1) / pairs.length) * 100) : 100,
      });
    }
  });

  return { rows, totalPairs: pairs.length };
}

export function exportCsv(rows) {
  const optionalHeaders = ["algo_score", "final_score", "source"];
  const headers = ["sent_id", "src_text", "tgt_text", "term_src", "term_tgt", "type", "note"].concat(
    optionalHeaders.filter((header) => rows.some((row) => row[header] !== undefined)),
  );
  const content = [
    headers.join(","),
    ...rows.map((row) =>
      headers
        .map((h) => {
          const value = String(row[h] ?? "").replaceAll('"', '""');
          return `"${value}"`;
        })
        .join(","),
    ),
  ].join("\n");
  return new Blob([content], { type: "text/csv;charset=utf-8;" });
}
