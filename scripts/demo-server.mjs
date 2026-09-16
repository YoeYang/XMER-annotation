import http from "node:http";
import { createServer as createViteServer } from "vite";

const HOST = "127.0.0.1";
const PORT = 5174;
const ANNOTATOR_ID = "DEMO-P3-07";
const DEMO_TOKEN = "demo";

const modalities = ["audio", "text", "face", "body", "audiovisual"];
const sources = {
  audio: "/media/example/audio.wav",
  text: "/transcripts/example.json",
  face: "/media/example/visual.mp4",
  body: "/media/example/visual.mp4",
  audiovisual: "/media/example/audiovisual.mp4",
};

const tasks = modalities.flatMap((modality) =>
  Array.from({ length: 4 }, (_, orderIndex) => ({
    task_id: "demo-" + modality + "-" + (orderIndex + 1),
    media_id: "demo-media-" + modality + "-" + (orderIndex + 1),
    display_id: "S" + String(orderIndex + 1).padStart(4, "0"),
    modality,
    src: sources[modality],
    duration: 6.715,
    target: "演示任务：请判断目标人物在当前模态中的连续情绪变化。",
    demo: true,
    timeline_origin: 0,
    order_index: orderIndex,
    speaker_ref_src: "/media/example/speaker.jpg",
    speaker_name: "Target",
  })),
);

const attempts = new Map();
const chunks = new Map();
const submissions = new Map();

function sendJson(response, status, value) {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  response.end(JSON.stringify(value));
}

async function readJson(request) {
  const parts = [];
  for await (const part of request) parts.push(part);
  if (!parts.length) return {};
  return JSON.parse(Buffer.concat(parts).toString("utf8"));
}

function samplesFor(attemptId) {
  const byIndex = new Map();
  for (const batch of chunks.get(attemptId)?.values() ?? []) {
    for (const sample of batch) byIndex.set(sample.sample_index, sample);
  }
  return [...byIndex.values()].sort(
    (left, right) => left.sample_index - right.sample_index,
  );
}

function refreshAttemptSampleState(attemptId) {
  const attempt = attempts.get(attemptId);
  if (!attempt) return;
  const samples = samplesFor(attemptId);
  attempt.sample_count = samples.length;
  attempt.last_media_time = samples.at(-1)?.media_time ?? 0;
}

function requireDemoToken(request, response) {
  if (request.headers.authorization === "Bearer " + DEMO_TOKEN) return true;
  sendJson(response, 401, { detail: "请使用演示链接进入" });
  return false;
}

async function handleApi(request, response, url) {
  if (!requireDemoToken(request, response)) return;
  const path = url.pathname.slice("/api".length);
  const segments = path.split("/").filter(Boolean);

  if (request.method === "GET" && path === "/me") {
    sendJson(response, 200, {
      annotator_id: ANNOTATOR_ID,
      display_name: "演示标注员",
      phase: "main",
      tasks,
    });
    return;
  }

  if (request.method === "GET" && path === "/attempts") {
    sendJson(
      response,
      200,
      [...attempts.values()].sort((left, right) =>
        left.started_at.localeCompare(right.started_at),
      ),
    );
    return;
  }

  if (request.method === "GET" && path === "/submissions") {
    sendJson(
      response,
      200,
      [...submissions.values()].sort(
        (left, right) => left.revision - right.revision,
      ),
    );
    return;
  }

  if (request.method === "GET" && path === "/export") {
    sendJson(response, 200, {
      schema_version: 1,
      exported_at: new Date().toISOString(),
      storage: "cloud",
      annotator_id: ANNOTATOR_ID,
      unsaved_attempt_ids: [],
      attempts: [...attempts.values()].map((attempt) => ({
        ...attempt,
        samples: samplesFor(attempt.attempt_id),
      })),
      submissions: [...submissions.values()],
    });
    return;
  }

  if (
    request.method === "GET" &&
    segments.length === 3 &&
    segments[0] === "attempts" &&
    segments[2] === "samples"
  ) {
    sendJson(response, 200, samplesFor(decodeURIComponent(segments[1])));
    return;
  }

  if (
    request.method === "PUT" &&
    segments.length === 4 &&
    segments[0] === "attempts" &&
    segments[2] === "chunks"
  ) {
    const attemptId = decodeURIComponent(segments[1]);
    const chunkIndex = Number(segments[3]);
    const body = await readJson(request);
    const batches = chunks.get(attemptId) ?? new Map();
    const previous = batches.get(chunkIndex);
    if (previous && JSON.stringify(previous) !== JSON.stringify(body.samples)) {
      sendJson(response, 409, { detail: "同一采样块不可覆盖" });
      return;
    }
    if (!previous) batches.set(chunkIndex, body.samples ?? []);
    chunks.set(attemptId, batches);
    refreshAttemptSampleState(attemptId);
    sendJson(response, 200, { accepted: true });
    return;
  }

  if (
    request.method === "POST" &&
    segments.length === 3 &&
    segments[0] === "attempts" &&
    segments[2] === "submit"
  ) {
    const attemptId = decodeURIComponent(segments[1]);
    const attempt = attempts.get(attemptId);
    if (!attempt || attempt.status !== "completed" || !attempt.sample_count) {
      sendJson(response, 409, { detail: "只能提交已完成的标注轮次" });
      return;
    }
    const body = await readJson(request);
    const existing = submissions.get(body.submission_id);
    if (existing) {
      sendJson(response, 200, existing);
      return;
    }
    const history = [...submissions.values()]
      .filter((submission) => {
        const row = attempts.get(submission.attempt_id);
        return (
          submission.task_id === attempt.task_id &&
          row?.dimension === attempt.dimension
        );
      })
      .sort((left, right) => right.revision - left.revision);
    const previous = history[0];
    const now = new Date().toISOString();
    const submission = {
      submission_id: body.submission_id,
      task_id: attempt.task_id,
      annotator_id: ANNOTATOR_ID,
      attempt_id: attemptId,
      revision: (previous?.revision ?? 0) + 1,
      previous_submission_id: previous?.submission_id ?? null,
      submitted_at: previous?.submitted_at ?? now,
      updated_at: previous ? now : null,
    };
    submissions.set(submission.submission_id, submission);
    sendJson(response, 200, submission);
    return;
  }

  if (
    request.method === "PUT" &&
    segments.length === 2 &&
    segments[0] === "attempts"
  ) {
    const attemptId = decodeURIComponent(segments[1]);
    const body = await readJson(request);
    const task = tasks.find((row) => row.task_id === body.task_id);
    if (!task) {
      sendJson(response, 404, { detail: "演示任务不存在" });
      return;
    }
    const previous = attempts.get(attemptId);
    const attempt = {
      schema_version: 1,
      attempt_id: attemptId,
      task_id: body.task_id,
      annotator_id: ANNOTATOR_ID,
      media_id: body.media_id,
      modality: body.modality,
      mode: body.mode,
      dimension: body.dimension,
      familiarization_plays: body.familiarization_plays,
      status: body.status,
      task_snapshot: body.task_snapshot ?? task,
      sample_rate_hz: body.sample_rate_hz,
      started_at: body.started_at,
      completed_at: body.completed_at,
      sample_count: previous?.sample_count ?? 0,
      last_media_time: previous?.last_media_time ?? 0,
      events: body.events ?? [],
      calibration: null,
    };
    attempts.set(attemptId, attempt);
    refreshAttemptSampleState(attemptId);
    sendJson(response, 200, attempt);
    return;
  }

  sendJson(response, 404, { detail: "演示 API 不存在" });
}

const vite = await createViteServer({
  appType: "spa",
  server: { middlewareMode: true },
});

const server = http.createServer((request, response) => {
  const url = new URL(request.url ?? "/", "http://" + HOST + ":" + PORT);
  if (url.pathname.startsWith("/api/")) {
    void handleApi(request, response, url).catch((error) => {
      console.error(error);
      if (!response.headersSent)
        sendJson(response, 500, { detail: "演示服务处理失败" });
      else response.end();
    });
    return;
  }
  vite.middlewares(request, response);
});

server.listen(PORT, HOST, () => {
  console.log("");
  console.log("XMER V3 交互演示已启动：");
  console.log("http://" + HOST + ":" + PORT + "/?t=" + DEMO_TOKEN);
  console.log("");
  console.log("数据仅保存在当前浏览器和本次演示进程中，Ctrl+C 可停止。");
});

async function close() {
  await vite.close();
  server.close(() => process.exit(0));
}

process.on("SIGINT", close);
process.on("SIGTERM", close);
