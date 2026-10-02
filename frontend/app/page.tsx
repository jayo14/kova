import {
  Navbar,
  Hero,
  HowItWorks,
  AgentLoop,
  UseCases,
  AgenticSection,
  EvidenceSection,
  FinalCTA,
  Footer,
} from "@/components/marketing";

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col">
      <Navbar />
      <main className="flex-1">
        <Hero />
        <HowItWorks />
        <AgentLoop />
        <UseCases />
        <AgenticSection />
        <EvidenceSection />
        <FinalCTA />
      </main>
      <Footer />
    </div>
  );
}
