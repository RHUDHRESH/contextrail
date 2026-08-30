from pathlib import Path
from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:3100"
OUTPUT_DIR = Path("docs/screens")
ROUTES = {
    "command-center": "/",
    "new-request": "/request",
    "approvals": "/approvals",
    "skills-tools": "/skills",
}
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        for viewport_name, viewport in VIEWPORTS.items():
            context = browser.new_context(viewport=viewport)
            page = context.new_page()
            console_errors: list[str] = []
            page.on(
                "console",
                lambda message: console_errors.append(
                    f"{message.text} at {message.location.get('url', 'unknown')}:{message.location.get('lineNumber', 0)}"
                ) if message.type == "error" else None,
            )
            page.on("pageerror", lambda error: console_errors.append(str(error)))

            for route_name, route in ROUTES.items():
                page.goto(f"{BASE_URL}{route}", wait_until="networkidle")
                page.screenshot(
                    path=str(OUTPUT_DIR / f"{viewport_name}-{route_name}.png"),
                    full_page=True,
                )

                metrics = page.evaluate(
                    """
                    () => {
                      const root = document.documentElement;
                      const interactive = [...document.querySelectorAll('a, button, input, select, textarea')]
                        .filter((el) => {
                          const style = getComputedStyle(el);
                          return style.visibility !== 'hidden' && style.display !== 'none';
                        });
                      const smallTargets = interactive
                        .map((el) => {
                          const rect = el.getBoundingClientRect();
                          return { tag: el.tagName, text: (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 80), width: rect.width, height: rect.height };
                        })
                        .filter((item) => item.width > 0 && item.height > 0 && (item.width < 44 || item.height < 44));
                      return {
                        horizontalOverflow: root.scrollWidth > root.clientWidth,
                        documentWidth: root.scrollWidth,
                        viewportWidth: root.clientWidth,
                        overflowers: [...document.querySelectorAll('body *')]
                          .map((el) => {
                            const rect = el.getBoundingClientRect();
                            return { tag: el.tagName, className: String(el.className || '').slice(0, 120), left: rect.left, right: rect.right, width: rect.width };
                          })
                          .filter((item) => item.right > root.clientWidth + 1 || item.left < -1)
                          .slice(0, 8),
                        smallTargets,
                      };
                    }
                    """
                )

                if metrics["horizontalOverflow"]:
                    failures.append(
                        f"{viewport_name}:{route_name} horizontal overflow "
                        f"({metrics['documentWidth']} > {metrics['viewportWidth']}); nodes={metrics['overflowers']}"
                    )
                if viewport_name == "mobile" and metrics["smallTargets"]:
                    sample = metrics["smallTargets"][:5]
                    failures.append(f"mobile:{route_name} has {len(metrics['smallTargets'])} small targets; sample={sample}")

            failures.extend(f"{viewport_name}:console {message}" for message in console_errors)
            context.close()

        browser.close()

    if failures:
        print("VISUAL_AUDIT_FINDINGS")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print(f"VISUAL_AUDIT_OK screenshots={len(ROUTES) * len(VIEWPORTS)} output={OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
