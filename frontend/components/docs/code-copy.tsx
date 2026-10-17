"use client";

import { useEffect } from "react";

export function CodeCopyManager() {
  useEffect(() => {
    const preBlocks = document.querySelectorAll<HTMLPreElement>(".doc-content pre");

    preBlocks.forEach((pre) => {
      if (pre.dataset.hasCopyButton) return;
      pre.dataset.hasCopyButton = "true";

      // Wrapper container styling
      pre.classList.add("relative", "group", "rounded-xl", "p-4", "my-5", "overflow-x-auto", "bg-[#18181b]", "text-[#f4f4f5]", "font-mono", "text-[13px]", "border", "border-border/40");

      const code = pre.querySelector("code");
      const rawText = code ? code.innerText : pre.innerText;

      // Create Copy Button
      const button = document.createElement("button");
      button.className =
        "absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity bg-white/10 hover:bg-white/20 text-white/80 hover:text-white px-2 py-1 rounded text-[11px] font-sans flex items-center gap-1 border border-white/10 backdrop-blur-sm cursor-pointer";
      button.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>
        </svg>
        <span>Copy</span>
      `;

      button.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(rawText);
          button.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20 6 9 17l-5-5"/>
            </svg>
            <span class="text-emerald-400 font-medium">Copied!</span>
          `;
          setTimeout(() => {
            button.innerHTML = `
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>
              </svg>
              <span>Copy</span>
            `;
          }, 2000);
        } catch (err) {
          console.error("Failed to copy code snippet:", err);
        }
      });

      pre.appendChild(button);
    });
  }, []);

  return null;
}
