export const schemaVersion = "cpm-2026-10-05-v1-candidate";
export const channels = {
  face: "面部",
  body: "身体",
  audio: "音频",
  text: "文本",
};
export type Channel = keyof typeof channels;
export type Dimension = "R" | "I" | "C" | "N";
export type Rating = {
  state: "unset" | "known" | "unknown";
  value: number | null;
  evidence_ids: string[];
  mixed: boolean;
  note: string;
};
export type Ratings = Record<Dimension, Rating>;
export const dimensions: {
  id: Dimension;
  name: string;
  question: string;
  anchors: string[];
  hint: string;
}[] = [
  {
    id: "R",
    name: "相关性",
    question: "这个事件对主体的目标、需要或处境有多重要？",
    anchors: ["几乎无关", "相关较弱", "中等相关", "相关较强", "高度相关"],
    hint: "衡量相关程度；负数不代表消极情感。",
  },
  {
    id: "I",
    name: "后果",
    question: "这个事件对可辨认的目标或处境产生什么影响？",
    anchors: ["严重不利", "较不利", "基本无影响", "较有利", "明显有利"],
    hint: "评价事件对目标的影响，而非表情是否积极。",
  },
  {
    id: "C",
    name: "应对能力",
    question: "线索是否支持主体能够处理、控制或适应这些后果？",
    anchors: ["很低", "较低", "一般", "较高", "很高"],
    hint: "依据行动、计划或适应性陈述；沉着与微笑本身不等于能应对。",
  },
  {
    id: "N",
    name: "规范相容性",
    question: "该事件是否符合主体可辨认的价值、角色要求或社会规范？",
    anchors: ["严重违背", "较不符合", "基本中性", "较符合", "明确符合"],
    hint: "评价对象固定为事件。回应是否礼貌，在表达约束中单独记录。",
  },
];
export interface Card {
  subject: string;
  event: string;
  goal: string;
  role: string;
  quote: string;
}
export interface Sample {
  clip_id: string;
  subset_id: string;
  source: string;
  va_clip_id: string | null;
  duration: number;
  original_card: Card;
  status: "draft" | "submitted" | null;
  attempt_no: number | null;
}
export interface Evidence {
  id: string;
  modality: Channel;
  span: number[];
  observation: string;
  verified: boolean;
}
export interface Annotation {
  subject_id: string;
  event_id: string;
  modality: "audiovisual";
  schema_version: string;
  anchor_version: string;
  card: Card;
  checks: Record<string, string>;
  score_window: number[];
  event_location: string;
  event_window: number[];
  ratings: Ratings;
  evidence: Evidence[];
  revision_reason: string;
  conflict: {
    status: string;
    modalities: Channel[];
    candidate_window: number[];
    candidate_source: string;
    reviewed_window: number[];
    reconciliation: string;
  };
  constraint: { status: string; evidence_ids: string[]; note: string };
  dynamic: {
    status: string;
    time: number;
    modalities: Channel[];
    description: string;
    score_window: number[];
    updated_ratings: Ratings | null;
  };
  explanation_review: {
    status: "not_generated";
    model_version: null;
    prompt_version: null;
    original: null;
  };
}
export const blankRatings = (): Ratings => {
  const blank = (): Rating => ({
    state: "unset",
    value: null,
    evidence_ids: [],
    mixed: false,
    note: "",
  });
  return { R: blank(), I: blank(), C: blank(), N: blank() };
};
export function blankAnnotation(sample: Sample): Annotation {
  const scenario = (Number(sample.clip_id.slice(-4)) - 1) % 3;
  return {
    subject_id: `${sample.clip_id}:subject-1`,
    event_id: `${sample.clip_id}:event-1`,
    modality: "audiovisual",
    schema_version: schemaVersion,
    anchor_version: schemaVersion,
    card: { ...sample.original_card },
    checks: {},
    score_window: [0, sample.duration],
    event_location: "",
    event_window: [0, sample.duration],
    ratings: blankRatings(),
    revision_reason: "",
    evidence: [
      {
        id: "E01",
        modality: "text",
        span: [1.2, 8.4],
        observation: sample.original_card.quote,
        verified: false,
      },
      {
        id: "E02",
        modality: "face",
        span: [2.4, 4.8],
        observation:
          scenario === 0
            ? "嘴角短暂下垂，随后恢复。"
            : scenario === 1
              ? "嘴角上扬，视线朝向对话者。"
              : "视线移向画面外，无法确认所指对象。",
        verified: false,
      },
      {
        id: "E03",
        modality: "audio",
        span: [4.8, 9.6],
        observation:
          scenario === 0
            ? "短暂停顿后继续说话，语速平稳。"
            : "说话中出现短暂停顿。",
        verified: false,
      },
    ],
    conflict: {
      status: "",
      modalities: [],
      candidate_window: [2.4, 4.8],
      candidate_source: "mock-candidate-v1",
      reviewed_window: [2.4, 4.8],
      reconciliation: "",
    },
    constraint: { status: "", evidence_ids: [], note: "" },
    dynamic: {
      status: "",
      time: 4.8,
      modalities: [],
      description: "",
      score_window: [4.8, sample.duration],
      updated_ratings: null,
    },
    explanation_review: {
      status: "not_generated",
      model_version: null,
      prompt_version: null,
      original: null,
    },
  };
}
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/cpm-api/${path}`, init);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}
