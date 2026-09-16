"""Gemini 调用薄封装：令牌桶限速、指数退避重试、用量与成本累计。

API key 只从环境变量 GEMINI_API_KEY 读，不落盘、不写进 manifest。
"""
import os, random, threading, time

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
# 2.5-flash 定价（美元/百万 token）。改模型时同步改这里。
PRICE_IN = float(os.environ.get("GEMINI_PRICE_IN", "0.30"))
PRICE_OUT = float(os.environ.get("GEMINI_PRICE_OUT", "2.50"))


class RateLimiter:
    """令牌桶：每分钟最多 rpm 次请求。"""

    def __init__(self, rpm):
        self.interval = 60.0 / max(1, rpm)
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.interval
        if wait:
            time.sleep(wait)


class Usage:
    def __init__(self):
        self._lock = threading.Lock()
        self.calls = self.tin = self.tout = 0

    def add(self, tin, tout):
        with self._lock:
            self.calls += 1
            self.tin += tin
            self.tout += tout

    @property
    def cost(self):
        return self.tin / 1e6 * PRICE_IN + self.tout / 1e6 * PRICE_OUT

    def summary(self):
        return (f"调用 {self.calls} 次，输入 {self.tin} tok，输出 {self.tout} tok，"
                f"约 ${self.cost:.4f}")


class Gemini:
    def __init__(self, rpm=60, max_retry=4, model=None):
        from google import genai
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise SystemExit("缺少环境变量 GEMINI_API_KEY")
        self.client = genai.Client(api_key=key)
        self.model = model or MODEL
        self.limiter = RateLimiter(rpm)
        self.max_retry = max_retry
        self.usage = Usage()

    def generate(self, parts, schema=None, temperature=0.0, thinking_budget=0):
        """parts: [str | types.Part]。返回 (文本, 用量元组)。失败抛最后一次异常。"""
        from google.genai import types
        cfg = types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json" if schema else None,
            response_schema=schema,
            thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
        )
        last = None
        for attempt in range(self.max_retry):
            self.limiter.acquire()
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=parts, config=cfg)
                u = resp.usage_metadata
                tin = getattr(u, "prompt_token_count", 0) or 0
                tout = ((getattr(u, "candidates_token_count", 0) or 0)
                        + (getattr(u, "thoughts_token_count", 0) or 0))
                self.usage.add(tin, tout)
                return resp.text, (tin, tout)
            except Exception as exc:                # 限流/瞬时错误都退避重试
                last = exc
                if attempt == self.max_retry - 1:
                    break
                time.sleep(min(60, 2 ** attempt * 2) * (0.7 + 0.6 * random.random()))
        raise last
