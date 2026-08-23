import { useState } from "react";
import { LiveDiagnosis } from "./components/LiveDiagnosis";
import { ExperimentResults } from "./components/ExperimentResults";

type Tab = "diagnosis" | "experiments";

function App() {
  const [tab, setTab] = useState<Tab>("diagnosis");

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold">
          SERA <span className="font-normal text-slate-500">— Suspect Extraction &amp; Regression Attribution</span>
        </h1>
        <nav className="mt-3 flex gap-1 text-sm">
          <button
            className={`rounded-md px-3 py-1.5 ${
              tab === "diagnosis" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
            }`}
            onClick={() => setTab("diagnosis")}
          >
            Live diagnosis
          </button>
          <button
            className={`rounded-md px-3 py-1.5 ${
              tab === "experiments" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
            }`}
            onClick={() => setTab("experiments")}
          >
            Experiment results
          </button>
        </nav>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-6">
        {tab === "diagnosis" ? <LiveDiagnosis /> : <ExperimentResults />}
      </main>
    </div>
  );
}

export default App;
