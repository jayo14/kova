"use client";

import { useEffect } from "react";

export function DocsTabsInit() {
  useEffect(() => {
    const tabRoots = document.querySelectorAll<HTMLElement>("[data-doc-tabs]");

    tabRoots.forEach((root) => {
      if (root.dataset.tabsReady) return;
      root.dataset.tabsReady = "true";

      const buttons = root.querySelectorAll<HTMLButtonElement>(".doc-tab");
      const panels = root.querySelectorAll<HTMLElement>(".doc-tab-panel");

      buttons.forEach((btn) => {
        btn.addEventListener("click", () => {
          const target = btn.dataset.tabTarget;
          if (!target) return;

          buttons.forEach((b) => {
            const active = b === btn;
            b.classList.toggle("doc-tab-active", active);
            b.setAttribute("aria-selected", String(active));
          });

          panels.forEach((p) => {
            const active = p.dataset.tabPanel === target;
            p.classList.toggle("doc-tab-panel-active", active);
          });
        });
      });
    });
  }, []);

  return null;
}
