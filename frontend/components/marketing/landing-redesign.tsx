"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

export function LandingRedesign() {
  const router = useRouter();
  const [heroUrl, setHeroUrl] = useState("");
  const [ctaUrl, setCtaUrl] = useState("");
  const [currency, setCurrency] = useState<"usd" | "ngn">("usd");
  const [isPlayingDemo, setIsPlayingDemo] = useState(false);

  const handleExplore = (targetUrl: string) => {
    const clean = targetUrl.trim();
    if (clean) {
      router.push(`/explore?url=${encodeURIComponent(clean)}`);
    } else {
      router.push("/explore");
    }
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#FBF7F0] font-sans text-[#2A170D] antialiased selection:bg-[#8A3513]/15 selection:text-[#2A170D]">
      {/* ============================================================ */}
      {/* FLOATING GLASS NAVIGATION                                    */}
      {/* ============================================================ */}
      <header className="fixed top-5 left-1/2 z-50 flex w-[min(960px,92%)] -translate-x-1/2 items-center justify-between rounded-full border border-white/80 bg-white/60 px-5 py-2.5 shadow-[0_1px_0_#fff_inset,0_20px_40px_-20px_rgba(90,40,10,0.25)] backdrop-blur-xl">
        <Link href="/" className="flex items-center gap-1 font-['Bricolage_Grotesque'] text-2xl font-bold tracking-tight text-[#2A170D]">
          Kova<span className="text-[#D58A56]">.</span>
        </Link>

        <nav className="hidden md:flex items-center gap-7 text-sm font-medium text-[#6B5646]">
          <a href="#product" className="transition-colors hover:text-[#8A3513]">Product</a>
          <a href="#how" className="transition-colors hover:text-[#8A3513]">How it works</a>
          <a href="#features" className="transition-colors hover:text-[#8A3513]">Features</a>
          <a href="#pricing" className="transition-colors hover:text-[#8A3513]">Pricing</a>
        </nav>

        <div className="flex items-center gap-3">
          <Link
            href="/auth/login"
            className="text-sm font-medium text-[#6B5646] transition-colors hover:text-[#8A3513] px-2 py-1"
          >
            Sign in
          </Link>
          <Link
            href="/auth/signup"
            className="btn-pill !py-2.5 !px-5 !text-sm"
          >
            Get started
          </Link>
        </div>
      </header>

      {/* ============================================================ */}
      {/* HERO SECTION                                                 */}
      {/* ============================================================ */}
      <section className="relative overflow-hidden pt-36 pb-20 md:pt-44 md:pb-24 [background:radial-gradient(1000px_600px_at_50%_-10%,#F6DCC2,transparent_70%)]">
        {/* Ambient Blurred Orbs */}
        <div className="orb -left-20 top-24 h-[420px] w-[420px] bg-[#E9A878]" />
        <div className="orb -right-16 top-96 h-[380px] w-[380px] bg-[#C9733F] [animation-delay:-6s]" />

        <div className="relative mx-auto max-w-[1200px] px-6 text-center">
          {/* Eyebrow badge */}
          <div className="inline-flex items-center gap-2.5 rounded-full border border-white/80 bg-white/60 px-4 py-2 text-xs font-medium text-[#2A170D] shadow-[0_1px_0_#fff_inset,0_10px_25px_-10px_rgba(90,40,10,0.2)] backdrop-blur-md">
            <span className="h-2 w-2 rounded-full bg-[#3E9B5F] shadow-[0_0_0_5px_rgba(62,155,95,0.2)]" />
            <span>Autonomous software agent</span>
          </div>

          {/* Main Display Headline */}
          <h1 className="mx-auto mt-6 max-w-4xl font-['Bricolage_Grotesque'] text-5xl font-bold tracking-tight leading-[1.04] sm:text-7xl md:text-[84px]">
            Let an agent <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513] tracking-normal">use</em> your software.
          </h1>

          {/* Subtitle */}
          <p className="mx-auto mt-5 max-w-xl text-lg md:text-xl text-[#6B5646] leading-relaxed">
            Give Kova a website and a goal. It explores the product, figures out what needs to happen, and executes the journey like a real user.
          </p>

          {/* Interactive URL Input Pill */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleExplore(heroUrl);
            }}
            className="mx-auto mt-8 flex max-w-[620px] items-center gap-3 rounded-full border border-white/80 bg-white/65 p-2 pl-6 shadow-[0_1px_0_#fff_inset,0_24px_50px_-20px_rgba(90,40,10,0.25)] backdrop-blur-xl transition-all focus-within:ring-2 focus-within:ring-[#8A3513]/20"
          >
            <input
              type="text"
              value={heroUrl}
              onChange={(e) => setHeroUrl(e.target.value)}
              placeholder="https://yourproduct.com"
              className="flex-1 bg-transparent font-['DM_Mono'] text-sm md:text-base text-[#2A170D] placeholder-[#6B5646]/60 outline-none"
            />
            <button
              type="submit"
              className="btn-pill !py-3 !px-6 !text-sm"
            >
              Explore →
            </button>
          </form>

          <p className="mt-4 text-xs text-[#6B5646]/80 font-medium">
            Paste your product URL, describe a goal, and watch it work.
          </p>

          {/* 3 Audience Glass Cards */}
          <div className="mx-auto mt-16 grid max-w-5xl grid-cols-1 gap-5 text-left md:grid-cols-3">
            <div className="glass p-6 transition-transform duration-300 hover:-translate-y-1">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#FBE9D6] to-[#F3C9A3]">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#8A3513" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.500-1-8-4-8-9V6z" />
                  <path d="M8.500 12l2.500 2.500 4.500-5" />
                </svg>
              </div>
              <h3 className="mt-3.5 font-['Bricolage_Grotesque'] text-xl font-bold tracking-tight text-[#2A170D]">QA teams</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-[#6B5646]">
                Stop maintaining brittle scripts. Kova works from the goal and adapts when the UI changes.
              </p>
            </div>

            <div className="glass p-6 transition-transform duration-300 hover:-translate-y-1">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#FBE9D6] to-[#F3C9A3]">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#8A3513" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 8l-5 4 5 4M15 8l5 4-5 4" />
                </svg>
              </div>
              <h3 className="mt-3.5 font-['Bricolage_Grotesque'] text-xl font-bold tracking-tight text-[#2A170D]">Vibe coders</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-[#6B5646]">
                AI built it fast. Kova clicks through it like a user and tells you what still works.
              </p>
            </div>

            <div className="glass p-6 transition-transform duration-300 hover:-translate-y-1">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#FBE9D6] to-[#F3C9A3]">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#8A3513" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 17l6-6 4 4 8-8M15 7h6v6" />
                </svg>
              </div>
              <h3 className="mt-3.5 font-['Bricolage_Grotesque'] text-xl font-bold tracking-tight text-[#2A170D]">Founders &amp; product teams</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-[#6B5646]">
                Verify every release and keep proof of what happened, with no manual walkthroughs.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ============================================================ */}
      {/* MARQUEE TICKER                                               */}
      {/* ============================================================ */}
      <section className="border-y border-[#2A170D]/10 py-6 overflow-hidden">
        <div className="marquee-ticker">
          <span>Test</span><span>·</span><span>Validate</span><span>·</span><span>Explore</span><span>·</span><span>Demonstrate</span><span>·</span>
          <span>Test</span><span>·</span><span>Validate</span><span>·</span><span>Explore</span><span>·</span><span>Demonstrate</span><span>·</span>
          <span>Test</span><span>·</span><span>Validate</span><span>·</span><span>Explore</span><span>·</span><span>Demonstrate</span><span>·</span>
          <span>Test</span><span>·</span><span>Validate</span><span>·</span><span>Explore</span><span>·</span><span>Demonstrate</span><span>·</span>
        </div>
      </section>

      {/* ============================================================ */}
      {/* PRODUCT SECTION                                              */}
      {/* ============================================================ */}
      <section id="product" className="py-24 text-center">
        <div className="mx-auto max-w-[1200px] px-6">
          <span className="pill-badge">Product</span>
          <h2 className="mx-auto mt-5 max-w-3xl font-['Bricolage_Grotesque'] text-4xl font-bold tracking-tight sm:text-5xl md:text-6xl text-[#2A170D]">
            See Kova work, <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">start to finish.</em>
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-base md:text-lg text-[#6B5646]">
            From a pasted URL to a full report with screenshot evidence and a video walkthrough.
          </p>

          {/* Large Showcase Container with Dot Grid */}
          <div className="relative mx-auto mt-16 rounded-[40px] bg-gradient-to-br from-[#E9A878] via-[#B2562A] to-[#8A3513] p-6 sm:p-12 md:py-16 md:px-24">
            {/* Background Texture & Orbs */}
            <div className="pointer-events-none absolute inset-0 rounded-[40px] overflow-hidden bg-[radial-gradient(rgba(255,255,255,0.22)_1px,transparent_1px)] [background-size:22px_22px]">
              <div className="orb -left-20 -top-24 h-[400px] w-[400px] bg-[#FBE9D6] opacity-40" />
              <div className="orb -right-16 -bottom-16 h-[360px] w-[360px] bg-[#F3C9A3] opacity-35 [animation-delay:-5s]" />
            </div>

            {/* Floating Left Slanted Card: Report */}
            <div className="sd hidden lg:block" style={{ left: "34px", top: "130px", transform: "rotate(-7deg)" }}>
              <div className="h-2 w-14 rounded-full bg-[#8A3513]" />
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="mt-2.5 flex items-center gap-2">
                  <span className="h-3 w-3 shrink-0 rounded-full bg-[#3E9B5F]" />
                  <span className="h-1.5 flex-1 rounded-full bg-[#E6B79A]" />
                </div>
              ))}
              <b className="mt-3 block font-['Bricolage_Grotesque'] text-sm font-bold text-[#2A170D]">Report</b>
            </div>

            {/* Floating Right Slanted Card: Screenshots */}
            <div className="sd hidden lg:block" style={{ right: "34px", top: "170px", transform: "rotate(7deg)" }}>
              <div className="grid grid-cols-2 gap-2">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="h-12 rounded-lg bg-gradient-to-br from-[#FBE9D6] to-[#F3C9A3] p-1.5">
                    <div className="h-1 w-8 rounded bg-[#8A3513]/40" />
                    <div className="mt-2 h-2 w-6 rounded bg-[#8A3513]/70" />
                  </div>
                ))}
              </div>
              <b className="mt-3 block font-['Bricolage_Grotesque'] text-sm font-bold text-[#2A170D]">Screenshot evidence</b>
            </div>

            {/* Floating Check Tile */}
            <div className="tile-float hidden sm:grid absolute -top-6 right-24 z-20">
              <svg width="28" height="28" viewBox="0 0 16 16" fill="none" stroke="#3E9B5F" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 8.5l3 3 7-7" />
              </svg>
            </div>

            {/* Central Browser Screen Mockup */}
            <div className="relative z-10 rounded-[32px] bg-[#FFFDFA] p-3 shadow-[0_40px_80px_-30px_rgba(40,10,0,0.6)] border border-white/80">
              <div className="relative aspect-video rounded-2xl overflow-hidden bg-gradient-to-br from-[#FFFDFA] to-[#F6E7D6]">
                <div className="absolute inset-0 p-5 md:p-8 flex flex-col justify-between text-left">
                  {/* Top bar of sample app */}
                  <div className="flex justify-between items-center border-b border-[#2A170D]/10 pb-3">
                    <b className="font-['Bricolage_Grotesque'] text-lg md:text-xl font-bold tracking-tight text-[#2A170D]">payflow</b>
                    <div className="flex gap-2">
                      <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-[#8A3513] shadow-sm">Send</span>
                      <span className="rounded-full px-3 py-1 text-xs font-medium text-[#6B5646]">Activity</span>
                      <span className="rounded-full px-3 py-1 text-xs font-medium text-[#6B5646]">Cards</span>
                    </div>
                  </div>

                  {/* Sample app content layout */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 my-auto">
                    <div className="rounded-xl bg-white p-4 shadow-sm border border-[#2A170D]/5">
                      <div className="font-['Bricolage_Grotesque'] text-base font-bold text-[#2A170D]">Send money</div>
                      <div className="mt-2.5 rounded-lg bg-[#F1E7D8] p-2 text-xs text-[#6B5646]">To · Amara Obi</div>
                      <div className="mt-2 rounded-lg bg-[#F1E7D8] p-2 font-['Bricolage_Grotesque'] text-lg font-bold text-[#2A170D]">$1,200.00</div>
                      <div className="mt-2.5 rounded-full bg-[#8A3513] py-2 text-center text-xs font-semibold text-white">Send transfer</div>
                    </div>

                    <div className="rounded-xl bg-white/70 p-4 border border-[#2A170D]/5 hidden md:block">
                      <div className="eye text-[11px]">Recent activity</div>
                      <div className="mt-2 space-y-1.5 text-xs text-[#2A170D]">
                        <div className="flex justify-between border-t border-[#2A170D]/10 pt-1.5">
                          <span>Transfer sent</span><b>−$1,200.00</b>
                        </div>
                        <div className="flex justify-between border-t border-[#2A170D]/10 pt-1.5">
                          <span>Salary</span><b className="text-[#3E9B5F]">+$4,800.00</b>
                        </div>
                        <div className="flex justify-between border-t border-[#2A170D]/10 pt-1.5">
                          <span>Card payment</span><b>−$64.20</b>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Simulated Cursor */}
                  <svg width="30" height="30" viewBox="0 0 24 24" className="absolute left-[30%] bottom-[16%] drop-shadow-[0_6px_8px_rgba(138,53,19,0.45)] transition-all duration-700" style={{ transform: isPlayingDemo ? "translate(120px, -40px)" : "none" }}>
                    <path d="M4 3l16 7-7 2-2 7z" fill="#8A3513" stroke="#fff" strokeWidth="1.5" />
                  </svg>
                </div>

                {/* Dark Gradient Overlay */}
                <div className={`absolute inset-0 bg-gradient-to-b from-[rgba(42,23,13,0.12)] to-[rgba(42,23,13,0.6)] transition-opacity duration-500 ${isPlayingDemo ? "opacity-30" : "opacity-100"}`} />

                {/* PRODUCT DEMO Chip */}
                <div className="absolute left-6 top-5 z-20 rounded-full bg-[#2A170D]/60 px-3.5 py-1.5 font-['DM_Mono'] text-xs text-white tracking-widest uppercase backdrop-blur-sm">
                  PRODUCT DEMO
                </div>

                {/* Concentric Pulsing Center Play Button */}
                <button
                  type="button"
                  onClick={() => setIsPlayingDemo(!isPlayingDemo)}
                  className={`pb transition-all duration-300 ${isPlayingDemo ? "opacity-0 pointer-events-none scale-75" : "opacity-100 scale-100"}`}
                  aria-label="Play product demo video"
                >
                  <svg width="36" height="36" viewBox="0 0 24 24" fill="#8A3513" className="ml-1">
                    <path d="M7 4.5v15l13-7.5z" />
                  </svg>
                </button>

                {/* Bottom Video Badge & Timeline Bar */}
                <div className="absolute left-6 right-6 bottom-5 z-20 text-left text-white">
                  <div className="font-['Bricolage_Grotesque'] text-lg md:text-2xl font-bold tracking-tight text-white drop-shadow-sm">
                    Watch Kova go from URL to full report
                  </div>
                  <div className="mt-3 flex items-center gap-3.5">
                    <div className="h-1.5 flex-1 rounded-full bg-white/35 overflow-hidden">
                      <div
                        className="h-full bg-white rounded-full transition-all duration-1000 ease-linear"
                        style={{ width: isPlayingDemo ? "100%" : "0%" }}
                      />
                    </div>
                    <span className="font-['DM_Mono'] text-xs text-white/90">
                      {isPlayingDemo ? "0:42 / 0:42" : "0:00 / 0:42"}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* 4 Bottom Journey Step Chips */}
            <div className="relative z-10 mt-8 grid grid-cols-2 gap-3 sm:grid-cols-4 md:-mx-12">
              <div className="chp">
                <i>01</i>
                <span>Paste your URL</span>
              </div>
              <div className="chp">
                <i>02</i>
                <span>Kova explores &amp; learns</span>
              </div>
              <div className="chp">
                <i>03</i>
                <span>Runs like a real user</span>
              </div>
              <div className="chp">
                <i>04</i>
                <span>Report, evidence &amp; video</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ============================================================ */}
      {/* HOW IT WORKS                                                 */}
      {/* ============================================================ */}
      <section id="how" className="py-24 text-center">
        <div className="mx-auto max-w-[1200px] px-6">
          <span className="pill-badge">How it works</span>
          <h2 className="mx-auto mt-5 max-w-3xl font-['Bricolage_Grotesque'] text-4xl font-bold tracking-tight sm:text-5xl md:text-6xl text-[#2A170D]">
            Give Kova <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">the job.</em>
          </h2>

          <div className="mt-16 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4 text-left">
            {/* Step 1 */}
            <div className="bento-card">
              <div className="font-['DM_Mono'] text-sm font-semibold text-[#D58A56]">01</div>
              <div className="bento-ill mt-5">
                <svg width="120" height="90" viewBox="0 0 120 90" fill="none">
                  <rect x="8" y="8" width="104" height="74" rx="12" fill="#fff" stroke="#8A3513" strokeWidth="2" />
                  <path d="M8 28h104" stroke="#8A3513" strokeWidth="2" />
                  <circle cx="20" cy="18" r="3" fill="#D58A56" />
                  <circle cx="30" cy="18" r="3" fill="#E6B79A" />
                  <rect x="44" y="13" width="56" height="10" rx="5" fill="#F1E7D8" />
                  <g className="gl">
                    <circle cx="60" cy="56" r="15" stroke="#8A3513" strokeWidth="2" />
                    <path d="M45 56h30M60 41c-8 9-8 21 0 30M60 41c8 9 8 21 0 30" stroke="#D58A56" strokeWidth="2" />
                  </g>
                </svg>
              </div>
              <h3 className="mt-6 font-['Bricolage_Grotesque'] text-2xl font-bold text-[#2A170D]">Give it a product</h3>
              <p className="mt-2 text-sm text-[#6B5646] leading-relaxed">Your website becomes Kova&apos;s environment.</p>
            </div>

            {/* Step 2 */}
            <div className="bento-card">
              <div className="font-['DM_Mono'] text-sm font-semibold text-[#D58A56]">02</div>
              <div className="bento-ill mt-5">
                <svg width="120" height="90" viewBox="0 0 120 90" fill="none">
                  <rect x="10" y="10" width="60" height="14" rx="7" fill="#fff" stroke="#8A3513" strokeWidth="2" />
                  <rect x="10" y="32" width="40" height="34" rx="8" fill="#fff" stroke="#D58A56" strokeWidth="2" />
                  <rect x="58" y="32" width="34" height="16" rx="8" fill="#fff" stroke="#D58A56" strokeWidth="2" />
                  <g className="mg">
                    <circle cx="82" cy="56" r="20" fill="rgba(255,255,255,0.6)" stroke="#8A3513" strokeWidth="3" />
                    <path d="M96 71l14 14" stroke="#8A3513" strokeWidth="5" strokeLinecap="round" />
                  </g>
                </svg>
              </div>
              <h3 className="mt-6 font-['Bricolage_Grotesque'] text-2xl font-bold text-[#2A170D]">Let it understand</h3>
              <p className="mt-2 text-sm text-[#6B5646] leading-relaxed">Kova explores the interface the way a real user would.</p>
            </div>

            {/* Step 3 */}
            <div className="bento-card">
              <div className="font-['DM_Mono'] text-sm font-semibold text-[#D58A56]">03</div>
              <div className="bento-ill mt-5">
                <svg width="120" height="90" viewBox="0 0 120 90" fill="none">
                  <rect x="14" y="16" width="70" height="26" rx="13" fill="#8A3513" />
                  <rect x="26" y="26" width="30" height="6" rx="3" fill="#F3C9A3" />
                  <circle className="rp" cx="70" cy="29" r="22" stroke="#D58A56" strokeWidth="2" opacity="0.6" />
                  <circle className="rp" cx="70" cy="29" r="34" stroke="#D58A56" strokeWidth="1.5" opacity="0.3" style={{ animationDelay: ".25s" }} />
                  <path className="cu" d="M66 40l34 14-14 4-4 14z" fill="#2A170D" stroke="#fff" strokeWidth="2" />
                </svg>
              </div>
              <h3 className="mt-6 font-['Bricolage_Grotesque'] text-2xl font-bold text-[#2A170D]">Let it act</h3>
              <p className="mt-2 text-sm text-[#6B5646] leading-relaxed">Clicks, types, uploads and completes the journey.</p>
            </div>

            {/* Step 4 */}
            <div className="bento-card">
              <div className="font-['DM_Mono'] text-sm font-semibold text-[#D58A56]">04</div>
              <div className="bento-ill mt-5">
                <svg width="120" height="90" viewBox="0 0 120 90" fill="none">
                  <rect x="26" y="6" width="62" height="78" rx="10" fill="#fff" stroke="#8A3513" strokeWidth="2" />
                  <path d="M38 24h38M38 36h38M38 48h22" stroke="#E6B79A" strokeWidth="4" strokeLinecap="round" />
                  <g className="bd">
                    <circle cx="84" cy="62" r="20" fill="#8A3513" />
                    <path d="M74 62l7 7 12-14" stroke="#fff" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
                  </g>
                </svg>
              </div>
              <h3 className="mt-6 font-['Bricolage_Grotesque'] text-2xl font-bold text-[#2A170D]">Get proof</h3>
              <p className="mt-2 text-sm text-[#6B5646] leading-relaxed">A full record of what happened, with evidence.</p>
            </div>
          </div>
        </div>
      </section>

      {/* ============================================================ */}
      {/* FEATURES BENTO GRID                                          */}
      {/* ============================================================ */}
      <section id="features" className="py-24 text-center">
        <div className="mx-auto max-w-[1200px] px-6">
          <span className="pill-badge">Features</span>
          <h2 className="mx-auto mt-5 max-w-3xl font-['Bricolage_Grotesque'] text-4xl font-bold tracking-tight sm:text-5xl md:text-6xl text-[#2A170D]">
            One agent. <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">Many jobs.</em>
          </h2>
          <p className="mx-auto mt-4 max-w-lg text-base md:text-lg text-[#6B5646]">
            Forget brittle test scripts and manual walkthroughs.
          </p>

          <div className="mt-16 grid grid-cols-1 gap-6 md:grid-cols-3 text-left">
            {/* Card 1: Test (span 2) */}
            <div className="bento-card md:col-span-2">
              <div className="bento-ill">
                <svg width="260" height="130" viewBox="0 0 260 130" fill="none" stroke="#8A3513" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="10" y="8" width="240" height="30" rx="15" fill="#fff" />
                  <rect x="10" y="50" width="240" height="30" rx="15" fill="#fff" />
                  <rect x="10" y="92" width="240" height="30" rx="15" fill="#fff" />
                  <circle className="tk" cx="30" cy="23" r="9" fill="#8A3513" />
                  <circle className="tk" style={{ animationDelay: ".25s" }} cx="30" cy="65" r="9" fill="#8A3513" />
                  <circle className="tk" style={{ animationDelay: ".5s" }} cx="30" cy="107" r="9" fill="#D58A56" stroke="none" />
                  <path d="M26 23l3 3 5-6M26 65l3 3 5-6" stroke="#fff" />
                  <path className="bar" d="M52 23h110" stroke="#E6B79A" strokeWidth="5" />
                  <path className="bar" style={{ animationDelay: ".25s" }} d="M52 65h150" stroke="#E6B79A" strokeWidth="5" />
                  <path className="bar" style={{ animationDelay: ".5s" }} d="M52 107h90" stroke="#E6B79A" strokeWidth="5" />
                </svg>
              </div>
              <h3 className="mt-6 font-['Bricolage_Grotesque'] text-2xl font-bold text-[#2A170D]">Test</h3>
              <p className="mt-2 text-sm text-[#6B5646] leading-relaxed">
                Run real user journeys before your users do. Catch broken workflows and regressions before code reaches production.
              </p>
            </div>

            {/* Card 2: Validate (span 1) */}
            <div className="bento-card md:col-span-1">
              <div className="bento-ill">
                <svg width="110" height="120" viewBox="0 0 36 40" fill="none" stroke="#8A3513" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path className="nd" d="M18 3l13 5v10c0 9-6 15-13 19C11 33 5 27 5 18V8z" fill="#fff" />
                  <path className="dr" pathLength={1} style={{ strokeDasharray: 1, animationDelay: ".35s" }} d="M12 19l4 4 8-10" stroke="#8A3513" strokeWidth="2.6" />
                </svg>
              </div>
              <h3 className="mt-6 font-['Bricolage_Grotesque'] text-2xl font-bold text-[#2A170D]">Validate</h3>
              <p className="mt-2 text-sm text-[#6B5646] leading-relaxed">
                Turn product requirements into executable journeys that verify shipped features.
              </p>
            </div>

            {/* Card 3: Explore (span 1) */}
            <div className="bento-card md:col-span-1">
              <div className="bento-ill">
                <svg width="240" height="130" viewBox="0 0 240 130" fill="none" stroke="#8A3513" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path className="dr" pathLength={1} style={{ strokeDasharray: 1 }} d="M40 65L110 25M40 65L110 100M110 25L190 55M110 100L190 55M110 25L110 100" />
                  <circle className="nd" cx="40" cy="65" r="14" fill="#fff" />
                  <circle className="nd" style={{ animationDelay: ".2s" }} cx="110" cy="25" r="12" fill="#fff" />
                  <circle className="nd" style={{ animationDelay: ".3s" }} cx="110" cy="100" r="12" fill="#fff" />
                  <circle className="nd" style={{ animationDelay: ".5s" }} cx="190" cy="55" r="16" fill="#8A3513" />
                  <circle cx="190" cy="55" r="26" stroke="#D58A56" strokeDasharray="3 6" />
                </svg>
              </div>
              <h3 className="mt-6 font-['Bricolage_Grotesque'] text-2xl font-bold text-[#2A170D]">Explore</h3>
              <p className="mt-2 text-sm text-[#6B5646] leading-relaxed">
                Let Kova discover how your product actually behaves, surfacing flows you never mapped.
              </p>
            </div>

            {/* Card 4: Demonstrate (span 2) */}
            <div className="bento-card md:col-span-2">
              <div className="bento-ill">
                <svg width="260" height="120" viewBox="0 0 260 120" fill="none" stroke="#8A3513" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="10" y="10" width="240" height="70" rx="14" fill="#fff" />
                  <circle className="nd" cx="130" cy="45" r="22" fill="#8A3513" />
                  <path className="nd" style={{ animationDelay: ".15s" }} d="M124 36l15 9-15 9z" fill="#fff" stroke="#fff" />
                  <rect x="10" y="94" width="240" height="8" rx="4" fill="#fff" stroke="none" />
                  <rect className="bar" style={{ animationDuration: "1.4s" }} x="10" y="94" width="150" height="8" rx="4" fill="#D58A56" stroke="none" />
                </svg>
              </div>
              <h3 className="mt-6 font-['Bricolage_Grotesque'] text-2xl font-bold text-[#2A170D]">Demonstrate</h3>
              <p className="mt-2 text-sm text-[#6B5646] leading-relaxed">
                Turn real product interactions into repeatable demonstrations with recorded proof.
              </p>
            </div>

            {/* Card 5: Dark Autonomous Loop (span 2) */}
            <div className="bento-card md:col-span-2 !bg-[#22120a] !text-white flex flex-col md:flex-row items-center gap-6 p-8 border-none [background:radial-gradient(500px_300px_at_90%_0%,#7a3114,transparent_70%),#22120a]">
              <div className="flex-1">
                <span className="inline-block rounded-full bg-white/10 px-3 py-1 font-['DM_Mono'] text-xs font-semibold text-[#F3C9A3]">
                  Autonomous loop
                </span>
                <h3 className="mt-4 font-['Bricolage_Grotesque'] text-2xl md:text-3xl font-bold text-white">
                  Observe. Understand. Act. Verify.
                </h3>
                <p className="mt-3 text-sm text-[#d8c6b4] leading-relaxed">
                  Kova decides each next move from what it sees, checks the result, and adapts when the path changes.
                </p>
              </div>

              <div className="shrink-0">
                <svg width="170" height="170" viewBox="0 0 170 170" aria-hidden="true">
                  <g style={{ transformOrigin: "85px 85px", animation: "spin 30s linear infinite" }}>
                    <circle cx="85" cy="85" r="78" fill="none" stroke="rgba(213,138,86,0.6)" strokeDasharray="2 8" />
                  </g>
                  <circle cx="85" cy="85" r="52" fill="none" stroke="rgba(255,255,255,0.2)" />
                  <circle className="nd" cx="85" cy="85" r="30" fill="#8A3513" />
                  <circle className="nd" style={{ animationDelay: ".15s" }} cx="85" cy="33" r="7" fill="#F3C9A3" />
                  <circle className="nd" style={{ animationDelay: ".3s" }} cx="137" cy="85" r="7" fill="#F3C9A3" />
                  <circle className="nd" style={{ animationDelay: ".45s" }} cx="85" cy="137" r="7" fill="#fff" />
                  <circle className="nd" style={{ animationDelay: ".6s" }} cx="33" cy="85" r="7" fill="#F3C9A3" />
                </svg>
              </div>
            </div>

            {/* Card 6: No script to maintain (span 1) */}
            <div className="bento-card md:col-span-1">
              <div className="bento-ill gap-2.5 flex flex-col justify-center items-center">
                <span className="font-['DM_Mono'] text-xs text-[#6B5646] line-through py-1.5 px-3.5 rounded-full border border-dashed border-[#2A170D]/30">
                  click(&quot;#submit-btn&quot;)
                </span>
                <span className="text-[#8A3513] font-bold">↓</span>
                <span className="btn-pill nd !py-2 !px-4 !text-xs" style={{ animationDelay: ".2s" }}>
                  Adapts to the goal
                </span>
              </div>
              <h3 className="mt-6 font-['Bricolage_Grotesque'] text-2xl font-bold text-[#2A170D]">No script to maintain</h3>
              <p className="mt-2 text-sm text-[#6B5646] leading-relaxed">
                Traditional automation breaks when a selector changes. Kova starts with an objective and works out the path.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ============================================================ */}
      {/* PRICING SECTION                                              */}
      {/* ============================================================ */}
      <section id="pricing" className="py-24 text-center">
        <div className="mx-auto max-w-[1200px] px-6">
          <span className="pill-badge">Pricing</span>
          <h2 className="mx-auto mt-5 max-w-3xl font-['Bricolage_Grotesque'] text-4xl font-bold tracking-tight sm:text-5xl md:text-6xl text-[#2A170D]">
            Simple <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">pricing plans.</em>
          </h2>
          <p className="mx-auto mt-4 max-w-lg text-base md:text-lg text-[#6B5646]">
            Start free. Upgrade when your runs outgrow it.
          </p>

          {/* Interactive Currency Switcher */}
          <div className="mt-8 inline-flex items-center rounded-full border border-[#2A170D]/10 bg-white p-1 shadow-sm">
            <button
              type="button"
              onClick={() => setCurrency("usd")}
              className={`rounded-full px-5 py-2 text-sm font-semibold transition-all ${
                currency === "usd"
                  ? "bg-[#2A170D] text-[#FBF7F0] shadow-sm"
                  : "text-[#6B5646] hover:text-[#2A170D]"
              }`}
            >
              $ USD
            </button>
            <button
              type="button"
              onClick={() => setCurrency("ngn")}
              className={`rounded-full px-5 py-2 text-sm font-semibold transition-all ${
                currency === "ngn"
                  ? "bg-[#2A170D] text-[#FBF7F0] shadow-sm"
                  : "text-[#6B5646] hover:text-[#2A170D]"
              }`}
            >
              ₦ NGN
            </button>
          </div>

          {/* 3 Pricing Cards */}
          <div className="mx-auto mt-14 grid max-w-5xl grid-cols-1 gap-6 md:grid-cols-3 text-left items-start">
            {/* Starter Plan */}
            <div className="bento-card">
              <h3 className="font-['Bricolage_Grotesque'] text-2xl font-bold text-[#2A170D]">Starter</h3>
              <p className="mt-1 text-sm text-[#6B5646]">For solo builders trying Kova.</p>
              <div className="my-6 font-['Bricolage_Grotesque'] text-5xl font-bold tracking-tight text-[#2A170D]">
                Free
              </div>
              <Link href="/auth/signup" className="btn-pill w-full !py-3">
                Start free
              </Link>
              <div className="mt-6 border-t border-[#8A3513]/15 pt-5 space-y-3 text-sm text-[#2A170D]">
                {["1 project", "50 runs a month", "Test with a goal in plain English", "Screenshot evidence", "Run reports", "Community support"].map((item) => (
                  <div key={item} className="flex items-start gap-2.5">
                    <svg className="mt-0.5 shrink-0 text-[#8A3513]" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 8.5l3 3 7-7" />
                    </svg>
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Pro Plan (Featured) */}
            <div className="bento-card relative !bg-gradient-to-br !from-[#B2562A] !to-[#8A3513] !text-white shadow-[0_40px_70px_-30px_#8A3513] md:-mt-5 md:pb-10">
              <span className="absolute -top-3.5 left-7 rounded-full bg-[#F3C9A3] px-3.5 py-1 text-xs font-bold text-[#6e2a10] shadow-sm">
                Most popular
              </span>
              <h3 className="font-['Bricolage_Grotesque'] text-2xl font-bold text-white">Pro</h3>
              <p className="mt-1 text-sm text-[#F3D9C4]">For small teams that ship often.</p>
              <div className="my-6 font-['Bricolage_Grotesque'] text-5xl font-bold tracking-tight text-white">
                {currency === "usd" ? "$29" : "₦45,000"}
                <span className="font-['DM_Sans'] text-lg font-medium opacity-70">/mo</span>
              </div>
              <Link
                href="/auth/signup?plan=pro"
                className="inline-flex w-full items-center justify-center rounded-full bg-white py-3 text-sm font-semibold text-[#2A170D] transition-transform hover:-translate-y-0.5 shadow-md"
              >
                Get started
              </Link>
              <div className="mt-6 border-t border-white/20 pt-5 space-y-3 text-sm text-white">
                <div className="flex items-start gap-2.5">
                  <svg className="mt-0.5 shrink-0 text-[#F3C9A3]" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M3 8.5l3 3 7-7" />
                  </svg>
                  <span><b>Everything in Starter, plus</b></span>
                </div>
                {["5 projects", "200 runs a month", "QA personas and user stories", "Video walkthroughs", "Shareable reports"].map((item) => (
                  <div key={item} className="flex items-start gap-2.5">
                    <svg className="mt-0.5 shrink-0 text-[#F3C9A3]" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 8.5l3 3 7-7" />
                    </svg>
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Scale Plan */}
            <div className="bento-card">
              <h3 className="font-['Bricolage_Grotesque'] text-2xl font-bold text-[#2A170D]">Scale</h3>
              <p className="mt-1 text-sm text-[#6B5646]">For QA teams and growing products.</p>
              <div className="my-6 font-['Bricolage_Grotesque'] text-5xl font-bold tracking-tight text-[#2A170D]">
                {currency === "usd" ? "$99" : "₦150,000"}
                <span className="font-['DM_Sans'] text-lg font-medium opacity-60">/mo</span>
              </div>
              <Link href="/auth/signup?plan=scale" className="btn-pill w-full !py-3">
                Get started
              </Link>
              <div className="mt-6 border-t border-[#8A3513]/15 pt-5 space-y-3 text-sm text-[#2A170D]">
                <div className="flex items-start gap-2.5">
                  <svg className="mt-0.5 shrink-0 text-[#8A3513]" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M3 8.5l3 3 7-7" />
                  </svg>
                  <span><b>Everything in Pro, plus</b></span>
                </div>
                {["Unlimited projects", "1,000 runs a month", "Scheduled and CI-triggered runs", "Team seats and roles", "Priority support"].map((item) => (
                  <div key={item} className="flex items-start gap-2.5">
                    <svg className="mt-0.5 shrink-0 text-[#8A3513]" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 8.5l3 3 7-7" />
                    </svg>
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <p className="mt-8 text-xs text-[#6B5646]">
            Prices in {currency === "usd" ? "USD" : "Nigerian naira"}. Runs reset monthly.
          </p>
        </div>
      </section>

      {/* ============================================================ */}
      {/* FINAL CTA                                                    */}
      {/* ============================================================ */}
      <section id="cta" className="py-24">
        <div className="mx-auto max-w-[1200px] px-6">
          <div className="relative overflow-hidden rounded-[40px] bg-gradient-to-br from-[#B2562A] to-[#6e2a10] py-20 px-6 sm:px-12 text-center text-white [background:radial-gradient(600px_400px_at_85%_0%,#E9A878,transparent_70%),linear-gradient(160deg,#B2562A,#6e2a10)]">
            <h2 className="mx-auto max-w-3xl font-['Bricolage_Grotesque'] text-4xl font-bold tracking-tight sm:text-6xl md:text-7xl">
              Give Kova <em className="font-['Instrument_Serif'] font-normal italic text-[#F3C9A3]">your product.</em>
            </h2>
            <p className="mx-auto mt-4 max-w-md text-base md:text-lg text-[#F3D9C4]">
              Start with a website. Let the agent take it from there.
            </p>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleExplore(ctaUrl);
              }}
              className="mx-auto mt-8 flex max-w-[580px] items-center gap-3 rounded-full border border-white/80 bg-white/70 p-2 pl-6 shadow-[0_1px_0_#fff_inset,0_20px_40px_-15px_rgba(40,10,0,0.5)] backdrop-blur-xl"
            >
              <input
                type="text"
                value={ctaUrl}
                onChange={(e) => setCtaUrl(e.target.value)}
                placeholder="https://yourproduct.com"
                className="flex-1 bg-transparent font-['DM_Mono'] text-sm md:text-base text-[#2A170D] placeholder-[#6B5646]/60 outline-none"
              />
              <button
                type="submit"
                className="btn-pill !py-3 !px-6 !text-sm"
              >
                Explore →
              </button>
            </form>
          </div>
        </div>
      </section>

      {/* ============================================================ */}
      {/* FOOTER                                                       */}
      {/* ============================================================ */}
      <footer className="ft py-10">
        <div className="mx-auto max-w-[1200px] px-6">
          <div className="ftp relative overflow-hidden rounded-[36px] bg-[#F1E7D8] p-8 md:p-14 min-h-[520px] transition-[background-position] duration-1000 ease-out bg-[radial-gradient(rgba(42,23,13,0.12)_1px,transparent_1px)] [background-size:14px_14px]">
            <div className="flex flex-col md:flex-row justify-between gap-10">
              <div>
                <h3 className="font-['Bricolage_Grotesque'] text-3xl font-bold tracking-tight text-[#2A170D]">
                  Kova<span className="text-[#D58A56]">.</span>
                </h3>
                <h4 className="mt-4 max-w-sm font-['Bricolage_Grotesque'] text-3xl md:text-5xl font-bold tracking-tight text-[#2A170D] leading-tight">
                  Stay confident with <em className="font-['Instrument_Serif'] font-normal italic text-[#8A3513]">every release.</em>
                </h4>
              </div>

              <div className="flex gap-16 text-sm text-[#6B5646]">
                <div className="flex flex-col gap-3 font-medium">
                  <a href="#product">Product</a>
                  <a href="#how">How it works</a>
                  <a href="#features">Features</a>
                  <a href="#pricing">Pricing</a>
                </div>
                <div className="flex flex-col gap-3 font-medium">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[#8A3513]">Developers</span>
                  <Link href="/auth/login">Sign in</Link>
                  <Link href="/auth/signup">Get started</Link>
                  <Link href="/status">System status</Link>
                </div>
              </div>
            </div>

            {/* Floating Decorative Tiles in Footer (f1 - f6) */}
            <div className="hidden lg:block">
              {/* f1: click animation */}
              <div className="tile-float f1 absolute left-[70px] top-[300px] -rotate-12">
                <svg width="28" height="28" viewBox="0 0 36 36" fill="#8A3513" stroke="#8A3513" strokeWidth="2" strokeLinejoin="round">
                  <path d="M8 5l22 10-9 3-3 9z" />
                </svg>
              </div>

              {/* f2: pop animation */}
              <div className="tile-float f2 absolute left-[260px] top-[380px] [animation-delay:-2s]">
                <svg width="30" height="30" viewBox="0 0 16 16" fill="none" stroke="#3E9B5F" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 8.5l3 3 7-7" />
                </svg>
              </div>

              {/* f3: blink animation */}
              <div className="tile-float f3 absolute left-[470px] top-[300px] rotate-8 [animation-delay:-4s]">
                <svg width="30" height="30" viewBox="0 0 36 36" fill="none" stroke="#8A3513" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 18s6-11 15-11 15 11 15 11-6 11-15 11S3 18 3 18z" />
                  <circle cx="18" cy="18" r="5" />
                </svg>
              </div>

              {/* f4: freeze/zap animation */}
              <div className="tile-float f4 absolute left-[680px] top-[390px] [animation-delay:-1s]">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="#D58A56" stroke="#8A3513" strokeWidth="1.5" strokeLinejoin="round">
                  <path d="M13 2L4 14h7l-1 8 9-12h-7z" />
                </svg>
              </div>

              {/* f5: wobble animation */}
              <div className="tile-float f5 absolute left-[880px] top-[300px] -rotate-6 [animation-delay:-5s]">
                <svg width="30" height="30" viewBox="0 0 36 36" fill="none" stroke="#8A3513" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M18 3l12 4v9c0 8-5 13-12 17C11 29 6 24 6 16V7z" />
                  <path d="M12 18l4 4 8-9" />
                </svg>
              </div>

              {/* f6: spin animation */}
              <div className="tile-float f6 absolute right-16 top-[390px] [animation-delay:-3s]">
                <svg width="28" height="28" viewBox="0 0 20 20" fill="none" stroke="#8A3513" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 10a7 7 0 0 1 12-5l2 2M17 3v4h-4M17 10a7 7 0 0 1-12 5l-2-2M3 17v-4h4" />
                </svg>
              </div>
            </div>

            {/* Copyright & Legal */}
            <div className="absolute left-8 right-8 bottom-6 border-t border-[#2A170D]/10 pt-4 flex flex-col sm:flex-row justify-between gap-2 text-xs text-[#6B5646]">
              <span>© 2026 Kova. All rights reserved.</span>
              <span>Privacy Policy &nbsp;·&nbsp; Terms of Service</span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
