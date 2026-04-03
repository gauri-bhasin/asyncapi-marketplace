import { Link, Route, Routes, useLocation } from "react-router-dom";
import HomePage from "./pages/HomePage";
import TimelinePage from "./pages/TimelinePage";
import TopicPage from "./pages/TopicPage";
import IncidentPage from "./pages/IncidentPage";

function AppShell() {
  const location = useLocation();
  const isTimeline = location.pathname.startsWith("/timeline");

  return (
    <div className="container">
      <header>
        <div>
          <h1>signalhub</h1>
          <div className="muted">AI-native operational signal layer</div>
        </div>
        <nav className="nav-links">
          <Link to="/" className={!isTimeline ? "badge badge-outline" : ""}>
            Catalog
          </Link>
          <Link to="/timeline" className={isTimeline ? "badge badge-outline" : ""}>
            Timeline
          </Link>
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/timeline" element={<TimelinePage />} />
        <Route path="/topics/:name" element={<TopicPage />} />
        <Route path="/incidents/:id" element={<IncidentPage />} />
      </Routes>
    </div>
  );
}

export default function App() {
  return <AppShell />;
}
