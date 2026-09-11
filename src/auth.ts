const TOKEN_KEY = "xmer-token";
// sessionStorage 不可用时（隐私模式）退回内存，至少本次会话能用
let inMemory: string | null = null;

/**
 * 从专属网址 `?t=…` 取出令牌并存入本次会话，随即**从地址栏抹掉**。
 *
 * 抹掉这一步不是洁癖：令牌留在地址栏会经 referer 外泄，也会随截图和
 * 复制链接一起被分享出去——那等于把这个人的标注身份送人。
 */
export function captureToken(): string | null {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("t");
  if (fromUrl) {
    inMemory = fromUrl;
    try {
      sessionStorage.setItem(TOKEN_KEY, fromUrl);
    } catch {
      /* 隐私模式下只保留内存副本 */
    }
    url.searchParams.delete("t");
    window.history.replaceState(null, "", url.toString());
    return fromUrl;
  }
  return getToken();
}

export function getToken(): string | null {
  if (inMemory) return inMemory;
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
