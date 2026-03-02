import { Link, Route, Routes } from "react-router-dom";
import HomePage from "./pages/HomePage";
import TopicPage from "./pages/TopicPage";
import ApiKeysPage from "./pages/ApiKeysPage";
import SubscriptionsPage from "./pages/SubscriptionsPage";
import DlqPage from "./pages/DlqPage";
import AuditPage from "./pages/AuditPage";

export default function App() {
  return (
    <div className="container">
      <header>
        <h1>AsyncAPI Marketplace</h1>
        <nav className="nav-links">
          <Link to="/">Catalog</Link>
          <Link to="/me/keys">API Keys</Link>
          <Link to="/me/subscriptions">Subscriptions</Link>
          <Link to="/ops/dlq">DLQ</Link>
          <Link to="/ops/audit">Audit</Link>
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/topic/:topicName" element={<TopicPage />} />
        <Route path="/me/keys" element={<ApiKeysPage />} />
        <Route path="/me/subscriptions" element={<SubscriptionsPage />} />
        <Route path="/ops/dlq" element={<DlqPage />} />
        <Route path="/ops/audit" element={<AuditPage />} />
      </Routes>
    </div>
  );
}
