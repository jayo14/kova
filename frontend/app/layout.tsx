import type { Metadata } from "next";
import localFont from "next/font/local";
import { Bricolage_Grotesque, Instrument_Serif, DM_Sans, DM_Mono } from "next/font/google";
import "./globals.css";

const bricolage = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-bricolage",
  display: "swap",
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-instrument-serif",
  display: "swap",
});

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-dm-sans",
  display: "swap",
});

const dmMono = DM_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-dm-mono",
  display: "swap",
});

const satoshi = localFont({
  src: [
    {
      path: "../public/fonts/satoshi/satoshi-regular.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "../public/fonts/satoshi/satoshi-medium.woff2",
      weight: "500",
      style: "normal",
    },
    {
      path: "../public/fonts/satoshi/satoshi-bold.woff2",
      weight: "700",
      style: "normal",
    },
    {
      path: "../public/fonts/satoshi/satoshi-black.woff2",
      weight: "900",
      style: "normal",
    },
  ],
  variable: "--font-satoshi",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Kova — Autonomous software agent",
  description: "Give Kova a website and a goal. It explores the product, figures out what needs to happen, and executes the journey like a real user.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className={`${satoshi.variable} ${bricolage.variable} ${instrumentSerif.variable} ${dmSans.variable} ${dmMono.variable} h-full antialiased`}
    >
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                if (typeof window !== 'undefined' && window.performance && typeof window.performance.measure === 'function') {
                  var origMeasure = window.performance.measure.bind(window.performance);
                  window.performance.measure = function(name, startOrOptions, end) {
                    try {
                      return origMeasure(name, startOrOptions, end);
                    } catch (e) {
                      // Suppress Next.js Turbopack dev timing calculation bug (negative timestamp)
                      return undefined;
                    }
                  };
                }
              })();
            `,
          }}
        />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap"
        />
      </head>
      <body suppressHydrationWarning className="min-h-full flex flex-col bg-background text-foreground font-sans">
        {children}
      </body>
    </html>
  );
}
