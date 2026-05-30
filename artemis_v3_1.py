# artemis_v3_1.py
# -*- coding: utf-8 -*-

"""
ARTEMIS V3.1
AI-Weighted Hybrid Term Extraction System

核心思想：
1. 算法负责宽召回：尽量找出可能术语候选。
2. AI 负责高权重裁判：判断候选属于 core_term / context_term / glossary_item / non_term。
3. 算法负责验真：防止幻觉、残片、重复、格式错误。
4. 输出固定 Excel 格式：
   sent_id, src_text, tgt_text, term_src, term_tgt, type, note

安装：
pip install pandas openpyxl openai python-dotenv

.env 示例：
OPENAI_API_KEY=你的新 key
OPENAI_MODEL=gpt-5.4
OPENAI_BASE_URL=https://api.openai.com/v1
ARTEMIS_LLM_API_STYLE=responses  # responses 或 chat

推荐运行：
python artemis_v3_1.py input/你的文件.json --mode balanced --llm-mode full

宽召回：
python artemis_v3_1.py input/你的文件.json --mode recall --llm-mode full --allow-empty-target

严格终版：
python artemis_v3_1.py input/你的文件.json --mode strict --llm-mode full
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# 1. 全局配置
# ============================================================

DEFAULT_MODEL = (
    os.getenv("OPENAI_MODEL")
    or os.getenv("ARTEMIS_MODEL")
    or "gpt-5.4"
)
DEFAULT_API_KEY = (
    os.getenv("ARTEMIS_API_KEY")
    or os.getenv("OPENAI_API_KEY")
    or ""
)
DEFAULT_BASE_URL = (
    os.getenv("ARTEMIS_BASE_URL")
    or os.getenv("OPENAI_BASE_URL")
    or os.getenv("OPENAI_API_BASE")
    or ""
)
DEFAULT_LLM_API_STYLE = (
    os.getenv("ARTEMIS_LLM_API_STYLE")
    or os.getenv("OPENAI_API_STYLE")
    or ("chat" if DEFAULT_BASE_URL else "responses")
)
if DEFAULT_LLM_API_STYLE not in {"responses", "chat"}:
    DEFAULT_LLM_API_STYLE = "chat" if DEFAULT_BASE_URL else "responses"

MODE_CONFIG = {
    # recall：适合初筛，保留 core + context + glossary
    "recall": {
        "algo_min_score": 1.6,
        "final_min_score": 2.7,
        "ai_weight": 0.80,
        "max_terms_per_sentence": 12,
        "keep_levels": {"core_term", "context_term", "glossary_item"},
    },

    # balanced：默认，保留 core + 较强 context
    "balanced": {
        "algo_min_score": 2.0,
        "final_min_score": 3.3,
        "ai_weight": 0.72,
        "max_terms_per_sentence": 8,
        "keep_levels": {"core_term", "context_term"},
    },

    # strict：适合最终术语表，只保留 core_term
    "strict": {
        "algo_min_score": 2.6,
        "final_min_score": 4.0,
        "ai_weight": 0.68,
        "max_terms_per_sentence": 6,
        "keep_levels": {"core_term"},
    },
}

CONFIG = {
    "model": DEFAULT_MODEL,
    "api_key": DEFAULT_API_KEY,
    "base_url": DEFAULT_BASE_URL,
    "llm_api_style": DEFAULT_LLM_API_STYLE,

    # full: AI 补充候选 + AI 裁判 + AI 对齐
    # judge: 只对算法候选做 AI 裁判 + AI 对齐
    # off: 不使用 AI
    "llm_mode": "full",

    "mode": "balanced",
    "ai_weight": 0.72,
    "algo_min_score": 2.0,
    "final_min_score": 3.3,
    "max_terms_per_sentence": 8,
    "keep_levels": {"core_term", "context_term"},

    "max_candidates_for_llm": 35,
    "max_ai_expand_terms": 8,

    # 找不到 term_tgt 是否保留
    "allow_empty_target": False,

    # 是否要求 term_tgt 字面出现在目标句中
    "require_target_substring": False,

    # 全文去重
    "deduplicate_global": True,

    # 默认不收普通地点、人名、编号等实体
    "include_named_entities": False,

    "llm_retries": 2,
    "debug_candidates": False,

    "output_columns": [
        "sent_id",
        "src_text",
        "tgt_text",
        "term_src",
        "term_tgt",
        "type",
        "note",
    ],
}

VALID_TYPES = {"pol", "eco", "soc", "tech", "cul", "edu", "org", "term"}
VALID_LEVELS = {"core_term", "context_term", "glossary_item", "non_term"}


# ============================================================
# 2. 通用信号与过滤资源
# ============================================================

TYPE_HINTS = {
    "pol": [
        "政策", "制度", "法律", "法规", "規制", "政府", "行政", "治理",
        "改革", "战略", "戦略", "公共", "监管", "管理", "条例",
    ],
    "eco": [
        "经济", "経済", "市场", "市場", "产业", "産業", "企业", "企業",
        "贸易", "貿易", "金融", "资本", "資本", "投资", "投資",
        "劳动", "労働", "雇用", "就业", "价格", "価格", "生产",
        "生産", "成本", "收益", "収益", "竞争", "競争",
    ],
    "soc": [
        "社会", "人口", "教育", "医疗", "医療", "福利", "福祉",
        "移民", "人材", "人才", "労働力", "劳动力", "地域",
        "格差", "少子", "高齢", "老龄", "雇用", "就业",
    ],
    "tech": [
        "技术", "技術", "AI", "人工智能", "人工知能", "算法",
        "アルゴリズム", "模型", "モデル", "系统", "システム",
        "数据", "データ", "平台", "プラットフォーム", "数字化",
        "デジタル", "自动化", "自動化", "API", "LLM", "NLP", "ICT", "DX",
    ],
    "cul": [
        "文化", "语言", "言語", "翻译", "翻訳", "历史", "歴史",
        "文学", "文脈", "语境", "価値観", "价值观", "観光", "旅游",
        "宗教", "仏教", "佛教", "神話", "传说", "伝説", "物語", "故事",
    ],
    "edu": [
        "教育", "学校", "大学", "课程", "授業", "学習", "留学",
        "研究", "修士", "博士", "入試", "考试", "試験", "カリキュラム",
    ],
    "org": [
        "部", "省", "庁", "委员会", "委員会", "协会", "協会",
        "机构", "機構", "组织", "組織", "研究所", "会社", "公司",
    ],
}

COMMON_TERM_SUFFIXES_ZH = [
    "政策", "制度", "机制", "体系", "战略", "治理", "管理", "模式",
    "结构", "系统", "模型", "算法", "技术", "平台", "数据",
    "市场", "产业", "经济", "资本", "劳动", "就业", "生产率",
    "风险", "安全", "路径", "效应", "能力", "资源",
    "理论", "方法", "标准", "原则", "框架", "流程", "协议",
    "文化", "语言", "翻译", "教育", "研究", "现象", "问题",
    "化", "性", "型", "制", "论", "法",
]

COMMON_TERM_SUFFIXES_JA = [
    "政策", "制度", "仕組み", "メカニズム", "戦略", "ガバナンス",
    "管理", "構造", "システム", "モデル", "アルゴリズム", "技術",
    "プラットフォーム", "データ", "市場", "産業", "経済", "資本",
    "労働", "雇用", "生産性", "リスク", "安全", "経路", "効果",
    "能力", "資源", "理論", "方法", "基準", "原則",
    "枠組み", "プロセス", "文化", "言語", "翻訳",
    "教育", "研究", "現象", "問題",
    "化", "性", "型", "制", "論", "法",
]

COMMON_TERM_PREFIXES_ZH = [
    "国际", "全球", "公共", "社会", "经济", "产业", "技术", "文化",
    "教育", "数字", "智能", "人工智能", "生成式", "现代", "新型",
    "可持续", "绿色", "跨境", "区域", "本土", "高度",
]

COMMON_TERM_PREFIXES_JA = [
    "国際", "グローバル", "公共", "社会", "経済", "産業", "技術",
    "文化", "教育", "デジタル", "人工知能", "生成", "現代",
    "新たな", "持続可能", "地域", "高度",
]

GENERIC_WORDS = {
    # Chinese
    "问题", "情况", "方面", "内容", "方式", "东西", "事情", "时候",
    "原因", "结果", "影响", "意义", "作用", "关系", "方法", "过程",
    "程度", "部分", "一些", "很多", "这个", "那个", "这些", "那些",
    "感觉", "想法", "态度", "老师", "学生", "学校", "今天", "昨天",
    "地方", "时间", "人们", "大家", "个人", "社会", "国家", "世界",
    "附近", "这里", "那里", "我们", "他们", "你们", "它们",

    # Japanese
    "問題", "場合", "内容", "方法", "もの", "こと", "理由", "結果",
    "影響", "意味", "役割", "関係", "過程", "程度", "部分",
    "これ", "それ", "あれ", "ここ", "そこ", "今日", "昨日",
    "感じ", "考え", "先生", "学生", "学校", "場所", "時間",
    "人々", "皆", "個人", "社会", "国家", "世界", "近く",
}

LOCATION_PATTERNS = [
    r"^[一二三四五六七八九十0-9０-９]+号馆$",
    r"^[一二三四五六七八九十0-9０-９]+号館$",
    r"^[一二三四五六七八九十0-9０-９]+号楼$",
    r"^[一二三四五六七八九十0-9０-９]+階$",
    r"^[一二三四五六七八九十0-9０-９]+楼$",
    r"^[A-ZＡ-Ｚ]区$",
    r"^[A-ZＡ-Ｚ]棟$",
    r"^第[一二三四五六七八九十0-9０-９]+章$",
    r"^第[一二三四五六七八九十0-9０-９]+节$",
    r"^図[0-9０-９]+$",
    r"^图[0-9０-９]+$",
    r"^表[0-9０-９]+$",
    r"^[0-9０-９]+年$",
    r"^[0-9０-９]+月$",
    r"^[0-9０-９]+日$",
    r"^[0-9０-９]+時$",
    r"^[0-9０-９]+点$",
    r"^[0-9０-９]+号$",
    r"^[0-9０-９]+番$",
]

ZH_BAD_START_END = set("的了和与及在对为把被从向由以而并或")
JA_BAD_PARTICLES = {
    "の", "に", "を", "が", "は", "へ", "で", "と", "も", "や",
    "から", "まで", "より", "について", "による", "における", "として",
}

BUILTIN_TERMS = {
    "人工智能": ("人工智能", "tech"),
    "人工知能": ("人工智能", "tech"),
    "生成AI": ("生成式AI", "tech"),
    "デジタル化": ("数字化", "tech"),
    "グローバル化": ("全球化", "eco"),
    "少子高齢化": ("少子老龄化", "soc"),
    "労働市場": ("劳动市场", "eco"),
    "文化遺産": ("文化遗产", "cul"),
    "自然景観": ("自然景观", "cul"),
    "観光資源": ("旅游资源", "cul"),
}


# ============================================================
# 3. 数据结构
# ============================================================

@dataclass
class SentencePair:
    sent_id: Any
    src_text: str
    tgt_text: str


@dataclass
class Candidate:
    term: str
    sent_id: Any
    src_text: str
    tgt_text: str
    lang: str
    source: Set[str] = field(default_factory=set)

    algo_score: float = 0.0
    ai_termhood: float = 0.0
    ai_translation_value: float = 0.0
    final_score: float = 0.0

    term_type: str = "term"
    term_tgt: str = ""
    ai_keep: bool = False
    ai_decision: str = ""
    term_level: str = "non_term"
    reasons: List[str] = field(default_factory=list)


# ============================================================
# 4. 基础工具函数
# ============================================================

def normalize_text(text: Any) -> str:
    if text is None:
        return ""
    text = str(text)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_key(term: str) -> str:
    term = normalize_text(term)
    term = term.lower()
    term = re.sub(r"\s+", "", term)
    term = term.replace("・", "")
    term = term.replace("／", "/")
    term = term.replace("-", "")
    term = term.replace("ー", "")
    return term


def extract_text_field(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return normalize_text(value)

    if isinstance(value, dict):
        for key in [
            "text", "content", "sentence",
            "src_text", "tgt_text",
            "source_text", "target_text",
            "source", "target",
            "src", "tgt",
            "ja", "jp", "zh", "cn", "en",
        ]:
            if key in value and value[key]:
                return extract_text_field(value[key])
        return ""

    if isinstance(value, list):
        parts = [extract_text_field(x) for x in value]
        parts = [p for p in parts if p]
        return normalize_text(" ".join(parts))

    return normalize_text(value)


def detect_lang(text: str) -> str:
    text = normalize_text(text)
    zh_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    kana_count = len(re.findall(r"[\u3040-\u30ff]", text))
    latin_count = len(re.findall(r"[A-Za-z]", text))

    if kana_count > 0:
        return "ja"
    if zh_count >= latin_count and zh_count > 0:
        return "zh"
    if latin_count > 0:
        return "en"
    return "unknown"


def contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff]", text))


def looks_like_acronym_or_tech(term: str) -> bool:
    t = normalize_text(term)
    if re.fullmatch(r"[A-Za-z]{2,12}", t):
        return True
    if re.search(r"(AI|DX|ICT|IT|GDP|API|LLM|NLP|SDGs|ESG|IoT)", t, re.I):
        return True
    return False


def is_pure_number_or_punctuation(term: str) -> bool:
    t = normalize_text(term)
    if re.fullmatch(r"[0-9０-９]+", t):
        return True
    if re.fullmatch(r"[\W_]+", t):
        return True
    return False


def is_location_like(term: str) -> bool:
    t = normalize_text(term)
    for pat in LOCATION_PATTERNS:
        if re.match(pat, t):
            return True
    return False


def is_generic_alone(term: str) -> bool:
    return normalize_text(term) in GENERIC_WORDS


def is_fragment(term: str, lang: str) -> bool:
    t = normalize_text(term)

    if not t:
        return True

    if len(t) <= 1:
        return True

    if is_pure_number_or_punctuation(t):
        return True

    if re.search(r"https?://|www\.|@", t):
        return True

    if re.search(r"[。！？!?；;，,]", t):
        return True

    if lang == "zh":
        if t[0] in ZH_BAD_START_END or t[-1] in ZH_BAD_START_END:
            return True

    if lang == "ja":
        for bad in JA_BAD_PARTICLES:
            if t.startswith(bad) or t.endswith(bad):
                return True

    return False


def is_named_entity_like(term: str) -> bool:
    t = normalize_text(term)

    if is_location_like(t):
        return True

    if re.search(r"(先生|老师|教授|さん|氏)$", t):
        return True

    if re.search(r"^(第)?[0-9０-９一二三四五六七八九十]+(章|节|節|号|番|層|层|页|頁)$", t):
        return True

    return False


def has_type_hint(term: str) -> bool:
    for hints in TYPE_HINTS.values():
        for h in hints:
            if h and h in term:
                return True
    return False


def classify_type(term: str) -> str:
    if term in BUILTIN_TERMS:
        return BUILTIN_TERMS[term][1]

    scores: Dict[str, int] = {}
    for typ, hints in TYPE_HINTS.items():
        score = 0
        for h in hints:
            if h and h in term:
                score += len(h)
        if score:
            scores[typ] = score

    if not scores:
        return "term"

    typ = max(scores.items(), key=lambda x: x[1])[0]
    return typ if typ in VALID_TYPES else "term"


def has_common_suffix(term: str, lang: str) -> bool:
    suffixes = COMMON_TERM_SUFFIXES_JA if lang == "ja" else COMMON_TERM_SUFFIXES_ZH
    return any(term.endswith(s) for s in suffixes)


def has_common_prefix(term: str, lang: str) -> bool:
    prefixes = COMMON_TERM_PREFIXES_JA if lang == "ja" else COMMON_TERM_PREFIXES_ZH
    return any(term.startswith(p) for p in prefixes)


def has_morphological_term_signal(term: str, lang: str) -> bool:
    if lang == "zh":
        return bool(re.search(r"(化|性|型|制|法|论|論)$", term))
    if lang == "ja":
        return bool(re.search(r"(化|性|型|制|論|法)$", term))
    return False


def split_text_chunks(text: str, lang: str) -> List[str]:
    text = normalize_text(text)
    parts = re.split(r"[。！？!?；;，,、：:（）()\[\]【】「」『』“”\"'\n\r\t]", text)

    chunks: List[str] = []

    for p in parts:
        p = normalize_text(p)
        if not p:
            continue

        if lang == "ja":
            subparts = re.split(
                r"(?:における|による|について|として|から|まで|より|には|では|"
                r"の|に|を|が|は|へ|で|と|も|や)",
                p,
            )
            chunks.extend([normalize_text(x) for x in subparts if normalize_text(x)])
        else:
            subparts = re.split(
                r"(?:以及|或者|但是|因为|所以|如果|虽然|并且|"
                r"和|与|及|对|在|由|为|通过|由于)",
                p,
            )
            chunks.extend([normalize_text(x) for x in subparts if normalize_text(x)])

    return chunks


def extract_json_array(text: str) -> List[Any]:
    text = normalize_text(text)
    if not text:
        return []

    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            for key in ["items", "terms", "data", "results"]:
                if isinstance(obj.get(key), list):
                    return obj[key]
            return []
    except Exception:
        pass

    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []

    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, list) else []
    except Exception:
        return []


def clamp_score(x: float, low: float = 0.0, high: float = 5.0) -> float:
    return max(low, min(high, x))


def target_contains(term_tgt: str, tgt_text: str) -> bool:
    if not term_tgt:
        return True
    return normalize_key(term_tgt) in normalize_key(tgt_text)


def clean_term_tgt(term_tgt: str) -> str:
    """
    对 AI 输出的目标术语做轻量规范化。
    不强行翻译，只去掉明显语境尾巴。
    """
    t = normalize_text(term_tgt)
    if not t:
        return ""

    # 去掉中文常见语境尾巴
    t = re.sub(r"(们|的|了|着|中|里|上|下|内|外)$", "", t)

    # 去掉日文常见助词尾巴
    for suf in ["の", "に", "を", "が", "は", "で", "と", "も", "へ", "から", "まで"]:
        if t.endswith(suf) and len(t) > len(suf) + 1:
            t = t[: -len(suf)]

    return normalize_text(t)


# ============================================================
# 5. JSON 读取
# ============================================================

def find_list_in_json(data: Any) -> List[Any]:
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in [
            "data", "items", "sentences", "records", "segments",
            "rows", "result", "results",
        ]:
            if isinstance(data.get(key), list):
                return data[key]

        list_values = [v for v in data.values() if isinstance(v, list)]
        if list_values:
            return max(list_values, key=len)

    return []


def read_json_pairs(path: str) -> List[SentencePair]:
    with open(path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    data = find_list_in_json(raw_data)

    if not isinstance(data, list):
        raise ValueError("JSON 必须是 list，或包含 data/items/sentences/records/segments 等 list 字段。")

    pairs: List[SentencePair] = []

    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue

        sent_id = (
            item.get("sent_id")
            or item.get("id")
            or item.get("sentence_id")
            or item.get("seg_id")
            or item.get("segment_id")
            or item.get("index")
            or i
        )

        raw_src = (
            item.get("src_text")
            or item.get("source_text")
            or item.get("source")
            or item.get("src")
            or item.get("ja")
            or item.get("jp")
            or item.get("zh")
            or item.get("text")
            or ""
        )

        raw_tgt = (
            item.get("tgt_text")
            or item.get("target_text")
            or item.get("target")
            or item.get("tgt")
            or item.get("translation")
            or item.get("zh_translation")
            or item.get("ja_translation")
            or item.get("cn")
            or item.get("en")
            or ""
        )

        src_text = extract_text_field(raw_src)
        tgt_text = extract_text_field(raw_tgt)

        if src_text:
            pairs.append(
                SentencePair(
                    sent_id=sent_id,
                    src_text=src_text,
                    tgt_text=tgt_text,
                )
            )

    return pairs


# ============================================================
# 6. 宽候选生成
# ============================================================

def add_candidate(
    cands: Dict[str, Candidate],
    term: str,
    pair: SentencePair,
    lang: str,
    source: str,
    typ: Optional[str] = None,
) -> None:
    term = normalize_text(term)
    if not term:
        return

    key = normalize_key(term)
    if not key:
        return

    if key not in cands:
        cands[key] = Candidate(
            term=term,
            sent_id=pair.sent_id,
            src_text=pair.src_text,
            tgt_text=pair.tgt_text,
            lang=lang,
            source={source},
            term_type=typ or classify_type(term),
        )
    else:
        cands[key].source.add(source)
        if typ:
            cands[key].term_type = typ


def generate_dictionary_candidates(pair: SentencePair, lang: str) -> Dict[str, Candidate]:
    cands: Dict[str, Candidate] = {}
    for term, (_, typ) in BUILTIN_TERMS.items():
        if term in pair.src_text:
            add_candidate(cands, term, pair, lang, "builtin_dict", typ)
    return cands


def generate_acronym_candidates(pair: SentencePair, lang: str) -> Dict[str, Candidate]:
    cands: Dict[str, Candidate] = {}
    for m in re.finditer(r"\b[A-Za-z][A-Za-z0-9+\-.]{1,15}\b", pair.src_text):
        term = m.group(0)
        if looks_like_acronym_or_tech(term):
            add_candidate(cands, term, pair, lang, "acronym", "tech")
    return cands


def generate_chunk_candidates(pair: SentencePair, lang: str) -> Dict[str, Candidate]:
    cands: Dict[str, Candidate] = {}
    chunks = split_text_chunks(pair.src_text, lang)

    for chunk in chunks:
        chunk = normalize_text(chunk)
        if not chunk:
            continue

        if lang == "zh":
            if 2 <= len(chunk) <= 14 and contains_cjk(chunk):
                add_candidate(cands, chunk, pair, lang, "chunk")
        elif lang == "ja":
            if 2 <= len(chunk) <= 20 and contains_cjk(chunk):
                add_candidate(cands, chunk, pair, lang, "chunk")

    return cands


def generate_pattern_candidates(pair: SentencePair, lang: str) -> Dict[str, Candidate]:
    cands: Dict[str, Candidate] = {}
    chunks = split_text_chunks(pair.src_text, lang)

    if lang == "zh":
        run_pattern = r"[\u4e00-\u9fffA-Za-z0-9]+"
        suffixes = COMMON_TERM_SUFFIXES_ZH
        prefixes = COMMON_TERM_PREFIXES_ZH
        max_len = 16
    else:
        run_pattern = r"[\u4e00-\u9fff\u3040-\u30ffA-Za-z0-9ー・]+"
        suffixes = COMMON_TERM_SUFFIXES_JA
        prefixes = COMMON_TERM_PREFIXES_JA
        max_len = 24

    for chunk in chunks:
        for run in re.findall(run_pattern, chunk):
            run = normalize_text(run)
            if not run:
                continue

            if has_type_hint(run) and 2 <= len(run) <= max_len:
                add_candidate(cands, run, pair, lang, "type_hint_run")

            for suf in suffixes:
                if suf not in run:
                    continue

                for m in re.finditer(re.escape(suf), run):
                    end = m.end()
                    left_limit = max(0, end - max_len)

                    for start in range(left_limit, end):
                        cand = run[start:end]

                        if len(cand) < 2:
                            continue
                        if cand == suf:
                            continue
                        if cand.endswith(suf):
                            add_candidate(cands, cand, pair, lang, "suffix_pattern")

            for pre in prefixes:
                if run.startswith(pre) and 2 <= len(run) <= max_len:
                    add_candidate(cands, run, pair, lang, "prefix_pattern")

            if lang == "zh":
                for m in re.finditer(r"[\u4e00-\u9fffA-Za-z0-9]{1,12}(?:化|性|型|制|法|论|論)", run):
                    add_candidate(cands, m.group(0), pair, lang, "morph_pattern")
            elif lang == "ja":
                for m in re.finditer(r"[\u4e00-\u9fff\u30a0-\u30ffA-Za-z0-9ー]{1,16}(?:化|性|型|制|論|法)", run):
                    add_candidate(cands, m.group(0), pair, lang, "morph_pattern")

    return cands


def generate_ngram_candidates(pair: SentencePair, lang: str) -> Dict[str, Candidate]:
    cands: Dict[str, Candidate] = {}
    chunks = split_text_chunks(pair.src_text, lang)

    if lang == "zh":
        pattern = r"[\u4e00-\u9fffA-Za-z0-9]+"
        min_n, max_n = 2, 8
    else:
        pattern = r"[\u4e00-\u9fff\u3040-\u30ffA-Za-z0-9ー・]+"
        min_n, max_n = 2, 10

    for chunk in chunks:
        for run in re.findall(pattern, chunk):
            run = normalize_text(run)
            if len(run) < min_n:
                continue

            upper = min(max_n, len(run))
            for n in range(min_n, upper + 1):
                for i in range(0, len(run) - n + 1):
                    cand = run[i:i + n]

                    if is_generic_alone(cand):
                        continue

                    if lang == "ja" and re.fullmatch(r"[\u3040-\u309fー]+", cand):
                        continue

                    if (
                        has_common_suffix(cand, lang)
                        or has_common_prefix(cand, lang)
                        or has_type_hint(cand)
                        or has_morphological_term_signal(cand, lang)
                        or looks_like_acronym_or_tech(cand)
                    ):
                        add_candidate(cands, cand, pair, lang, "ngram_signal")

    return cands


def generate_rule_candidates(pair: SentencePair) -> List[Candidate]:
    lang = detect_lang(pair.src_text)
    if lang not in {"zh", "ja"}:
        lang = "zh" if contains_cjk(pair.src_text) else "unknown"

    merged: Dict[str, Candidate] = {}

    generators = [
        generate_dictionary_candidates,
        generate_acronym_candidates,
        generate_chunk_candidates,
        generate_pattern_candidates,
        generate_ngram_candidates,
    ]

    for gen in generators:
        sub = gen(pair, lang)
        for key, cand in sub.items():
            if key not in merged:
                merged[key] = cand
            else:
                merged[key].source.update(cand.source)

    return list(merged.values())


# ============================================================
# 7. 算法弱评分
# ============================================================

def compute_corpus_freq(pairs: List[SentencePair], candidates: List[Candidate]) -> Dict[str, int]:
    text = "\n".join(pair.src_text for pair in pairs)
    freq: Dict[str, int] = {}

    for c in candidates:
        key = normalize_key(c.term)
        if key not in freq:
            freq[key] = max(1, text.count(c.term))

    return freq


def score_candidate(cand: Candidate, corpus_freq: Dict[str, int]) -> Candidate:
    term = cand.term
    lang = cand.lang
    length = len(term)

    raw = 0.0
    reasons: List[str] = []

    source_weights = {
        "builtin_dict": 3.0,
        "acronym": 2.0,
        "type_hint_run": 1.5,
        "suffix_pattern": 1.5,
        "prefix_pattern": 1.2,
        "morph_pattern": 1.2,
        "ngram_signal": 1.0,
        "chunk": 0.6,
        "llm_expand": 2.5,
    }

    for s in cand.source:
        if s in source_weights:
            raw += source_weights[s]
            reasons.append(s)

    if lang == "zh":
        if length == 1:
            raw -= 4.0
        elif length == 2:
            raw += 0.6
        elif 3 <= length <= 8:
            raw += 1.2
        elif 9 <= length <= 14:
            raw += 0.7
        else:
            raw -= 2.0
    elif lang == "ja":
        if length <= 1:
            raw -= 4.0
        elif 2 <= length <= 4:
            raw += 0.5
        elif 5 <= length <= 12:
            raw += 1.2
        elif 13 <= length <= 20:
            raw += 0.7
        else:
            raw -= 2.0

    if has_common_suffix(term, lang):
        raw += 1.4
        reasons.append("common_suffix")

    if has_common_prefix(term, lang):
        raw += 0.8
        reasons.append("common_prefix")

    if has_type_hint(term):
        raw += 1.2
        reasons.append("type_hint")

    if has_morphological_term_signal(term, lang):
        raw += 1.0
        reasons.append("morph_signal")

    if looks_like_acronym_or_tech(term):
        raw += 1.5
        reasons.append("acronym_or_tech")

    freq = corpus_freq.get(normalize_key(term), 1)
    if freq >= 2:
        raw += min(1.5, 0.4 * freq)
        reasons.append(f"freq_{freq}")

    if is_generic_alone(term):
        raw -= 5.0
        reasons.append("generic_alone")

    if is_fragment(term, lang):
        raw -= 5.0
        reasons.append("fragment")

    if is_location_like(term):
        raw -= 2.0
        reasons.append("location_like")

    if is_named_entity_like(term):
        raw -= 1.0
        reasons.append("entity_like")

    digit_count = len(re.findall(r"[0-9０-９]", term))
    if digit_count >= 2 and not looks_like_acronym_or_tech(term):
        raw -= 1.5
        reasons.append("digit_heavy")

    if lang == "ja" and re.fullmatch(r"[\u3040-\u309fー]+", term):
        raw -= 3.0
        reasons.append("pure_hiragana")

    cand.algo_score = clamp_score(raw, 0.0, 5.0)
    cand.reasons = reasons

    if cand.term_type not in VALID_TYPES:
        cand.term_type = classify_type(term)

    return cand


def preliminary_filter(cand: Candidate) -> bool:
    term = cand.term
    lang = cand.lang

    if not term:
        return False

    if is_fragment(term, lang):
        return False

    if is_generic_alone(term):
        return False

    if is_pure_number_or_punctuation(term):
        return False

    if not contains_cjk(term) and not looks_like_acronym_or_tech(term):
        return False

    if cand.algo_score < CONFIG["algo_min_score"]:
        return False

    return True


def resolve_nested_candidates(cands: List[Candidate]) -> List[Candidate]:
    sorted_cands = sorted(cands, key=lambda c: (c.algo_score, len(c.term)), reverse=True)
    kept: List[Candidate] = []

    for cand in sorted_cands:
        duplicate = False

        for ex in kept:
            if normalize_key(cand.term) == normalize_key(ex.term):
                duplicate = True
                break

            if cand.term in ex.term and cand.term != ex.term:
                if cand.algo_score + 1.2 < ex.algo_score and "builtin_dict" not in cand.source:
                    duplicate = True
                    break

        if not duplicate:
            kept.append(cand)

    return sorted(kept, key=lambda c: c.algo_score, reverse=True)


# ============================================================
# 8. 规则对齐兜底
# ============================================================

def rule_align_target(cand: Candidate) -> Candidate:
    tgt = cand.tgt_text
    term = cand.term

    if not tgt:
        return cand

    if term in BUILTIN_TERMS:
        suggested = BUILTIN_TERMS[term][0]
        if suggested and suggested in tgt:
            cand.term_tgt = clean_term_tgt(suggested)
            return cand

    mapping = [
        ("人工知能", "人工智能"),
        ("人工智能", "人工智能"),
        ("生成AI", "生成式AI"),
        ("デジタル化", "数字化"),
        ("グローバル化", "全球化"),
        ("少子高齢化", "少子老龄化"),
        ("労働市場", "劳动市场"),
        ("文化遺産", "文化遗产"),
        ("自然景観", "自然景观"),
        ("観光資源", "旅游资源"),
    ]

    for src_kw, tgt_kw in mapping:
        if src_kw in term and tgt_kw in tgt:
            cand.term_tgt = clean_term_tgt(tgt_kw)
            return cand

    if looks_like_acronym_or_tech(term):
        m = re.search(rf"\b{re.escape(term)}\b", tgt, re.I)
        if m:
            cand.term_tgt = clean_term_tgt(m.group(0))
            return cand

    return cand


# ============================================================
# 9. OpenAI 调用
# ============================================================

def llm_is_enabled() -> bool:
    return CONFIG["llm_mode"] in {"full", "judge"} and bool(CONFIG["api_key"])


def get_openai_client():
    from openai import OpenAI
    kwargs = {"api_key": CONFIG["api_key"], "timeout": 30.0}
    if CONFIG["base_url"]:
        kwargs["base_url"] = CONFIG["base_url"]
    return OpenAI(**kwargs)


def call_llm_responses(client: Any, prompt: str) -> str:
    response = client.responses.create(
        model=CONFIG["model"],
        input=[
            {
                "role": "system",
                "content": (
                    "You are a strict terminology extraction and bilingual term alignment assistant. "
                    "Return only valid JSON. Do not include markdown."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )
    return normalize_text(response.output_text)


def call_llm_chat_completions(client: Any, prompt: str) -> str:
    response = client.chat.completions.create(
        model=CONFIG["model"],
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a strict terminology extraction and bilingual term alignment assistant. "
                    "Return only valid JSON. Do not include markdown."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0,
    )
    return normalize_text(response.choices[0].message.content or "")


def call_llm_json_array(prompt: str, task_name: str) -> List[Any]:
    if not llm_is_enabled():
        return []

    client = get_openai_client()
    last_error: Optional[Exception] = None

    for attempt in range(1, CONFIG["llm_retries"] + 1):
        try:
            if CONFIG["llm_api_style"] == "chat":
                text = call_llm_chat_completions(client, prompt)
            else:
                text = call_llm_responses(client, prompt)
            arr = extract_json_array(text)
            if isinstance(arr, list):
                return arr

        except Exception as e:
            last_error = e
            print(f"[WARN] LLM {task_name} failed on attempt {attempt}: {e}")
            time.sleep(1.5 * attempt)

    if last_error:
        print(f"[WARN] LLM {task_name} finally failed: {last_error}")

    return []


def llm_expand_candidates(pair: SentencePair, rule_candidates: List[Candidate]) -> List[Candidate]:
    if CONFIG["llm_mode"] != "full" or not llm_is_enabled():
        return []

    lang = detect_lang(pair.src_text)
    if lang not in {"zh", "ja"}:
        lang = "zh" if contains_cjk(pair.src_text) else "unknown"

    existing = [
        {
            "term_src": c.term,
            "type_guess": c.term_type,
            "algo_score": round(c.algo_score, 2),
        }
        for c in sorted(rule_candidates, key=lambda x: x.algo_score, reverse=True)[:CONFIG["max_candidates_for_llm"]]
    ]

    prompt = f"""
你是一个通用型翻译术语抽取助手。

你的任务：
从源语句子中补充规则系统可能漏掉的“候选术语”。

你不是关键词抽取器，也不是命名实体识别器。
你的目标是为翻译术语表找候选项。

术语定义：
术语是指在某一文本主题中具有稳定概念意义、相对固定表达形式、翻译时值得保持一致的词语或短语。

请优先补充：
1. 领域概念；
2. 稳定复合名词；
3. 专业或半专业表达；
4. 翻译时需要统一译法的表达；
5. 具有概念密度的名词性短语。

请不要补充：
1. 普通日常词；
2. 情绪词，除非在该领域中具有专门概念意义；
3. 地点、楼号、编号、人名，除非它在文本中明显具有术语表价值；
4. 句子残片；
5. 泛化词，如“问题”“情况”“影响”“方面”“内容”；
6. 只因为出现频率高而重要的普通词。

源语句子：
{pair.src_text}

目标语句子：
{pair.tgt_text}

规则系统已有候选：
{json.dumps(existing, ensure_ascii=False, indent=2)}

请只输出遗漏候选，最多 {CONFIG["max_ai_expand_terms"]} 个。
输出 JSON 数组：
[
  {{
    "term_src": "必须逐字来自源语句子",
    "type": "pol/eco/soc/tech/cul/edu/org/term"
  }}
]

要求：
- term_src 必须是源语句子中的原文片段，不要改写。
- 不要输出已有候选。
- 不确定就不要补充。
- 只输出 JSON 数组。
"""

    data = call_llm_json_array(prompt, "expand")
    cands: List[Candidate] = []

    existing_keys = {normalize_key(c.term) for c in rule_candidates}

    for item in data:
        if not isinstance(item, dict):
            continue

        term = normalize_text(item.get("term_src", ""))
        typ = normalize_text(item.get("type", "term"))

        if not term:
            continue

        if normalize_key(term) in existing_keys:
            continue

        if term not in pair.src_text:
            continue

        if typ not in VALID_TYPES:
            typ = classify_type(term)

        if is_fragment(term, lang) or is_generic_alone(term):
            continue

        cands.append(
            Candidate(
                term=term,
                sent_id=pair.sent_id,
                src_text=pair.src_text,
                tgt_text=pair.tgt_text,
                lang=lang,
                source={"llm_expand"},
                term_type=typ,
            )
        )

    return cands[:CONFIG["max_ai_expand_terms"]]


def llm_judge_candidates(pair: SentencePair, candidates: List[Candidate]) -> List[Candidate]:
    if not llm_is_enabled():
        return candidates

    if not candidates:
        return []

    compact = [
        {
            "term_src": c.term,
            "type_guess": c.term_type,
            "algo_score_0_to_5": round(c.algo_score, 2),
            "term_tgt_guess": c.term_tgt,
            "source": sorted(list(c.source)),
            "signals": c.reasons[:6],
        }
        for c in sorted(candidates, key=lambda x: x.algo_score, reverse=True)[:CONFIG["max_candidates_for_llm"]]
    ]

    prompt = f"""
你是一个严格的“翻译术语表审核器”。

你的任务不是抽关键词，而是判断候选是否适合进入翻译术语表。

通用术语定义：
术语是指在当前文本主题中具有稳定概念意义、相对固定表达形式、翻译时值得保持一致的词语或短语。

请将每个候选分成四类：
1. core_term：强术语，适合进入最终术语表；
2. context_term：语境术语，当前文本中有术语价值，但不一定是跨领域强术语；
3. glossary_item：注释性词条，适合宽召回或人工复核，但不一定适合严格术语表；
4. non_term：普通词、残片、地点编号、人名、泛化表达等，不应保留。

判断标准：
- 是否是稳定概念？
- 是否具有领域性或半专业性？
- 是否具有翻译复用价值？
- 是否不是普通日常词？
- 是否不是地点、编号、人名或普通命名实体？
- 是否不是句子残片？
- 是否不是过度泛化表达？

请注意：
- “术语”不等于所有名词。
- “术语”不等于所有关键词。
- “术语”不等于所有专有名词。
- 如果某个地点/人物/机构名只是具体实体，而不是概念术语，默认不要保留。
- 如果某个表达虽然常见，但在该文本主题下需要统一译法，可以保留。
- 如果不确定，宁可把 term_level 降为 glossary_item 或 non_term。

源语句子：
{pair.src_text}

目标语句子：
{pair.tgt_text}

候选列表：
{json.dumps(compact, ensure_ascii=False, indent=2)}

请输出 JSON 数组：
[
  {{
    "term_src": "必须来自候选列表",
    "term_tgt": "目标语句子中的对应表达；没有明确对应则为空字符串",
    "type": "pol/eco/soc/tech/cul/edu/org/term",
    "termhood": 1,
    "translation_value": 1,
    "term_level": "core_term/context_term/glossary_item/non_term",
    "category_decision": "term/generic_word/location_entity/person_entity/org_entity/fragment/uncertain",
    "keep": false
  }}
]

评分说明：
- termhood: 1-5，术语性。5=非常像专业术语，1=完全不是术语。
- translation_value: 1-5，翻译复用价值。5=强烈需要术语表统一，1=不需要。
- keep: 只有当它至少是 glossary_item 且适合进入某种术语候选表时才为 true。
- strict 模式会只保留 core_term；balanced 模式保留 core_term 和较强 context_term；recall 模式可保留 glossary_item。

term_tgt 要求：
- 优先从目标语句子中摘取已有表达。
- 不要自由发挥新译文。
- 不要输出整句。
- 没有明确对应时返回空字符串。

只输出 JSON 数组，不要输出解释。
"""

    data = call_llm_json_array(prompt, "judge")
    by_key = {normalize_key(c.term): c for c in candidates}
    judged: List[Candidate] = []

    for item in data:
        if not isinstance(item, dict):
            continue

        term_src = normalize_text(item.get("term_src", ""))
        key = normalize_key(term_src)

        if key not in by_key:
            continue

        c = by_key[key]

        try:
            termhood = float(item.get("termhood", 0))
        except Exception:
            termhood = 0.0

        try:
            translation_value = float(item.get("translation_value", 0))
        except Exception:
            translation_value = 0.0

        typ = normalize_text(item.get("type", c.term_type))
        if typ not in VALID_TYPES:
            typ = c.term_type if c.term_type in VALID_TYPES else "term"

        term_level = normalize_text(item.get("term_level", "non_term"))
        if term_level not in VALID_LEVELS:
            term_level = "non_term"

        c.ai_termhood = clamp_score(termhood, 0.0, 5.0)
        c.ai_translation_value = clamp_score(translation_value, 0.0, 5.0)
        c.ai_keep = item.get("keep", False) is True
        c.ai_decision = normalize_text(item.get("category_decision", ""))
        c.term_level = term_level
        c.term_type = typ
        c.term_tgt = clean_term_tgt(item.get("term_tgt", c.term_tgt))

        judged.append(c)

    return judged


# ============================================================
# 10. 最终融合与保留逻辑
# ============================================================

def compute_final_score(c: Candidate) -> Candidate:
    ai_weight = CONFIG["ai_weight"]
    algo_weight = 1.0 - ai_weight

    ai_score = 0.70 * c.ai_termhood + 0.30 * c.ai_translation_value

    if CONFIG["llm_mode"] == "off" or not llm_is_enabled():
        c.final_score = c.algo_score
        return c

    c.final_score = algo_weight * c.algo_score + ai_weight * ai_score
    return c


def should_keep_final(c: Candidate) -> bool:
    term = c.term
    lang = c.lang

    if not term:
        return False

    if is_fragment(term, lang):
        return False

    if is_generic_alone(term):
        return False

    if is_pure_number_or_punctuation(term):
        return False

    if is_named_entity_like(term) and not CONFIG["include_named_entities"]:
        if not (
            c.term_level == "core_term"
            and c.ai_termhood >= 4.5
            and c.ai_translation_value >= 3.0
        ):
            return False

    if CONFIG["require_target_substring"] and c.term_tgt:
        if not target_contains(c.term_tgt, c.tgt_text):
            return False

    if not c.term_tgt and not CONFIG["allow_empty_target"]:
        return False

    # 无 AI 模式
    if CONFIG["llm_mode"] == "off" or not llm_is_enabled():
        return c.final_score >= CONFIG["final_min_score"]

    if not c.ai_keep:
        return False

    if c.term_level not in CONFIG["keep_levels"]:
        return False

    if c.ai_decision in {"generic_word", "location_entity", "person_entity", "fragment"}:
        if not CONFIG["include_named_entities"]:
            return False

    # 不同 level 的通用保留条件
    if c.term_level == "core_term":
        return c.ai_termhood >= 4.0 and c.ai_translation_value >= 3.0

    if c.term_level == "context_term":
        if CONFIG["mode"] == "strict":
            return False
        return c.ai_termhood >= 3.5 and c.final_score >= CONFIG["final_min_score"]

    if c.term_level == "glossary_item":
        if CONFIG["mode"] != "recall":
            return False
        return c.ai_termhood >= 3.0 and c.final_score >= CONFIG["final_min_score"] - 0.3

    return False


def postprocess_candidates(cands: List[Candidate]) -> List[Candidate]:
    level_rank = {
        "core_term": 3,
        "context_term": 2,
        "glossary_item": 1,
        "non_term": 0,
    }

    cands = sorted(
        cands,
        key=lambda c: (
            level_rank.get(c.term_level, 0),
            c.final_score,
            c.ai_termhood,
            len(c.term),
        ),
        reverse=True,
    )

    kept: List[Candidate] = []

    for c in cands:
        skip = False

        for ex in kept:
            if normalize_key(c.term) == normalize_key(ex.term):
                skip = True
                break

            if c.term in ex.term and c.term != ex.term:
                if c.final_score + 0.7 < ex.final_score:
                    skip = True
                    break

        if not skip:
            kept.append(c)

    return kept


# ============================================================
# 11. Debug 输出
# ============================================================

def save_debug_candidates(debug_rows: List[Dict[str, Any]], input_path: str) -> None:
    if not CONFIG["debug_candidates"]:
        return

    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)

    stem = Path(input_path).stem
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{stem}_debug_candidates_v31_{timestamp}.xlsx"

    df = pd.DataFrame(debug_rows)
    if not df.empty:
        df.to_excel(path, index=False)

    print(f"[DEBUG] Saved candidate debug file to: {path}")


# ============================================================
# 12. 主抽取流程
# ============================================================

def extract_terms(
    pairs: List[SentencePair],
    input_path: str,
    progress_callback=None,
) -> List[Dict[str, Any]]:
    print("[INFO] Generating broad algorithmic candidates...")

    pair_to_candidates: Dict[Any, List[Candidate]] = {}
    all_candidates: List[Candidate] = []

    for pair in pairs:
        rule_cands = generate_rule_candidates(pair)
        pair_to_candidates[pair.sent_id] = rule_cands
        all_candidates.extend(rule_cands)

    corpus_freq = compute_corpus_freq(pairs, all_candidates)

    rows: List[Dict[str, Any]] = []
    seen_global: Set[str] = set()
    debug_rows: List[Dict[str, Any]] = []

    for idx, pair in enumerate(pairs, start=1):
        print(f"[INFO] Processing sentence {idx}/{len(pairs)} | sent_id={pair.sent_id}")

        if progress_callback is not None:
            progress_callback(
                current=idx,
                total=len(pairs),
                sent_id=pair.sent_id,
                current_rows=len(rows),
            )

        rule_cands = pair_to_candidates.get(pair.sent_id, [])
        scored = [score_candidate(c, corpus_freq) for c in rule_cands]

        preliminary = [c for c in scored if preliminary_filter(c)]
        preliminary = resolve_nested_candidates(preliminary)

        expanded: List[Candidate] = []
        if CONFIG["llm_mode"] == "full" and llm_is_enabled():
            expanded = llm_expand_candidates(pair, preliminary)
            if expanded:
                for c in expanded:
                    score_candidate(c, corpus_freq)
                print(f"[INFO] LLM expanded {len(expanded)} candidates.")

        merged = preliminary + expanded
        merged = resolve_nested_candidates(merged)
        merged = [rule_align_target(c) for c in merged]

        if CONFIG["llm_mode"] in {"full", "judge"} and llm_is_enabled():
            judged = llm_judge_candidates(pair, merged)
        else:
            judged = merged

        if not judged and CONFIG["llm_mode"] == "off":
            judged = merged

        judged = [compute_final_score(c) for c in judged]

        for c in judged:
            debug_rows.append(
                {
                    "sent_id": c.sent_id,
                    "src_text": c.src_text,
                    "tgt_text": c.tgt_text,
                    "term": c.term,
                    "term_tgt": c.term_tgt,
                    "type": c.term_type,
                    "term_level": c.term_level,
                    "source": ",".join(sorted(c.source)),
                    "algo_score": c.algo_score,
                    "ai_termhood": c.ai_termhood,
                    "ai_translation_value": c.ai_translation_value,
                    "final_score": c.final_score,
                    "ai_keep": c.ai_keep,
                    "ai_decision": c.ai_decision,
                    "reasons": ",".join(c.reasons),
                }
            )

        final_kept = [c for c in judged if should_keep_final(c)]
        final_kept = postprocess_candidates(final_kept)
        final_kept = final_kept[:CONFIG["max_terms_per_sentence"]]

        for cand in final_kept:
            key = normalize_key(cand.term)

            if CONFIG["deduplicate_global"] and key in seen_global:
                continue

            rows.append(
                {
                    "sent_id": pair.sent_id,
                    "src_text": pair.src_text,
                    "tgt_text": pair.tgt_text,
                    "term_src": cand.term,
                    "term_tgt": cand.term_tgt,
                    "type": cand.term_type if cand.term_type in VALID_TYPES else "term",
                    "note": "",
                }
            )

            seen_global.add(key)

    save_debug_candidates(debug_rows, input_path)
    return rows


# ============================================================
# 13. Excel 导出
# ============================================================

def export_excel(rows: List[Dict[str, Any]], output_path: str) -> None:
    columns = CONFIG["output_columns"]
    df = pd.DataFrame(rows)

    for col in columns:
        if col not in df.columns:
            df[col] = ""

    df = df[columns]

    output_path = str(output_path)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="terms")

        ws = writer.book["terms"]

        widths = {
            "A": 12,
            "B": 52,
            "C": 52,
            "D": 26,
            "E": 32,
            "F": 12,
            "G": 20,
        }

        for col, width in widths.items():
            ws.column_dimensions[col].width = width

        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = cell.alignment.copy(wrap_text=True, vertical="top")

        ws.freeze_panes = "A2"

    print(f"[OK] Exported {len(rows)} terms to: {output_path}")


def make_default_output_path(input_path: str) -> str:
    stem = Path(input_path).stem
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    return str(out_dir / f"{stem}_terms_v31_{timestamp}.xlsx")


# ============================================================
# 14. CLI
# ============================================================

def apply_mode(mode: str) -> None:
    mode_conf = MODE_CONFIG[mode]
    CONFIG["mode"] = mode
    CONFIG["algo_min_score"] = mode_conf["algo_min_score"]
    CONFIG["final_min_score"] = mode_conf["final_min_score"]
    CONFIG["ai_weight"] = mode_conf["ai_weight"]
    CONFIG["max_terms_per_sentence"] = mode_conf["max_terms_per_sentence"]
    CONFIG["keep_levels"] = mode_conf["keep_levels"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="ARTEMIS V3.1 AI-Weighted Hybrid Term Extraction System"
    )

    parser.add_argument("input_json", help="输入 JSON 文件路径。")

    parser.add_argument(
        "-o",
        "--output",
        default="",
        help="输出 Excel 文件路径。不填则自动保存到 output/。",
    )

    parser.add_argument(
        "--mode",
        choices=["recall", "balanced", "strict"],
        default="balanced",
        help="recall=多抽一点；balanced=默认平衡；strict=少而精。",
    )

    parser.add_argument(
        "--llm-mode",
        choices=["full", "judge", "off"],
        default="full",
        help="full=AI补充+裁判+对齐；judge=只裁判+对齐；off=不用AI。",
    )

    parser.add_argument(
        "--ai-weight",
        type=float,
        default=None,
        help="AI 权重，0-1。默认由 mode 决定。",
    )

    parser.add_argument(
        "--algo-min-score",
        type=float,
        default=None,
        help="算法候选最低分。默认由 mode 决定。",
    )

    parser.add_argument(
        "--final-min-score",
        type=float,
        default=None,
        help="最终保留最低分。默认由 mode 决定。",
    )

    parser.add_argument(
        "--allow-empty-target",
        action="store_true",
        help="找不到 term_tgt 时也保留术语。",
    )

    parser.add_argument(
        "--require-target-substring",
        action="store_true",
        help="要求 term_tgt 必须字面出现在目标句中。",
    )

    parser.add_argument(
        "--include-named-entities",
        action="store_true",
        help="允许输出地点、人名、普通命名实体。默认不建议开启。",
    )

    parser.add_argument(
        "--max-terms-per-sentence",
        type=int,
        default=None,
        help="每句最多输出多少术语。默认由 mode 决定。",
    )

    parser.add_argument(
        "--model",
        default=CONFIG["model"],
        help="模型名。默认读取 OPENAI_MODEL 或 ARTEMIS_MODEL。",
    )

    parser.add_argument(
        "--api-key",
        default=CONFIG["api_key"],
        help="LLM API key。默认读取 ARTEMIS_API_KEY 或 OPENAI_API_KEY。",
    )

    parser.add_argument(
        "--base-url",
        default=CONFIG["base_url"],
        help="OpenAI-compatible API base URL。默认读取 ARTEMIS_BASE_URL 或 OPENAI_BASE_URL。",
    )

    parser.add_argument(
        "--llm-api-style",
        choices=["responses", "chat"],
        default=CONFIG["llm_api_style"],
        help="LLM 调用接口。OpenAI 默认 responses；第三方兼容接口通常用 chat。",
    )

    parser.add_argument(
        "--debug-read",
        action="store_true",
        help="只读取 JSON 并打印前 5 条 src/tgt。",
    )

    parser.add_argument(
        "--debug-candidates",
        action="store_true",
        help="输出候选调试 Excel。",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    apply_mode(args.mode)

    CONFIG["llm_mode"] = args.llm_mode
    CONFIG["allow_empty_target"] = args.allow_empty_target
    CONFIG["require_target_substring"] = args.require_target_substring
    CONFIG["include_named_entities"] = args.include_named_entities
    CONFIG["model"] = args.model
    CONFIG["api_key"] = args.api_key
    CONFIG["base_url"] = args.base_url
    CONFIG["llm_api_style"] = args.llm_api_style
    CONFIG["debug_candidates"] = args.debug_candidates

    if args.ai_weight is not None:
        CONFIG["ai_weight"] = clamp_score(args.ai_weight, 0.0, 1.0)

    if args.algo_min_score is not None:
        CONFIG["algo_min_score"] = args.algo_min_score

    if args.final_min_score is not None:
        CONFIG["final_min_score"] = args.final_min_score

    if args.max_terms_per_sentence is not None:
        CONFIG["max_terms_per_sentence"] = args.max_terms_per_sentence

    if CONFIG["llm_mode"] != "off" and not CONFIG["api_key"]:
        print("[WARN] 没有检测到 ARTEMIS_API_KEY 或 OPENAI_API_KEY，自动切换到 --llm-mode off。")
        CONFIG["llm_mode"] = "off"

    input_path = args.input_json
    output_path = args.output or make_default_output_path(input_path)

    print("=" * 72)
    print("ARTEMIS V3.1 | AI-Weighted Hybrid Term Extraction")
    print("=" * 72)
    print(f"[INFO] Input: {input_path}")
    print(f"[INFO] Output: {output_path}")
    print(f"[INFO] Mode: {CONFIG['mode']}")
    print(f"[INFO] LLM mode: {CONFIG['llm_mode']}")
    print(f"[INFO] Model: {CONFIG['model']}")
    print(f"[INFO] LLM API style: {CONFIG['llm_api_style']}")
    if CONFIG["base_url"]:
        print(f"[INFO] LLM base URL: {CONFIG['base_url']}")
    print(f"[INFO] AI weight: {CONFIG['ai_weight']}")
    print(f"[INFO] Algorithm candidate min score: {CONFIG['algo_min_score']}")
    print(f"[INFO] Final min score: {CONFIG['final_min_score']}")
    print(f"[INFO] Keep levels: {CONFIG['keep_levels']}")
    print(f"[INFO] Max terms per sentence: {CONFIG['max_terms_per_sentence']}")
    print(f"[INFO] Allow empty target: {CONFIG['allow_empty_target']}")
    print(f"[INFO] Include named entities: {CONFIG['include_named_entities']}")
    print("=" * 72)

    pairs = read_json_pairs(input_path)

    if not pairs:
        print("[WARN] 没有读取到有效句对。")
        sys.exit(0)

    print(f"[INFO] Loaded {len(pairs)} sentence pairs.")

    if args.debug_read:
        print("\n[DEBUG] 前 5 条读取结果：")
        for p in pairs[:5]:
            print("-" * 60)
            print("sent_id:", p.sent_id)
            print("src_text:", p.src_text)
            print("tgt_text:", p.tgt_text)
        return

    rows = extract_terms(pairs, input_path)
    export_excel(rows, output_path)


if __name__ == "__main__":
    main()
