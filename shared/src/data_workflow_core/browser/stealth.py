"""Stealth 指纹注入（浏览器执行层·环境层）。

目标：隐藏 Playwright/自动化浏览器与真实 Chrome 的差异，降低 1688 等平台
风控在“环境层”的触发概率。仅做“一致性伪装”（与真实浏览器表现一致），
不绕过登录、授权或访问控制；验证码/滑块仍按流程进入人工接管或重试。

用法（接入 PlaywrightBrowserSession 后无需手动调用）：

    context = browser.new_context(...)
    apply_stealth(context)
    page = context.new_page()

实现要点：
- init script 在每次导航/子帧创建时于页面脚本之前执行，可持续覆盖；
- 全部补丁使用 try/except 包裹，任一站点注入失败不影响采集；
- canvas/WebGL 伪装为“同会话内一致”的指纹，非真实绕过。
"""

from __future__ import annotations

from typing import Any


_CANVAS_PATCH = """
  // 同会话内一致的细微 canvas 指纹抖动（可选，默认开启）
  (() => {
    try {
      if (!window.__stealth_canvas_seed) {
        window.__stealth_canvas_seed = Math.floor(Math.random() * 1000);
      }
      const seed = window.__stealth_canvas_seed;
      const jitter = (v) => {
        const n = v + (seed % 7) * 0.003;
        return n > 255 ? 255 : n < 0 ? 0 : n;
      };
      const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
      CanvasRenderingContext2D.prototype.getImageData = function (...args) {
        const img = origGetImageData.apply(this, args);
        try {
          const data = img.data;
          for (let i = 0; i < data.length; i += 4 * 37) {
            data[i] = jitter(data[i]);
            data[i + 1] = jitter(data[i + 1]);
            data[i + 2] = jitter(data[i + 2]);
          }
        } catch (_) {}
        return img;
      };
    } catch (_) {}
  })();
"""


def build_stealth_init_script(*, canvas_noise: bool = True) -> str:
    """生成 stealth init script（每次导航前注入页面）。"""
    return f"""
(() => {{
  const ok = (fn) => {{ try {{ fn(); }} catch (_) {{}} }};

  // 1. 抹除自动化标记
  ok(() => {{
    Object.defineProperty(Navigator.prototype, "webdriver", {{
      get: () => undefined,
    }});
  }});

  // 2. 语言环境（与 launch locale 保持一致）
  ok(() => {{
    Object.defineProperty(Navigator.prototype, "languages", {{
      get: () => ["zh-CN", "zh"],
    }});
  }});

  // 3. plugins 列表（Playwright 默认为空数组，真实 Chrome 有 PDF/NaCl）
  ok(() => {{
    const pluginData = [
      {{ name: "Chrome PDF Plugin", filename: "internal-pdf-viewer", description: "Portable Document Format" }},
      {{ name: "Chrome PDF Viewer", filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai", description: "" }},
      {{ name: "Native Client", filename: "internal-nacl-plugin", description: "" }},
    ];
    const makePlugin = (data) => {{
      const p = {{ name: data.name, filename: data.filename, description: data.description, length: 1, 0: {{}} }};
      p.item = (i) => (i === 0 ? p[0] : null);
      p.namedItem = (n) => null;
      return p;
    }};
    Object.defineProperty(Navigator.prototype, "plugins", {{
      get: () => {{
        const arr = pluginData.map(makePlugin);
        arr.item = (i) => arr[i] || null;
        arr.namedItem = (n) => arr.find((p) => p.name === n) || null;
        arr.refresh = () => {{}};
        return arr;
      }},
    }});
  }});

  // 4. chrome 对象补齐（扩展 API 外观）
  ok(() => {{
    if (!window.chrome) window.chrome = {{}};
    if (!window.chrome.runtime) {{
      window.chrome.runtime = {{
        connect: () => ({{ postMessage: () => {{}}, disconnect: () => {{}} }}),
        sendMessage: () => {{}},
        id: undefined,
      }};
    }}
    if (!window.chrome.csi) window.chrome.csi = () => ({{}});
    if (!window.chrome.loadTimes) window.chrome.loadTimes = () => ({{}});
  }});

  // 5. permissions.query 兼容真实浏览器语义
  ok(() => {{
    const origQuery = window.navigator.permissions.query.bind(window.navigator.permissions);
    window.navigator.permissions.query = (params) =>
      params && params.name === "notifications"
        ? Promise.resolve({{ state: Notification.permission }})
        : origQuery(params);
  }});

  // 6. 常规桌面硬件参数
  ok(() => {{
    Object.defineProperty(Navigator.prototype, "hardwareConcurrency", {{ get: () => 8 }});
  }});
  ok(() => {{
    Object.defineProperty(Navigator.prototype, "deviceMemory", {{ get: () => 8 }});
  }});

  // 7. 窗口尺寸一致性（headless 下 outer/inner 差异易被探测）
  ok(() => {{
    Object.defineProperty(window, "outerWidth", {{ get: () => window.innerWidth }});
    Object.defineProperty(window, "outerHeight", {{ get: () => window.innerHeight }});
  }});

  // 8. WebGL 厂商/渲染器统一（避免暴露虚拟机/软件渲染特征）
  ok(() => {{
    const getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (param) {{
      if (param === 37445) return "Intel Inc.";
      if (param === 37446) return "Intel Iris OpenGL Engine";
      return getParam.call(this, param);
    }};
  }});

  {_CANVAS_PATCH if canvas_noise else "  // canvas 抖动已关闭"}
}})();
"""


STEALTH_INIT_SCRIPT: str = build_stealth_init_script()


def stealth_launch_args() -> list[str]:
    """额外 Chrome 启动参数（与现有会话参数合并时自动去重）。"""
    return [
        "--disable-blink-features=AutomationControlled",
        "--lang=zh-CN",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def apply_stealth(context: Any, *, canvas_noise: bool = True) -> None:
    """向 Playwright context 注入 stealth init script。"""
    context.add_init_script(build_stealth_init_script(canvas_noise=canvas_noise))
