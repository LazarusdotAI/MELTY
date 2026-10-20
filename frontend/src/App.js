import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "./components/ui/sonner";
import TopBar from "./components/TopBar";
import Copilot from "./pages/Copilot";
import GameSelector from "./pages/GameSelector";
import Trainer from "./pages/Trainer";
import Discover from "./pages/Discover";
import Mods from "./pages/Mods";
import Release from "./pages/Release";
import Companion from "./pages/Companion";
import Adapters from "./pages/Adapters";
import AssetsPage from "./pages/AssetsPage";
import AssetWorkshop from "./pages/AssetWorkshop";
import Budget from "./pages/Budget";
import Ideas from "./pages/Ideas";

export default function App() {
  return (
    <BrowserRouter>
      <div className="grain min-h-screen bg-[#08090d] text-slate-100">
        <TopBar />
        <div className="relative z-10">
          <Routes>
            <Route path="/" element={<Copilot />} />
            <Route path="/mods/:id" element={<Copilot />} />
            <Route path="/games" element={<GameSelector />} />
            <Route path="/trainer" element={<Trainer />} />
            <Route path="/new" element={<Navigate to="/" replace />} />
            <Route path="/discover" element={<Discover />} />
            <Route path="/mods" element={<Mods />} />
            <Route path="/ideas" element={<Ideas />} />
            <Route path="/releases/:id" element={<Release />} />
            <Route path="/companion" element={<Companion />} />
            <Route path="/adapters" element={<Adapters />} />
            <Route path="/assets" element={<AssetsPage />} />
            <Route path="/workshop" element={<AssetWorkshop />} />
            <Route path="/budget" element={<Budget />} />
          </Routes>
        </div>
        <Toaster position="top-right" theme="dark" />
      </div>
    </BrowserRouter>
  );
}
